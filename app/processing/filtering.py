"""Deterministic article filtering and URL normalization."""

import logging
from typing import List, Set, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.core.logging import setup_logger
from app.ingestion.models import Article

logger = setup_logger("filtering")

# Standard tracking parameters to strip during normalization
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "gclid",
    "fbclid",
    "ref",
    "source",
}


def normalize_url(raw_url: str) -> str:
    """Normalizes a URL by trimming, lowercasing scheme/host, and stripping tracking parameters.

    Args:
        raw_url: The unnormalized URL string.

    Returns:
        str: Cleaned, canonicalized URL.
    """
    if not raw_url:
        return ""

    url_str = raw_url.strip()
    try:
        parsed = urlparse(url_str)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        # Remove default ports if present
        if (scheme == "http" and netloc.endswith(":80")) or (
            scheme == "https" and netloc.endswith(":443")
        ):
            netloc = netloc.rsplit(":", 1)[0]

        # Normalize path: strip trailing slash unless path is just '/'
        path = parsed.path
        if path.endswith("/") and len(path) > 1:
            path = path.rstrip("/")

        # Filter out tracking query parameters
        query_params = parse_qsl(parsed.query, keep_blank_values=False)
        cleaned_query = [
            (k, v) for k, v in query_params if k.lower() not in TRACKING_PARAMS
        ]
        # Sort query params for determinism
        cleaned_query.sort(key=lambda x: x[0])
        new_query = urlencode(cleaned_query)

        # Remove fragment/hash
        normalized = urlunparse((scheme, netloc, path, parsed.params, new_query, ""))
        return normalized
    except Exception as err:
        logger.debug(f"Failed to normalize URL '{raw_url}': {err}")
        return url_str


def is_valid_article(article: Article) -> Tuple[bool, str]:
    """Validates whether an article meets basic quality thresholds.

    Args:
        article: Ingested article candidate.

    Returns:
        Tuple[bool, str]: (is_valid, rejection_reason)
    """
    if not article.title or not article.title.strip():
        return False, "Missing title"

    if len(article.title.strip()) < 5:
        return False, "Title too short"

    if not article.url or not article.url.strip():
        return False, "Missing URL"

    norm_url = normalize_url(article.url)
    if not (norm_url.startswith("http://") or norm_url.startswith("https://")):
        return False, "Invalid URL scheme"

    return True, "Valid"


def filter_and_deduplicate(articles: List[Article]) -> List[Article]:
    """Filters invalid articles, normalizes URLs, and removes exact duplicates.

    Preserves the earliest-encountered instance of duplicate URLs.

    Args:
        articles: Raw list of ingested articles.

    Returns:
        List[Article]: Cleaned, deduplicated articles.
    """
    seen_urls: Set[str] = set()
    cleaned_articles: List[Article] = []

    for article in articles:
        # Check basic validity
        valid, reason = is_valid_article(article)
        if not valid:
            logger.debug(f"Filtered out article '{article.title}': {reason}")
            continue

        # Canonicalize URL
        canonical_url = normalize_url(article.url)
        if canonical_url in seen_urls:
            logger.debug(f"Filtered duplicate URL '{canonical_url}': '{article.title}'")
            # Preserve cross-feed source attribution on the retained article
            for existing in cleaned_articles:
                if existing.url == canonical_url:
                    if not existing.all_sources:
                        existing.all_sources = [existing.source]
                    if article.source and article.source not in existing.all_sources:
                        existing.all_sources.append(article.source)
                    break
            continue

        seen_urls.add(canonical_url)

        # Update article URL with canonicalized version
        article.url = canonical_url
        if not article.all_sources:
            article.all_sources = [article.source]
        cleaned_articles.append(article)

    logger.info(
        f"Filtering complete: Ingested {len(articles)} -> Retained {len(cleaned_articles)} unique articles"
    )
    return cleaned_articles
