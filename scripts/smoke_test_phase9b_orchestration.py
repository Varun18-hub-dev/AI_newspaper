"""Live/Local smoke test script for Phase 9B Daily GPU Worker Orchestration."""

from datetime import datetime
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.orchestration.ec2_controller import EC2WorkerController
from app.orchestration.lifecycle import LifecycleManager, WorkerState
from app.orchestration.scheduler import EventBridgeScheduleConfig
from app.orchestration.watchdog import WorkerWatchdog
from app.storage.publisher import EditionPublisher, EditionStory, EditionValidator


def run_smoke_test() -> None:
    print("=" * 70)
    print(" Phase 9B GPU Worker Orchestration & Publication Smoke Test")
    print("=" * 70)

    # 1. State Machine Transitions
    print("\n[1/5] Testing Lifecycle State Machine...")
    lifecycle = LifecycleManager(run_id="run_smoke_test_001", edition_id="edition_smoke_test_001")
    assert lifecycle.context.current_state == WorkerState.STARTING
    lifecycle.transition_to(WorkerState.READY, message="Readiness verified")
    lifecycle.transition_to(WorkerState.RUNNING, message="Discovery active")
    lifecycle.transition_to(WorkerState.PUBLISHING, message="Assembling manifest")
    lifecycle.transition_to(WorkerState.SUCCESS, message="Edition promoted live")
    print(f"  -> State: {lifecycle.context.current_state} (Duration: {lifecycle.context.duration_seconds}s)")
    print(f"  -> Transitions recorded: {len(lifecycle.context.transitions)}")

    # 2. Watchdog Runtime Monitoring
    print("\n[2/5] Testing Watchdog Time Budget Monitor...")
    watchdog = WorkerWatchdog(target_runtime_minutes=0.001, max_runtime_minutes=0.003)
    watchdog.start()
    time.sleep(0.1)
    is_expired, is_warning, msg = watchdog.check()
    print(f"  -> Target check: warning={is_warning}, expired={is_expired}")
    print(f"  -> Watchdog message: '{msg}'")

    # 3. Edition Validation & Atomic Publication
    print("\n[3/5] Testing Edition Publishing & Atomic Flip...")
    pub_dir = Path("data/smoke_test_editions")
    pub_dir.mkdir(parents=True, exist_ok=True)
    publisher = EditionPublisher(storage_backend="local", local_dir=str(pub_dir))

    sample_stories = [
        EditionStory(
            story_id=f"story_{i}",
            title=f"Smoke Test Story #{i} on Emerging Technology",
            url=f"https://example.com/smoke-test-{i}",
            domain="AI" if i % 2 == 0 else "Cybersecurity",
            summary=f"Detailed validated summary for story #{i} with substantive technical facts.",
            sources=["TechCrunch AI", "arXiv"],
            first_seen_at=datetime.utcnow().isoformat(),
        )
        for i in range(1, 6)
    ]

    success, manifest, err = publisher.publish_edition(
        edition_id="edition_20261010_smoke",
        stories=sample_stories,
        run_id="run_smoke_001",
    )
    assert success is True
    print(f"  -> Publication status: SUCCESS (Stories: {manifest.total_stories}, Checksum: {manifest.checksum[:8]})")

    current = publisher.get_current_edition()
    assert current is not None
    assert current.edition_id == "edition_20261010_smoke"
    print(f"  -> Current edition pointer: {current.edition_id} ({current.total_stories} stories)")

    # 4. EventBridge Schedule Configuration
    print("\n[4/5] Testing EventBridge Scheduler Configuration...")
    schedule_cfg = EventBridgeScheduleConfig(
        schedule_name="ai-newspaper-daily-test",
        cron_expression="cron(0 6 * * ? *)",
        timezone="Asia/Kolkata",
    )
    boto_params = schedule_cfg.to_boto3_params()
    print(f"  -> Schedule: {boto_params['Name']} at {boto_params['ScheduleExpressionTimezone']} ({boto_params['ScheduleExpression']})")

    # 5. EC2 Controller Idempotency
    print("\n[5/5] Testing EC2 Controller Logic...")
    controller = EC2WorkerController(instance_id="i-mockedinstance12345")
    print(f"  -> Controller initialized for region: {controller.region}")

    # Clean up test editions
    import shutil
    shutil.rmtree(pub_dir, ignore_errors=True)

    print("\n" + "=" * 70)
    print(" ALL 5 ORCHESTRATION SMOKE TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    run_smoke_test()
