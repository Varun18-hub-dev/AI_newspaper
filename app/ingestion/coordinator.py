"""Multi-source news discovery coordinator orchestrating RSS feeds and external source adapters."""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.adapters.arxiv import ArxivAdapter
from app.ingestion.adapters.base import BaseSourceAdapter
from app.ingestion.adapters.github import GitHubAdapter
from app.ingestion.adapters.hackernews import HackerNewsAdapter
from app.ingestion.adapters.nvd import NVDAdapter
from app.ingestion.models import Article
from app.ingestion.rss import RSSConnector

logger = setup_logger("discovery_coordinator")


class MultiSourceDiscoveryCoordinator:
    """Coordinates parallel/isolated news discovery across publisher RSS feeds and API adapters."""

    def __init__(
        self,
        rss_connector: Optional[RSSConnector] = None,
        arxiv_adapter: Optional[ArxivAdapter] = None,
        hn_adapter: Optional[HackerNewsAdapter] = None,
        github_adapter: Optional[GitHubAdapter] = None,
        nvd_adapter: Optional[NVDAdapter] = None,
    ):
        """Initializes the discovery coordinator with configurable adapters.

        Args:
            rss_connector: RSSConnector instance.
            arxiv_adapter: ArxivAdapter instance.
            hn_adapter: HackerNewsAdapter instance.
            github_adapter: GitHubAdapter instance.
            nvd_adapter: NVDAdapter instance.
        """
        self.rss = rss_connector or RSSConnector()
        self.arxiv = arxiv_adapter or ArxivAdapter()
        self.hn = hn_adapter or HackerNewsAdapter()
        self.github = github_adapter or GitHubAdapter()
        self.nvd = nvd_adapter or NVDAdapter()

    def discover_all(
        self,
        domains: Optional[List[str]] = None,
    ) -> Tuple[List[Article], Dict[str, Dict[str, Any]]]:
        """Discovers articles across all enabled RSS feeds and external source adapters.

        Guarantees complete fault isolation: a failure in any adapter or feed does
        NOT interrupt discovery from other sources.

        Args:
            domains: Optional list of domains to discover. Defaults to settings.enabled_domains.

        Returns:
            Tuple[List[Article], Dict[str, Dict[str, Any]]]:
                - Combined list of raw discovered articles.
                - Telemetry mapping source identifiers to status dictionaries.
        """
        target_domains = domains if domains is not None else settings.enabled_domains
        all_articles: List[Article] = []
        statuses: Dict[str, Dict[str, Any]] = {}

        # 1. Discover from RSS/Atom Publisher Feeds
        try:
            logger.info(f"Ingesting RSS feeds for domains: {target_domains}")
            rss_articles, rss_statuses = self.rss.fetch_all_domains(target_domains)
            all_articles.extend(rss_articles)
            statuses.update(rss_statuses)
            statuses["rss_summary"] = {
                "status": "SUCCESS" if rss_articles else "EMPTY",
                "count": len(rss_articles),
                "error": None,
            }
        except Exception as err:
            logger.error(f"RSS discovery encountered unexpected error: {err}")
            statuses["rss_summary"] = {
                "status": "FAILED",
                "count": 0,
                "error": str(err),
            }

        # 2. Discover from External Source Adapters
        adapters: List[BaseSourceAdapter] = [
            self.arxiv,
            self.hn,
            self.github,
            self.nvd,
        ]

        for adapter in adapters:
            adapter_key = adapter.name.lower().replace(" ", "_")
            if not adapter.enabled:
                logger.info(f"Source adapter '{adapter.name}' is disabled; skipping.")
                statuses[adapter_key] = {
                    "status": "DISABLED",
                    "count": 0,
                    "error": None,
                }
                continue

            try:
                logger.info(f"Ingesting from external source adapter: {adapter.name}")
                adapter_articles, telemetry = adapter.fetch()
                all_articles.extend(adapter_articles)
                statuses[adapter_key] = telemetry
                logger.info(
                    f"Adapter '{adapter.name}' discovered {len(adapter_articles)} articles "
                    f"(status={telemetry.get('status')})"
                )
            except Exception as err:
                err_msg = f"Adapter '{adapter.name}' failed with unexpected exception: {err}"
                logger.error(err_msg)
                statuses[adapter_key] = {
                    "status": "FAILED",
                    "count": 0,
                    "error": str(err),
                }

        logger.info(
            f"Multi-source discovery complete: Total {len(all_articles)} raw articles "
            f"collected across {len(statuses)} sources/feeds."
        )
        return all_articles, statuses
