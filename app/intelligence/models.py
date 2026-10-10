"""Pydantic and TypedDict models for the Phase 8.1 Agentic Intelligence Layer."""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, TypedDict
from pydantic import BaseModel, Field

from app.ingestion.models import Article
from app.extraction.models import ExtractedContent
from app.processing.models import PreFilterResult, ProcessedArticle
from app.clustering.models import StoryCluster


class ClaimItem(BaseModel):
    """An individual factual claim extracted from candidate story text."""

    claim_text: str = Field(..., description="The factual proposition asserted by the article.")
    source_name: str = Field(..., description="Publication that asserted the claim.")
    source_url: str = Field(..., description="URL of the source asserting the claim.")
    is_corroborated: bool = Field(
        default=False,
        description="Whether this claim is corroborated by more than one independent source."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score that the claim is directly supported by the article text."
    )


class SpecialistAnalysisResult(BaseModel):
    """Structured output returned by a domain specialist agent."""

    cluster_id: str
    domain: str
    topic: str
    is_relevant: bool = True
    relevance_score: float = Field(default=0.85, ge=0.0, le=1.0)
    main_development: str = Field(
        ...,
        description="Core news event or technological development in 1-2 sentences."
    )
    key_claims: List[str] = Field(
        default_factory=list,
        description="List of specific claims extracted from the article."
    )
    evidence_level: Literal["STRONG", "MODERATE", "INSUFFICIENT", "CONFLICTING"] = "STRONG"
    priority_score: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Recommended editorial placement score."
    )
    priority_rationale: str = Field(
        default="",
        description="Concise rationale for why this development matters to readers."
    )
    raw_response: Optional[str] = None
    retry_count: int = 0
    fallback_used: bool = False


class EvidenceValidationResult(BaseModel):
    """Result of evidence, claim, and prompt-injection validation."""

    cluster_id: str
    is_valid: bool = True
    is_prompt_injection_detected: bool = False
    injection_reason: Optional[str] = None
    single_source_only: bool = True
    verified_claims: List[ClaimItem] = Field(default_factory=list)
    unsupported_claims: List[str] = Field(default_factory=list)
    has_conflicting_reports: bool = False
    conflict_notes: Optional[str] = None
    sanitized_summary: Optional[str] = None


class StorySynthesisResult(BaseModel):
    """Final synthesized newspaper story output ready for publication and storage."""

    cluster_id: str
    headline: str
    summary: str
    domain: str
    topic: str
    priority_score: float
    relevance_score: float
    sources: List[str]
    representative_source: str
    representative_url: str
    source_count: int
    key_claims: List[ClaimItem]
    has_updates: bool = False
    update_reason: Optional[str] = None
    evidence_level: str = "STRONG"
    agent_attribution: str


# =============================================================================
# LangGraph State Schema
# =============================================================================
class CandidateStoryInput(BaseModel):
    """Encapsulates a candidate story cluster passing into the intelligence graph."""

    cluster_id: str
    representative_article: Article
    member_articles: List[Article]
    extracted_content: Optional[ExtractedContent] = None
    pre_filter_result: Optional[PreFilterResult] = None
    ranking_score: float = 1.0
    domain: str = "ai"
    sources: List[str] = Field(default_factory=list)


class IntelligenceGraphState(TypedDict, total=False):
    """Explicit typed state coordinated by LangGraph."""

    # Run metadata & telemetry
    run_id: str
    status: str
    started_at: str
    execution_mode: str  # "LANGGRAPH_MULTI_AGENT"

    # Input candidates
    candidate_clusters: List[CandidateStoryInput]

    # Node step mappings
    domain_routes: Dict[str, str]  # cluster_id -> domain
    specialist_results: Dict[str, SpecialistAnalysisResult]  # cluster_id -> analysis
    evidence_results: Dict[str, EvidenceValidationResult]  # cluster_id -> validation
    synthesized_stories: Dict[str, StorySynthesisResult]  # cluster_id -> final story

    # Operational & error telemetry
    retry_counts: Dict[str, int]  # cluster_id -> retries
    errors: List[Dict[str, Any]]
    llm_call_count: int
    qwen_evaluations_avoided: int
    fallback_count: int
    duration_seconds: float
