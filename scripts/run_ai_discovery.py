"""CLI demonstration of Phase 3.1 AI News Discovery Pipeline with Ranking & Latency Optimization."""

import argparse
import sys
import time
from pathlib import Path

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
from app.ingestion.rss import RSSConnector
from app.processing.article_processor import ArticleProcessor


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Phase 3.1 Optimized AI News Discovery Pipeline."
    )
    parser.add_argument(
        "--candidates",
        type=int,
        default=settings.qwen_max_candidates,
        help="Max top-ranked candidate articles to evaluate with Qwen (default: 10)",
    )
    parser.add_argument(
        "--skip-clustering",
        action="store_true",
        help="Skip semantic story clustering",
    )
    parser.add_argument(
        "--skip-extraction",
        action="store_true",
        help="Skip webpage fetching and rely on RSS excerpts directly",
    )
    args = parser.parse_args()

    print("=" * 68)
    print("AI DISCOVERY PIPELINE -- PHASE 4 (DEDUPLICATION & STORY CLUSTERING)")
    print("=" * 68)
    print(f"Target Domain: AI / Artificial Intelligence")
    print(f"Configured Sources: {len(settings.ai_rss_feeds)}")
    print(f"Top-K Candidate Evaluation Limit: {args.candidates}")
    print(f"Semantic Clustering: {'Disabled' if args.skip_clustering else 'Enabled'}")
    print("=" * 68)

    pipeline_start = time.time()

    # Step 1: Ingestion
    print("\n--- 1. Ingesting RSS Feeds ---")
    connector = RSSConnector()
    all_articles, statuses = connector.fetch_all(settings.ai_rss_feeds)

    print("\nSources:")
    for url, info in statuses.items():
        symbol = "[OK]" if info["status"] == "SUCCESS" else "[FAIL]"
        err_msg = f" ({info['error']})" if info["error"] else ""
        print(f"  {symbol} {url} -- {info['count']} articles{err_msg}")

    print(f"\nTotal Collected: {len(all_articles)}")

    # Step 2: Content Extraction, Pre-Filtering, Clustering, Ranking & Qwen Evaluation
    print(f"\n--- 2. Extraction, Pre-Filter, Story Clustering & Top-{args.candidates} Qwen Evaluation ---")
    processor = ArticleProcessor()

    processed_articles, metrics = processor.process_with_metrics(
        articles=all_articles,
        max_candidates=args.candidates,
        enable_extraction=not args.skip_extraction,
        enable_pre_filter=True,
        enable_clustering=not args.skip_clustering,
        enable_storage=settings.enable_storage,
    )

    print("\n--- 3. Top-Ranked Story Cluster Representatives & Qwen Classification Results ---\n")
    for idx, item in enumerate(processed_articles, start=1):
        rel_str = "YES" if item.classification.is_relevant else "NO"
        pf_score = item.pre_filter.pre_filter_score if item.pre_filter else 0.0
        tier = item.pre_filter.tier if item.pre_filter else "N/A"
        rank = item.ranking_score
        words = item.extracted_content.word_count if item.extracted_content else 0
        method = item.extracted_content.extraction_method if item.extracted_content else "none"
        sources_str = ", ".join(item.cluster_sources) if item.cluster_sources else item.article.source

        print(f"[{idx}] {item.article.title}")
        print(f"    Source (Canonical): {item.article.source}")
        if item.cluster_id:
            print(f"    Story Cluster:      {item.cluster_id} ({item.cluster_source_count} sources: {sources_str})")
        print(f"    URL:                {item.article.url}")
        print(f"    Extracted:          {words} words ({method})")
        print(f"    Rank Score:         {rank:.3f} (Tier: {tier}, PreFilter: {pf_score:.2f})")
        print(f"    Qwen Relevant:      {rel_str}")
        print(f"    Relevance Score:    {item.classification.relevance_score:.2f}")
        print(f"    Topic (Taxonomy):   {item.classification.topic}")
        print(f"    Reason:             {item.classification.reason}")
        print()

    total_pipeline_time = time.time() - pipeline_start

    print("=" * 68)
    print("PHASE 4 COMPLETE PIPELINE METRICS")
    print("=" * 68)
    print(f"RSS articles collected:           {metrics.total_rss_articles}")
    print(f"Valid articles after URL dedup:   {metrics.valid_articles}")
    print(f"Content extraction success:       {metrics.extraction_success}")
    print(f"Content extraction fallback:      {metrics.extraction_failed}")
    print(f"Rejected by deterministic filter: {metrics.rejected_pre_filter}")
    print(f"Pre-filter candidate pool:        {metrics.candidates_passed_to_llm}")
    print(f"Story clusters formed:            {metrics.total_clusters}")
    print(f"Multi-source story clusters:      {metrics.multi_source_clusters}")
    print(f"Clustering calls saved:           {metrics.clustering_saved_calls}")
    print(f"Clustering step runtime:          {metrics.clustering_runtime_seconds:.3f}s")
    print(f"Top-K candidates sent to Qwen:    {metrics.qwen_calls}")
    print(f"Total Qwen calls saved:           {metrics.valid_articles - metrics.qwen_calls}")
    print(f"Candidate pool reduction:         {metrics.reduction_percentage:.1f}%")
    print(f"Qwen confirmed relevant:          {metrics.qwen_relevant}")
    print(f"Qwen confirmed irrelevant:        {metrics.qwen_irrelevant}")
    print(f"Qwen total inference runtime:     {metrics.qwen_runtime_seconds:.2f}s")
    print(f"Average Qwen latency per call:    {metrics.average_qwen_seconds:.2f}s")
    print(f"Total pipeline execution time:    {total_pipeline_time:.2f}s")
    print("=" * 68)


if __name__ == "__main__":
    main()
