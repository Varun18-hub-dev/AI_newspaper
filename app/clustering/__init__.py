"""Story clustering and semantic deduplication package (Phase 4)."""

from app.clustering.clusterer import StoryClusterer
from app.clustering.embeddings import (
    EmbeddingProvider,
    TFIDFEmbeddingProvider,
    MiniLMEmbeddingProvider,
    get_embedding_provider,
)
from app.clustering.entity_guard import EntityGuard
from app.clustering.models import ClusteringMetrics, StoryCluster
from app.clustering.representative import (
    RepresentativeSelector,
    compute_article_representative_score,
)

__all__ = [
    "StoryCluster",
    "ClusteringMetrics",
    "StoryClusterer",
    "EmbeddingProvider",
    "TFIDFEmbeddingProvider",
    "MiniLMEmbeddingProvider",
    "get_embedding_provider",
    "EntityGuard",
    "RepresentativeSelector",
    "compute_article_representative_score",
]
