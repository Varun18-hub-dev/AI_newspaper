"""CLI demonstration of Phase 6 Multi-Domain News Discovery Pipeline."""

import argparse
import sys
import time
from pathlib import Path
from typing import List

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from app.core.config import settings
from app.domains.registry import get_domain_registry
from app.ingestion.rss import RSSConnector
from app.processing.article_processor import ArticleProcessor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase 6 Multi-Domain News Discovery Pipeline."
    )
    parser.add_argument(
        "--domains",
        type=str,
        default=None,
        help="Comma-separated domains to discover (e.g. 'ai,technology,science,cybersecurity,business').",
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=5,
        help="Maximum candidates to evaluate with Qwen (default: 5).",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip full DOM webpage extraction and rely on RSS descriptions.",
    )
    parser.add_argument(
        "--skip-clustering",
        action="store_true",
        help="Skip semantic story clustering and process raw candidates directly.",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Skip LLM classification (ingestion, pre-filter, and clustering smoke test only).",
    )
    parser.add_argument(
        "--items-per-feed",
        type=int,
        default=5,
        help="Maximum items to fetch per feed for fast demonstration (default: 5).",
    )

    args = parser.parse_args()

    registry = get_domain_registry()
    if args.domains:
        target_domains = [d.strip().lower() for d in args.domains.split(",") if d.strip()]
    else:
        target_domains = [d.domain_id for d in registry.list_domains(enabled_only=True)]

    print("=" * 80)
    print("PHASE 6 MULTI-DOMAIN NEWS DISCOVERY PIPELINE")
    print(f"Target Domains: {', '.join(target_domains)}")
    print(f"Max candidates for LLM: {args.candidates}")
    print("=" * 80)

    # Step 1: Ingestion
    print("\n--- 1. Multi-Domain RSS Feed Ingestion ---")
    connector = RSSConnector(max_items_per_feed=args.items_per_feed)
    t0 = time.time()
    all_articles, feed_statuses = connector.fetch_all_domains(domain_keys=target_domains)
    ingest_time = time.time() - t0

    domain_counts = {}
    for a in all_articles:
        domain_counts[a.domain] = domain_counts.get(a.domain, 0) + 1

    print(f"\nFeed Ingestion Summary ({len(feed_statuses)} feeds in {ingest_time:.2f}s):")
    for url, info in feed_statuses.items():
        symbol = "[OK]" if info["status"] == "SUCCESS" else "[FAIL]"
        dom = info.get("domain", "Unknown")
        err_msg = f" ({info['error']})" if info["error"] else ""
        print(f"  {symbol} [{dom}] {url} -- {info['count']} items{err_msg}")

    print(f"\nTotal Ingested Articles: {len(all_articles)}")
    print("Articles by Domain:")
    for dom, cnt in sorted(domain_counts.items()):
        print(f"  - {dom}: {cnt} articles")

    if not all_articles:
        print("\nNo articles were discovered. Exiting.")
        return

    # Step 2: Processing Pipeline
    print(f"\n--- 2. Extraction, Pre-Filter, Story Clustering & Top-{args.candidates} Qwen Evaluation ---")
    processor = ArticleProcessor()
    max_cands = 0 if args.skip_llm else args.candidates

    processed_articles, metrics = processor.process_with_metrics(
        articles=all_articles,
        max_candidates=max_cands,
        enable_extraction=not args.skip_extraction,
        enable_pre_filter=True,
        enable_clustering=not args.skip_clustering,
        enable_storage=False,
    )

    # Step 3: Reporting Results
    print("\n--- 3. Discovered Articles & Classification Results ---\n")
    if not processed_articles:
        print("No articles passed pre-filtering or were selected for LLM classification.")
    else:
        for idx, item in enumerate(processed_articles, start=1):
            rel_str = "YES" if item.classification.is_relevant else "NO"
            score = item.classification.relevance_score
            topic = item.classification.topic
            dom = item.article.domain
            pf_score = item.pre_filter.pre_filter_score if item.pre_filter else 0.0
            tier = item.pre_filter.tier if item.pre_filter else "N/A"
            rank = item.ranking_score
            sources_str = ", ".join(item.cluster_sources) if item.cluster_sources else item.article.source

            print(f"[{idx}] [{dom}] {item.article.title}")
            print(f"    Source:             {item.article.source} (All: {', '.join(item.article.all_sources)})")
            if item.cluster_id:
                print(f"    Story Cluster:      {item.cluster_id} ({item.cluster_source_count} sources: {sources_str})")
            print(f"    Pre-Filter:         Score: {pf_score:.2f} | Tier: {tier} | Rank: {rank:.3f}")
            print(f"    LLM Classification: Relevant: {rel_str} (Score: {score:.2f}) | Domain: {dom} | Topic: {topic}")
            print(f"    Reason:             {item.classification.reason}")
            print()

    # Step 4: Telemetry Summary
    print("=" * 80)
    print("PIPELINE TELEMETRY & PERFORMANCE METRICS")
    print("=" * 80)
    print(f"Total Ingested Articles:          {metrics.total_rss_articles}")
    print(f"Valid Deduplicated Articles:      {metrics.valid_articles}")
    print(f"Articles Filtered Out:            {metrics.total_rss_articles - metrics.valid_articles}")
    print(f"Pre-Filter Retention:             {metrics.candidates_passed_to_llm}/{metrics.valid_articles} ({metrics.reduction_percentage}% reduction)")
    print(f"Total Story Clusters Formed:      {metrics.total_clusters} ({metrics.multi_source_clusters} multi-source)")
    print(f"LLM Evals Executed:               {metrics.qwen_calls} (Relevant: {metrics.qwen_relevant}, Irrelevant: {metrics.qwen_irrelevant})")
    print(f"Compute Calls Avoided:            {metrics.qwen_calls_saved}")
    print(f"Total Pipeline Runtime:           {metrics.total_runtime_seconds:.2f}s")
    if metrics.qwen_calls > 0:
        print(f"Average Qwen Latency:             {metrics.average_qwen_seconds:.2f}s/article")
    print("=" * 80)


if __name__ == "__main__":
    main()
