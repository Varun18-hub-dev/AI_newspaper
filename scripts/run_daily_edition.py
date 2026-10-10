"""Unified CLI runner for daily newspaper publication supporting both CPU-only and GPU modes."""

import argparse
from datetime import datetime
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.core.logging import setup_logger
from app.orchestration.runner import GPUWorkerPipelineRunner

logger = setup_logger("daily_edition_cli")


def main():
    parser = argparse.ArgumentParser(description="Run daily newspaper publication pipeline.")
    parser.add_argument(
        "--cpu-only",
        action="store_true",
        help="Run in CPU-only mode (deterministic source-grounded summaries, no LLM inference).",
    )
    parser.add_argument(
        "--agentic",
        action="store_true",
        help="Enable LangGraph agentic intelligence workflow for high-value synthesis.",
    )
    parser.add_argument(
        "--domains",
        type=str,
        default=None,
        help="Comma-separated list of domains to ingest (e.g. ai,technology,science).",
    )
    parser.add_argument(
        "--auto-stop",
        action="store_true",
        help="Automatically stop EC2 instance upon completion.",
    )
    parser.add_argument(
        "--storage-backend",
        type=str,
        choices=["local", "s3"],
        default=None,
        help="Edition storage backend destination ('local' or 's3').",
    )

    args = parser.parse_args()

    domains_list = [d.strip() for d in args.domains.split(",")] if args.domains else None

    # Determine inference mode
    use_llm = not args.cpu_only
    if args.cpu_only:
        print("[INFO] CPU-only mode requested: generative LLM inference will be disabled.")
    elif args.agentic:
        print("[INFO] Agentic intelligence mode requested: LangGraph orchestration active.")
    else:
        print("[INFO] Standard LLM inference mode active.")

    runner = GPUWorkerPipelineRunner()

    success, manifest, context = runner.run_worker_pipeline(
        domains=domains_list,
        enable_agentic_workflow=args.agentic,
        auto_stop_on_finish=args.auto_stop,
        enable_llm_inference=use_llm,
    )

    if success and manifest:
        print("\n" + "=" * 65)
        print(" [SUCCESS] Daily Edition Published Successfully!")
        print("=" * 65)
        print(f"  Edition ID:      {manifest.edition_id}")
        print(f"  Publication Date:{manifest.publication_date}")
        print(f"  Total Stories:   {manifest.total_stories}")
        print(f"  Domain Breakdown:{json.dumps(manifest.domain_counts, indent=2)}")
        print(f"  Checksum:        {manifest.checksum[:16]}...")
        print("=" * 65)
        sys.exit(0)
    else:
        print("\n" + "=" * 65)
        print(" [FAILED] Daily Edition Publication Failed.")
        print("=" * 65)
        print(f"  Worker State:    {context.get('current_state')}")
        print(f"  Error Message:   {context.get('last_message')}")
        print("=" * 65)
        sys.exit(1)


if __name__ == "__main__":
    main()
