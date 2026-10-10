"""Data models for persistent storage and cross-run deduplication (Phase 5)."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ArticleRecord(BaseModel):
    """Database record representation of an ingested or processed article."""

    id: str = Field(..., description="Stable deterministic article ID (e.g. art_<hash>)")
    canonical_url: str = Field(..., description="Canonicalized article URL")
    original_url: str = Field(..., description="Original raw URL as provided by feed")
    normalized_title: str = Field(..., description="Cleaned article headline")
    source: str = Field(..., description="Publishing source name")
    author: Optional[str] = Field(default=None, description="Article author")
    published_at: Optional[datetime] = Field(default=None, description="Original publication timestamp")
    first_seen_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when article was first ingested"
    )
    last_seen_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when article was most recently observed"
    )
    content_fingerprint: Optional[str] = Field(
        default=None, description="SHA-256 fingerprint of article text/description"
    )
    cluster_id: Optional[str] = Field(
        default=None, description="Associated story cluster ID if assigned"
    )
    processing_status: str = Field(
        default="PENDING",
        description="Status: PENDING, CLASSIFIED_RELEVANT, CLASSIFIED_IRRELEVANT, REJECTED_PREFILTER, FAILED",
    )
    relevance_score: Optional[float] = Field(
        default=None, description="LLM relevance classification score"
    )
    topic: Optional[str] = Field(default=None, description="Classified topic category")
    domain: str = Field(default="AI", description="Information domain")
    extra_metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary JSON metadata"
    )


class StoryClusterRecord(BaseModel):
    """Database record representation of a persisted story cluster."""

    id: str = Field(..., description="Unique story cluster identifier (e.g. cluster_<hash>)")
    representative_article_id: str = Field(
        ..., description="Foreign key ID of the canonical representative article"
    )
    first_seen_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when cluster was first created"
    )
    last_seen_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when cluster was last updated"
    )
    last_processed_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when cluster was evaluated or reviewed"
    )
    story_fingerprint: Optional[str] = Field(
        default=None, description="Fingerprint representing cluster's key entities and products"
    )
    lifecycle_status: str = Field(
        default="ACTIVE", description="Lifecycle: ACTIVE, UPDATED, ARCHIVED"
    )
    source_count: int = Field(default=1, description="Number of distinct sources covering cluster")
    sources: List[str] = Field(default_factory=list, description="List of source names covering cluster")
    topic: Optional[str] = Field(default=None, description="Dominant topic category")
    domain: str = Field(default="AI", description="Information domain")
    extra_metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary JSON metadata"
    )


class ClusterMemberRecord(BaseModel):
    """Relationship record linking an article to a story cluster."""

    cluster_id: str = Field(..., description="Foreign key to story_clusters")
    article_id: str = Field(..., description="Foreign key to articles")
    is_representative: bool = Field(default=False, description="Whether article is cluster representative")
    added_at: datetime = Field(
        default_factory=datetime.utcnow, description="Timestamp when member was associated"
    )
    is_meaningful_update: bool = Field(
        default=False, description="Whether article introduced meaningful new updates to story"
    )
    update_reason: Optional[str] = Field(
        default=None, description="Explanation of update classification"
    )


class StorageMetrics(BaseModel):
    """Operational telemetry for database persistence and deduplication."""

    articles_checked: int = 0
    new_articles_persisted: int = 0
    exact_duplicates_skipped: int = 0
    previously_seen_recognized: int = 0
    failed_articles_retried: int = 0
    historical_story_matches: int = 0
    new_clusters_persisted: int = 0
    clusters_updated: int = 0
    meaningful_updates_detected: int = 0
    storage_failures: int = 0


class PipelineRunRecord(BaseModel):
    """Database record tracking the lifecycle and telemetry of an automated or manual pipeline execution."""

    id: str = Field(..., description="Unique run identifier (e.g. run_20261009_060000_abc123)")
    trigger_type: str = Field(default="SCHEDULED", description="Trigger type: SCHEDULED or MANUAL")
    started_at: datetime = Field(default_factory=datetime.utcnow, description="Timestamp when run began")
    completed_at: Optional[datetime] = Field(default=None, description="Timestamp when run completed")
    duration_seconds: Optional[float] = Field(default=None, description="Total execution duration in seconds")
    status: str = Field(
        default="RUNNING",
        description="Run status: RUNNING, SUCCESS, PARTIAL_SUCCESS, FAILED",
    )
    articles_discovered: int = Field(default=0, description="Total articles discovered across all feeds")
    articles_deduplicated: int = Field(default=0, description="Unique articles remaining after URL dedup")
    articles_prefiltered: int = Field(default=0, description="Candidates retained after pre-filter")
    clusters_formed: int = Field(default=0, description="Total story clusters formed")
    qwen_evaluations: int = Field(default=0, description="Number of LLM evaluations performed")
    articles_stored: int = Field(default=0, description="Total articles persisted/registered in database")
    domain_counts: Dict[str, int] = Field(default_factory=dict, description="Article count per domain")
    feed_errors: List[str] = Field(default_factory=list, description="List of feed ingestion failures")
    error_message: Optional[str] = Field(default=None, description="Fatal or critical error message if failed")
    run_metadata: Dict[str, Any] = Field(default_factory=dict, description="Detailed run telemetry metadata")

