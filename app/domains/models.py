"""Domain definitions, feed configurations, and taxonomy models for Multi-Domain Discovery (Phase 6)."""

from typing import List, Optional
from pydantic import BaseModel, Field


class FeedConfig(BaseModel):
    """Configuration for an individual RSS/Atom feed source."""

    url: str = Field(..., description="Feed URL")
    source_name: Optional[str] = Field(
        default=None, description="Human-friendly source publication name"
    )
    enabled: bool = Field(default=True, description="Whether this feed is active")


class DomainConfig(BaseModel):
    """Configuration and classification parameters for an information domain."""

    domain_id: str = Field(..., description="Unique slug identifier (e.g. 'ai', 'cybersecurity')")
    display_name: str = Field(..., description="Canonical display name (e.g. 'Artificial Intelligence')")
    description: str = Field(default="", description="Domain scope description")
    enabled: bool = Field(default=True, description="Whether this domain is enabled")
    feeds: List[FeedConfig] = Field(default_factory=list, description="Configured RSS/Atom feeds")
    allowed_topics: List[str] = Field(
        default_factory=list, description="Controlled subtopic taxonomy for classification"
    )
    pre_filter_threshold: float = Field(
        default=0.20, description="Minimum pre-filter score to send candidate to LLM"
    )
    strong_signals: List[str] = Field(
        default_factory=list, description="Domain-specific strong keyword patterns"
    )
    standalone_signals: List[str] = Field(
        default_factory=list, description="Domain-specific standalone keyword patterns"
    )
    prompt_template: Optional[str] = Field(
        default=None, description="Compact Qwen relevance classification prompt template"
    )
