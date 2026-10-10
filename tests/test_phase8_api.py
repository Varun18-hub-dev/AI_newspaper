"""Unit and integration tests for Phase 8 FastAPI backend API."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.api.app import create_app
from app.api.routes import get_db, get_runner
from app.storage.sqlite import SQLiteDatabase


@pytest.fixture
def client():
    """Provides a TestClient fixture with the FastAPI application."""
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_api_root(client):
    """Verifies that the root endpoint returns API metadata."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Personalized AI Newspaper API"
    assert data["version"] == "1.0.0"
    assert "/docs" in data["docs_url"]


def test_health_endpoint(client):
    """Verifies the health check endpoint returns 200 and database stats."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("ok", "degraded")
    assert data["database_connected"] is True
    assert "total_articles" in data["database_stats"]
    assert "total_story_clusters" in data["database_stats"]


def test_domains_endpoint(client):
    """Verifies that the domains endpoint lists configured domains with counts."""
    response = client.get("/api/domains")
    assert response.status_code == 200
    data = response.json()
    assert "domains" in data
    assert data["total_domains"] >= 5
    domain_ids = [d["domain_id"] for d in data["domains"]]
    assert "ai" in domain_ids
    assert "technology" in domain_ids
    assert "cybersecurity" in domain_ids
    assert "science" in domain_ids
    assert "business" in domain_ids

    # Each domain should include topics and display name
    for d in data["domains"]:
        assert "display_name" in d
        assert "topics" in d
        assert isinstance(d["topics"], list)
        assert "article_count" in d
        assert "cluster_count" in d


def test_latest_newspaper_pagination(client):
    """Verifies pagination and structure of the latest newspaper stories endpoint."""
    response = client.get("/api/newspaper/latest?page=1&page_size=5")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data
    assert data["page"] == 1
    assert data["page_size"] == 5
    assert "total_pages" in data

    if data["items"]:
        story = data["items"][0]
        assert "cluster_id" in story
        assert "headline" in story
        assert "domain" in story
        assert "member_count" in story
        assert "sources" in story
        assert isinstance(story["sources"], list)
        assert "published_at" in story


def test_latest_newspaper_domain_filter(client):
    """Verifies domain filtering in latest newspaper stories."""
    response = client.get("/api/newspaper/latest?domain=ai&page=1&page_size=10")
    assert response.status_code == 200
    data = response.json()
    assert data["domain_filter"] == "ai"
    for story in data["items"]:
        assert story["domain"].lower() == "ai"


def test_story_detail_not_found(client):
    """Verifies 404 response for non-existent story cluster."""
    response = client.get("/api/newspaper/stories/nonexistent_cluster_id_12345")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_story_detail_success(client):
    """Verifies fetching details of an existing story cluster."""
    # First get an existing story ID
    list_res = client.get("/api/newspaper/latest?page=1&page_size=1")
    assert list_res.status_code == 200
    stories = list_res.json().get("items", [])
    if not stories:
        pytest.skip("No stories in database to test detail endpoint")

    cluster_id = stories[0]["cluster_id"]
    detail_res = client.get(f"/api/newspaper/stories/{cluster_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["cluster_id"] == cluster_id
    assert "headline" in detail
    assert "members" in detail
    assert len(detail["members"]) >= 1

    # Check member structure
    member = detail["members"][0]
    assert "article_id" in member
    assert "title" in member
    assert "source" in member
    assert "url" in member
    assert "is_representative" in member


def test_runs_endpoints(client):
    """Verifies runs listing and latest run endpoints."""
    # List runs
    runs_res = client.get("/api/runs?limit=5")
    assert runs_res.status_code == 200
    runs_data = runs_res.json()
    assert "items" in runs_data
    assert "total" in runs_data

    # Latest run
    latest_res = client.get("/api/runs/latest")
    assert latest_res.status_code == 200
    latest_data = latest_res.json()
    if latest_data is not None:
        assert "run_id" in latest_data
        assert "status" in latest_data
        assert "trigger_type" in latest_data


def test_manual_refresh_conflict_when_locked(client):
    """Verifies HTTP 409 Conflict when a pipeline run is already locked/running."""
    runner = get_runner()
    # Mock runner.lock.is_locked() to True
    with patch.object(runner.lock, "is_locked", return_value=True):
        response = client.post("/api/runs/refresh")
        assert response.status_code == 409
        assert "already currently active" in response.json()["detail"]


def test_manual_refresh_accepted_when_unlocked(client):
    """Verifies HTTP 202 Accepted when trigger_manual_refresh succeeds without conflict."""
    runner = get_runner()
    # Mock runner.lock.is_locked() to False and mock _execute_refresh_in_background
    with patch.object(runner.lock, "is_locked", return_value=False):
        with patch("app.api.routes._execute_refresh_in_background") as mock_exec:
            response = client.post("/api/runs/refresh?domains=ai,science")
            assert response.status_code == 202
            data = response.json()
            assert data["status"] == "TRIGGERED"
            assert "started in background" in data["message"]
