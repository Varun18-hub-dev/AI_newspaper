"""Data models for article content extraction."""

from typing import Optional
from pydantic import BaseModel, Field


class ExtractedContent(BaseModel):
    """Normalized content extracted from an article webpage or fallback source."""

    url: str = Field(..., description="Target webpage URL")
    title: Optional[str] = Field(default=None, description="Extracted HTML document title")
    text: str = Field(default="", description="Cleaned prose of the main article body")
    word_count: int = Field(default=0, description="Word count of extracted prose")
    extraction_method: str = Field(
        default="none",
        description="Method used for extraction (e.g., 'article_tag', 'main_tag', 'paragraphs', 'rss_fallback')",
    )
    extraction_success: bool = Field(
        default=True,
        description="Whether content was successfully extracted",
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if extraction failed",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Featured image or og:image URL if available",
    )
