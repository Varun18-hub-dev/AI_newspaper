"""High-level persistence service orchestrating article deduplication and cluster persistence."""

from datetime import datetime, timedelta
import json
from typing import Dict, List, Optional, Set, Tuple

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.models import Article
from app.clustering.models import StoryCluster
from app.processing.models import ProcessedArticle
from app.storage.fingerprint import (
    compute_content_fingerprint,
    compute_story_fingerprint,
    generate_article_id,
    is_meaningful_update,
)
from app.storage.models import (
    ArticleRecord,
    ClusterMemberRecord,
    StorageMetrics,
    StoryClusterRecord,
)
from app.storage.sqlite import SQLiteDatabase

logger = setup_logger("storage_service")


class StorageService:
    """Coordinates persistence, cross-run article deduplication, and historical story tracking."""

    def __init__(self, db: Optional[SQLiteDatabase] = None):
        """Initializes service with SQLite database."""
        self.db = db or SQLiteDatabase()

    def article_record_to_article(self, rec: ArticleRecord) -> Article:
        """Converts database ArticleRecord back into an ingestion Article model."""
        return Article(
            title=rec.normalized_title,
            url=rec.canonical_url,
            source=rec.source,
            author=rec.author,
            published_at=rec.published_at,
            description=rec.extra_metadata.get("description"),
            content=rec.extra_metadata.get("content"),
            image_url=rec.extra_metadata.get("image_url"),
            discovered_at=rec.first_seen_at,
            domain=rec.domain,
            all_sources=rec.extra_metadata.get("all_sources", [rec.source]),
            raw_metadata={
                k: v
                for k, v in rec.extra_metadata.items()
                if k not in ("description", "content", "image_url", "all_sources", "agent_summary", "alternate_urls")
            },
        )

    def check_and_register_articles(
        self, articles: List[Article]
    ) -> Tuple[List[Article], List[Article], StorageMetrics]:
        """Checks incoming articles against database to filter previously seen items and register new ones.

        Idempotency: Repeatedly ingesting identical feeds updates last_seen_at without duplicate records.
        Fault-tolerance: Articles that previously failed during an earlier run are marked eligible for retry.

        Args:
            articles: Ingested and canonicalized articles.

        Returns:
            Tuple: (articles_to_process, skipped_articles, metrics)
        """
        metrics = StorageMetrics(articles_checked=len(articles))
        to_process: List[Article] = []
        skipped: List[Article] = []

        now = datetime.utcnow()

        for article in articles:
            fp = compute_content_fingerprint(
                article.content or article.description or "",
                title=article.title,
            )

            # 1. Lookup by canonical URL
            existing = self.db.get_article_by_canonical_url(article.url)

            # 2. Lookup by title and source if URL changed or redirected
            if not existing and article.title and article.source:
                existing = self.db.get_article_by_title_and_source(
                    article.title, article.source
                )

            # 3. Lookup by content fingerprint for changed URLs from the same source
            if not existing and fp:
                existing_fp = self.db.get_article_by_fingerprint(fp)
                if existing_fp and existing_fp.source == article.source:
                    existing = existing_fp

            if existing:
                # Refresh last seen timestamp
                self.db.update_article_seen(existing.id, now)

                # If URL changed from original canonical URL on same source, track alternate URL
                if existing.canonical_url != article.url:
                    alt_urls = existing.extra_metadata.get("alternate_urls", [])
                    if article.url not in alt_urls:
                        alt_urls.append(article.url)
                        existing.extra_metadata["alternate_urls"] = alt_urls
                        with self.db.get_connection() as conn:
                            conn.execute(
                                "UPDATE articles SET extra_metadata = ? WHERE id = ?;",
                                (json.dumps(existing.extra_metadata), existing.id),
                            )
                    logger.info(
                        f"Recognized changed URL for article '{existing.normalized_title[:45]}' "
                        f"(original='{existing.canonical_url}', new='{article.url}')"
                    )

                # Check processing status
                if existing.processing_status in (
                    "CLASSIFIED_RELEVANT",
                    "CLASSIFIED_IRRELEVANT",
                    "REJECTED_PREFILTER",
                ):
                    metrics.previously_seen_recognized += 1
                    metrics.exact_duplicates_skipped += 1
                    skipped.append(article)
                    logger.debug(
                        f"Skipping previously processed article '{article.title[:45]}' "
                        f"(status={existing.processing_status})"
                    )
                elif existing.processing_status == "FAILED":
                    # Eligible for retry
                    metrics.failed_articles_retried += 1
                    to_process.append(article)
                    logger.info(
                        f"Retrying previously failed article '{article.title[:45]}' (id={existing.id})"
                    )
                else:
                    # Incomplete or pending
                    to_process.append(article)
            else:
                # Brand new article
                art_id = generate_article_id(article.url)
                record = ArticleRecord(
                    id=art_id,
                    canonical_url=article.url,
                    original_url=article.url,
                    normalized_title=article.title,
                    source=article.source,
                    author=article.author,
                    published_at=article.published_at,
                    first_seen_at=now,
                    last_seen_at=now,
                    content_fingerprint=fp,
                    processing_status="PENDING",
                    domain=article.domain,
                    extra_metadata={
                        "description": article.description,
                        "content": article.content,
                        "image_url": getattr(article, "image_url", None),
                        "all_sources": getattr(article, "all_sources", [article.source]),
                        **getattr(article, "raw_metadata", {}),
                    },
                )
                try:
                    success = self.db.insert_article(record)
                    if success:
                        metrics.new_articles_persisted += 1
                        to_process.append(article)
                    else:
                        # Already exists via concurrent insert or collision
                        metrics.previously_seen_recognized += 1
                        skipped.append(article)
                except Exception as e:
                    logger.error(f"Failed to persist article '{article.url}': {e}")
                    metrics.storage_failures += 1
                    to_process.append(article)

        return to_process, skipped, metrics

    def get_historical_cluster_candidates(
        self, lookback_days: Optional[float] = None
    ) -> List[Tuple[StoryClusterRecord, Article]]:
        """Retrieves active historical clusters within lookback window along with representative articles.

        Args:
            lookback_days: Lookback window in days (defaults to settings.storage_history_lookback_days).

        Returns:
            List[Tuple[StoryClusterRecord, Article]]: Historical clusters and representative articles.
        """
        days = (
            lookback_days
            if lookback_days is not None
            else settings.storage_history_lookback_days
        )
        cutoff = datetime.utcnow() - timedelta(days=days)

        active_clusters = self.db.get_active_clusters_in_window(cutoff)
        candidates: List[Tuple[StoryClusterRecord, Article]] = []

        for cl_rec in active_clusters:
            rep_art_rec = self.db.get_article_by_id(cl_rec.representative_article_id)
            if rep_art_rec:
                art_obj = self.article_record_to_article(rep_art_rec)
                candidates.append((cl_rec, art_obj))

        logger.debug(
            f"Loaded {len(candidates)} historical cluster candidates within {days:.1f}d lookback window"
        )
        return candidates

    def persist_cluster_group(
        self,
        cluster: StoryCluster,
        is_update: bool = False,
        meaningful_update: bool = False,
        update_reason: Optional[str] = None,
    ) -> None:
        """Persists or updates a story cluster and its member relations."""
        now = datetime.utcnow()
        rep_id = generate_article_id(cluster.representative_article.url)

        # Check if cluster already exists in DB
        existing = self.db.get_cluster_by_id(cluster.cluster_id)

        first_seen = existing.first_seen_at if existing else now
        lifecycle = "UPDATED" if meaningful_update else ("ACTIVE" if not existing else existing.lifecycle_status)

        all_sources = list(set(cluster.sources + (existing.sources if existing else [])))

        cl_rec = StoryClusterRecord(
            id=cluster.cluster_id,
            representative_article_id=rep_id,
            first_seen_at=first_seen,
            last_seen_at=now,
            last_processed_at=now,
            story_fingerprint=compute_story_fingerprint(cluster.representative_article.title),
            lifecycle_status=lifecycle,
            source_count=len(all_sources),
            sources=all_sources,
            domain=cluster.representative_article.domain,
            extra_metadata={
                "similarity_score": cluster.similarity_score,
                "time_span_hours": cluster.time_span_hours,
            },
        )
        self.db.upsert_cluster(cl_rec)

        # Record all member relationships
        for mem in cluster.member_articles:
            mem_id = generate_article_id(mem.url)
            is_rep = (mem.url == cluster.representative_article.url)
            self.db.add_cluster_member(
                cluster_id=cluster.cluster_id,
                article_id=mem_id,
                is_representative=is_rep,
                is_meaningful_update=meaningful_update if not is_rep else False,
                update_reason=update_reason if not is_rep else None,
                added_at=now,
            )

    def mark_articles_prefilter_rejected(self, articles: List[Article]) -> None:
        """Records deterministic pre-filter rejection status for articles."""
        for art in articles:
            art_id = generate_article_id(art.url)
            self.db.update_article_status(
                article_id=art_id,
                status="REJECTED_PREFILTER",
                relevance_score=0.0,
            )

    def mark_article_failed(self, article: Article, error_msg: str) -> None:
        """Records processing failure for an article to allow future retry."""
        url_val = article.url if hasattr(article, "url") else str(article)
        art_id = generate_article_id(url_val)
        self.db.update_article_status(
            article_id=art_id,
            status="FAILED",
        )

    def persist_processed_article(self, processed: ProcessedArticle) -> None:
        """Updates article with final LLM relevance classification and cluster ID."""
        art_id = generate_article_id(processed.article.url)
        status = (
            "CLASSIFIED_RELEVANT"
            if processed.classification.is_relevant
            else "CLASSIFIED_IRRELEVANT"
        )
        fp = None
        if processed.extracted_content and processed.extracted_content.text:
            fp = compute_content_fingerprint(
                processed.extracted_content.text, title=processed.article.title
            )

        summary = processed.classification.reason if processed.classification else None

        self.db.update_article_status(
            article_id=art_id,
            status=status,
            relevance_score=processed.classification.relevance_score,
            topic=processed.classification.topic,
            cluster_id=processed.cluster_id,
            content_fingerprint=fp,
            summary=summary,
        )
