"""Pipeline execution runner with telemetry tracking, error isolation, and persistence."""

from datetime import datetime
import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.coordinator import MultiSourceDiscoveryCoordinator
from app.ingestion.models import Article
from app.ingestion.rss import RSSConnector
from app.processing.article_processor import ArticleProcessor
from app.processing.models import ProcessedArticle, PipelineMetrics
from app.scheduler.lock import PipelineRunAlreadyActiveError, PipelineRunLock
from app.storage.models import PipelineRunRecord
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase

logger = setup_logger("pipeline_runner")


def generate_run_id() -> str:
    """Generates unique run ID with timestamp and random suffix."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    return f"run_{ts}_{rand_suffix}"


class DailyPipelineRunner:
    """Coordinates daily and manual execution of multi-domain discovery pipeline."""

    def __init__(
        self,
        db: Optional[SQLiteDatabase] = None,
        storage_service: Optional[StorageService] = None,
        rss_connector: Optional[RSSConnector] = None,
        article_processor: Optional[ArticleProcessor] = None,
        lock_file_path: Optional[str] = None,
        discovery_coordinator: Optional[MultiSourceDiscoveryCoordinator] = None,
    ):
        """Initializes the pipeline runner.

        Args:
            db: SQLiteDatabase instance. Defaults to shared SQLiteDatabase.
            storage_service: StorageService instance.
            rss_connector: RSSConnector instance.
            article_processor: ArticleProcessor instance.
            lock_file_path: Optional path to lockfile for overlap prevention.
            discovery_coordinator: Optional MultiSourceDiscoveryCoordinator instance.
        """
        self.db = db or SQLiteDatabase()
        self.storage_service = storage_service or StorageService(db=self.db)
        self.connector = rss_connector or RSSConnector()
        self._custom_connector_injected = rss_connector is not None
        self._custom_coordinator_injected = discovery_coordinator is not None
        self.coordinator = discovery_coordinator or MultiSourceDiscoveryCoordinator(
            rss_connector=self.connector
        )
        self.processor = article_processor or ArticleProcessor(
            storage_service=self.storage_service
        )
        self.lock = PipelineRunLock(lock_file_path=lock_file_path)

    def run_pipeline(
        self,
        trigger_type: str = "SCHEDULED",
        domains: Optional[List[str]] = None,
        max_candidates: Optional[int] = None,
        articles: Optional[List[Article]] = None,
        raise_on_overlap: bool = True,
        enable_agentic_workflow: Optional[bool] = None,
    ) -> PipelineRunRecord:
        """Executes the complete news discovery and processing pipeline with run tracking.

        Args:
            trigger_type: Execution trigger ('SCHEDULED' or 'MANUAL').
            domains: Optional list of domains to ingest (default: all enabled).
            max_candidates: Optional limit on LLM candidate classifications.
            articles: Optional pre-collected articles (for tests or mocked runs).
            raise_on_overlap: Whether to raise PipelineRunAlreadyActiveError if locked.

        Returns:
            PipelineRunRecord: Persisted run record containing lifecycle status and telemetry.

        Raises:
            PipelineRunAlreadyActiveError: If another run is currently holding the lock.
        """
        # 1. Acquire concurrency lock
        try:
            self.lock.acquire()
        except PipelineRunAlreadyActiveError as err:
            logger.warning(f"Pipeline run skipped due to concurrency lock: {err}")
            if raise_on_overlap:
                raise
            # Return synthetic or last record if not raising
            return PipelineRunRecord(
                id=generate_run_id(),
                trigger_type=trigger_type,
                status="LOCKED_SKIPPED",
                error_message=str(err),
            )

        run_id = generate_run_id()
        started_at = datetime.utcnow()
        start_time_perf = time.time()

        run_record = PipelineRunRecord(
            id=run_id,
            trigger_type=trigger_type.upper(),
            started_at=started_at,
            status="RUNNING",
        )

        try:
            # Clean up any orphaned RUNNING records from prior process crashes
            stale_count = self.db.cleanup_interrupted_runs()
            if stale_count > 0:
                logger.warning(f"Cleaned up {stale_count} orphaned RUNNING records from previous crashed processes.")

            # Persist initial RUNNING state
            self.db.insert_run(run_record)
            logger.info(f"=== Starting pipeline run {run_id} ({trigger_type}) ===")

            feed_errors: List[str] = []
            domain_counts: Dict[str, int] = {}

            # 2. Ingestion Phase
            if articles is None:
                target_domains = domains if domains is not None else settings.enabled_domains
                if self._custom_connector_injected and not self._custom_coordinator_injected:
                    logger.info(f"Fetching RSS feeds for domains: {target_domains}")
                    raw_articles, feed_statuses = self.connector.fetch_all_domains(target_domains)
                else:
                    logger.info(f"Discovering multi-source news for domains: {target_domains}")
                    raw_articles, feed_statuses = self.coordinator.discover_all(target_domains)

                # Record feed statuses & errors
                for source_key, status_info in feed_statuses.items():
                    if isinstance(status_info, dict) and status_info.get("status") not in (
                        "SUCCESS",
                        "EMPTY",
                        "DISABLED",
                        "SKIPPED_DOMAIN",
                    ):
                        err_msg = f"{source_key} ({status_info.get('domain', 'source')}): {status_info.get('error')}"
                        feed_errors.append(err_msg)
                        logger.warning(f"Source/Feed error recorded: {err_msg}")
            else:
                raw_articles = articles
                feed_statuses = {}

            run_record.articles_discovered = len(raw_articles)
            run_record.feed_errors = feed_errors

            # Calculate article domain breakdown
            for art in raw_articles:
                d_key = (art.domain or "ai").lower()
                domain_counts[d_key] = domain_counts.get(d_key, 0) + 1
            run_record.domain_counts = domain_counts

            logger.info(
                f"Discovered {len(raw_articles)} articles across {len(domain_counts)} domains "
                f"({len(feed_errors)} feed errors recorded)."
            )

            # 3. Processing Phase (dedup, extraction, pre-filter, clustering, Qwen, persistence)
            processed_articles: List[ProcessedArticle] = []
            metrics: Optional[PipelineMetrics] = None

            if raw_articles:
                use_agentic = (
                    enable_agentic_workflow
                    if enable_agentic_workflow is not None
                    else settings.enable_agentic_intelligence
                )
                processed_articles, metrics = self.processor.process_with_metrics(
                    articles=raw_articles,
                    max_candidates=max_candidates,
                    enable_storage=True,
                    enable_agentic_workflow=use_agentic,
                )

                run_record.articles_deduplicated = getattr(metrics, "valid_articles", len(raw_articles))
                run_record.articles_prefiltered = getattr(metrics, "candidates_passed_to_llm", 0)
                run_record.clusters_formed = getattr(metrics, "total_clusters", 0)
                run_record.qwen_evaluations = getattr(metrics, "qwen_calls", 0)

                # Count articles stored or registered
                run_record.articles_stored = getattr(metrics, "new_articles_persisted", 0) or getattr(metrics, "valid_articles", len(raw_articles))

                run_record.run_metadata = {
                    "multi_source_clusters": getattr(metrics, "multi_source_clusters", 0),
                    "historical_story_matches": getattr(metrics, "historical_story_matches", 0),
                    "meaningful_story_updates_detected": getattr(metrics, "meaningful_story_updates_detected", 0),
                    "clustering_saved_calls": getattr(metrics, "clustering_saved_calls", 0),
                    "qwen_evaluations_avoided": getattr(metrics, "qwen_evaluations_avoided", 0),
                    "qwen_relevant": getattr(metrics, "qwen_relevant", 0),
                    "qwen_irrelevant": getattr(metrics, "qwen_irrelevant", 0),
                    "reduction_percentage": getattr(metrics, "reduction_percentage", 0.0),
                }
            else:
                logger.info("No articles discovered in this run.")

            # 4. Status Determination
            if feed_errors and len(raw_articles) == 0:
                # All feeds failed and zero articles discovered
                run_record.status = "FAILED"
                run_record.error_message = f"All feed ingests failed: {'; '.join(feed_errors[:3])}"
            elif feed_errors and len(raw_articles) > 0:
                # Partial feed failures, but some succeeded
                run_record.status = "PARTIAL_SUCCESS"
            else:
                run_record.status = "SUCCESS"

            completed_at = datetime.utcnow()
            run_record.completed_at = completed_at
            run_record.duration_seconds = round(time.time() - start_time_perf, 2)

            self.db.update_run(run_record)
            logger.info(
                f"=== Finished pipeline run {run_id}: status={run_record.status}, "
                f"duration={run_record.duration_seconds}s, "
                f"discovered={run_record.articles_discovered}, "
                f"clusters={run_record.clusters_formed}, "
                f"qwen={run_record.qwen_evaluations} ==="
            )
            return run_record

        except Exception as exc:
            logger.critical(f"Pipeline run {run_id} failed with critical exception: {exc}", exc_info=True)
            run_record.status = "FAILED"
            run_record.error_message = str(exc)
            run_record.completed_at = datetime.utcnow()
            run_record.duration_seconds = round(time.time() - start_time_perf, 2)
            try:
                self.db.update_run(run_record)
            except Exception as update_err:
                logger.error(f"Failed to record run failure in SQLite: {update_err}")
            raise

        finally:
            self.lock.release()
