"""FastAPI route handlers for newspaper browsing, domain taxonomy, run history, and refresh triggers."""

from datetime import datetime
import hmac
import math
import threading
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, status

from app.api.models import (
    DomainItemResponse,
    DomainsListResponse,
    HealthResponse,
    ManualRefreshResponse,
    NewspaperStoryResponse,
    PaginatedRunsResponse,
    PaginatedStoriesResponse,
    PipelineRunResponse,
    StoryDetailResponse,
    StoryMemberResponse,
)
from app.core.config import settings
from app.core.logging import setup_logger
from app.domains.registry import get_domain_registry
from app.scheduler.lock import PipelineRunAlreadyActiveError
from app.scheduler.runner import DailyPipelineRunner, generate_run_id
from app.storage.sqlite import SQLiteDatabase

logger = setup_logger("api_routes")

router = APIRouter(prefix="/api", tags=["newspaper"])

# Shared singleton dependencies
_DB: Optional[SQLiteDatabase] = None
_RUNNER: Optional[DailyPipelineRunner] = None


def get_db() -> SQLiteDatabase:
    """Returns or lazily initializes the shared SQLiteDatabase instance."""
    global _DB
    if _DB is None:
        _DB = SQLiteDatabase()
    return _DB


def get_runner() -> DailyPipelineRunner:
    """Returns or lazily initializes the shared DailyPipelineRunner instance."""
    global _RUNNER
    if _RUNNER is None:
        _RUNNER = DailyPipelineRunner(db=get_db())
    return _RUNNER


# =============================================================================
# 1. System Health
# =============================================================================
@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Returns the operational status, database connectivity, and persistent storage metrics."""
    db = get_db()
    try:
        stats = db.get_database_stats()
        return HealthResponse(
            status="ok",
            database_connected=True,
            database_stats={
                "total_articles": stats.get("total_articles", 0),
                "total_story_clusters": stats.get("total_story_clusters", 0),
                "total_cluster_members": stats.get("total_cluster_members", 0),
                "classified_articles": stats.get("classified_articles", 0),
                "total_pipeline_runs": stats.get("total_pipeline_runs", 0),
                "db_size_bytes": stats.get("db_size_bytes", 0),
            },
        )
    except Exception as err:
        logger.error(f"Health check database failure: {err}")
        return HealthResponse(
            status="degraded",
            database_connected=False,
            database_stats={"error": str(err)},
        )


# =============================================================================
# 2. Newspaper Editions & Stories
# =============================================================================
@router.get("/newspaper/latest", response_model=PaginatedStoriesResponse)
def get_latest_edition(
    domain: Optional[str] = Query(None, description="Filter stories by domain (e.g. ai, technology, science, cybersecurity, business)"),
    topic: Optional[str] = Query(None, description="Filter stories by subtopic"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(12, ge=1, le=50, description="Number of stories per page"),
) -> PaginatedStoriesResponse:
    """Returns the latest curated newspaper stories with optional domain and topic filtering.

    Reads atomically from the published edition manifest; falls back to SQLite database if
    no published edition is active.
    """
    from app.storage.publisher import EditionPublisher

    publisher = EditionPublisher()
    manifest = publisher.get_current_edition()

    if manifest and manifest.stories:
        filtered_stories = manifest.stories
        if domain:
            norm_d = domain.strip().lower()
            filtered_stories = [s for s in filtered_stories if s.domain.lower() == norm_d]
        if topic:
            norm_t = topic.strip().lower()
            filtered_stories = [s for s in filtered_stories if (s.topic or "").lower() == norm_t]

        total = len(filtered_stories)
        total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
        start_idx = (page - 1) * page_size
        paged_slice = filtered_stories[start_idx : start_idx + page_size]

        # Calculate staleness (> 24 hours since published_at)
        is_stale = False
        try:
            pub_dt = datetime.fromisoformat(manifest.published_at.replace("Z", "+00:00"))
            if pub_dt.tzinfo:
                pub_dt = pub_dt.replace(tzinfo=None)
            is_stale = (datetime.utcnow() - pub_dt).total_seconds() > 86400
        except Exception:
            pass

        items = [
            NewspaperStoryResponse(
                cluster_id=s.story_id,
                headline=s.title,
                summary=s.summary,
                domain=s.domain,
                topic=s.topic or "General",
                published_at=s.published_at,
                first_seen_at=s.first_seen_at,
                representative_source=s.sources[0] if s.sources else "Unknown",
                representative_url=s.url,
                source_count=len(s.sources),
                sources=s.sources,
                relevance_score=s.relevance_score,
                member_count=len(s.sources),
                image_url=getattr(s, "image_url", None) or s.raw_metadata.get("image_url"),
            )
            for s in paged_slice
        ]

        return PaginatedStoriesResponse(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            domain_filter=domain,
            topic_filter=topic,
            edition_id=manifest.edition_id,
            published_at=manifest.published_at,
            is_stale=is_stale,
        )

    # Fallback to direct SQLite query
    db = get_db()
    stories_data, total = db.get_newspaper_stories(
        domain=domain,
        topic=topic,
        page=page,
        page_size=page_size,
    )

    items = [NewspaperStoryResponse(**s) for s in stories_data]
    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1

    return PaginatedStoriesResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
        domain_filter=domain,
        topic_filter=topic,
        edition_id=None,
        published_at=None,
        is_stale=False,
    )


@router.get("/newspaper/stories/{cluster_id}", response_model=StoryDetailResponse)
def get_story_detail(cluster_id: str) -> StoryDetailResponse:
    """Retrieves complete details of a story cluster, including all syndicating sources and updates."""
    db = get_db()
    detail = db.get_story_detail(cluster_id)
    if not detail:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Story cluster '{cluster_id}' not found.",
        )

    members = [StoryMemberResponse(**m) for m in detail["members"]]
    detail["members"] = members
    return StoryDetailResponse(**detail)


# =============================================================================
# 3. Domain Registry & Taxonomies
# =============================================================================
@router.get("/domains", response_model=DomainsListResponse)
def list_domains() -> DomainsListResponse:
    """Lists all configured news domains, controlled taxonomies, and live story counts."""
    registry = get_domain_registry()
    db = get_db()
    stats = db.get_domain_and_topic_counts()
    cluster_counts = stats.get("cluster_counts", {})
    article_counts = stats.get("article_counts", {})

    items: list[DomainItemResponse] = []
    for d_cfg in registry.list_domains(enabled_only=False):
        items.append(
            DomainItemResponse(
                domain_id=d_cfg.domain_id,
                display_name=d_cfg.display_name,
                description=d_cfg.description,
                topics=d_cfg.allowed_topics,
                article_count=article_counts.get(d_cfg.domain_id.lower(), 0),
                cluster_count=cluster_counts.get(d_cfg.domain_id.lower(), 0),
                is_enabled=d_cfg.enabled,
            )
        )

    return DomainsListResponse(domains=items, total_domains=len(items))


# =============================================================================
# 4. Pipeline Runs & Telemetry
# =============================================================================
@router.get("/runs/latest", response_model=Optional[PipelineRunResponse])
def get_latest_run() -> Optional[PipelineRunResponse]:
    """Retrieves the most recent automated or manual pipeline execution."""
    db = get_db()
    recent = db.get_recent_runs(limit=1)
    if not recent:
        return None
    r = recent[0]
    return PipelineRunResponse(**r.model_dump())


@router.get("/runs", response_model=PaginatedRunsResponse)
def list_recent_runs(
    limit: int = Query(10, ge=1, le=50, description="Max runs to return"),
) -> PaginatedRunsResponse:
    """Lists recent pipeline run executions ordered from newest to oldest."""
    db = get_db()
    runs = db.get_recent_runs(limit=limit)
    items = [PipelineRunResponse(**r.model_dump()) for r in runs]
    return PaginatedRunsResponse(items=items, total=len(items), limit=limit)


# =============================================================================
# 5. Non-Blocking Manual Refresh
# =============================================================================
def _execute_refresh_in_background(
    runner: DailyPipelineRunner,
    domains: Optional[list[str]] = None,
    enable_agentic_workflow: Optional[bool] = None,
) -> None:
    """Executes the pipeline runner safely in a worker thread."""
    try:
        runner.run_pipeline(
            trigger_type="MANUAL",
            domains=domains,
            raise_on_overlap=False,
            enable_agentic_workflow=enable_agentic_workflow,
        )
    except Exception as err:
        logger.error(f"Background manual refresh encountered error: {err}")


@router.post("/runs/refresh", response_model=ManualRefreshResponse, status_code=status.HTTP_202_ACCEPTED)
def trigger_manual_refresh(
    domains: Optional[str] = Query(None, description="Comma-separated domains to refresh (optional)"),
    agentic: Optional[bool] = Query(None, description="Enable LangGraph agentic intelligence (optional)"),
    admin_key: Optional[str] = Query(None, description="Admin API key for protected trigger"),
    x_admin_api_key: Optional[str] = Header(None, alias="X-Admin-Api-Key", description="Admin API key header"),
) -> ManualRefreshResponse:
    """Triggers an asynchronous manual execution of the multi-domain discovery pipeline.

    Security & Guarantees:
    - Protected by admin API key if ADMIN_API_KEY is configured in environment.
    - Non-blocking: returns HTTP 202 Accepted immediately.
    - Prevents overlapping executions: returns HTTP 409 Conflict if another run is active.
    """
    # 1. Security Verification
    configured_key = getattr(settings, "admin_api_key", None)
    if configured_key:
        provided_key = x_admin_api_key or admin_key
        if not provided_key or not hmac.compare_digest(provided_key, configured_key):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized: Valid X-Admin-Api-Key or admin_key required to trigger pipeline.",
            )

    runner = get_runner()

    # 2. Check if concurrency lock is currently held
    if runner.lock.is_locked():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A pipeline run is already currently active. Please wait for it to complete.",
        )

    domain_list = [d.strip() for d in domains.split(",") if d.strip()] if domains else None

    # 3. Launch background execution thread
    worker_thread = threading.Thread(
        target=_execute_refresh_in_background,
        args=(runner, domain_list, agentic),
        daemon=True,
        name="ManualRefreshWorkerThread",
    )
    worker_thread.start()

    logger.info("Manual refresh pipeline triggered asynchronously.")
    return ManualRefreshResponse(
        status="TRIGGERED",
        message="Discovery pipeline started in background. Monitor /api/runs/latest for real-time progress.",
    )


# =============================================================================
# 6. Published Editions History
# =============================================================================
@router.get("/editions")
def list_published_editions(limit: int = Query(30, ge=1, le=100)):
    """Lists historical published daily newspaper editions."""
    from app.storage.publisher import EditionPublisher

    publisher = EditionPublisher()
    editions = publisher.list_editions(limit=limit)
    current_ptr = publisher.get_current_pointer()
    return {
        "current_edition_id": current_ptr.edition_id if current_ptr else None,
        "current_published_at": current_ptr.published_at if current_ptr else None,
        "editions": editions,
        "total": len(editions),
    }
