"""Storage and persistence package for Phase 5."""

from app.storage.fingerprint import (
    compute_content_fingerprint,
    compute_story_fingerprint,
    generate_article_id,
    generate_cluster_id,
    is_meaningful_update,
)
from app.storage.models import (
    ArticleRecord,
    ClusterMemberRecord,
    PipelineRunRecord,
    StorageMetrics,
    StoryClusterRecord,
)
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase

__all__ = [
    "SQLiteDatabase",
    "StorageService",
    "ArticleRecord",
    "StoryClusterRecord",
    "ClusterMemberRecord",
    "PipelineRunRecord",
    "StorageMetrics",
    "generate_article_id",
    "generate_cluster_id",
    "compute_content_fingerprint",
    "compute_story_fingerprint",
    "is_meaningful_update",
]
