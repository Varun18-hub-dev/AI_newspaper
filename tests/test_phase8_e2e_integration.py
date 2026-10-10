"""End-to-end integration test for Phase 8: Database -> FastAPI -> Client Contract."""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.routes import get_db, get_runner
from app.domains.registry import get_domain_registry


@pytest.fixture(scope="module")
def api_client():
    """Provides a shared TestClient with the full FastAPI application."""
    app = create_app()
    with TestClient(app) as client:
        yield client


class TestPhase8EndToEndIntegration:
    """Verifies end-to-end data flow, multi-domain filtering, pagination, and error handling."""

    def test_e2e_health_and_database_telemetry(self, api_client):
        """Validates that /api/health reflects live SQLite database state."""
        res = api_client.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["database_connected"] is True

        db = get_db()
        stats = db.get_database_stats()
        assert data["database_stats"]["total_articles"] == stats.get("total_articles", 0)
        assert data["database_stats"]["total_story_clusters"] == stats.get("total_story_clusters", 0)

    def test_e2e_domain_registry_consistency(self, api_client):
        """Validates that /api/domains matches registry configuration and counts."""
        res = api_client.get("/api/domains")
        assert res.status_code == 200
        data = res.json()
        assert data["total_domains"] >= 5

        registry = get_domain_registry()
        registered_keys = {d.domain_id for d in registry.list_domains(enabled_only=False)}
        api_domains = {d["domain_id"] for d in data["domains"]}

        for d_cfg in registry.list_domains(enabled_only=False):
            assert d_cfg.domain_id in api_domains
            # Find the domain payload
            dom_payload = next(d for d in data["domains"] if d["domain_id"] == d_cfg.domain_id)
            assert dom_payload["display_name"] == d_cfg.display_name
            assert dom_payload["topics"] == d_cfg.allowed_topics

    def test_e2e_latest_newspaper_and_pagination(self, api_client):
        """Validates pagination flow across newspaper edition stories."""
        # Page 1 with page_size=2
        res1 = api_client.get("/api/newspaper/latest?page=1&page_size=2")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["page"] == 1
        assert data1["page_size"] == 2
        total = data1["total"]

        if total > 2:
            assert len(data1["items"]) == 2
            # Page 2
            res2 = api_client.get("/api/newspaper/latest?page=2&page_size=2")
            assert res2.status_code == 200
            data2 = res2.json()
            assert data2["page"] == 2
            # Items on page 1 and page 2 must be disjoint
            p1_ids = {s["cluster_id"] for s in data1["items"]}
            p2_ids = {s["cluster_id"] for s in data2["items"]}
            assert p1_ids.isdisjoint(p2_ids)

    def test_e2e_multi_domain_filtering(self, api_client):
        """Validates domain-specific filtering for each registered domain."""
        for domain_slug in ["ai", "technology", "science", "cybersecurity", "business"]:
            res = api_client.get(f"/api/newspaper/latest?domain={domain_slug}&page=1&page_size=10")
            assert res.status_code == 200
            data = res.json()
            assert data["domain_filter"] == domain_slug
            for item in data["items"]:
                assert item["domain"].lower() == domain_slug

    def test_e2e_story_detail_and_source_attribution(self, api_client):
        """Validates that a story detail contains valid constituent articles and links."""
        res = api_client.get("/api/newspaper/latest?page=1&page_size=5")
        assert res.status_code == 200
        items = res.json().get("items", [])
        if not items:
            pytest.skip("No story clusters in database")

        story = items[0]
        cluster_id = story["cluster_id"]

        detail_res = api_client.get(f"/api/newspaper/stories/{cluster_id}")
        assert detail_res.status_code == 200
        detail = detail_res.json()
        assert detail["cluster_id"] == cluster_id
        assert detail["headline"] == story["headline"]
        assert len(detail["members"]) >= 1

        # Check member articles
        has_primary = False
        for m in detail["members"]:
            assert m["article_id"]
            assert m["title"]
            assert m["url"].startswith("http")
            assert m["source"]
            if m["is_representative"]:
                has_primary = True

        assert has_primary is True, "At least one member article must be designated as representative."

    def test_e2e_invalid_story_returns_404(self, api_client):
        """Validates that an invalid story cluster ID returns 404."""
        res = api_client.get("/api/newspaper/stories/cluster_does_not_exist_9999")
        assert res.status_code == 404
        assert "not found" in res.json()["detail"].lower()

    def test_e2e_invalid_query_params_return_422(self, api_client):
        """Validates that invalid pagination parameters return 422 Unprocessable Entity."""
        res = api_client.get("/api/newspaper/latest?page=0")  # ge=1
        assert res.status_code == 422

        res2 = api_client.get("/api/newspaper/latest?page_size=100")  # le=50
        assert res2.status_code == 422

    def test_e2e_concurrency_lock_collision(self, api_client):
        """Validates that simultaneous refresh attempts trigger HTTP 409 Conflict."""
        runner = get_runner()
        with patch.object(runner.lock, "is_locked", return_value=True):
            res = api_client.post("/api/runs/refresh")
            assert res.status_code == 409
            assert "already currently active" in res.json()["detail"]

    def test_e2e_manual_refresh_trigger_accepted(self, api_client):
        """Validates that when free, refresh triggers background execution with 202."""
        runner = get_runner()
        with patch.object(runner.lock, "is_locked", return_value=False):
            with patch("app.api.routes._execute_refresh_in_background") as mock_exec:
                res = api_client.post("/api/runs/refresh")
                assert res.status_code == 202
                data = res.json()
                assert data["status"] == "TRIGGERED"
