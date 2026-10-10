"""Live smoke test script for Phase 9A Multi-Source News Ingestion Integration.

Validates connectivity, response parsing, and normalization against real external endpoints:
1. arXiv Atom/RSS feed
2. Hacker News Firebase REST API
3. GitHub REST API (unauthenticated or with GITHUB_TOKEN)
4. NVD CVE REST API (unauthenticated or with NVD_API_KEY)
5. Configured Publisher RSS/Atom feeds
"""

from pathlib import Path
import sys
import time
from typing import Dict, Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion.adapters.arxiv import ArxivAdapter
from app.ingestion.adapters.github import GitHubAdapter
from app.ingestion.adapters.hackernews import HackerNewsAdapter
from app.ingestion.adapters.nvd import NVDAdapter
from app.ingestion.rss import RSSConnector
from app.domains.registry import get_domain_registry


def run_smoke_test() -> None:
    print("=" * 70)
    print(" Phase 9A Multi-Source News Ingestion Live Smoke Test")
    print("=" * 70)

    results: Dict[str, Dict[str, Any]] = {}

    # 1. arXiv Adapter
    print("\n[1/5] Testing arXiv Adapter (cs.AI)...")
    arxiv = ArxivAdapter(categories=["cs.AI"], max_results_per_category=3)
    try:
        t0 = time.time()
        articles, telem = arxiv.fetch(limit=3)
        elapsed = round(time.time() - t0, 2)
        results["arXiv"] = {
            "status": telem.get("status"),
            "count": len(articles),
            "latency": elapsed,
            "sample": articles[0].title if articles else "None",
        }
        print(f"  -> Status: {telem.get('status')} | Ingested: {len(articles)} in {elapsed}s")
        if articles:
            print(f"  -> Sample: '{articles[0].title[:65]}...' ({articles[0].url})")
    except Exception as e:
        results["arXiv"] = {"status": "FAILED", "count": 0, "error": str(e)}
        print(f"  -> Error: {e}")

    # 2. Hacker News Adapter
    print("\n[2/5] Testing Hacker News Adapter...")
    hn = HackerNewsAdapter(min_score=15, max_items=3)
    try:
        t0 = time.time()
        articles, telem = hn.fetch(limit=3)
        elapsed = round(time.time() - t0, 2)
        results["Hacker News"] = {
            "status": telem.get("status"),
            "count": len(articles),
            "latency": elapsed,
            "sample": articles[0].title if articles else "None",
        }
        print(f"  -> Status: {telem.get('status')} | Ingested: {len(articles)} in {elapsed}s")
        if articles:
            print(f"  -> Sample: '{articles[0].title[:65]}...' ({articles[0].url})")
    except Exception as e:
        results["Hacker News"] = {"status": "FAILED", "count": 0, "error": str(e)}
        print(f"  -> Error: {e}")

    # 3. GitHub Adapter
    print("\n[3/5] Testing GitHub Adapter...")
    gh = GitHubAdapter(min_stars=200, max_items=2)
    try:
        t0 = time.time()
        articles, telem = gh.fetch(limit=2)
        elapsed = round(time.time() - t0, 2)
        results["GitHub"] = {
            "status": telem.get("status"),
            "count": len(articles),
            "latency": elapsed,
            "sample": articles[0].title if articles else "None",
        }
        print(f"  -> Status: {telem.get('status')} | Ingested: {len(articles)} in {elapsed}s")
        if articles:
            print(f"  -> Sample: '{articles[0].title[:65]}...' ({articles[0].url})")
    except Exception as e:
        results["GitHub"] = {"status": "FAILED", "count": 0, "error": str(e)}
        print(f"  -> Error: {e}")

    # 4. NVD Adapter
    print("\n[4/5] Testing NVD Adapter...")
    nvd = NVDAdapter(results_per_page=2)
    try:
        t0 = time.time()
        articles, telem = nvd.fetch(limit=2)
        elapsed = round(time.time() - t0, 2)
        results["NVD"] = {
            "status": telem.get("status"),
            "count": len(articles),
            "latency": elapsed,
            "sample": articles[0].title if articles else "None",
        }
        print(f"  -> Status: {telem.get('status')} | Ingested: {len(articles)} in {elapsed}s")
        if articles:
            print(f"  -> Sample: '{articles[0].title[:65]}...' ({articles[0].url})")
    except Exception as e:
        results["NVD"] = {"status": "FAILED", "count": 0, "error": str(e)}
        print(f"  -> Error: {e}")

    # 5. Publisher RSS Sample (one from each domain)
    print("\n[5/5] Testing Publisher RSS Feeds across 5 domains...")
    rss = RSSConnector(max_items_per_feed=2)
    sample_feeds = [
        ("AI", "https://bair.berkeley.edu/blog/feed.xml"),
        ("Technology", "https://feeds.arstechnica.com/arstechnica/index"),
        ("Science", "https://www.nature.com/nature.rss"),
        ("Cybersecurity", "https://www.bleepingcomputer.com/feed/"),
        ("Business and startups", "https://siliconangle.com/feed/"),
    ]
    rss_count = 0
    t0 = time.time()
    for domain, url in sample_feeds:
        try:
            arts, _ = rss.fetch_all(urls=[url], domain=domain)
            rss_count += len(arts)
            print(f"  -> [{domain}] {url[:45]}... : {len(arts)} articles")
        except Exception as e:
            print(f"  -> [{domain}] {url[:45]}... : FAILED ({e})")
    elapsed_rss = round(time.time() - t0, 2)
    results["Publisher RSS"] = {
        "status": "SUCCESS" if rss_count > 0 else "FAILED",
        "count": rss_count,
        "latency": elapsed_rss,
    }

    # Summary Table
    print("\n" + "=" * 70)
    print(" SMOKE TEST SUMMARY TABLE")
    print("=" * 70)
    print(f"{'Source':<18} | {'Status':<12} | {'Count':<6} | {'Latency':<8}")
    print("-" * 52)
    for source, data in results.items():
        print(f"{source:<18} | {str(data.get('status')):<12} | {str(data.get('count')):<6} | {str(data.get('latency')) + 's':<8}")
    print("=" * 70)


if __name__ == "__main__":
    run_smoke_test()
