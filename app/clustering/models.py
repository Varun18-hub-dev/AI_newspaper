"""Data models for semantic story deduplication and clustering (Phase 4)."""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field

from app.ingestion.models import Article


class StoryCluster(BaseModel):
    """Represents a deduplicated story grouping one or more articles covering the same real-world event."""

    cluster_id: str = Field(..., description="Deterministic unique identifier for the story cluster")
    representative_article: Article = Field(
        ..., description="The chosen canonical article representing this story cluster"
    )
    member_articles: List[Article] = Field(
        default_factory=list,
        description="All articles covering this event belonging to the cluster",
    )
    source_count: int = Field(
        default=1, description="Number of unique sources covering this story cluster"
    )
    sources: List[str] = Field(
        default_factory=list, description="Unique source names covering this story cluster"
    )
    similarity_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Internal pairwise similarity score (or 1.0 for singletons)",
    )
    time_span_hours: float = Field(
        default=0.0,
        ge=0.0,
        description="Time difference in hours between earliest and latest published member",
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the cluster was formed",
    )


class ClusteringMetrics(BaseModel):
    """Execution metrics and reduction statistics for story clustering."""

    total_input_articles: int = Field(
        default=0, description="Total articles submitted for clustering"
    )
    total_clusters: int = Field(
        default=0, description="Total story clusters formed"
    )
    multi_source_clusters: int = Field(
        default=0, description="Story clusters covered by 2 or more distinct sources"
    )
    single_article_clusters: int = Field(
        default=0, description="Clusters with only one article"
    )
    deduplication_ratio: float = Field(
        default=0.0,
        description="Percentage of redundant candidate articles consolidated into clusters",
    )
    clustering_runtime_seconds: float = Field(
        default=0.0, description="Execution time of the clustering step in seconds"
    )
