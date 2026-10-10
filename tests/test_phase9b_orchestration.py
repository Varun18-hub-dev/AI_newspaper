"""Comprehensive test suite for Phase 9B Daily GPU Worker Orchestration and Automated Publication."""

from datetime import datetime, timedelta
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.api.routes import router
from app.core.config import settings
from app.ingestion.models import Article
from app.orchestration.ec2_controller import EC2WorkerController
from app.orchestration.lifecycle import LifecycleManager, WorkerState
from app.orchestration.runner import GPUWorkerPipelineRunner
from app.orchestration.scheduler import EventBridgeScheduleConfig
from app.orchestration.watchdog import WorkerWatchdog
from app.storage.publisher import (
    CurrentEditionPointer,
    EditionManifest,
    EditionPublisher,
    EditionStory,
    EditionValidator,
)
from app.storage.sqlite import SQLiteDatabase


# =============================================================================
# 1. Lifecycle State Machine Tests
# =============================================================================

def test_lifecycle_state_machine_valid_progression():
    """Verify standard happy-path progression through lifecycle states."""
    lm = LifecycleManager(run_id="run_test_001", edition_id="edition_test_001")
    assert lm.context.current_state == WorkerState.STARTING

    assert lm.transition_to(WorkerState.READY, message="Checks passed") is True
    assert lm.context.ready_at is not None

    assert lm.transition_to(WorkerState.RUNNING, message="Ingesting") is True
    assert lm.transition_to(WorkerState.PUBLISHING, message="Publishing") is True
    assert lm.transition_to(WorkerState.SUCCESS, message="Edition live") is True
    assert lm.context.completed_at is not None
    assert lm.context.duration_seconds is not None

    assert lm.transition_to(WorkerState.STOPPING, message="Self-stopping") is True
    assert lm.transition_to(WorkerState.STOPPED, message="Stopped") is True
    assert lm.is_terminal() is True


def test_lifecycle_disallows_illegal_transitions():
    """Verify state machine rejects invalid backwards or jumping transitions."""
    lm = LifecycleManager(run_id="run_test_002", edition_id="edition_test_002")
    # Cannot jump from STARTING directly to PUBLISHING
    assert lm.transition_to(WorkerState.PUBLISHING) is False
    assert lm.context.current_state == WorkerState.STARTING

    # Transition to READY
    assert lm.transition_to(WorkerState.READY) is True
    # Cannot go back from READY to STARTING
    assert lm.transition_to(WorkerState.STARTING) is False


def test_lifecycle_terminal_failure_recording():
    """Verify failure state captures error message and duration."""
    lm = LifecycleManager(run_id="run_test_003", edition_id="edition_test_003")
    lm.transition_to(WorkerState.READY)
    lm.transition_to(WorkerState.RUNNING)
    lm.transition_to(WorkerState.FAILED, message="Database disk full")

    assert lm.context.current_state == WorkerState.FAILED
    assert lm.context.error_message == "Database disk full"
    assert lm.is_terminal() is True


# =============================================================================
# 2. Watchdog Runtime Budget & Safety Limits
# =============================================================================

def test_watchdog_detects_soft_target_and_hard_limit():
    """Verify watchdog emits warning on soft target and expires on hard limit."""
    # 0.05s target, 0.1s hard limit
    wd = WorkerWatchdog(target_runtime_minutes=0.05 / 60.0, max_runtime_minutes=0.15 / 60.0)
    wd.start()

    # Right after start
    expired, warning, msg = wd.check()
    assert expired is False
    assert warning is False

    # Sleep past soft target
    import time
    time.sleep(0.06)
    expired, warning, msg = wd.check()
    assert expired is False
    assert warning is True
    assert "soft performance target" in msg

    # Sleep past hard limit
    time.sleep(0.10)
    expired, warning, msg = wd.check()
    assert expired is True
    assert "maximum runtime limit" in msg


# =============================================================================
# 3. EC2 Worker Controller & Idempotency
# =============================================================================

def test_ec2_start_idempotency_when_already_running():
    """Verify start_worker ignores duplicate requests when instance is running or pending."""
    mock_client = MagicMock()
    mock_client.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]
    }

    controller = EC2WorkerController(instance_id="i-test12345", ec2_client=mock_client)
    ok, msg = controller.start_worker()

    assert ok is True
    assert "already running (idempotent)" in msg
    mock_client.start_instances.assert_not_called()


def test_ec2_start_triggers_when_stopped():
    """Verify start_worker initiates StartInstances when instance is stopped."""
    mock_client = MagicMock()
    mock_client.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": "stopped"}}]}]
    }

    controller = EC2WorkerController(instance_id="i-test12345", ec2_client=mock_client)
    ok, msg = controller.start_worker()

    assert ok is True
    assert "start initiated" in msg
    mock_client.start_instances.assert_called_once_with(InstanceIds=["i-test12345"])


def test_ec2_stop_worker():
    """Verify stop_worker initiates StopInstances."""
    mock_client = MagicMock()
    mock_client.describe_instances.return_value = {
        "Reservations": [{"Instances": [{"State": {"Name": "running"}}]}]
    }

    controller = EC2WorkerController(instance_id="i-test12345", ec2_client=mock_client)
    ok, msg = controller.stop_worker()

    assert ok is True
    assert "stop initiated" in msg
    mock_client.stop_instances.assert_called_once_with(InstanceIds=["i-test12345"], Hibernate=False)


# =============================================================================
# 4. Edition Validation Gate & Atomic Publication
# =============================================================================

def test_edition_validator_rejects_empty_or_corrupt_stories():
    """Verify EditionValidator rejects empty sets, missing titles, or empty summaries."""
    validator = EditionValidator(min_stories=3)

    # Empty list
    ok, reason = validator.validate([])
    assert ok is False
    assert "0 stories" in reason

    # Too few stories
    story_valid = EditionStory(
        story_id="s1",
        title="Valid Story Headline Here",
        url="https://example.com/valid-story",
        domain="AI",
        summary="A substantive summary containing detailed technical facts.",
        sources=["TechCrunch"],
        first_seen_at=datetime.utcnow().isoformat(),
    )
    ok, reason = validator.validate([story_valid])
    assert ok is False
    assert "below minimum required threshold" in reason

    # Invalid URL story
    story_bad_url = EditionStory(
        story_id="s2",
        title="Valid Story Headline 2",
        url="not-a-valid-url",
        domain="AI",
        summary="Valid summary text with proper length.",
        sources=["Reuters"],
        first_seen_at=datetime.utcnow().isoformat(),
    )
    ok, reason = validator.validate([story_valid, story_valid, story_bad_url])
    assert ok is False
    assert "invalid URL" in reason


def test_atomic_edition_publishing_and_pointer_flip(tmp_path):
    """Verify publishing writes manifest, verifies checksum, and updates current_edition pointer."""
    publisher = EditionPublisher(storage_backend="local", local_dir=str(tmp_path))

    stories = [
        EditionStory(
            story_id=f"story_{i}",
            title=f"Important News Story Number {i}",
            url=f"https://example.com/news-{i}",
            domain="AI" if i % 2 == 0 else "Technology",
            summary=f"Substantive technical summary of event #{i} with verified grounding.",
            sources=["TechCrunch", "Ars Technica"],
            first_seen_at=datetime.utcnow().isoformat(),
        )
        for i in range(1, 5)
    ]

    ok, manifest, err = publisher.publish_edition(
        edition_id="edition_20261010_01",
        stories=stories,
        run_id="run_001",
    )

    assert ok is True
    assert manifest is not None
    assert manifest.total_stories == 4
    assert manifest.checksum is not None

    # Check files created on disk
    assert (tmp_path / "edition_20261010_01.json").exists()
    assert (tmp_path / "current_edition.json").exists()

    # Verify pointer
    current = publisher.get_current_edition()
    assert current is not None
    assert current.edition_id == "edition_20261010_01"
    assert current.total_stories == 4


def test_failed_publication_preserves_previous_edition(tmp_path):
    """Verify that if a subsequent run fails validation, the previous live edition remains active."""
    publisher = EditionPublisher(storage_backend="local", local_dir=str(tmp_path))

    # Day 1: Successful publication
    day1_stories = [
        EditionStory(
            story_id=f"day1_s{i}",
            title=f"Day 1 High Quality Story #{i}",
            url=f"https://example.com/day1-{i}",
            domain="AI",
            summary=f"Day 1 detailed verified summary for article #{i}.",
            sources=["TechCrunch"],
            first_seen_at=datetime.utcnow().isoformat(),
        )
        for i in range(1, 4)
    ]
    ok1, m1, _ = publisher.publish_edition(
        edition_id="edition_day1",
        stories=day1_stories,
        run_id="run_day1",
    )
    assert ok1 is True
    assert publisher.get_current_edition().edition_id == "edition_day1"

    # Day 2: Attempt publication with invalid stories (too few)
    day2_bad = [
        EditionStory(
            story_id="day2_bad",
            title="Single lonely story",
            url="https://example.com/bad",
            domain="AI",
            summary="Too few stories.",
            sources=["TechCrunch"],
            first_seen_at=datetime.utcnow().isoformat(),
        )
    ]
    ok2, m2, err = publisher.publish_edition(
        edition_id="edition_day2",
        stories=day2_bad,
        run_id="run_day2",
    )
    assert ok2 is False

    # Current edition must STILL be Day 1!
    active = publisher.get_current_edition()
    assert active.edition_id == "edition_day1"
    assert active.total_stories == 3


# =============================================================================
# 5. Full GPU Worker Pipeline Runner Mocked Execution
# =============================================================================

def test_gpu_worker_pipeline_runner_success(tmp_path):
    """Verify GPUWorkerPipelineRunner coordinates discovery, processing, and publishing."""
    mem_db = SQLiteDatabase(db_path=":memory:")
    publisher = EditionPublisher(storage_backend="local", local_dir=str(tmp_path))

    # Mock discovery returning 3 valid articles
    mock_coordinator = MagicMock()
    mock_articles = [
        Article(
            title=f"Discovered Story Title #{i}",
            url=f"https://example.com/discovered-{i}",
            source="arXiv",
            domain="AI",
            description=f"Abstract of discovered article #{i}.",
        )
        for i in range(1, 4)
    ]
    mock_coordinator.discover_all.return_value = (mock_articles, {"arxiv": {"status": "SUCCESS"}})

    # Mock processor
    mock_processor = MagicMock()
    from app.processing.models import ProcessedArticle, RelevanceClassification
    mock_processed = [
        ProcessedArticle(
            article=art,
            classification=RelevanceClassification(
                is_relevant=True,
                relevance_score=0.95,
                topic="LLMs",
                reason=f"Synthesized agentic summary for article: {art.title}",
            ),
            cluster_id=f"cluster_{i}",
        )
        for i, art in enumerate(mock_articles, start=1)
    ]
    mock_processor.process_with_metrics.return_value = (mock_processed, MagicMock())

    # Mock EC2 controller
    mock_ec2 = MagicMock()

    runner = GPUWorkerPipelineRunner(
        db=mem_db,
        publisher=publisher,
        discovery_coordinator=mock_coordinator,
        article_processor=mock_processor,
        ec2_controller=mock_ec2,
    )

    success, manifest, telem = runner.run_worker_pipeline(auto_stop_on_finish=True)

    assert success is True
    assert manifest is not None
    assert manifest.total_stories == 3
    assert telem["current_state"] == "STOPPED"
    mock_ec2.stop_worker.assert_called_once()

    # Active edition flipped
    current = publisher.get_current_edition()
    assert current.edition_id == manifest.edition_id


def test_gpu_worker_pipeline_runner_readiness_failure():
    """Verify worker fails safely if database connectivity or readiness fails."""
    mock_db = MagicMock()
    mock_db.get_database_stats.side_effect = Exception("DB Connection Timeout")
    mock_ec2 = MagicMock()

    runner = GPUWorkerPipelineRunner(
        db=mock_db,
        ec2_controller=mock_ec2,
    )

    success, manifest, telem = runner.run_worker_pipeline(auto_stop_on_finish=True)
    assert success is False
    assert manifest is None
    assert telem["current_state"] == "STOPPED"
    assert "DB Connection Timeout" in telem["error_message"]
    mock_ec2.stop_worker.assert_called_once()


# =============================================================================
# 6. Website API Integration & Admin Authorization
# =============================================================================

def test_api_serves_published_edition_manifest(tmp_path, monkeypatch):
    """Verify /api/newspaper/latest serves from EditionPublisher with edition_id and published_at."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    publisher = EditionPublisher(storage_backend="local", local_dir=str(tmp_path))
    stories = [
        EditionStory(
            story_id=f"pub_s{i}",
            title=f"Published Lead Headline #{i}",
            url=f"https://pubnews.com/{i}",
            domain="AI",
            topic="LLMs",
            summary=f"Published summary content for story #{i}.",
            sources=["BAIR Blog"],
            first_seen_at=datetime.utcnow().isoformat(),
        )
        for i in range(1, 5)
    ]
    publisher.publish_edition("edition_20261010_latest", stories, "run_test_api")

    monkeypatch.setattr(settings, "editions_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "local")

    resp = client.get("/api/newspaper/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edition_id"] == "edition_20261010_latest"
    assert data["total"] == 4
    assert len(data["items"]) == 4
    assert data["items"][0]["headline"] == "Published Lead Headline #1"


def test_api_stale_data_flag_when_edition_older_than_24h(tmp_path, monkeypatch):
    """Verify /api/newspaper/latest marks is_stale=True when edition is older than 24h."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    publisher = EditionPublisher(storage_backend="local", local_dir=str(tmp_path))
    old_time = (datetime.utcnow() - timedelta(hours=30)).isoformat()

    stories = [
        EditionStory(
            story_id=f"old_s{i}",
            title=f"Old Story Headline #{i}",
            url=f"https://oldnews.com/{i}",
            domain="Science",
            summary="Old summary text.",
            sources=["Nature News"],
            first_seen_at=old_time,
        )
        for i in range(1, 4)
    ]
    checksum = publisher._compute_checksum([s.model_dump() for s in stories])
    manifest = EditionManifest(
        edition_id="edition_old_yesterday",
        publication_date="2026-10-08",
        published_at=old_time,
        total_stories=3,
        run_id="run_old",
        checksum=checksum,
        stories=stories,
    )
    (tmp_path / "edition_old_yesterday.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    pointer = CurrentEditionPointer(
        edition_id="edition_old_yesterday",
        published_at=old_time,
        checksum=checksum,
        total_stories=3,
        run_id="run_old",
    )
    (tmp_path / "current_edition.json").write_text(pointer.model_dump_json(), encoding="utf-8")

    monkeypatch.setattr(settings, "editions_dir", str(tmp_path))
    monkeypatch.setattr(settings, "storage_backend", "local")

    resp = client.get("/api/newspaper/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["edition_id"] == "edition_old_yesterday"
    assert data["is_stale"] is True


def test_api_admin_key_security_on_manual_refresh(monkeypatch):
    """Verify /api/runs/refresh enforces ADMIN_API_KEY security when configured."""
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    monkeypatch.setattr(settings, "admin_api_key", "secret-admin-passphrase-1234")

    # Unauthorized attempt (missing key) -> 403 Forbidden
    resp_unauth = client.post("/api/runs/refresh")
    assert resp_unauth.status_code == 403

    # Unauthorized attempt (wrong key) -> 403 Forbidden
    resp_wrong = client.post("/api/runs/refresh", headers={"X-Admin-Api-Key": "wrong-key"})
    assert resp_wrong.status_code == 403

    # Authorized attempt (valid key) -> 202 Accepted (or 409 if locked)
    resp_auth = client.post("/api/runs/refresh", headers={"X-Admin-Api-Key": "secret-admin-passphrase-1234"})
    assert resp_auth.status_code in (202, 409)


def test_edition_checksum_tamper_detection(tmp_path):
    """Verify EditionPublisher rejects manifests whose payload has been corrupted or tampered with."""
    publisher = EditionPublisher(storage_backend="local", local_dir=str(tmp_path))
    stories = [
        EditionStory(
            story_id="s1",
            title="Real Story",
            url="https://example.com/1",
            domain="AI",
            summary="Real summary.",
            sources=["Feed"],
            first_seen_at=datetime.utcnow().isoformat(),
        )
    ]
    # Tampered manifest with bogus checksum
    manifest = EditionManifest(
        edition_id="edition_tampered",
        publication_date="2026-10-10",
        published_at=datetime.utcnow().isoformat(),
        total_stories=1,
        run_id="run_tamper",
        checksum="corrupted_sha256_hash",
        stories=stories,
    )
    (tmp_path / "edition_tampered.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    # get_edition should detect the mismatch and return None
    loaded = publisher.get_edition("edition_tampered")
    assert loaded is None

