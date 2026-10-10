"""Hacker News source adapter using the official Firebase REST API."""

from datetime import datetime, timedelta
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.adapters.base import BaseSourceAdapter, clean_text
from app.ingestion.models import Article

logger = setup_logger("hackernews_adapter")

AI_KEYWORDS = re.compile(
    r"\b(?:ai|llm|llms|gpt|openai|claude|gemini|deepseek|qwen|agentic|neural|machine learning|diffusion|transformer)\b",
    re.IGNORECASE,
)
CYBER_KEYWORDS = re.compile(
    r"\b(?:cybersecurity|security|cyber|cve|vulnerability|exploit|malware|ransomware|breach|hacked|zero-day|phishing|infosec|backdoor)\b",
    re.IGNORECASE,
)
BUSINESS_KEYWORDS = re.compile(
    r"\b(?:startup|funding|venture capital|series [a-d]|ipo|valuation|acquisition|acquired|layoffs?|antitrust)\b",
    re.IGNORECASE,
)


class HackerNewsAdapter(BaseSourceAdapter):
    """Fetches high-ranking stories and discussions from the official Hacker News API."""

    def __init__(
        self,
        min_score: Optional[int] = None,
        max_items: Optional[int] = None,
        lookback_hours: float = 48.0,
        timeout: float = 10.0,
        enabled: Optional[bool] = None,
    ):
        super().__init__(
            name="Hacker News",
            default_domain="Technology",
            timeout=timeout,
            enabled=enabled if enabled is not None else settings.enable_hackernews,
            user_agent="AI-Newspaper/1.0",
        )
        self.min_score = (
            min_score if min_score is not None else settings.hackernews_min_score
        )
        self.max_items = (
            max_items if max_items is not None else settings.hackernews_max_items
        )
        self.lookback_hours = lookback_hours
        self.base_url = "https://hacker-news.firebaseio.com/v0"

    def _classify_domain(self, title: str) -> str:
        """Classifies story domain based on headline keyword signals."""
        if AI_KEYWORDS.search(title):
            return "AI"
        if CYBER_KEYWORDS.search(title):
            return "Cybersecurity"
        if BUSINESS_KEYWORDS.search(title):
            return "Business and startups"
        return "Technology"

    def fetch_item(self, item_id: int) -> Optional[Dict[str, Any]]:
        """Fetches a single Hacker News item by ID."""
        url = f"{self.base_url}/item/{item_id}.json"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                return resp.json()
        except Exception as err:
            logger.debug(f"Failed to fetch HN item {item_id}: {err}")
        return None

    def parse_hn_item(self, item: Dict[str, Any]) -> Optional[Article]:
        """Converts raw Hacker News JSON item into an Article model."""
        if not item or item.get("type") != "story":
            return None

        # Filter deleted or dead items
        if item.get("deleted") or item.get("dead"):
            return None

        title = item.get("title")
        if not title or len(title.strip()) < 5:
            return None

        item_id = item.get("id")
        score = item.get("score", 0)
        descendants = item.get("descendants", 0)
        by = item.get("by")
        timestamp = item.get("time")

        # Score filter
        if score < self.min_score:
            return None

        published_at = datetime.utcfromtimestamp(timestamp) if timestamp else None
        if published_at:
            cutoff = datetime.utcnow() - timedelta(hours=self.lookback_hours)
            if published_at < cutoff:
                return None

        # Discussion URL
        hn_discussion_url = f"https://news.ycombinator.com/item?id={item_id}"
        external_url = item.get("url")

        # Canonical URL: external URL if present, otherwise HN discussion URL
        canonical_url = external_url.strip() if external_url and external_url.strip() else hn_discussion_url

        # Description
        raw_text = item.get("text")
        text_clean = clean_text(raw_text) if raw_text else None
        description = (
            text_clean
            if text_clean
            else f"Hacker News discussion ({score} points, {descendants} comments): {hn_discussion_url}"
        )

        domain = self._classify_domain(title)

        return Article(
            title=title.strip(),
            url=canonical_url,
            source="Hacker News",
            author=by,
            published_at=published_at,
            description=description,
            domain=domain,
            raw_metadata={
                "hn_id": item_id,
                "score": score,
                "comments_count": descendants,
                "discussion_url": hn_discussion_url,
                "is_external": bool(external_url),
            },
        )

    def fetch(
        self,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[Article], Dict[str, Any]]:
        """Discovers recent top stories from Hacker News.

        Args:
            domain: Optional target domain filter.
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

        try:
            top_ids_url = f"{self.base_url}/topstories.json"
            resp = self.session.get(top_ids_url, timeout=self.timeout)
            resp.raise_for_status()
            story_ids = resp.json() or []
        except Exception as err:
            err_msg = f"Failed to retrieve HN top stories: {err}"
            logger.error(err_msg)
            return [], {
                "status": "FAILED",
                "count": 0,
                "error": err_msg,
                "latency_seconds": round(time.time() - start_time, 2),
            }

        # Inspect top stories (check up to 40 candidates to satisfy limit)
        candidates_to_check = story_ids[: min(45, len(story_ids))]
        for sid in candidates_to_check:
            if len(articles) >= max_fetch:
                break
            try:
                item_data = self.fetch_item(sid)
                if not item_data:
                    continue
                article = self.parse_hn_item(item_data)
                if not article:
                    continue

                if domain:
                    if article.domain.lower() != domain.strip().lower():
                        continue

                articles.append(article)
            except Exception as err:
                logger.debug(f"Error processing HN item {sid}: {err}")

        latency = round(time.time() - start_time, 2)
        logger.info(f"Hacker News adapter discovered {len(articles)} articles (scanned {len(candidates_to_check)} items)")

        return articles, {
            "status": "SUCCESS" if articles or not errors else "DEGRADED",
            "count": len(articles),
            "error": "; ".join(errors) if errors else None,
            "latency_seconds": latency,
        }
