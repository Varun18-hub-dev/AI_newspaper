"""Source adapters package for multi-source news discovery."""

from app.ingestion.adapters.base import BaseSourceAdapter
from app.ingestion.adapters.arxiv import ArxivAdapter
from app.ingestion.adapters.hackernews import HackerNewsAdapter
from app.ingestion.adapters.github import GitHubAdapter
from app.ingestion.adapters.nvd import NVDAdapter

__all__ = [
    "BaseSourceAdapter",
    "ArxivAdapter",
    "HackerNewsAdapter",
    "GitHubAdapter",
    "NVDAdapter",
]
