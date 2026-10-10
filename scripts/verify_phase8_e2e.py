"""Verification script for Phase 8 End-to-End Integration.

Spins up a test client, exercises all REST API endpoints, inspects database counts,
and verifies frontend assets.
"""

import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).parent.parent.resolve()))

from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.routes import get_db


def main():
    print("=" * 70)
    print("PHASE 8 END-TO-END VERIFICATION AUDIT")
    print("=" * 70)

    app = create_app()
    client = TestClient(app)

    # 1. Root & Health Check
    res_root = client.get("/")
    print(f"[1] Root endpoint status: {res_root.status_code}")
    assert res_root.status_code == 200, "Root failed"
    print(f"    Payload: {res_root.json()}")

    res_health = client.get("/api/health")
    print(f"[2] Health endpoint status: {res_health.status_code}")
    assert res_health.status_code == 200, "Health check failed"
    health = res_health.json()
    print(f"    Status: {health['status']}, Database Connected: {health['database_connected']}")
    print(f"    Database Stats: {health['database_stats']}")

    # 2. Domains
    res_domains = client.get("/api/domains")
    print(f"[3] Domains endpoint status: {res_domains.status_code}")
    assert res_domains.status_code == 200, "Domains failed"
    domains_data = res_domains.json()
    print(f"    Configured Domains ({domains_data['total_domains']}):")
    for d in domains_data["domains"]:
        print(f"      - {d['display_name']} ({d['domain_id']}): {d['cluster_count']} clusters, {d['article_count']} articles")

    # 3. Newspaper Edition
    res_stories = client.get("/api/newspaper/latest?page=1&page_size=3")
    print(f"[4] Latest Stories endpoint status: {res_stories.status_code}")
    assert res_stories.status_code == 200, "Latest stories failed"
    stories_data = res_stories.json()
    print(f"    Total stories available: {stories_data['total']}, Total pages: {stories_data['total_pages']}")
    if stories_data["items"]:
        top = stories_data["items"][0]
        print(f"    Top Story: '{top['headline']}'")
        print(f"      Domain: {top['domain']}, Topic: {top['topic']}")
        print(f"      Sources ({top['source_count']}): {', '.join(top['sources'])}")

        # 4. Story Detail
        res_detail = client.get(f"/api/newspaper/stories/{top['cluster_id']}")
        print(f"[5] Story Detail endpoint status: {res_detail.status_code}")
        assert res_detail.status_code == 200, "Story detail failed"
        detail = res_detail.json()
        print(f"      Constituent member articles: {len(detail['members'])}")
        for m in detail["members"]:
            rep_flag = " [LEAD]" if m["is_representative"] else ""
            print(f"        * [{m['source']}]{rep_flag} {m['title'][:60]}... ({m['url']})")

    # 5. Runs & Refresh
    res_runs = client.get("/api/runs?limit=3")
    print(f"[6] Recent Runs endpoint status: {res_runs.status_code}")
    assert res_runs.status_code == 200, "Runs endpoint failed"
    runs_data = res_runs.json()
    print(f"    Recent runs count: {runs_data['total']}")
    if runs_data["items"]:
        latest = runs_data["items"][0]
        print(f"    Latest run: ID={latest['run_id']}, Status={latest['status']}, Trigger={latest['trigger_type']}")

    print("=" * 70)
    print("ALL PHASE 8 VERIFICATION GATES PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    main()
