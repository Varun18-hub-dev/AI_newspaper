"""Benchmarking script testing different Qwen candidate batch sizes."""

import sys
import time
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.core.config import settings
from app.ingestion.rss import RSSConnector
from app.processing.article_processor import ArticleProcessor


def run_benchmark():
    print("=" * 65)
    print("PHASE 3.1: BATCH SIZE & LATENCY BENCHMARKING")
    print("=" * 65)

    connector = RSSConnector()
    articles, _ = connector.fetch_all(settings.ai_rss_feeds)
    print(f"Ingested {len(articles)} raw articles for benchmarking.")

    batch_sizes = [5, 10]
    results = {}

    for k in batch_sizes:
        print(f"\n--- Testing Top-K Batch Size: {k} ---")
        processor = ArticleProcessor()
        t0 = time.time()
        processed, metrics = processor.process_with_metrics(
            articles=articles,
            max_candidates=k,
            enable_extraction=False,  # Use RSS excerpts for consistent inference benchmarking
            enable_pre_filter=True,
        )
        wall_time = time.time() - t0

        results[k] = {
            "evaluated": len(processed),
            "relevant": metrics.qwen_relevant,
            "irrelevant": metrics.qwen_irrelevant,
            "qwen_runtime": metrics.qwen_runtime_seconds,
            "avg_latency": metrics.average_qwen_seconds,
            "total_time": round(wall_time, 2),
            "topics": [p.classification.topic for p in processed if p.classification.is_relevant],
        }

        print(f"Batch Size {k} Completed:")
        print(f"  Articles Evaluated: {results[k]['evaluated']}")
        print(f"  Relevant Found:     {results[k]['relevant']}")
        print(f"  Qwen Runtime:       {results[k]['qwen_runtime']:.2f}s")
        print(f"  Avg Latency/call:   {results[k]['avg_latency']:.2f}s")
        print(f"  Topics Identified:  {set(results[k]['topics'])}")

    print("\n" + "=" * 65)
    print("BATCH SIZE COMPARISON SUMMARY")
    print("=" * 65)
    print(f"{'Batch Size':<12} | {'Relevant':<10} | {'Qwen Time (s)':<15} | {'Avg/Call (s)':<14} | {'Total Time (s)':<14}")
    print("-" * 65)
    for k, data in results.items():
        print(f"{k:<12} | {data['relevant']:<10} | {data['qwen_runtime']:<15.2f} | {data['avg_latency']:<14.2f} | {data['total_time']:<14.2f}")
    print("=" * 65)


if __name__ == "__main__":
    run_benchmark()
