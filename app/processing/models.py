"""Data models for article processing, relevance classification, ranking, and telemetry metrics."""

from datetime import datetime
from typing import Literal, Optional, Tuple
from pydantic import BaseModel, Field, field_validator

from app.ingestion.models import Article
from app.extraction.models import ExtractedContent
from app.processing.pre_filter import PreFilterResult

ALLOWED_TOPICS: Tuple[str, ...] = (
    "AI Agents",
    "LLMs",
    "Large Language Models",
    "Generative AI",
    "AI Safety",
    "Machine Learning",
    "Computer Vision",
    "NLP",
    "Robotics",
    "AI Infrastructure",
    "AI Hardware",
    "AI Research",
    "AI Startups",
    "Other",
)


def normalize_topic_taxonomy(raw_topic: str) -> str:
    """Maps a raw topic string into one of the controlled ALLOWED_TOPICS."""
    if not raw_topic or not raw_topic.strip():
        return "Other"

    cleaned = raw_topic.strip()
    # Direct match (case-insensitive)
    for allowed in ALLOWED_TOPICS:
        if cleaned.lower() == allowed.lower():
            return allowed

    # Heuristic mapping for common variants
    low = cleaned.lower()
    if "agent" in low:
        return "AI Agents"
    elif "llm" in low or "large language model" in low:
        return "LLMs"
    elif "generative" in low or "genai" in low or "diffusion" in low:
        return "Generative AI"
    elif "safety" in low or "alignment" in low or "ethics" in low or "security" in low:
        return "AI Safety"
    elif "hardware" in low or "chip" in low or "gpu" in low or "semiconductor" in low:
        return "AI Hardware"
    elif "infra" in low or "datacenter" in low or "data center" in low or "cloud" in low:
        return "AI Infrastructure"
    elif "vision" in low or "image" in low or "video" in low:
        return "Computer Vision"
    elif "nlp" in low or "speech" in low or "asr" in low or "audio" in low:
        return "NLP"
    elif "robot" in low or "autonomous" in low:
        return "Robotics"
    elif "startup" in low or "funding" in low or "raises" in low:
        return "AI Startups"
    elif "research" in low or "benchmark" in low or "paper" in low:
        return "AI Research"
    elif "machine learning" in low or "ml" in low:
        return "Machine Learning"

    return "Other"


def normalize_technology_topic(raw_topic: str) -> str:
    """Maps a raw topic string into one of the controlled Technology topics."""
    from app.domains.registry import TECHNOLOGY_TOPICS
    if not raw_topic or not raw_topic.strip():
        return "Other"
    cleaned = raw_topic.strip()
    for allowed in TECHNOLOGY_TOPICS:
        if cleaned.lower() == allowed.lower():
            return allowed
    low = cleaned.lower()
    if "software" in low or "app" in low or "code" in low or "programming" in low:
        return "Software & Apps"
    elif "hardware" in low or "gadget" in low or "device" in low:
        return "Hardware & Devices"
    elif "consumer" in low or "phone" in low or "tv" in low or "audio" in low:
        return "Consumer Tech"
    elif "cloud" in low or "aws" in low or "azure" in low or "server" in low:
        return "Cloud Computing"
    elif "mobile" in low or "android" in low or "ios" in low or "5g" in low:
        return "Mobile & Telecom"
    elif "os" in low or "operating system" in low or "windows" in low or "linux" in low or "macos" in low:
        return "Operating Systems"
    elif "chip" in low or "semiconductor" in low or "processor" in low or "cpu" in low or "gpu" in low:
        return "Semiconductors"
    elif "web" in low or "internet" in low or "browser" in low:
        return "Internet & Web"
    return "Other"


def normalize_science_topic(raw_topic: str) -> str:
    """Maps a raw topic string into one of the controlled Science topics."""
    from app.domains.registry import SCIENCE_TOPICS
    if not raw_topic or not raw_topic.strip():
        return "Other"
    cleaned = raw_topic.strip()
    for allowed in SCIENCE_TOPICS:
        if cleaned.lower() == allowed.lower():
            return allowed
    low = cleaned.lower()
    if "space" in low or "astronomy" in low or "nasa" in low or "telescope" in low or "planet" in low:
        return "Space & Astronomy"
    elif "physics" in low or "quantum" in low or "particle" in low:
        return "Physics"
    elif "bio" in low or "gene" in low or "crispr" in low or "dna" in low:
        return "Biology & Genetics"
    elif "health" in low or "medicine" in low or "clinical" in low or "vaccine" in low:
        return "Medicine & Health"
    elif "climate" in low or "earth" in low or "environment" in low or "ocean" in low:
        return "Climate & Earth"
    elif "material" in low or "superconductor" in low or "nano" in low:
        return "Materials Science"
    elif "brain" in low or "neuro" in low:
        return "Neuroscience"
    return "Other"


def normalize_cybersecurity_topic(raw_topic: str) -> str:
    """Maps a raw topic string into one of the controlled Cybersecurity topics."""
    from app.domains.registry import CYBERSECURITY_TOPICS
    if not raw_topic or not raw_topic.strip():
        return "Other"
    cleaned = raw_topic.strip()
    for allowed in CYBERSECURITY_TOPICS:
        if cleaned.lower() == allowed.lower():
            return allowed
    low = cleaned.lower()
    if "cve" in low or "vulnerabilit" in low or "flaw" in low or "zero-day" in low or "0-day" in low:
        return "Vulnerabilities & CVEs"
    elif "breach" in low or "leak" in low or "dump" in low:
        return "Data Breaches"
    elif "malware" in low or "ransomware" in low or "trojan" in low or "infostealer" in low or "spyware" in low:
        return "Malware & Ransomware"
    elif "apt" in low or "threat actor" in low or "hacker" in low or "group" in low:
        return "Threat Actors & APTs"
    elif "appsec" in low or "application" in low or "web security" in low:
        return "Application Security"
    elif "network" in low or "cloud security" in low or "firewall" in low or "ddos" in low:
        return "Network & Cloud Security"
    elif "policy" in low or "compliance" in low or "regulation" in low or "cisa" in low:
        return "Security Policy & Compliance"
    return "Other"


def normalize_business_topic(raw_topic: str) -> str:
    """Maps a raw topic string into one of the controlled Business topics."""
    from app.domains.registry import BUSINESS_TOPICS
    if not raw_topic or not raw_topic.strip():
        return "Other"
    cleaned = raw_topic.strip()
    for allowed in BUSINESS_TOPICS:
        if cleaned.lower() == allowed.lower():
            return allowed
    low = cleaned.lower()
    if "venture" in low or "funding" in low or "seed" in low or "series" in low or "round" in low:
        return "Venture Capital & Funding"
    elif "startup" in low or "founder" in low or "launch" in low:
        return "Startups"
    elif "m&a" in low or "acquisition" in low or "acquired" in low or "merger" in low or "ipo" in low:
        return "M&A and IPOs"
    elif "big tech" in low or "giant" in low or "apple" in low or "google" in low or "meta" in low or "amazon" in low or "microsoft" in low:
        return "Tech Giants & Big Tech"
    elif "antitrust" in low or "regulation" in low or "sec" in low or "lawsuit" in low:
        return "Regulation & Antitrust"
    elif "leader" in low or "ceo" in low or "executive" in low or "c-suite" in low:
        return "Leadership & Executive"
    elif "market" in low or "economy" in low or "stock" in low or "earnings" in low or "revenue" in low:
        return "Markets & Economy"
    return "Other"


def normalize_topic_for_domain(domain: str, raw_topic: str) -> str:
    """Dispatches topic normalization to the appropriate domain taxonomy with cross-domain fallback."""
    if not raw_topic or not raw_topic.strip():
        return "Other"

    dom = (domain or "ai").strip().lower()
    normalizers = {
        "ai": normalize_topic_taxonomy,
        "technology": normalize_technology_topic,
        "science": normalize_science_topic,
        "cybersecurity": normalize_cybersecurity_topic,
        "business": normalize_business_topic,
    }

    # Canonicalize primary domain
    primary_key = "ai"
    if dom in ("technology", "tech"):
        primary_key = "technology"
    elif dom in ("science",):
        primary_key = "science"
    elif dom in ("cybersecurity", "security", "infosec"):
        primary_key = "cybersecurity"
    elif dom in ("business", "startups", "business and startups"):
        primary_key = "business"

    # Try primary domain first
    primary_res = normalizers[primary_key](raw_topic)
    if primary_res != "Other":
        return primary_res

    # Fallback: check if the topic matches any other domain taxonomy
    for key, fn in normalizers.items():
        if key != primary_key:
            res = fn(raw_topic)
            if res != "Other":
                return res

    return "Other"


class RelevanceClassification(BaseModel):
    """Structured relevance classification produced by LLM across news domains."""

    is_relevant: bool = Field(
        ...,
        description="Whether the article is genuinely relevant to its target domain",
    )
    relevance_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence or relevance score between 0.0 and 1.0",
    )
    topic: str = Field(
        ...,
        description="Controlled subtopic from the domain taxonomy",
    )
    reason: str = Field(
        ...,
        max_length=1000,
        description="Brief concise rationale explaining the classification decision",
    )
    domain: str = Field(
        default="AI",
        description="Information domain category",
    )

    @field_validator("topic", mode="before")
    @classmethod
    def validate_and_normalize_topic(cls, v: str, info) -> str:
        """Validates and strictly maps topic to the domain taxonomy."""
        domain_val = "AI"
        if info.data and "domain" in info.data:
            domain_val = info.data["domain"]
        return normalize_topic_for_domain(domain_val, str(v))


class AIRelevanceClassification(RelevanceClassification):
    """Backward-compatible model for AI domain relevance classification."""
    pass


class ProcessedArticle(BaseModel):
    """Article paired with its content extraction, pre-filter, ranking, and LLM classification."""

    article: Article
    classification: RelevanceClassification
    extracted_content: Optional[ExtractedContent] = Field(
        default=None,
        description="Extracted and cleaned webpage prose",
    )
    pre_filter: Optional[PreFilterResult] = Field(
        default=None,
        description="Cheap deterministic relevance scoring result",
    )
    ranking_score: float = Field(
        default=0.0,
        description="Multi-factor deterministic candidate ranking score",
    )
    cluster_id: Optional[str] = Field(
        default=None,
        description="Assigned story cluster identifier if clustered",
    )
    cluster_source_count: int = Field(
        default=1,
        description="Number of distinct sources covering this story cluster",
    )
    cluster_sources: list[str] = Field(
        default_factory=list,
        description="List of distinct sources covering this story cluster",
    )
    processed_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when processing and classification occurred",
    )


class PipelineMetrics(BaseModel):
    """Detailed telemetry and performance counters for the discovery pipeline."""

    total_rss_articles: int = 0
    valid_articles: int = 0
    extraction_success: int = 0
    extraction_failed: int = 0
    rejected_pre_filter: int = 0
    candidates_passed_to_llm: int = 0
    total_clusters: int = 0
    multi_source_clusters: int = 0
    clustering_saved_calls: int = 0
    clustering_runtime_seconds: float = 0.0
    qwen_calls: int = 0
    qwen_relevant: int = 0
    qwen_irrelevant: int = 0
    qwen_calls_saved: int = 0
    reduction_percentage: float = 0.0
    total_runtime_seconds: float = 0.0
    qwen_runtime_seconds: float = 0.0
    average_qwen_seconds: float = 0.0

    # Phase 5 Persistent Storage & Cross-Day Deduplication Telemetry
    articles_collected: int = 0
    new_articles_persisted: int = 0
    exact_duplicates_skipped: int = 0
    previously_seen_articles_recognized: int = 0
    historical_story_matches: int = 0
    new_story_clusters_created: int = 0
    meaningful_story_updates_detected: int = 0
    qwen_evaluations_avoided: int = 0
    storage_failures: int = 0

    # Phase 6 Multi-Domain Telemetry
    domain_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Count of articles collected per domain",
    )
