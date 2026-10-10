"""Data models for content ingestion."""

from datetime import datetime
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field, field_validator


class Article(BaseModel):
    """Normalized article model representing an item ingested from an external source."""

    title: str = Field(..., description="Headline or title of the article")
    url: str = Field(..., description="Canonical or source URL of the article")
    source: str = Field(..., description="Name or identifier of the publishing source")
    author: Optional[str] = Field(default=None, description="Author or contributor name if available")
    published_at: Optional[datetime] = Field(default=None, description="Original publication timestamp")
    description: Optional[str] = Field(default=None, description="Summary or excerpt from the feed")
    content: Optional[str] = Field(default=None, description="Full or partial text content if provided")
    discovered_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the article was fetched by the pipeline",
    )
    domain: str = Field(default="AI", description="Information domain category")
    image_url: Optional[str] = Field(default=None, description="Featured or top image URL if available")
    all_sources: list[str] = Field(
        default_factory=list,
        description="All publishing sources associated with this article across feeds",
    )
    raw_metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Source-specific raw metadata (e.g. CVE metrics, HN score, GitHub stars, arXiv paper ID)",
    )


    @field_validator("title", "url", "source", mode="before")
    @classmethod
    def validate_non_empty_strings(cls, v: str, info) -> str:
        """Ensures core string fields are not empty or whitespace-only."""
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"Field '{info.field_name}' must be a non-empty string.")
        return v.strip()

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validates domain is set and normalized."""
        if not v or not v.strip():
            return "AI"
        v_clean = v.strip()
        low = v_clean.lower()
        if low in ("ai", "artificial intelligence"):
            return "AI"
        elif low in ("technology", "tech"):
            return "Technology"
        elif low in ("science",):
            return "Science"
        elif low in ("cybersecurity", "security", "infosec"):
            return "Cybersecurity"
        elif low in ("business", "startups", "business and startups", "business & startups"):
            return "Business and startups"
        return v_clean
