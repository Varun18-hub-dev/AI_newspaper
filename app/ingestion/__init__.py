"""Ingestion package providing feed connectors, source adapters, and models."""

from app.ingestion.models import Article
from app.ingestion.rss import RSSConnector
from app.ingestion.coordinator import MultiSourceDiscoveryCoordinator
from app.ingestion.adapters.arxiv import ArxivAdapter
from app.ingestion.adapters.hackernews import HackerNewsAdapter
from app.ingestion.adapters.github import GitHubAdapter
from app.ingestion.adapters.nvd import NVDAdapter

__all__ = [
    "Article",
    "RSSConnector",
    "MultiSourceDiscoveryCoordinator",
    "ArxivAdapter",
    "HackerNewsAdapter",
    "GitHubAdapter",
    "NVDAdapter",
]
