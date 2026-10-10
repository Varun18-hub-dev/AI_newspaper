"""CLI entry point for daily scheduling, manual runs, and run telemetry status."""

import argparse
from datetime import datetime
import os
from pathlib import Path
import signal
import sys
import time

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.core.config import settings
from app.core.logging import setup_logger
from app.scheduler.lock import PipelineRunAlreadyActiveError
from app.scheduler.runner import DailyPipelineRunner
from app.scheduler.scheduler import DailyScheduler
from app.storage.sqlite import SQLiteDatabase

logger = setup_logger("run_scheduler_cli")


def format_runs_table(runs: list) -> str:
    """Formats a list of PipelineRunRecords as a human-readable text table."""
    if not runs:
        return "No pipeline runs recorded in database."

    header = (
        f"{'Run ID':<26} | {'Trigger':<9} | {'Started (UTC)':<19} | "
        f"{'Duration':<8} | {'Status':<15} | {'Disc.':<5} | {'Clust.':<6} | {'Qwen':<4} | {'Errors':<6}"
    )
    separator = "-" * len(header)
    rows = [separator, header, separator]

    for r in runs:
        dur = f"{r.duration_seconds:.1f}s" if r.duration_seconds is not None else "-"
        started = r.started_at.strftime("%Y-%m-%d %H:%M:%S") if r.started_at else "-"
        err_count = len(r.feed_errors) if r.feed_errors else 0
        row_str = (
            f"{r.id:<26} | {r.trigger_type:<9} | {started:<19} | "
            f"{dur:<8} | {r.status:<15} | {r.articles_discovered:<5} | "
            f"{r.clusters_formed:<6} | {r.qwen_evaluations:<4} | {err_count:<6}"
        )
        rows.append(row_str)

    rows.append(separator)
    return "\n".join(rows)


def print_status(db: SQLiteDatabase, limit: int = 10) -> None:
    """Prints recent pipeline runs and current database stats."""
    print("\n" + "=" * 90)
    print("PERSONALIZED AI NEWSPAPER - PIPELINE RUN HISTORY")
    print("=" * 90)

    stats = db.get_database_stats()
    print(f"Database Path:         {stats.get('db_path')}")
    print(f"Total Persistent Runs: {stats.get('total_pipeline_runs')}")
    print(f"Total Stored Articles: {stats.get('total_articles')}")
    print(f"Total Story Clusters:  {stats.get('total_story_clusters')}")
    print(f"Total Cluster Members: {stats.get('total_cluster_members')}")
    print("\nRecent Pipeline Runs:")

    runs = db.get_recent_runs(limit=limit)
    print(format_runs_table(runs))
    print()


def run_now(
    domains: list[str] | None = None,
    max_candidates: int | None = None,
) -> int:
    """Executes the pipeline immediately as a manual trigger."""
    print("\n" + "=" * 70)
    print("Executing Manual Pipeline Run (--now)")
    print("=" * 70)

    runner = DailyPipelineRunner()
    try:
        record = runner.run_pipeline(
            trigger_type="MANUAL",
            domains=domains,
            max_candidates=max_candidates,
            raise_on_overlap=True,
        )
        print(f"\nPipeline Run Completed:")
        print(f"  Run ID:              {record.id}")
        print(f"  Status:              {record.status}")
        print(f"  Duration:            {record.duration_seconds:.2f} seconds")
        print(f"  Articles Discovered: {record.articles_discovered}")
        print(f"  Unique Deduplicated: {record.articles_deduplicated}")
        print(f"  Candidates Retained: {record.articles_prefiltered}")
        print(f"  Story Clusters:      {record.clusters_formed}")
        print(f"  Qwen Evaluations:    {record.qwen_evaluations}")
        print(f"  Domain Breakdown:    {record.domain_counts}")
        if record.feed_errors:
            print(f"  Feed Ingest Errors ({len(record.feed_errors)}):")
            for err in record.feed_errors:
                print(f"    - {err}")

        return 0 if record.status in ("SUCCESS", "PARTIAL_SUCCESS") else 1

    except PipelineRunAlreadyActiveError as lock_err:
        print(f"\n[BLOCKED] Cannot execute run: {lock_err}")
        return 2
    except Exception as err:
        print(f"\n[FAILED] Pipeline run failed: {err}")
        return 1


def run_daemon(
    schedule_time: str | None = None,
    timezone_str: str | None = None,
    run_on_startup: bool = False,
) -> None:
    """Runs the scheduler loop in the foreground, responding to SIGINT / SIGTERM."""
    target_time = schedule_time or settings.schedule_time
    target_tz = timezone_str or settings.schedule_timezone

    print("\n" + "=" * 70)
    print("Starting Daily Scheduler Daemon")
    print("=" * 70)
    print(f"Scheduled Daily Execution Time: {target_time} ({target_tz})")
    print(f"Run on Startup:                 {run_on_startup}")
    print("Press Ctrl+C to stop.\n")

    scheduler = DailyScheduler(
        schedule_time=target_time,
        timezone_str=target_tz,
        run_on_startup=run_on_startup,
    )

    # Calculate and display next run
    next_dt, delay_sec = scheduler.calculate_next_run()
    print(f"Next scheduled execution at: {next_dt.isoformat()} (in {delay_sec:.0f}s / {delay_sec/3600:.2f}h)")

    # Graceful shutdown handler
    def handle_signal(sig, frame):
        print("\nShutdown signal received. Stopping scheduler gracefully...")
        scheduler.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    scheduler.start()

    try:
        while scheduler.is_running:
            time.sleep(1.0)
    except KeyboardInterrupt:
        handle_signal(None, None)


def main() -> None:
    """Parses command-line arguments and routes to appropriate execution mode."""
    parser = argparse.ArgumentParser(
        description="Personalized AI Newspaper - Daily Scheduling & Automation CLI"
    )
    group = parser.add_mutually_exclusive_group(required=False)
    group.add_argument(
        "--now",
        action="store_true",
        help="Run discovery pipeline immediately as a manual trigger and exit.",
    )
    group.add_argument(
        "--daemon",
        action="store_true",
        help="Start the background daily scheduler daemon.",
    )
    group.add_argument(
        "--status",
        action="store_true",
        help="View recent pipeline run telemetry and database statistics.",
    )

    parser.add_argument(
        "--time",
        type=str,
        default=None,
        help="Scheduled execution time in HH:MM format (default: 06:00).",
    )
    parser.add_argument(
        "--timezone",
        type=str,
        default=None,
        help="IANA timezone for scheduling (e.g. UTC, America/New_York, Asia/Kolkata).",
    )
    parser.add_argument(
        "--domains",
        type=str,
        default=None,
        help="Comma-separated domains to process (e.g. ai,technology,cybersecurity).",
    )
    parser.add_argument(
        "--max-candidates",
        type=int,
        default=None,
        help="Max candidate articles for LLM evaluation.",
    )
    parser.add_argument(
        "--run-on-startup",
        action="store_true",
        default=False,
        help="Run immediately on daemon startup if today's run has not yet succeeded.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of recent runs to display in --status (default: 10).",
    )

    args = parser.parse_args()
    db = SQLiteDatabase()

    if args.status:
        print_status(db, limit=args.limit)
        sys.exit(0)

    if args.now:
        domain_list = [d.strip() for d in args.domains.split(",") if d.strip()] if args.domains else None
        code = run_now(domains=domain_list, max_candidates=args.max_candidates)
        sys.exit(code)

    if args.daemon:
        run_daemon(
            schedule_time=args.time,
            timezone_str=args.timezone,
            run_on_startup=args.run_on_startup,
        )
        sys.exit(0)

    # If no flags passed, display status and help
    print_status(db, limit=5)
    parser.print_help()


if __name__ == "__main__":
    main()
