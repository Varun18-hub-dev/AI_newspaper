"""Unit and integration tests for Phase 7: Daily Scheduling, Automation & Lifecycle Tracking."""

from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo
import pytest

from app.core.config import settings
from app.ingestion.models import Article
from app.processing.models import (
    ProcessedArticle,
    RelevanceClassification,
    PipelineMetrics,
)
from app.scheduler.lock import PipelineRunAlreadyActiveError, PipelineRunLock
from app.scheduler.runner import DailyPipelineRunner, generate_run_id
from app.scheduler.scheduler import DailyScheduler
from app.storage.models import PipelineRunRecord
from app.storage.sqlite import SQLiteDatabase


@pytest.fixture
def mem_db():
    """Provides an isolated in-memory SQLiteDatabase instance."""
    return SQLiteDatabase(":memory:")


@pytest.fixture
def temp_lock_file(tmp_path):
    """Provides an isolated lockfile path for testing."""
    return str(tmp_path / "test_pipeline.lock")


def _make_sample_article(
    url: str = "https://example.com/ai/article1",
    title: str = "Breakthrough in AI Reasoning",
    domain: str = "AI",
    source: str = "TechCrunch",
) -> Article:
    """Helper to construct valid Article instances."""
    return Article(
        title=title,
        url=url,
        source=source,
        domain=domain,
        description="A major advance in machine learning and reasoning models.",
        published_at=datetime.utcnow(),
    )


# =============================================================================
# 1. Next-Run Calculation & Timezone Tests
# =============================================================================
def test_next_run_calculation_same_day(mem_db):
    """If target time has not yet passed and no run occurred today, schedule for today."""
    scheduler = DailyScheduler(
        db=mem_db,
        schedule_time="06:00",
        timezone_str="UTC",
    )
    # 04:30 UTC -> next run should be 06:00 UTC today
    ref_now = datetime(2026, 10, 10, 4, 30, 0, tzinfo=ZoneInfo("UTC"))
    next_run, delay = scheduler.calculate_next_run(now_dt=ref_now)

    assert next_run.year == 2026
    assert next_run.month == 10
    assert next_run.day == 10
    assert next_run.hour == 6
    assert next_run.minute == 0
    assert delay == pytest.approx(90 * 60, abs=1.0)  # 1.5 hours


def test_next_run_calculation_next_day(mem_db):
    """If target time has passed today, schedule for tomorrow."""
    scheduler = DailyScheduler(
        db=mem_db,
        schedule_time="06:00",
        timezone_str="UTC",
    )
    # 07:15 UTC -> target 06:00 has passed; next run should be 06:00 UTC tomorrow
    ref_now = datetime(2026, 10, 10, 7, 15, 0, tzinfo=ZoneInfo("UTC"))
    next_run, delay = scheduler.calculate_next_run(now_dt=ref_now)

    assert next_run.year == 2026
    assert next_run.month == 10
    assert next_run.day == 11
    assert next_run.hour == 6
    assert next_run.minute == 0
    # 22 hours 45 minutes = 22.75 * 3600 = 81900 seconds
    assert delay == pytest.approx(81900.0, abs=1.0)


def test_next_run_calculation_different_timezones(mem_db):
    """Verifies timezone awareness across America/New_York and Asia/Kolkata."""
    # Test New York (EDT/EST)
    scheduler_ny = DailyScheduler(
        db=mem_db,
        schedule_time="08:00",
        timezone_str="America/New_York",
    )
    ref_ny = datetime(2026, 10, 10, 6, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    next_ny, delay_ny = scheduler_ny.calculate_next_run(now_dt=ref_ny)
    assert next_ny.day == 10
    assert next_ny.hour == 8
    assert delay_ny == pytest.approx(2 * 3600, abs=1.0)

    # Test Kolkata (IST: UTC+5:30)
    scheduler_ist = DailyScheduler(
        db=mem_db,
        schedule_time="09:30",
        timezone_str="Asia/Kolkata",
    )
    ref_ist = datetime(2026, 10, 10, 10, 0, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    next_ist, delay_ist = scheduler_ist.calculate_next_run(now_dt=ref_ist)
    # 10:00 IST is after 09:30 IST, so next run is tomorrow at 09:30
    assert next_ist.day == 11
    assert next_ist.hour == 9
    assert next_ist.minute == 30
    assert delay_ist == pytest.approx(23.5 * 3600, abs=1.0)


def test_invalid_timezone_fails_clearly(mem_db):
    """Scheduler raises ValueError when an invalid timezone string is provided."""
    with pytest.raises(ValueError, match="Invalid timezone"):
        DailyScheduler(
            db=mem_db,
            schedule_time="06:00",
            timezone_str="NonExistent/Timezone_Invalid",
        )


def test_invalid_schedule_time_fails_clearly(mem_db):
    """Scheduler raises ValueError when invalid schedule times are provided."""
    with pytest.raises(ValueError, match="Invalid schedule_time"):
        DailyScheduler(db=mem_db, schedule_time="25:00")

    with pytest.raises(ValueError, match="Invalid schedule_time"):
        DailyScheduler(db=mem_db, schedule_time="06:60")

    with pytest.raises(ValueError, match="Invalid schedule_time"):
        DailyScheduler(db=mem_db, schedule_time="invalid_format")


def test_daylight_saving_transitions_america_new_york(mem_db):
    """Verifies that next_run preserves exact 06:00 wall-clock time across DST transitions."""
    scheduler = DailyScheduler(
        db=mem_db,
        schedule_time="06:00",
        timezone_str="America/New_York",
    )

    # 1. Spring-Forward Transition (Clocks advance 1 hr on 2026-03-08 at 02:00, 23-hour day)
    # Reference: 2026-03-07 10:00 (EST, UTC-5). Next run: 2026-03-08 06:00 (EDT, UTC-4).
    # Elapsed duration: 14 hrs on March 7 + 6 hrs on March 8 - 1 skipped hr = 19 physical hours.
    ref_spring = datetime(2026, 3, 7, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    next_spring, delay_spring = scheduler.calculate_next_run(now_dt=ref_spring)
    assert next_spring.year == 2026
    assert next_spring.month == 3
    assert next_spring.day == 8
    assert next_spring.hour == 6
    assert next_spring.minute == 0
    assert delay_spring == pytest.approx(19 * 3600.0, abs=1.0)

    # 2. Fall-Back Transition (Clocks retreat 1 hr on 2026-11-01 at 02:00, 25-hour day)
    # Reference: 2026-10-31 10:00 (EDT, UTC-4). Next run: 2026-11-01 06:00 (EST, UTC-5).
    # Elapsed duration: 14 hrs on Oct 31 + 6 hrs on Nov 1 + 1 repeated hr = 21 physical hours.
    ref_fall = datetime(2026, 10, 31, 10, 0, 0, tzinfo=ZoneInfo("America/New_York"))
    next_fall, delay_fall = scheduler.calculate_next_run(now_dt=ref_fall)
    assert next_fall.year == 2026
    assert next_fall.month == 11
    assert next_fall.day == 1
    assert next_fall.hour == 6
    assert next_fall.minute == 0
    assert delay_fall == pytest.approx(21 * 3600.0, abs=1.0)


# =============================================================================
# 2. Restart Duplicate Prevention
# =============================================================================
def test_restart_duplicate_prevention_skips_same_day(mem_db):
    """If application restarts after today's scheduled run completed, next run is tomorrow."""
    # Record a successful scheduled run for today (2026-10-10 05:00 UTC)
    today_run = PipelineRunRecord(
        id="run_20261010_050000_123456",
        trigger_type="SCHEDULED",
        started_at=datetime(2026, 10, 10, 5, 0, 0),
        completed_at=datetime(2026, 10, 10, 5, 1, 0),
        duration_seconds=60.0,
        status="SUCCESS",
        articles_discovered=10,
    )
    mem_db.insert_run(today_run)

    scheduler = DailyScheduler(
        db=mem_db,
        schedule_time="06:00",
        timezone_str="UTC",
    )

    # Reference time is 05:30 UTC (before the 06:00 target time)
    ref_now = datetime(2026, 10, 10, 5, 30, 0, tzinfo=ZoneInfo("UTC"))

    # Even though 05:30 < 06:00, today's run already completed, so it MUST schedule for tomorrow!
    assert scheduler.has_run_completed_today(ref_now) is True
    next_run, delay = scheduler.calculate_next_run(now_dt=ref_now)

    assert next_run.day == 11  # Tomorrow!
    assert next_run.hour == 6


def test_restart_runs_if_last_run_was_yesterday(mem_db):
    """If last successful run was yesterday, today's run is scheduled for today."""
    yesterday_run = PipelineRunRecord(
        id="run_20261009_060000_123456",
        trigger_type="SCHEDULED",
        started_at=datetime(2026, 10, 9, 6, 0, 0),
        completed_at=datetime(2026, 10, 9, 6, 1, 0),
        duration_seconds=60.0,
        status="SUCCESS",
    )
    mem_db.insert_run(yesterday_run)

    scheduler = DailyScheduler(
        db=mem_db,
        schedule_time="06:00",
        timezone_str="UTC",
    )

    ref_now = datetime(2026, 10, 10, 5, 0, 0, tzinfo=ZoneInfo("UTC"))
    assert scheduler.has_run_completed_today(ref_now) is False

    next_run, _ = scheduler.calculate_next_run(now_dt=ref_now)
    assert next_run.day == 10  # Today!
    assert next_run.hour == 6


# =============================================================================
# 3. Concurrency & Overlap Prevention
# =============================================================================
def test_lock_acquire_and_release(temp_lock_file):
    """Verifies acquiring and releasing the lock works normally."""
    lock = PipelineRunLock(lock_file_path=temp_lock_file)
    assert lock.acquire() is True
    assert lock.is_locked() is True
    lock.release()
    assert lock.is_locked() is False


def test_lock_prevents_concurrent_runs(temp_lock_file):
    """Verifies that attempting to acquire a held lock raises PipelineRunAlreadyActiveError."""
    lock1 = PipelineRunLock(lock_file_path=temp_lock_file)
    lock2 = PipelineRunLock(lock_file_path=temp_lock_file)

    with lock1:
        with pytest.raises(PipelineRunAlreadyActiveError):
            lock2.acquire()

    # After lock1 releases, lock2 can acquire successfully
    with lock2:
        assert lock2.is_locked() is True


def test_runner_overlap_rejection(mem_db, temp_lock_file):
    """DailyPipelineRunner raises PipelineRunAlreadyActiveError when another run is active."""
    runner1 = DailyPipelineRunner(db=mem_db, lock_file_path=temp_lock_file)
    runner2 = DailyPipelineRunner(db=mem_db, lock_file_path=temp_lock_file)

    # Acquire lock on runner1
    runner1.lock.acquire()
    try:
        with pytest.raises(PipelineRunAlreadyActiveError):
            runner2.run_pipeline(trigger_type="MANUAL", raise_on_overlap=True)

        # Without raise_on_overlap, returns record with status LOCKED_SKIPPED
        skipped = runner2.run_pipeline(trigger_type="SCHEDULED", raise_on_overlap=False)
        assert skipped.status == "LOCKED_SKIPPED"
    finally:
        runner1.lock.release()


# =============================================================================
# 4. Pipeline Run Lifecycle & SQLite Persistence
# =============================================================================
def test_pipeline_run_success_telemetry(mem_db, temp_lock_file):
    """Executes a pipeline run and verifies persisted telemetry in SQLite."""
    sample_articles = [
        _make_sample_article(
            url="https://example.com/ai/art1",
            title="OpenAI Unveils Reasoning Model",
            domain="AI",
            source="TechCrunch",
        ),
        _make_sample_article(
            url="https://example.com/cyber/art2",
            title="Zero-Day Vulnerability Discovered in Cloud Storage",
            domain="Cybersecurity",
            source="DarkReading",
        ),
    ]

    mock_metrics = PipelineMetrics(
        valid_articles=2,
        candidates_passed_to_llm=2,
        total_clusters=2,
        multi_source_clusters=0,
        qwen_calls=2,
        qwen_relevant=2,
        reduction_percentage=0.0,
    )

    mock_processor = MagicMock()
    mock_processor.process_with_metrics.return_value = ([], mock_metrics)

    runner = DailyPipelineRunner(
        db=mem_db,
        article_processor=mock_processor,
        lock_file_path=temp_lock_file,
    )

    record = runner.run_pipeline(
        trigger_type="MANUAL",
        articles=sample_articles,
    )

    assert record.status == "SUCCESS"
    assert record.trigger_type == "MANUAL"
    assert record.articles_discovered == 2
    assert record.articles_deduplicated == 2
    assert record.clusters_formed == 2
    assert record.qwen_evaluations == 2
    assert record.domain_counts.get("ai") == 1
    assert record.domain_counts.get("cybersecurity") == 1
    assert record.duration_seconds is not None
    assert record.completed_at is not None

    # Verify retrieval from database
    persisted = mem_db.get_run_by_id(record.id)
    assert persisted is not None
    assert persisted.status == "SUCCESS"
    assert persisted.articles_discovered == 2
    assert persisted.domain_counts == record.domain_counts

    # Verify get_recent_runs
    recent = mem_db.get_recent_runs(limit=5)
    assert len(recent) == 1
    assert recent[0].id == record.id

    # Verify get_last_successful_run
    last_success = mem_db.get_last_successful_run(trigger_type="MANUAL")
    assert last_success is not None
    assert last_success.id == record.id


def test_pipeline_run_partial_success_on_feed_errors(mem_db, temp_lock_file):
    """Verifies that isolated feed failures result in PARTIAL_SUCCESS with captured errors."""
    mock_connector = MagicMock()
    # 1 article from healthy feed, 1 failing feed
    mock_connector.fetch_all_domains.return_value = (
        [_make_sample_article(title="Healthy Story", domain="AI")],
        {
            "https://healthy.com/feed": {"status": "SUCCESS", "count": 1, "domain": "AI", "error": None},
            "https://failing.com/rss": {"status": "FAILED", "count": 0, "domain": "Science", "error": "503 Service Unavailable"},
        },
    )

    mock_processor = MagicMock()
    mock_metrics = PipelineMetrics(valid_articles=1, candidates_passed_to_llm=1, total_clusters=1, qwen_calls=1)
    mock_processor.process_with_metrics.return_value = ([], mock_metrics)

    runner = DailyPipelineRunner(
        db=mem_db,
        rss_connector=mock_connector,
        article_processor=mock_processor,
        lock_file_path=temp_lock_file,
    )

    record = runner.run_pipeline(trigger_type="SCHEDULED")

    assert record.status == "PARTIAL_SUCCESS"
    assert len(record.feed_errors) == 1
    assert "503 Service Unavailable" in record.feed_errors[0]
    assert record.articles_discovered == 1

    persisted = mem_db.get_run_by_id(record.id)
    assert persisted.status == "PARTIAL_SUCCESS"
    assert len(persisted.feed_errors) == 1


def test_pipeline_run_failed_on_all_feed_errors(mem_db, temp_lock_file):
    """Verifies that total ingestion failure marks run as FAILED with error message."""
    mock_connector = MagicMock()
    mock_connector.fetch_all_domains.return_value = (
        [],
        {
            "https://dead.com/feed": {"status": "FAILED", "count": 0, "domain": "AI", "error": "ConnectionRefusedError"},
        },
    )

    runner = DailyPipelineRunner(
        db=mem_db,
        rss_connector=mock_connector,
        lock_file_path=temp_lock_file,
    )

    record = runner.run_pipeline(trigger_type="SCHEDULED")

    assert record.status == "FAILED"
    assert record.articles_discovered == 0
    assert "ConnectionRefusedError" in record.error_message


def test_pipeline_run_critical_exception_handling(mem_db, temp_lock_file):
    """Verifies that an unhandled exception marks run as FAILED and releases the lock."""
    mock_connector = MagicMock()
    mock_connector.fetch_all_domains.side_effect = RuntimeError("Fatal hardware crash")

    runner = DailyPipelineRunner(
        db=mem_db,
        rss_connector=mock_connector,
        lock_file_path=temp_lock_file,
    )

    with pytest.raises(RuntimeError):
        runner.run_pipeline(trigger_type="SCHEDULED")

    # Lock must be released
    assert runner.lock.is_locked() is False

    # Run record in DB must be FAILED
    runs = mem_db.get_recent_runs(limit=1)
    assert len(runs) == 1
    assert runs[0].status == "FAILED"
    assert "Fatal hardware crash" in runs[0].error_message


# =============================================================================
# 5. Scheduler Lifecycle & Graceful Shutdown
# =============================================================================
def test_scheduler_manual_trigger(mem_db, temp_lock_file):
    """trigger_now executes manual run immediately and persists record."""
    runner = MagicMock()
    runner.run_pipeline.return_value = PipelineRunRecord(
        id="run_manual_test_01",
        trigger_type="MANUAL",
        status="SUCCESS",
    )

    scheduler = DailyScheduler(runner=runner, db=mem_db)
    rec = scheduler.trigger_now()

    assert rec.trigger_type == "MANUAL"
    assert rec.status == "SUCCESS"
    runner.run_pipeline.assert_called_once_with(trigger_type="MANUAL")


def test_scheduler_graceful_start_and_stop(mem_db):
    """Verifies starting background scheduler thread and stopping it cleanly."""
    scheduler = DailyScheduler(
        db=mem_db,
        schedule_time="23:59",
        timezone_str="UTC",
    )

    assert scheduler.is_running is False
    scheduler.start()
    assert scheduler.is_running is True

    # Allow thread to start
    time.sleep(0.05)

    scheduler.stop(timeout=1.0)
    assert scheduler.is_running is False


def test_stale_lock_recovery_after_process_termination(tmp_path):
    """Simulates unexpected process termination holding the lock; confirms lock recovers immediately."""
    import subprocess
    import sys

    lock_file = str(tmp_path / "proc_test.lock")

    # Child script that acquires lock, prints ACQUIRED, then sleeps
    proc_code = (
        "import time, portalocker\n"
        f"lock = portalocker.Lock(r'{lock_file}', flags=portalocker.LOCK_EX | portalocker.LOCK_NB)\n"
        "lock.acquire()\n"
        "print('ACQUIRED', flush=True)\n"
        "time.sleep(30)\n"
    )

    p = subprocess.Popen([sys.executable, "-c", proc_code], stdout=subprocess.PIPE, text=True)
    try:
        # Wait until child acquires lock
        line = p.stdout.readline().strip()
        assert line == "ACQUIRED"

        # Parent attempts to acquire lock -> must fail while child is alive
        parent_lock = PipelineRunLock(lock_file_path=lock_file)
        with pytest.raises(PipelineRunAlreadyActiveError):
            parent_lock.acquire()

        # Now simulate unexpected process termination / crash
        p.kill()
        p.wait()

        # OS kernel releases file handle; parent must acquire successfully
        assert parent_lock.acquire() is True
        assert parent_lock.is_locked() is True
        parent_lock.release()
    finally:
        if p.poll() is None:
            p.kill()


def test_sqlite_cleanup_interrupted_runs(mem_db):
    """Confirms that orphaned RUNNING records from crashes are safely marked FAILED."""
    interrupted_run = PipelineRunRecord(
        id="run_crashed_123",
        trigger_type="SCHEDULED",
        started_at=datetime.utcnow(),
        status="RUNNING",
    )
    mem_db.insert_run(interrupted_run)

    rec = mem_db.get_run_by_id("run_crashed_123")
    assert rec.status == "RUNNING"

    # Cleanup marks orphaned run as FAILED
    cleaned = mem_db.cleanup_interrupted_runs()
    assert cleaned == 1

    rec_after = mem_db.get_run_by_id("run_crashed_123")
    assert rec_after.status == "FAILED"
    assert "Interrupted" in rec_after.error_message


def test_manual_and_scheduled_share_same_pipeline_runner(mem_db, temp_lock_file):
    """Verifies that manual and scheduled triggers invoke the exact same DailyPipelineRunner."""
    mock_processor = MagicMock()
    mock_metrics = PipelineMetrics(valid_articles=1, candidates_passed_to_llm=1, total_clusters=1, qwen_calls=1)
    mock_processor.process_with_metrics.return_value = ([], mock_metrics)

    runner = DailyPipelineRunner(
        db=mem_db,
        article_processor=mock_processor,
        lock_file_path=temp_lock_file,
    )

    art = _make_sample_article()

    # 1. Manual trigger
    rec_manual = runner.run_pipeline(trigger_type="MANUAL", articles=[art])
    assert rec_manual.trigger_type == "MANUAL"
    assert rec_manual.status == "SUCCESS"

    # 2. Scheduled trigger
    rec_sched = runner.run_pipeline(trigger_type="SCHEDULED", articles=[art])
    assert rec_sched.trigger_type == "SCHEDULED"
    assert rec_sched.status == "SUCCESS"

    # Both recorded in SQLite
    runs = mem_db.get_recent_runs(limit=2)
    assert len(runs) == 2

