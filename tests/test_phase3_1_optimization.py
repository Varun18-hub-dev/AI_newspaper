"""Unit tests for Phase 3.1: Ranking, Taxonomy, Latency Optimization, and Recall."""

from datetime import datetime
import pytest

from app.ingestion.models import Article
from app.extraction.models import ExtractedContent
from app.processing.models import (
    ALLOWED_TOPICS,
    AIRelevanceClassification,
    ProcessedArticle,
    normalize_topic_taxonomy,
)
from app.processing.pre_filter import DeterministicPreFilter, PreFilterResult
from app.processing.article_processor import ArticleProcessor
from app.llm.base import LLMProvider


# =====================================================================
# 1. Topic Taxonomy and Normalization Tests
# =====================================================================
def test_topic_taxonomy_normalization():
    """Verify raw LLM topic strings are mapped into controlled ALLOWED_TOPICS."""
    assert normalize_topic_taxonomy("AI Agents") == "AI Agents"
    assert normalize_topic_taxonomy("autonomous agents") == "AI Agents"
    assert normalize_topic_taxonomy("Large Language Models") in ("LLMs", "Large Language Models")
    assert normalize_topic_taxonomy("LLM") in ("LLMs", "Large Language Models")
    assert normalize_topic_taxonomy("generative ai models") == "Generative AI"
    assert normalize_topic_taxonomy("AI Alignment and Safety") == "AI Safety"
    assert normalize_topic_taxonomy("Nvidia GPUs and AI Chips") == "AI Hardware"
    assert normalize_topic_taxonomy("Datacenter compute") == "AI Infrastructure"
    assert normalize_topic_taxonomy("Robotics") == "Robotics"
    assert normalize_topic_taxonomy("Unknown random domain") == "Other"


def test_ai_relevance_classification_topic_validation():
    """Verify Pydantic model automatically normalizes topic to allowed taxonomy."""
    result = AIRelevanceClassification(
        is_relevant=True,
        relevance_score=0.92,
        topic="Large Language Models",  # Variant string
        reason="The article discusses new LLM release.",
    )
    assert result.topic in ALLOWED_TOPICS
    assert result.topic in ("LLMs", "Large Language Models")


# =====================================================================
# 2. Candidate Ranking Tests
# =====================================================================
def test_pre_filter_ranking_order():
    """Verify rank_candidates correctly sorts candidates by Tier, ranking score, and relevance."""
    pre_filter = DeterministicPreFilter()

    art_high = Article(
        title="OpenAI announces new LLM foundation model",
        url="https://huggingface.co/blog/new-model",
        source="Hugging Face",
    )
    res_high = pre_filter.evaluate(art_high, None)

    art_med = Article(
        title="Autonomous forklift tested in logistics center",
        url="https://techcrunch.com/logistics",
        source="TechCrunch",
    )
    res_med = pre_filter.evaluate(art_med, None)

    art_low = Article(
        title="Hotel discount rates for annual developer summit",
        url="https://arstechnica.com/hotel",
        source="Ars Technica",
    )
    res_low = pre_filter.evaluate(art_low, None)

    assert res_high.tier == "HIGH"
    assert res_med.tier in ("HIGH", "MEDIUM")
    assert res_low.tier == "LOW"

    ranked = pre_filter.rank_candidates([(art_med, res_med), (art_high, res_high)])
    # art_high should be ranked first
    assert ranked[0][0].title == art_high.title


# =====================================================================
# 3. Compact Prompt & Latency Optimization Tests
# =====================================================================
def test_compact_prompt_bounds():
    """Verify build_prompt creates a bounded prompt containing taxonomy and concise excerpt."""
    processor = ArticleProcessor()
    art = Article(
        title="Scaling Laws for Frontier Models",
        url="https://news.ai/item",
        source="AI Research",
        description="Detailed empirical exploration of scaling exponents.",
    )
    content = ExtractedContent(
        url=art.url,
        text="A" * 5000,  # 5,000 characters of raw body text
        word_count=800,
        extraction_success=True,
    )

    prompt = processor.build_prompt(art, content)
    # Ensure taxonomy is included
    assert "Allowed topics" in prompt
    assert "LLMs" in prompt
    assert "AI Agents" in prompt
    # Ensure prompt length is bounded (< 1,200 chars) instead of bloating with 5,000 chars
    assert len(prompt) < 1200


# =====================================================================
# 4. Top-K Candidate Selection Pipeline Test
# =====================================================================
class CountingMockLLM(LLMProvider):
    def __init__(self):
        self.call_count = 0

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        return (
            '{\n  "is_relevant": true,\n  "relevance_score": 0.95,\n'
            '  "topic": "AI Agents",\n  "reason": "Discusses AI agent systems."\n}'
        )


def test_top_k_selection_limits_qwen_calls():
    """Verify process_with_metrics strictly limits Qwen calls to max_candidates."""
    mock_llm = CountingMockLLM()
    processor = ArticleProcessor(llm_provider=mock_llm)

    articles = [
        Article(title=f"AI Agent System {i}", url=f"https://huggingface.co/blog/{i}", source="Hugging Face")
        for i in range(15)
    ]

    results, metrics = processor.process_with_metrics(
        articles=articles,
        max_candidates=5,  # Top-5 only
        enable_extraction=False,
        enable_pre_filter=True,
        enable_clustering=False,
    )

    assert len(results) == 5
    assert metrics.qwen_calls == 5
    assert mock_llm.call_count == 5
    assert metrics.candidates_passed_to_llm == 15
