"""Modular RSS and Atom feed connector."""

from datetime import datetime
from email.utils import parsedate_to_datetime
import html
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
import requests

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.models import Article

logger = setup_logger("rss_connector")


def _clean_html(raw_html: Optional[str]) -> Optional[str]:
    """Strips HTML tags and unescapes HTML entities from text."""
    if not raw_html:
        return None
    # Strip HTML tags
    clean_text = re.sub(r"<[^>]+>", " ", raw_html)
    # Unescape HTML entities (&amp;, &nbsp;, etc.)
    clean_text = html.unescape(clean_text)
    # Collapse multiple whitespaces
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    return clean_text if clean_text else None


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parses date string from RFC 2822 (RSS) or ISO 8601 (Atom)."""
    if not date_str or not date_str.strip():
        return None
    cleaned = date_str.strip()

    # Try RFC 2822 (standard for RSS pubDate)
    try:
        dt = parsedate_to_datetime(cleaned)
        # Convert to naive or keep UTC
        return dt.replace(tzinfo=None)
    except Exception:
        pass

    # Try ISO 8601 (standard for Atom published/updated)
    try:
        # Handle 'Z' suffix
        iso_clean = cleaned.replace("Z", "+00:00")
        dt = datetime.fromisoformat(iso_clean)
        return dt.replace(tzinfo=None)
    except Exception:
        pass

    return None


def _extract_image_url(item: ET.Element, raw_html: Optional[str] = None) -> Optional[str]:
    """Safely extracts a featured image URL from enclosures, media tags, or embedded HTML.

    Never fetches external images or calls external APIs. Only reads feed metadata.
    """
    for child in item:
        tag_low = child.tag.lower()
        # 1. RSS Enclosure
        if tag_low.endswith("enclosure"):
            url = child.attrib.get("url")
            mime = child.attrib.get("type", "").lower()
            if url and ("image" in mime or any(url.lower().split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"))):
                return url.strip()
        # 2. Yahoo Media RSS (<media:content> or <media:thumbnail>)
        if tag_low.endswith("content") or tag_low.endswith("thumbnail"):
            url = child.attrib.get("url")
            medium = child.attrib.get("medium", "").lower()
            if url and (medium == "image" or any(url.lower().split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"))):
                return url.strip()
        # 3. Atom link rel="enclosure"
        if tag_low.endswith("link") and child.attrib.get("rel") == "enclosure":
            url = child.attrib.get("href")
            mime = child.attrib.get("type", "").lower()
            if url and ("image" in mime or any(url.lower().split("?")[0].endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"))):
                return url.strip()

    # 4. Embedded <img> in raw HTML description
    if raw_html:
        m = re.search(r'<img[^>]+src=["\'](https?://[^"\']+\.(?:jpg|jpeg|png|webp|gif)(?:\?[^"\']*)?)["\']', raw_html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m2 = re.search(r'<img[^>]+src=["\'](https?://[^"\']+)["\']', raw_html, re.IGNORECASE)
        if m2:
            candidate = m2.group(1).strip()
            if not candidate.lower().endswith((".svg", ".ico")):
                return candidate

    return None


class RSSConnector:
    """Fetches and normalizes articles from RSS and Atom XML feeds."""

    def __init__(
        self,
        timeout: float = 15.0,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 AI-Newspaper/1.0",
        max_items_per_feed: Optional[int] = None,
    ):
        """Initializes the connector.

        Args:
            timeout: HTTP timeout for feed requests.
            user_agent: User-Agent header string.
            max_items_per_feed: Maximum items to extract per feed (default from settings).
        """
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_items_per_feed = (
            max_items_per_feed
            if max_items_per_feed is not None
            else settings.max_items_per_feed
        )
        self.session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()
        session.headers.update({
            "User-Agent": self.user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
        })
        try:
            from requests.adapters import HTTPAdapter
            from urllib3.util import Retry

            retries = Retry(
                total=3,
                backoff_factor=1,
                status_forcelist=[429, 500, 502, 503, 504],
                raise_on_status=False,
            )
            adapter = HTTPAdapter(max_retries=retries)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
        except Exception as e:
            logger.debug(f"Could not attach Retry adapter: {e}")
        return session

    def fetch_feed(
        self,
        url: str,
        domain: str = "AI",
        source_name_override: Optional[str] = None,
    ) -> List[Article]:
        """Fetches and parses a single RSS/Atom feed.

        Args:
            url: URL of the feed.
            domain: Target news domain (default: 'AI').
            source_name_override: Optional explicit name for the source.

        Returns:
            List[Article]: Parsed and normalized articles.

        Raises:
            requests.RequestException: On network or HTTP failure.
            ET.ParseError: On invalid XML structure.
        """
        logger.info(f"Fetching feed ({domain}): {url}")
        response = self.session.get(
            url,
            timeout=self.timeout,
        )
        response.raise_for_status()

        return self.parse_feed_xml(
            response.content,
            fallback_source=source_name_override or url,
            domain=domain,
        )

    def parse_feed_xml(
        self,
        xml_bytes: bytes,
        fallback_source: str = "RSS Feed",
        domain: str = "AI",
    ) -> List[Article]:
        """Parses raw XML bytes into Article instances.

        Supports both RSS 2.0 (<rss><channel><item>) and Atom 1.0 (<feed><entry>).

        Args:
            xml_bytes: Raw XML response bytes.
            fallback_source: Fallback source name if feed metadata is absent.
            domain: Information domain category (default: 'AI').

        Returns:
            List[Article]: List of normalized articles.
        """
        root = ET.fromstring(xml_bytes)
        root_tag = root.tag.lower()

        if root_tag.endswith("feed"):
            return self._parse_atom_feed(root, fallback_source, domain=domain)
        elif root_tag.endswith("rss") or root_tag.endswith("rdf"):
            return self._parse_rss_feed(root, fallback_source, domain=domain)
        else:
            # Check if root contains channel or entry directly
            if root.find("channel") is not None:
                return self._parse_rss_feed(root, fallback_source, domain=domain)
            elif any(c.tag.lower().endswith("entry") for c in root):
                return self._parse_atom_feed(root, fallback_source, domain=domain)
            raise ValueError(f"Unrecognized XML feed format with root tag: {root.tag}")

    def _parse_rss_feed(
        self,
        root: ET.Element,
        fallback_source: str,
        domain: str = "AI",
    ) -> List[Article]:
        """Parses an RSS 2.0 / RDF feed."""
        channel = root.find("channel")
        if channel is None:
            channel = root

        feed_title = channel.findtext("title")
        source_name = (feed_title.strip() if feed_title else None) or self._derive_source_name(fallback_source)

        articles: List[Article] = []
        # Support namespaced and non-namespaced item tags
        items = [elem for elem in channel if elem.tag.lower().endswith("item")]
        if not items and channel is not root:
            items = [elem for elem in root if elem.tag.lower().endswith("item")]

        for item in items[: self.max_items_per_feed]:
            title_elem = [c for c in item if c.tag.lower().endswith("title")]
            title = (title_elem[0].text if title_elem and title_elem[0].text else None) or item.findtext("title")

            link_elem = [c for c in item if c.tag.lower().endswith("link")]
            link = (link_elem[0].text if link_elem and link_elem[0].text else None) or item.findtext("link")
            if not link:
                # Some feeds put link in guid if isPermaLink="true"
                guid_elem = [c for c in item if c.tag.lower().endswith("guid")]
                if guid_elem and guid_elem[0].text and (
                    guid_elem[0].attrib.get("isPermaLink", "true") == "true"
                    or guid_elem[0].text.startswith("http")
                ):
                    link = guid_elem[0].text

            if not title or not link or not title.strip() or not link.strip():
                logger.debug(f"Skipping RSS item with missing title or link: title={title}, link={link}")
                continue

            # Publication date
            date_elem = [c for c in item if c.tag.lower().endswith("pubdate") or c.tag.lower().endswith("date")]
            pub_date_str = (date_elem[0].text if date_elem and date_elem[0].text else None) or item.findtext("pubDate")
            published_at = _parse_date(pub_date_str)

            # Description / Summary
            desc_elem = [c for c in item if c.tag.lower().endswith("description") or c.tag.lower().endswith("encoded")]
            desc_raw = (desc_elem[0].text if desc_elem and desc_elem[0].text else None) or item.findtext("description")
            description = _clean_html(desc_raw)

            # Author
            author_elem = [c for c in item if c.tag.lower().endswith("creator") or c.tag.lower().endswith("author")]
            author = (author_elem[0].text if author_elem and author_elem[0].text else None) or item.findtext("author")
            if author:
                author = author.strip()

            image_url = _extract_image_url(item, desc_raw)

            try:
                article = Article(
                    title=title.strip(),
                    url=link.strip(),
                    source=source_name,
                    author=author,
                    published_at=published_at,
                    description=description,
                    domain=domain,
                    image_url=image_url,
                )
                articles.append(article)
            except Exception as err:
                logger.warning(f"Failed to create Article from RSS item: {err}")

        return articles

    def _parse_atom_feed(
        self,
        root: ET.Element,
        fallback_source: str,
        domain: str = "AI",
    ) -> List[Article]:
        """Parses an Atom 1.0 feed."""
        feed_title_elem = [c for c in root if c.tag.lower().endswith("title")]
        feed_title = feed_title_elem[0].text if feed_title_elem and feed_title_elem[0].text else None
        source_name = (feed_title.strip() if feed_title else None) or self._derive_source_name(fallback_source)

        articles: List[Article] = []
        entries = [elem for elem in root if elem.tag.lower().endswith("entry")]

        for entry in entries[: self.max_items_per_feed]:
            title_elems = [c for c in entry if c.tag.lower().endswith("title")]
            title = title_elems[0].text if title_elems and title_elems[0].text else None

            # Atom links can be <link href="..." rel="alternate"/>
            link = None
            link_elems = [c for c in entry if c.tag.lower().endswith("link")]
            for l in link_elems:
                href = l.attrib.get("href")
                rel = l.attrib.get("rel", "alternate")
                if href and rel in ("alternate", ""):
                    link = href
                    break
            if not link and link_elems:
                link = link_elems[0].attrib.get("href")

            if not title or not link or not title.strip() or not link.strip():
                logger.debug(f"Skipping Atom entry with missing title or link: title={title}, link={link}")
                continue

            # Date
            date_elems = [c for c in entry if c.tag.lower() in ("published", "updated", "{http://www.w3.org/2005/atom}published", "{http://www.w3.org/2005/atom}updated")]
            date_str = date_elems[0].text if date_elems and date_elems[0].text else None
            published_at = _parse_date(date_str)

            # Summary / Content
            summary_elems = [c for c in entry if c.tag.lower().endswith("summary") or c.tag.lower().endswith("content")]
            desc_raw = summary_elems[0].text if summary_elems and summary_elems[0].text else None
            description = _clean_html(desc_raw)

            # Author
            author = None
            author_elems = [c for c in entry if c.tag.lower().endswith("author")]
            if author_elems:
                name_elem = [c for c in author_elems[0] if c.tag.lower().endswith("name")]
                if name_elem and name_elem[0].text:
                    author = name_elem[0].text.strip()
                elif author_elems[0].text:
                    author = author_elems[0].text.strip()

            image_url = _extract_image_url(entry, desc_raw)

            try:
                article = Article(
                    title=title.strip(),
                    url=link.strip(),
                    source=source_name,
                    author=author,
                    published_at=published_at,
                    description=description,
                    domain=domain,
                    image_url=image_url,
                )
                articles.append(article)
            except Exception as err:
                logger.warning(f"Failed to create Article from Atom entry: {err}")

        return articles

    def _derive_source_name(self, fallback: str) -> str:
        """Derives a human-friendly source name from URL if title is missing."""
        try:
            parsed = urlparse(fallback)
            if parsed.netloc:
                netloc = parsed.netloc.lower()
                if netloc.startswith("www."):
                    netloc = netloc[4:]
                return netloc
        except Exception:
            pass
        return fallback

    def fetch_all(
        self,
        urls: Optional[List[str]] = None,
        domain: str = "AI",
    ) -> Tuple[List[Article], Dict[str, Dict[str, Any]]]:
        """Fetches articles across multiple configured feeds safely.

        A failure in one feed does NOT crash the pipeline.

        Args:
            urls: List of feed URLs. If None, uses configured settings.ai_rss_feeds.
            domain: Target news domain (default: 'AI').

        Returns:
            Tuple[List[Article], Dict[str, Dict[str, Any]]]:
                - List of all collected articles
                - Mapping of url -> { "status": "SUCCESS"|"FAILED", "count": int, "error": Optional[str] }
        """
        target_urls = urls if urls is not None else settings.ai_rss_feeds
        all_articles: List[Article] = []
        statuses: Dict[str, Dict[str, Any]] = {}

        for url in target_urls:
            try:
                articles = self.fetch_feed(url, domain=domain)
                all_articles.extend(articles)
                statuses[url] = {
                    "status": "SUCCESS",
                    "count": len(articles),
                    "error": None,
                    "domain": domain,
                }
                logger.info(f"Successfully ingested {len(articles)} articles from {url} ({domain})")
            except Exception as err:
                logger.error(f"Failed to ingest feed {url} ({domain}): {err}")
                statuses[url] = {
                    "status": "FAILED",
                    "count": 0,
                    "error": str(err),
                    "domain": domain,
                }

        return all_articles, statuses

    def fetch_domain(
        self, domain_key: str
    ) -> Tuple[List[Article], Dict[str, Dict[str, Any]]]:
        """Fetches articles for all feeds in a single domain.

        Args:
            domain_key: Domain slug or name (e.g. 'ai', 'cybersecurity').

        Returns:
            Tuple[List[Article], Dict[str, Dict[str, Any]]]:
                - Articles collected for this domain.
                - Mapping of feed URL to feed status.
        """
        from app.domains.registry import get_domain_registry

        registry = get_domain_registry()
        domain_cfg = registry.get_domain(domain_key)
        if not domain_cfg:
            logger.warning(f"Unknown domain key '{domain_key}'. No feeds fetched.")
            return [], {}

        canonical_domain = domain_cfg.display_name
        feed_urls = [
            f.url
            for f in domain_cfg.feeds
            if f.enabled
        ]
        # Also check settings.domain_rss_feeds override if available
        override_urls = settings.domain_rss_feeds.get(domain_cfg.domain_id)
        if override_urls:
            feed_urls = override_urls

        return self.fetch_all(urls=feed_urls, domain=canonical_domain)

    def fetch_all_domains(
        self, domain_keys: Optional[List[str]] = None
    ) -> Tuple[List[Article], Dict[str, Dict[str, Any]]]:
        """Fetches articles across all specified or configured enabled domains.

        Isolates failures across feeds and domains: one failing feed or domain
        does not stop discovery from other feeds.

        Args:
            domain_keys: Optional list of domains to fetch. If None, uses settings.enabled_domains.

        Returns:
            Tuple[List[Article], Dict[str, Dict[str, Any]]]:
                - List of all collected articles across all enabled domains.
                - Combined feed statuses mapping url -> status dict.
        """
        from app.domains.registry import get_domain_registry

        registry = get_domain_registry()
        targets = domain_keys if domain_keys is not None else settings.enabled_domains
        all_articles: List[Article] = []
        all_statuses: Dict[str, Dict[str, Any]] = {}

        for key in targets:
            norm_key = registry.normalize_domain_key(key)
            if not registry.is_domain_enabled(norm_key):
                logger.info(f"Domain '{key}' is disabled; skipping.")
                continue

            try:
                domain_arts, domain_stats = self.fetch_domain(norm_key)
                all_articles.extend(domain_arts)
                all_statuses.update(domain_stats)
            except Exception as e:
                logger.error(f"Error fetching domain '{key}': {e}. Continuing with others.")

        return all_articles, all_statuses
