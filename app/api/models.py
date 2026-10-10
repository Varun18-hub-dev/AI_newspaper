"""Pydantic schemas for the Personalized AI Newspaper REST API."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, model_validator


class HealthResponse(BaseModel):
    """System health and storage readiness response."""

    status: str = Field(default="ok", description="Service health state")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    version: str = Field(default="1.0.0")
    database_connected: bool = True
    database_stats: Dict[str, Any] = Field(default_factory=dict)


class NewspaperStoryResponse(BaseModel):
    """Representative newspaper story summary for edition list and card display."""

    cluster_id: str
    headline: str
    summary: Optional[str] = None
    domain: str
    topic: Optional[str] = "General"
    published_at: Optional[str] = None
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    representative_source: str
    representative_url: str
    source_count: int = 1
    sources: List[str] = Field(default_factory=list)
    has_updates: bool = False
    update_reason: Optional[str] = None
    relevance_score: Optional[float] = None
    member_count: int = 1
    image_url: Optional[str] = None


class StoryMemberResponse(BaseModel):
    """Detailed member article within a multi-source story cluster."""

    article_id: str
    title: str
    url: str
    canonical_url: str
    source: str
    author: Optional[str] = None
    published_at: Optional[str] = None
    domain: str
    topic: Optional[str] = None
    relevance_score: Optional[float] = None
    is_representative: bool = False
    is_meaningful_update: bool = False
    update_reason: Optional[str] = None
    added_at: Optional[str] = None
    excerpt: Optional[str] = None
    image_url: Optional[str] = None


class StoryDetailResponse(BaseModel):
    """Complete detail view of a story cluster including all source articles."""

    cluster_id: str
    headline: str
    summary: Optional[str] = None
    domain: str
    topic: Optional[str] = "General"
    published_at: Optional[str] = None
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    representative_source: str
    representative_url: str
    source_count: int = 1
    sources: List[str] = Field(default_factory=list)
    image_url: Optional[str] = None
    lifecycle_status: str = "ACTIVE"
    members: List[StoryMemberResponse] = Field(default_factory=list)


class PaginatedStoriesResponse(BaseModel):
    """Paginated collection of newspaper stories."""

    items: List[NewspaperStoryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int
    domain_filter: Optional[str] = None
    topic_filter: Optional[str] = None
    edition_id: Optional[str] = None
    published_at: Optional[str] = None
    is_stale: bool = False


class DomainItemResponse(BaseModel):
    """Configured news domain with taxonomy and article counts."""

    domain_id: str
    display_name: str
    description: str
    topics: List[str] = Field(default_factory=list)
    article_count: int = 0
    cluster_count: int = 0
    is_enabled: bool = True


class DomainsListResponse(BaseModel):
    """List of all supported news domains."""

    domains: List[DomainItemResponse]
    total_domains: int


class PipelineRunResponse(BaseModel):
    """Telemetry and lifecycle status of a discovery pipeline execution."""

    id: str
    run_id: Optional[str] = None
    trigger_type: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    status: str
    articles_discovered: int = 0
    articles_deduplicated: int = 0
    articles_prefiltered: int = 0
    clusters_formed: int = 0
    qwen_evaluations: int = 0
    articles_stored: int = 0
    domain_counts: Dict[str, int] = Field(default_factory=dict)
    feed_errors: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None
    run_metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def populate_run_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "run_id" not in data and "id" in data:
                data["run_id"] = data["id"]
        return data


class PaginatedRunsResponse(BaseModel):
    """List of recent pipeline runs."""

    items: List[PipelineRunResponse]
    total: int
    limit: int


class ManualRefreshResponse(BaseModel):
    """Response returned when a manual pipeline run is requested."""

    status: str = Field(..., description="TRIGGERED, ALREADY_RUNNING, or FAILED")
    message: str
    run_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
