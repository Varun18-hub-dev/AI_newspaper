"""GitHub source adapter for public open-source repositories and releases."""

from datetime import datetime, timedelta
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.adapters.base import BaseSourceAdapter, clean_text, parse_iso_or_rfc_date
from app.ingestion.models import Article

logger = setup_logger("github_adapter")


class GitHubAdapter(BaseSourceAdapter):
    """Discovers trending and high-impact repositories and releases using GitHub REST API."""

    def __init__(
        self,
        token: Optional[str] = None,
        min_stars: Optional[int] = None,
        max_items: Optional[int] = None,
        timeout: float = 12.0,
        enabled: Optional[bool] = None,
    ):
        super().__init__(
            name="GitHub",
            default_domain="Technology",
            timeout=timeout,
            enabled=enabled if enabled is not None else settings.enable_github,
            user_agent="AI-Newspaper/1.0",
        )
        self.token = token or settings.github_token
        self.min_stars = min_stars if min_stars is not None else settings.github_min_stars
        self.max_items = max_items if max_items is not None else settings.github_max_items
        self.base_url = "https://api.github.com"

        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def _determine_domain(self, topics: List[str], description: str) -> str:
        """Categorizes repository domain based on topics and description."""
        combined = " ".join(topics).lower() + " " + (description or "").lower()
        if any(k in combined for k in ["llm", "machine-learning", "deep-learning", "ai-agent", "transformer", "diffusion", "openai"]):
            return "AI"
        if any(k in combined for k in ["cybersecurity", "security-tools", "vulnerability", "malware", "exploit", "cve"]):
            return "Cybersecurity"
        if any(k in combined for k in ["physics", "astronomy", "bioinformatics", "quantum-computing", "scientific"]):
            return "Science"
        return "Technology"

    def search_repositories(
        self,
        query: str,
        limit: int = 5,
    ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Executes a search query against the GitHub search API.

        Handles rate limiting gracefully.

        Returns:
            Tuple[List[dict], Optional[str]]: (items, error_message)
        """
        url = f"{self.base_url}/search/repositories"
        params = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": limit,
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 403 or resp.status_code == 429:
                reset_time = resp.headers.get("X-RateLimit-Reset")
                logger.warning(
                    f"GitHub API rate limit encountered (status={resp.status_code}, reset={reset_time})"
                )
                return [], f"GitHub API rate limit reached (HTTP {resp.status_code})"
            resp.raise_for_status()
            data = resp.json()
            return data.get("items", []), None
        except Exception as err:
            logger.warning(f"GitHub search query failed ('{query}'): {err}")
            return [], str(err)

    def parse_repo_item(self, repo: Dict[str, Any]) -> Optional[Article]:
        """Converts raw GitHub repository JSON into an Article model."""
        full_name = repo.get("full_name")
        html_url = repo.get("html_url")
        if not full_name or not html_url:
            return None

        stars = repo.get("stargazers_count", 0)
        if stars < self.min_stars:
            return None

        desc_raw = repo.get("description")
        desc_clean = clean_text(desc_raw) if desc_raw else None
        topics = repo.get("topics", [])
        language = repo.get("language")

        owner = repo.get("owner", {}).get("login")
        pushed_at = parse_iso_or_rfc_date(repo.get("pushed_at")) or parse_iso_or_rfc_date(repo.get("created_at"))

        headline = f"{full_name}: {desc_clean[:90]}" if desc_clean else full_name
        description = (
            f"{desc_clean or 'Open-source repository.'} "
            f"Stars: {stars:,} | Language: {language or 'Not specified'} | Topics: {', '.join(topics[:5])}"
        )

        domain = self._determine_domain(topics, desc_clean or "")

        return Article(
            title=headline,
            url=html_url,
            source="GitHub",
            author=owner,
            published_at=pushed_at,
            description=description,
            domain=domain,
            raw_metadata={
                "repo_name": full_name,
                "stars": stars,
                "forks": repo.get("forks_count", 0),
                "language": language,
                "topics": topics,
            },
        )

    def fetch(
        self,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[Article], Dict[str, Any]]:
        """Discovers meaningful repositories across target domains.

        Args:
            domain: Optional target domain ('AI', 'Cybersecurity', 'Technology', etc.).
            limit: Maximum items to return.

        Returns:
            Tuple[List[Article], Dict[str, Any]]: (articles, telemetry)
        """
        start_time = time.time()
        if not self.enabled:
            return [], {
                "status": "DISABLED",
                "count": 0,
                "error": None,
                "latency_seconds": 0.0,
            }

        max_fetch = limit or self.max_items
        articles: List[Article] = []
        errors: List[str] = []

        # Target search queries
        queries: List[Tuple[str, str]] = []
        norm_domain = domain.strip().lower() if domain else None

        if not norm_domain or norm_domain == "ai":
            queries.append((f"topic:machine-learning stars:>{self.min_stars}", "AI"))
        if not norm_domain or norm_domain == "cybersecurity":
            queries.append((f"topic:cybersecurity stars:>{self.min_stars}", "Cybersecurity"))
        if not norm_domain or norm_domain == "technology":
            queries.append((f"topic:developer-tools stars:>{self.min_stars}", "Technology"))

        for q, query_domain in queries:
            if len(articles) >= max_fetch:
                break
            items, err = self.search_repositories(q, limit=max(3, max_fetch // len(queries) + 1))
            if err:
                errors.append(err)
            for item in items:
                art = self.parse_repo_item(item)
                if art:
                    if domain and art.domain.lower() != norm_domain:
                        art.domain = query_domain
                    articles.append(art)
                    if len(articles) >= max_fetch:
                        break

        latency = round(time.time() - start_time, 2)
        status = "SUCCESS" if articles or not errors else ("RATE_LIMITED" if any("rate limit" in e.lower() for e in errors) else "FAILED")

        return articles, {
            "status": status,
            "count": len(articles),
            "authenticated": bool(self.token),
            "error": "; ".join(errors) if errors else None,
            "latency_seconds": latency,
        }
