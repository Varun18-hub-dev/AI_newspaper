"""arXiv source adapter for AI and Science research papers."""

from datetime import datetime
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import xml.etree.ElementTree as ET

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.adapters.base import BaseSourceAdapter, clean_text, parse_iso_or_rfc_date
from app.ingestion.models import Article

logger = setup_logger("arxiv_adapter")

# Mapping arXiv subject categories to newspaper domains
ARXIV_CATEGORY_DOMAINS = {
    "cs.ai": "AI",
    "cs.lg": "AI",
    "cs.cl": "AI",
    "cs.cv": "AI",
    "cs.ro": "AI",
    "stat.ml": "AI",
    "physics.gen-ph": "Science",
    "quant-ph": "Science",
    "astro-ph": "Science",
    "q-bio": "Science",
    "cond-mat": "Science",
}


class ArxivAdapter(BaseSourceAdapter):
    """Fetches recently announced research papers from arXiv via RSS/Atom feeds and API."""

    def __init__(
        self,
        categories: Optional[List[str]] = None,
        max_results_per_category: Optional[int] = None,
        timeout: float = 15.0,
        enabled: Optional[bool] = None,
        use_api_endpoint: bool = False,
    ):
        super().__init__(
            name="arXiv",
            default_domain="AI",
            timeout=timeout,
            enabled=enabled if enabled is not None else settings.enable_arxiv,
            user_agent="AI-Newspaper/1.0 (mailto:admin@example.com)",
        )
        self.categories = categories or settings.arxiv_categories
        self.max_results = (
            max_results_per_category
            if max_results_per_category is not None
            else settings.arxiv_max_results
        )
        self.use_api_endpoint = use_api_endpoint

    def _determine_domain(self, category: str) -> str:
        """Determines newspaper domain from arXiv category code."""
        cat_lower = category.lower().strip()
        for prefix, domain in ARXIV_CATEGORY_DOMAINS.items():
            if cat_lower == prefix or cat_lower.startswith(prefix + "."):
                return domain
        if cat_lower.startswith("cs.") or cat_lower.startswith("stat."):
            return "AI"
        return "Science"

    def _clean_arxiv_title(self, raw_title: Optional[str]) -> str:
        """Cleans arXiv paper title by removing 'Title:', arXiv IDs, and extra newlines."""
        if not raw_title:
            return ""
        cleaned = re.sub(r"^(?:arXiv:\S+\s+)?(?:Title:\s*)?", "", raw_title.strip(), flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _clean_arxiv_abstract(self, raw_desc: Optional[str]) -> Optional[str]:
        """Cleans abstract by removing Announce Type and leading labels."""
        if not raw_desc:
            return None
        cleaned = clean_text(raw_desc)
        if not cleaned:
            return None
        # Remove arXiv announcement headers like "arXiv:2610.1234v1 Announce Type: new Abstract: "
        cleaned = re.sub(r"^arXiv:[^\s]+\s+Announce Type:\s*\w+\s*(?:Abstract:\s*)?", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^Abstract:\s*", "", cleaned, flags=re.IGNORECASE).strip()
        return cleaned if cleaned else None

    def _extract_paper_id(self, link_or_guid: str) -> Optional[str]:
        """Extracts arXiv identifier (e.g. '2610.12345') from URL or GUID."""
        match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", link_or_guid)
        if match:
            return match.group(1)
        return None

    def parse_arxiv_xml(self, xml_bytes: bytes, category: str) -> List[Article]:
        """Parses arXiv RSS or Atom XML payload into Article models.

        Args:
            xml_bytes: Raw XML bytes from arXiv response.
            category: Subject category string (e.g. 'cs.AI').

        Returns:
            List[Article]: Normalized articles.
        """
        domain = self._determine_domain(category)
        articles: List[Article] = []

        try:
            root = ET.fromstring(xml_bytes)
        except Exception as err:
            logger.error(f"arXiv XML parsing error for category {category}: {err}")
            return []

        # Check if Atom feed (<feed><entry>)
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
        if entries:
            for entry in entries[: self.max_results]:
                raw_title = entry.findtext("{http://www.w3.org/2005/Atom}title")
                title = self._clean_arxiv_title(raw_title)

                link_elem = entry.find("{http://www.w3.org/2005/Atom}link[@rel='alternate']")
                link = link_elem.attrib.get("href") if link_elem is not None else entry.findtext("{http://www.w3.org/2005/Atom}id")

                paper_id = self._extract_paper_id(link or "")
                canonical_url = f"https://arxiv.org/abs/{paper_id}" if paper_id else (link or "").strip()

                if not title or not canonical_url or len(title) < 5:
                    continue

                pub_date_str = entry.findtext("{http://www.w3.org/2005/Atom}published") or entry.findtext("{http://www.w3.org/2005/Atom}updated")
                published_at = parse_iso_or_rfc_date(pub_date_str)

                summary_elem = entry.findtext("{http://www.w3.org/2005/Atom}summary")
                description = self._clean_arxiv_abstract(summary_elem)

                # Authors
                author_names = [
                    a.findtext("{http://www.w3.org/2005/Atom}name")
                    for a in entry.findall("{http://www.w3.org/2005/Atom}author")
                    if a.findtext("{http://www.w3.org/2005/Atom}name")
                ]
                author_str = ", ".join(author_names[:3]) + (" et al." if len(author_names) > 3 else "") if author_names else None

                articles.append(
                    Article(
                        title=title,
                        url=canonical_url,
                        source="arXiv",
                        author=author_str,
                        published_at=published_at,
                        description=description,
                        domain=domain,
                        raw_metadata={
                            "arxiv_id": paper_id or "",
                            "category": category,
                            "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf" if paper_id else "",
                        },
                    )
                )
            return articles

        # Otherwise RSS 1.0/2.0 (<channel><item> or <rdf:RDF><item>)
        items = root.findall(".//{http://purl.org/rss/1.0/}item") or root.findall(".//item")
        for item in items[: self.max_results]:
            raw_title = item.findtext("{http://purl.org/rss/1.0/}title") or item.findtext("title")
            title = self._clean_arxiv_title(raw_title)

            raw_link = item.findtext("{http://purl.org/rss/1.0/}link") or item.findtext("link")
            paper_id = self._extract_paper_id(raw_link or "")
            canonical_url = f"https://arxiv.org/abs/{paper_id}" if paper_id else (raw_link or "").strip()

            if not title or not canonical_url or len(title) < 5:
                continue

            pub_date_str = item.findtext("{http://purl.org/dc/elements/1.1/}date") or item.findtext("pubDate")
            published_at = parse_iso_or_rfc_date(pub_date_str)

            raw_desc = item.findtext("{http://purl.org/rss/1.0/}description") or item.findtext("description")
            description = self._clean_arxiv_abstract(raw_desc)

            author = item.findtext("{http://purl.org/dc/elements/1.1/}creator") or item.findtext("author")
            author_str = clean_text(author)

            articles.append(
                Article(
                    title=title,
                    url=canonical_url,
                    source="arXiv",
                    author=author_str,
                    published_at=published_at,
                    description=description,
                    domain=domain,
                    raw_metadata={
                        "arxiv_id": paper_id or "",
                        "category": category,
                        "pdf_url": f"https://arxiv.org/pdf/{paper_id}.pdf" if paper_id else "",
                    },
                )
            )

        return articles

    def fetch_category(self, category: str) -> List[Article]:
        """Fetches research papers for a single arXiv category."""
        if self.use_api_endpoint:
            url = f"https://export.arxiv.org/api/query?search_query=cat:{category}&sortBy=submittedDate&sortOrder=descending&max_results={self.max_results}"
        else:
            url = f"https://rss.arxiv.org/rss/{category}"

        logger.info(f"Fetching arXiv category '{category}' from {url}")
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return self.parse_arxiv_xml(resp.content, category=category)

    def fetch(
        self,
        domain: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> Tuple[List[Article], Dict[str, Any]]:
        """Fetches arXiv papers across configured categories with domain filtering.

        Args:
            domain: Optional domain filter ('AI', 'Science', etc.).
            limit: Optional overall article limit.

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

        all_articles: List[Article] = []
        errors: List[str] = []

        target_categories = self.categories
        if domain:
            norm_domain = domain.strip().lower()
            target_categories = [
                c for c in self.categories
                if self._determine_domain(c).lower() == norm_domain
            ]
            if not target_categories and norm_domain == "ai":
                target_categories = ["cs.AI", "cs.LG"]
            elif not target_categories and norm_domain == "science":
                target_categories = ["physics.gen-ph"]

        for cat in target_categories:
            try:
                cat_articles = self.fetch_category(cat)
                all_articles.extend(cat_articles)
                logger.info(f"arXiv category '{cat}' returned {len(cat_articles)} papers")
            except Exception as err:
                err_msg = f"arXiv category '{cat}' failed: {err}"
                logger.warning(err_msg)
                errors.append(err_msg)

        if limit and len(all_articles) > limit:
            all_articles = all_articles[:limit]

        latency = round(time.time() - start_time, 2)
        status = "SUCCESS" if all_articles or not errors else ("DEGRADED" if all_articles else "FAILED")

        return all_articles, {
            "status": status,
            "count": len(all_articles),
            "error": "; ".join(errors) if errors else None,
            "latency_seconds": latency,
            "categories_queried": target_categories,
        }
