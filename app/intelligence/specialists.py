"""Domain-specialized intelligence agents for multi-domain news evaluation."""

import json
import time
from typing import Any, Dict, List, Optional
from pydantic import ValidationError

from app.core.logging import setup_logger
from app.domains.registry import (
    AI_TOPICS,
    TECHNOLOGY_TOPICS,
    SCIENCE_TOPICS,
    CYBERSECURITY_TOPICS,
    BUSINESS_TOPICS,
)
from app.intelligence.evidence import format_untrusted_text
from app.intelligence.models import (
    CandidateStoryInput,
    SpecialistAnalysisResult,
)
from app.llm.base import LLMProvider, LLMError

logger = setup_logger("domain_specialists")


class BaseDomainSpecialist:
    """Base class for domain-specialized intelligence agents."""

    domain_id: str = "general"
    role_name: str = "News Analyst"
    allowed_topics: List[str] = ["General", "Other"]

    def __init__(self, llm_provider: Optional[LLMProvider] = None):
        self.llm_provider = llm_provider

    def build_prompt(self, candidate: CandidateStoryInput) -> str:
        """Constructs a compact, prompt-injection-safe evaluation prompt."""
        art = candidate.representative_article
        raw_text = (
            candidate.extracted_content.text
            if candidate.extracted_content and candidate.extracted_content.text
            else art.description or ""
        )
        safe_content = format_untrusted_text(raw_text, max_words=300)
        topics_str = ", ".join(self.allowed_topics)

        return (
            f"You are a specialized {self.role_name}. Return ONLY valid JSON matching this schema:\n"
            f"{{\n"
            f'  "is_relevant": true,\n'
            f'  "relevance_score": 0.90,\n'
            f'  "topic": "{self.allowed_topics[0]}",\n'
            f'  "main_development": "Factual news summary in 1 sentence under 25 words.",\n'
            f'  "key_claims": ["Factual claim 1", "Factual claim 2"],\n'
            f'  "evidence_level": "STRONG",\n'
            f'  "priority_score": 0.85,\n'
            f'  "priority_rationale": "Short rationale under 15 words."\n'
            f"}}\n\n"
            f"Allowed topics (select EXACTLY one): [{topics_str}].\n"
            f"Article Headline: {art.title}\n"
            f"Source Publication: {art.source}\n"
            f"{safe_content}\n"
        )

    def analyze_cluster(
        self,
        candidate: CandidateStoryInput,
        llm: Optional[LLMProvider] = None,
        max_retries: int = 2,
    ) -> SpecialistAnalysisResult:
        """Executes domain analysis with bounded retries and deterministic fallback."""
        active_llm = llm or self.llm_provider
        if not active_llm:
            return self._build_fallback(candidate, reason="No LLM provider configured")

        prompt = self.build_prompt(candidate)

        for attempt in range(max_retries + 1):
            try:
                # Specialist JSON requires up to 256 tokens to complete safely
                try:
                    raw_response = active_llm.generate(prompt, max_tokens=256)
                except TypeError:
                    raw_response = active_llm.generate(prompt)
                parsed = self._parse_json_response(raw_response)

                # Validate and normalize topic
                topic = parsed.get("topic", self.allowed_topics[0])
                if topic not in self.allowed_topics:
                    topic = self.allowed_topics[-1]  # Default to 'Other'

                return SpecialistAnalysisResult(
                    cluster_id=candidate.cluster_id,
                    domain=self.domain_id,
                    topic=topic,
                    is_relevant=bool(parsed.get("is_relevant", True)),
                    relevance_score=float(parsed.get("relevance_score", 0.85)),
                    main_development=str(parsed.get("main_development", candidate.representative_article.title)),
                    key_claims=list(parsed.get("key_claims", [])),
                    evidence_level=parsed.get("evidence_level", "STRONG"),
                    priority_score=float(parsed.get("priority_score", 0.80)),
                    priority_rationale=str(parsed.get("priority_rationale", "")),
                    raw_response=raw_response,
                    retry_count=attempt,
                    fallback_used=False,
                )
            except (LLMError, json.JSONDecodeError, ValidationError, Exception) as err:
                logger.warning(
                    f"[{self.role_name}] Evaluation attempt {attempt + 1}/{max_retries + 1} failed: {err}"
                )
                if attempt == max_retries:
                    logger.error(
                        f"[{self.role_name}] Exhausted retries for cluster '{candidate.cluster_id}'. Using deterministic fallback."
                    )
                    return self._build_fallback(candidate, reason=str(err), retry_count=attempt)

        return self._build_fallback(candidate, reason="Unknown failure")

    def _parse_json_response(self, text: str) -> Dict[str, Any]:
        """Extracts JSON object from model response, handling Markdown code blocks and truncated tails."""
        cleaned = text.strip()
        if "```json" in cleaned:
            cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in cleaned:
            cleaned = cleaned.split("```", 1)[1].split("```", 1)[0].strip()

        start = cleaned.find("{")
        if start == -1:
            raise json.JSONDecodeError("No opening '{' found", cleaned, 0)

        end = cleaned.rfind("}")
        if end != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                pass

        # Attempt recovery if JSON was cut off near the end
        sub = cleaned[start:].rstrip(", \n\r\t")
        if sub.count('"') % 2 != 0:
            sub += '"'
        if not sub.endswith("}"):
            sub += "}"
        return json.loads(sub)

    def _build_fallback(
        self,
        candidate: CandidateStoryInput,
        reason: str,
        retry_count: int = 0,
    ) -> SpecialistAnalysisResult:
        """Constructs a reliable deterministic fallback when agent inference fails."""
        art = candidate.representative_article
        pf = candidate.pre_filter_result

        # Use pre-filter score or default
        rel_score = pf.pre_filter_score if pf else 0.80
        ranking_score = pf.ranking_score if pf else 0.75
        topic = self.allowed_topics[0] if self.allowed_topics else "General"

        main_dev = art.description or art.title
        if len(main_dev) > 160:
            main_dev = main_dev[:157] + "..."

        return SpecialistAnalysisResult(
            cluster_id=candidate.cluster_id,
            domain=self.domain_id,
            topic=topic,
            is_relevant=True,
            relevance_score=rel_score,
            main_development=main_dev,
            key_claims=[f"Reported by {art.source}"],
            evidence_level="MODERATE",
            priority_score=ranking_score,
            priority_rationale=f"Deterministic fallback applied ({reason})",
            retry_count=retry_count,
            fallback_used=True,
        )


# =============================================================================
# Five Specialized Domain Agent Classes
# =============================================================================
class AIResearcherSpecialist(BaseDomainSpecialist):
    domain_id = "ai"
    role_name = "AI Researcher"
    allowed_topics = AI_TOPICS


class TechnologyResearcherSpecialist(BaseDomainSpecialist):
    domain_id = "technology"
    role_name = "Technology Researcher"
    allowed_topics = TECHNOLOGY_TOPICS


class ScienceResearcherSpecialist(BaseDomainSpecialist):
    domain_id = "science"
    role_name = "Science Researcher"
    allowed_topics = SCIENCE_TOPICS


class CybersecurityResearcherSpecialist(BaseDomainSpecialist):
    domain_id = "cybersecurity"
    role_name = "Cybersecurity Researcher"
    allowed_topics = CYBERSECURITY_TOPICS


class BusinessResearcherSpecialist(BaseDomainSpecialist):
    domain_id = "business"
    role_name = "Business and Startups Researcher"
    allowed_topics = BUSINESS_TOPICS


# =============================================================================
# Specialist Factory
# =============================================================================
_SPECIALIST_REGISTRY = {
    "ai": AIResearcherSpecialist,
    "technology": TechnologyResearcherSpecialist,
    "science": ScienceResearcherSpecialist,
    "cybersecurity": CybersecurityResearcherSpecialist,
    "business": BusinessResearcherSpecialist,
}


def get_domain_specialist(domain_id: str, llm_provider: Optional[LLMProvider] = None) -> BaseDomainSpecialist:
    """Returns the specialized agent for a given domain, with graceful fallback."""
    cleaned = (domain_id or "ai").strip().lower()
    # Handle aliases
    if cleaned in ("tech", "electronics", "software"):
        cleaned = "technology"
    elif cleaned in ("security", "infosec", "cyber"):
        cleaned = "cybersecurity"
    elif cleaned in ("startups", "finance", "business & startups"):
        cleaned = "business"

    specialist_cls = _SPECIALIST_REGISTRY.get(cleaned, AIResearcherSpecialist)
    return specialist_cls(llm_provider=llm_provider)
