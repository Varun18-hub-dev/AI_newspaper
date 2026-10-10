"""Base interface and common utilities for Phase 9A multi-source news adapters."""

from abc import ABC, abstractmethod
from datetime import datetime
from email.utils import parsedate_to_datetime
import html
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from app.core.logging import setup_logger
from app.ingestion.models import Article

logger = setup_logger("source_adapter")


def clean_text(raw_text: Optional[str]) -> Optional[str]:
    """Strips HTML tags, collapses whitespace, and unescapes entities."""
    if not raw_text:
        return None
    # Strip HTML tags
    cleaned = re.sub(r"<[^>]+>", " ", raw_text)
    # Unescape HTML entities
    cleaned = html.unescape(cleaned)
    # Collapse multiple whitespaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else None


def parse_iso_or_rfc_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parses ISO-8601 or RFC-2822 date string into a UTC datetime (naive UTC)."""
    if not date_str or not date_str.strip():
        return None
    cleaned = date_str.strip()

    # Try RFC 2822
    try:
        dt = parsedate_to_datetime(cleaned)
        return dt.replace(tzinfo=None)
    except Exception:
        pass

    # Try ISO 8601
    try:
        iso_clean = cleaned.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_clean)
        return dt.replace(tzinfo=None)
    except Exception:
        pass

    return None


class BaseSourceAdapter(ABC):
    """Abstract base class for all external news and data source adapters."""

    def __init__(
        self,
        name: str,
        default_domain: str = "Technology",
        timeout: float = 15.0,
        enabled: bool = True,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-Newspaper/1.0",
    ):
        self.name = name
        self.default_domain = default_domain
        self.timeout = timeout
        self.enabled = enabled
        self.user_agent = user_agent
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        """Constructs a requests Session with bounded retries and exponential backoff."""
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/json, application/xml, text/xml, */*",
        })
        try:
            retries = Retry(
                total=3,
                backoff_factor=1.0,
                status_forcelist=[429, 500, 502, 503, 504],
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retries)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        except Exception as e:
            logger.debug(f"Could not attach Retry adapter in {self.name}: {e}")
        return session

    @abstractmethod
    def fetch(
        self,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[Article], Dict[str, Any]]:
        """Fetches articles from the source.

        Args:
            domain: Target news domain (e.g. 'AI', 'Cybersecurity', 'Science').
            limit: Maximum items to retrieve.

        Returns:
            Tuple[List[Article], Dict[str, Any]]:
                - List of normalized Article instances.
                - Source telemetry dictionary containing status, count, error, latency.
        """
        pass
