"""Daily GPU Worker Pipeline Runner orchestrating full ingestion, publication, and shutdown."""

from datetime import datetime
import logging
import time
from typing import Any, Dict, List, Optional, Tuple
import uuid

from app.core.config import settings
from app.core.logging import setup_logger
from app.ingestion.coordinator import MultiSourceDiscoveryCoordinator
from app.ingestion.models import Article
from app.orchestration.ec2_controller import EC2WorkerController
from app.orchestration.lifecycle import LifecycleManager, WorkerState
from app.orchestration.watchdog import WorkerWatchdog
from app.processing.article_processor import ArticleProcessor
from app.processing.models import ProcessedArticle
from app.storage.publisher import EditionPublisher, EditionStory, EditionManifest
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase

logger = setup_logger("gpu_worker_runner")


def generate_edition_id() -> str:
    """Generates unique daily edition identifier (e.g. edition_20261010_060000)."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"edition_{ts}"


def generate_run_id() -> str:
    """Generates unique pipeline execution run identifier."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    return f"run_{ts}_{rand_suffix}"


class GPUWorkerPipelineRunner:
    """Coordinates daily scheduled news ingestion, model intelligence, atomic publication, and self-shutdown."""

    def __init__(
        self,
        db: Optional[SQLiteDatabase] = None,
        storage_service: Optional[StorageService] = None,
        publisher: Optional[EditionPublisher] = None,
        discovery_coordinator: Optional[MultiSourceDiscoveryCoordinator] = None,
        article_processor: Optional[ArticleProcessor] = None,
        ec2_controller: Optional[EC2WorkerController] = None,
        watchdog: Optional[WorkerWatchdog] = None,
    ):
        self.db = db or SQLiteDatabase()
        self.storage_service = storage_service or StorageService(db=self.db)
        self.publisher = publisher or EditionPublisher()
        self.coordinator = discovery_coordinator or MultiSourceDiscoveryCoordinator()
        self.processor = article_processor or ArticleProcessor(storage_service=self.storage_service)
        self.ec2 = ec2_controller or EC2WorkerController()
        self.watchdog = watchdog or WorkerWatchdog()

    def run_worker_pipeline(
        self,
        domains: Optional[List[str]] = None,
        enable_agentic_workflow: Optional[bool] = None,
        auto_stop_on_finish: Optional[bool] = None,
        enable_llm_inference: Optional[bool] = None,
    ) -> Tuple[bool, Optional[EditionManifest], Dict[str, Any]]:
        """Executes the complete daily GPU worker pipeline lifecycle.

        Steps:
        1. Initialize LifecycleManager & Watchdog.
        2. System Readiness Verification (Storage, Health).
        3. Multi-Source Ingestion across 23 RSS feeds + arXiv + HN + GitHub + NVD.
        4. Article Processing (Deduplication, Extraction, Pre-filter, Clustering, Evaluation).
        5. Atomic Edition Publishing (Validation Gate, Checksums, Pointer Flip).
        6. Controlled Shutdown via EC2 Control Plane.

        Returns:
            Tuple[bool, Optional[EditionManifest], Dict[str, Any]]:
                - Success flag
                - Published EditionManifest (or None if failed)
                - Lifecycle telemetry context
        """
        run_id = generate_run_id()
        edition_id = generate_edition_id()
        lifecycle = LifecycleManager(run_id=run_id, edition_id=edition_id)
        self.watchdog.start()

        auto_stop = (
            auto_stop_on_finish
            if auto_stop_on_finish is not None
            else getattr(settings, "auto_stop_worker", False)
        )

        logger.info(f"=== Starting Daily GPU Worker Pipeline: {run_id} ({edition_id}) ===")

        # Step 1: Readiness Check
        try:
            db_stats = self.db.get_database_stats()
            lifecycle.transition_to(
                WorkerState.READY,
                message=f"Database connectivity confirmed (total articles: {db_stats.get('total_articles', 0)})",
            )
        except Exception as err:
            err_msg = f"Readiness check failed: {err}"
            lifecycle.transition_to(WorkerState.FAILED, message=err_msg)
            self._handle_shutdown(lifecycle, auto_stop)
            return False, None, lifecycle.context.model_dump()

        # Step 2: Multi-Source Ingestion & Processing
        lifecycle.transition_to(WorkerState.RUNNING, message="Starting multi-source ingestion")
        target_domains = domains if domains is not None else settings.enabled_domains

        try:
            # 2a. Discover articles
            raw_articles, source_statuses = self.coordinator.discover_all(domains=target_domains)
            logger.info(f"Discovered {len(raw_articles)} raw articles across sources.")

            # Check watchdog limits
            is_expired, is_warning, watch_msg = self.watchdog.check()
            if is_expired:
                lifecycle.transition_to(WorkerState.FAILED, message=watch_msg)
                self._handle_shutdown(lifecycle, auto_stop)
                return False, None, lifecycle.context.model_dump()

            # 2b. Process articles
            use_agentic = (
                enable_agentic_workflow
                if enable_agentic_workflow is not None
                else getattr(settings, "enable_agentic_intelligence", False)
            )

            processed_articles: List[ProcessedArticle] = []
            if raw_articles:
                processed_articles, metrics = self.processor.process_with_metrics(
                    articles=raw_articles,
                    enable_agentic_workflow=use_agentic,
                    enable_llm_inference=enable_llm_inference,
                )
            logger.info(f"Processed {len(processed_articles)} candidate articles.")

            # Step 3: Atomic Edition Assembly & Publishing
            lifecycle.transition_to(WorkerState.PUBLISHING, message="Assembling and validating daily edition")

            edition_stories: List[EditionStory] = []
            for pa in processed_articles:
                art = pa.article
                # Build summary from agentic reasoning, description, or fallback
                summary_text = (
                    pa.classification.reason
                    if pa.classification and pa.classification.reason and len(pa.classification.reason.strip()) >= 10
                    else (
                        art.description
                        if art.description and len(art.description.strip()) >= 10
                        else f"{art.title} - Coverage from {art.source}."
                    )
                )
                story = EditionStory(
                    story_id=pa.cluster_id or f"story_{art.url[:16]}",
                    title=art.title,
                    url=art.url,
                    domain=art.domain,
                    topic=pa.classification.topic if pa.classification else None,
                    summary=summary_text,
                    sources=art.all_sources if art.all_sources else [art.source],
                    published_at=art.published_at.isoformat() if art.published_at else None,
                    first_seen_at=art.discovered_at.isoformat(),
                    relevance_score=pa.classification.relevance_score if pa.classification else 1.0,
                    image_url=getattr(art, "image_url", None),
                    raw_metadata=art.raw_metadata,
                )
                edition_stories.append(story)

            # Publish with validation gate
            pub_ok, manifest, pub_err = self.publisher.publish_edition(
                edition_id=edition_id,
                stories=edition_stories,
                run_id=run_id,
            )

            if pub_ok and manifest:
                has_degraded = any(
                    isinstance(v, dict) and v.get("status") in ("FAILED", "RATE_LIMITED")
                    for v in source_statuses.values()
                )
                final_state = WorkerState.PARTIAL_SUCCESS if has_degraded else WorkerState.SUCCESS
                lifecycle.transition_to(
                    final_state,
                    message=f"Edition '{edition_id}' published successfully with {len(edition_stories)} stories.",
                    telemetry={
                        "total_stories": len(edition_stories),
                        "sources_count": len(manifest.sources_represented),
                        "domain_distribution": manifest.domain_counts,
                    },
                )
                self._handle_shutdown(lifecycle, auto_stop)
                return True, manifest, lifecycle.context.model_dump()
            else:
                err_msg = f"Atomic edition publishing failed: {pub_err}"
                lifecycle.transition_to(WorkerState.FAILED, message=err_msg)
                self._handle_shutdown(lifecycle, auto_stop)
                return False, None, lifecycle.context.model_dump()

        except Exception as err:
            err_msg = f"Worker pipeline encountered unexpected error: {err}"
            logger.error(err_msg, exc_info=True)
            lifecycle.transition_to(WorkerState.FAILED, message=err_msg)
            self._handle_shutdown(lifecycle, auto_stop)
            return False, None, lifecycle.context.model_dump()

    def _handle_shutdown(self, lifecycle: LifecycleManager, auto_stop: bool) -> None:
        """Handles controlled shutdown transitions."""
        if auto_stop:
            lifecycle.transition_to(WorkerState.STOPPING, message="Initiating EC2 self-shutdown")
            self.ec2.stop_worker()
            lifecycle.transition_to(WorkerState.STOPPED, message="Worker shutdown confirmed")
        else:
            logger.info("Auto-stop disabled; worker remaining active for development/inspection.")
