"""Processing package providing filtering, pre-filtering, classification, and pipeline orchestration."""

from app.processing.models import (
    AIRelevanceClassification,
    ProcessedArticle,
    PipelineMetrics,
)
from app.processing.filtering import (
    normalize_url,
    is_valid_article,
    filter_and_deduplicate,
)
from app.processing.pre_filter import (
    DeterministicPreFilter,
    PreFilterResult,
)
from app.processing.article_processor import ArticleProcessor

__all__ = [
    "AIRelevanceClassification",
    "ProcessedArticle",
    "PipelineMetrics",
    "normalize_url",
    "is_valid_article",
    "filter_and_deduplicate",
    "DeterministicPreFilter",
    "PreFilterResult",
    "ArticleProcessor",
]
