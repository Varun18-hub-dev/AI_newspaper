"""Fingerprinting and story update detection utilities for Phase 5."""

import hashlib
import re
from typing import Optional, Set, Tuple

from app.core.config import settings
from app.ingestion.models import Article


def generate_article_id(canonical_url: str) -> str:
    """Generates a stable, deterministic article ID based on its canonical URL."""
    cleaned = canonical_url.strip().lower()
    digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()[:16]
    return f"art_{digest}"


def generate_cluster_id(representative_article_id: str, timestamp_str: str) -> str:
    """Generates a stable unique cluster ID."""
    raw = f"{representative_article_id}_{timestamp_str}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"cluster_{digest}"


def normalize_text_tokens(text: str) -> Set[str]:
    """Tokenizes and cleans text into a set of lowercased alphanumeric words."""
    if not text:
        return set()
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = {t.strip() for t in cleaned.split() if len(t.strip()) > 2}
    return tokens


def compute_content_fingerprint(
    text: Optional[str], title: Optional[str] = None
) -> str:
    """Computes a SHA-256 fingerprint for article prose or summary.

    Args:
        text: Article body or description.
        title: Optional headline to incorporate.

    Returns:
        str: Hexadecimal SHA-256 digest.
    """
    body = (text or "").strip()
    head = (title or "").strip()
    combined = f"{head}\n{body}".strip().lower()
    # Normalize excessive whitespace
    normalized = re.sub(r"\s+", " ", combined)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_story_fingerprint(
    title: str,
    entities: Optional[Set[str]] = None,
    products: Optional[Set[str]] = None,
) -> str:
    """Computes a deterministic fingerprint representing an event cluster."""
    ent_part = ",".join(sorted(entities or []))
    prod_part = ",".join(sorted(products or []))
    title_tokens = ",".join(sorted(normalize_text_tokens(title)))
    raw = f"ent:{ent_part}|prod:{prod_part}|title:{title_tokens}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# Regex pattern identifying explicit editorial update signals
UPDATE_MARKERS_PATTERN = re.compile(
    r"\b(update|updated|follow-up|followup|confirmed|rollback|rolls out|patch|fixes|rectifies|response)\b",
    re.IGNORECASE,
)


def is_meaningful_update(
    old_article: Article,
    new_article: Article,
    time_diff_hours: float,
    old_text: Optional[str] = None,
    new_text: Optional[str] = None,
    jaccard_threshold: Optional[float] = None,
    time_threshold_hours: Optional[float] = None,
) -> Tuple[bool, str]:
    """Determines whether a new article covering an existing event represents a meaningful update.

    Implements a conservative, deterministic policy:
    1. Explicit editorial markers in headline ("Update:", "Confirmed:", etc.).
    2. Substantial textual vocabulary expansion / Jaccard distance (> threshold)
       published after a notable elapsed time (> time threshold).
    3. Otherwise, treated as duplicate/redundant coverage.

    Args:
        old_article: Baseline or representative article of the existing cluster.
        new_article: Newly discovered article matching the same event.
        time_diff_hours: Publication or discovery difference in hours.
        old_text: Text body or description of baseline article.
        new_text: Text body or description of new article.
        jaccard_threshold: Minimum Jaccard distance to qualify as new content.
        time_threshold_hours: Minimum hours between articles for content updates.

    Returns:
        Tuple[bool, str]: (is_meaningful, reason)
    """
    j_thresh = (
        jaccard_threshold
        if jaccard_threshold is not None
        else settings.meaningful_update_jaccard_threshold
    )
    t_thresh = (
        time_threshold_hours
        if time_threshold_hours is not None
        else settings.meaningful_update_time_threshold_hours
    )

    # Rule 1: Check explicit update signals in new article headline
    if UPDATE_MARKERS_PATTERN.search(new_article.title):
        return True, "Headline contains explicit update marker (e.g. Update/Confirmed/Follow-up)"

    # Rule 2: Text vocabulary divergence over time
    body_old = old_text or old_article.description or ""
    body_new = new_text or new_article.description or ""

    tokens_old = normalize_text_tokens(f"{old_article.title} {body_old}")
    tokens_new = normalize_text_tokens(f"{new_article.title} {body_new}")

    if tokens_old and tokens_new:
        intersection = len(tokens_old.intersection(tokens_new))
        union = len(tokens_old.union(tokens_new))
        jaccard_sim = intersection / union if union > 0 else 1.0
        jaccard_dist = 1.0 - jaccard_sim

        # If vocabulary changed significantly and sufficient time elapsed
        if jaccard_dist >= j_thresh and time_diff_hours >= t_thresh:
            return (
                True,
                f"Substantial vocabulary divergence ({jaccard_dist:.2f} >= {j_thresh}) "
                f"after {time_diff_hours:.1f}h elapsed",
            )

    return False, "Redundant or duplicate coverage without substantial new disclosures"
