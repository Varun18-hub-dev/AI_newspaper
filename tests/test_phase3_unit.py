"""Unit tests for Phase 3: Webpage Fetcher, Content Extractor, Text Cleaner, and Deterministic Pre-filter."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from app.ingestion.models import Article
from app.extraction.cleaner import clean_article_text, truncate_for_classification
from app.extraction.extractor import ContentExtractor
from app.extraction.fetcher import WebPageFetcher
from app.extraction.models import ExtractedContent
from app.processing.models import AIRelevanceClassification, ProcessedArticle, PipelineMetrics
from app.processing.pre_filter import DeterministicPreFilter, PreFilterResult
from app.processing.article_processor import ArticleProcessor
from app.llm.base import LLMProvider


# =====================================================================
# 1. Cleaner Unit Tests
# =====================================================================
def test_cleaner_unicode_and_whitespace():
    """Verify clean_article_text normalizes unicode ligatures, carriage returns, and spaces."""
    raw = "Here is an article with  multiple   spaces.\r\n\r\nSecond paragraph with “curly quotes”."
    cleaned = clean_article_text(raw)
    assert "multiple spaces." in cleaned
    assert "“curly quotes”" in cleaned or '"curly quotes"' in cleaned
    assert "\r" not in cleaned
    assert "\n\n" in cleaned


def test_cleaner_boilerplate_removal():
    """Verify boilerplate lines like newsletters and socials are removed."""
    raw = (
        "Groundbreaking new model achieves state-of-the-art results.\n\n"
        "Sign up for our daily newsletter to stay updated!\n"
        "Follow us on Twitter for more news.\n"
        "All rights reserved."
    )
    cleaned = clean_article_text(raw)
    assert "Groundbreaking new model" in cleaned
    assert "newsletter" not in cleaned.lower()
    assert "follow us on twitter" not in cleaned.lower()


def test_cleaner_truncate_for_classification():
    """Verify truncate_for_classification truncates at sentence boundary cleanly."""
    text = (
        "Sentence one is about AI. Sentence two describes neural networks. "
        "Sentence three covers training. Sentence four wraps up."
    )
    # Truncate to length that cuts between sentences
    truncated = truncate_for_classification(text, max_chars=60)
    assert truncated.endswith(".")
    assert "Sentence one is about AI." in truncated
    assert len(truncated) <= 60


# =====================================================================
# 2. Fetcher Unit Tests
# =====================================================================
@patch.object(requests.Session, "get")
def test_fetcher_success(mock_get):
    """Verify successful HTML fetch returns text without errors."""
    mock_resp = MagicMock()
    mock_resp.text = "<html><body><article><p>Hello world</p></article></body></html>"
    mock_resp.headers = {"Content-Type": "text/html; charset=utf-8"}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    fetcher = WebPageFetcher()
    html, err = fetcher.fetch_html("https://example.com/article")
    assert html is not None
    assert "Hello world" in html
    assert err is None


@patch.object(requests.Session, "get")
def test_fetcher_timeout(mock_get):
    """Verify timeout is caught and returns descriptive error."""
    mock_get.side_effect = requests.exceptions.Timeout("Timed out")
    fetcher = WebPageFetcher()
    html, err = fetcher.fetch_html("https://example.com/slow")
    assert html is None
    assert "timed out" in err.lower()


@patch.object(requests.Session, "get")
def test_fetcher_http_failure(mock_get):
    """Verify HTTP 404/500 errors are caught gracefully."""
    mock_get.side_effect = requests.exceptions.HTTPError("404 Not Found")
    fetcher = WebPageFetcher()
    html, err = fetcher.fetch_html("https://example.com/404")
    assert html is None
    assert "http status error" in err.lower()


@patch.object(requests.Session, "get")
def test_fetcher_connection_failure(mock_get):
    """Verify connection failure returns error message without crashing."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Connection refused")
    fetcher = WebPageFetcher()
    html, err = fetcher.fetch_html("https://example.com/down")
    assert html is None
    assert "connection failed" in err.lower()


# =====================================================================
# 3. Extractor Unit Tests
# =====================================================================
def test_extractor_article_tag():
    """Verify extractor extracts prose from <article> container."""
    html = """
    <html>
      <head><title>Sample Article Page</title></head>
      <body>
        <nav><a href="/">Home</a></nav>
        <article>
          <h1>Deep Learning Advances</h1>
          <p>Researchers have released an efficient new transformer architecture.</p>
          <p>It achieves comparable perplexity with half the memory footprint.</p>
        </article>
        <footer>Copyright 2026</footer>
      </body>
    </html>
    """
    extractor = ContentExtractor()
    result = extractor.extract_from_html(html, "https://example.com/art")
    assert result.extraction_success is True
    assert result.extraction_method == "article_tag"
    assert "transformer architecture" in result.text
    assert "Home" not in result.text
    assert result.word_count > 10


def test_extractor_paragraphs_fallback():
    """Verify extractor falls back to paragraphs when no semantic container exists."""
    html = """
    <html>
      <body>
        <div>
          <p>This is a significant artificial intelligence breakthrough announced today.</p>
          <p>The reasoning model demonstrates superior coding benchmarks on complex tasks.</p>
        </div>
      </body>
    </html>
    """
    extractor = ContentExtractor()
    result = extractor.extract_from_html(html, "https://example.com/art")
    assert result.extraction_success is True
    assert "reasoning model" in result.text


def test_extractor_fallback_on_sparse_html():
    """Verify extractor uses RSS fallback description when webpage HTML is sparse."""
    sparse_html = "<html><body><div>Login to read</div></body></html>"
    extractor = ContentExtractor()
    result = extractor.extract_from_html(
        sparse_html,
        "https://example.com/art",
        fallback_text="OpenAI releases reasoning model with improved coding capabilities.",
    )
    assert result.extraction_success is True
    assert result.extraction_method == "rss_fallback"
    assert "improved coding capabilities" in result.text


# =====================================================================
# 4. Deterministic Pre-Filter Unit Tests
# =====================================================================
def test_pre_filter_clearly_ai_article():
    """Verify clearly AI article passes pre-filter with strong score."""
    art = Article(
        title="Open-Source Reasoning Model Released by Researchers",
        url="https://news.ai/item-1",
        source="AI Daily",
        description="A new foundation model trained on synthetic data for reasoning tasks.",
    )
    content = ExtractedContent(
        url=art.url,
        text="The team introduced an open-source reasoning model leveraging fine-tuning on LLMs.",
        word_count=50,
        extraction_success=True,
    )
    pre_filter = DeterministicPreFilter(threshold=0.20)
    result = pre_filter.evaluate(art, content)

    assert result.should_send_to_llm is True
    assert result.pre_filter_score >= 0.50
    assert any("reasoning" in s or "model" in s or "llm" in s for s in result.signals)


def test_pre_filter_clearly_irrelevant_article():
    """Verify promotional noise / non-AI article is rejected."""
    art = Article(
        title="5 days to TechCrunch Disrupt 2026: Don't pay more at the door for your pass",
        url="https://techcrunch.com/disrupt-tickets",
        source="TechCrunch",
        description="Buy your ticket now before the discount ends and prices increase.",
    )
    content = ExtractedContent(
        url=art.url,
        text="Register today for tickets to the annual conference. Networking and exhibitions.",
        word_count=50,
        extraction_success=True,
    )
    pre_filter = DeterministicPreFilter(threshold=0.20)
    result = pre_filter.evaluate(art, content)

    assert result.should_send_to_llm is False
    assert result.pre_filter_score < 0.20


def test_pre_filter_conservative_ambiguous_article():
    """Verify ambiguous article with subtle AI signals passes to Qwen (conservative false negative avoidance)."""
    art = Article(
        title="Autonomous Warehouse Logistics Robot Fleet Expands",
        url="https://logistics.com/fleet",
        source="LogisticsNews",
        description="New sensor systems and path-planning algorithms installed.",
    )
    pre_filter = DeterministicPreFilter(threshold=0.20)
    result = pre_filter.evaluate(art, None)

    # Has "robot", "autonomous" -> passes threshold to let Qwen decide
    assert result.should_send_to_llm is True
    assert result.pre_filter_score >= 0.20


# =====================================================================
# 5. End-to-End Processing & Telemetry Unit Tests (Mocked LLM)
# =====================================================================
class MockFastLLM(LLMProvider):
    def generate(self, prompt: str, **kwargs) -> str:
        return (
            '{\n  "is_relevant": true,\n  "relevance_score": 0.95,\n'
            '  "topic": "Reasoning Models",\n  "reason": "Discusses AI reasoning model."\n}'
        )


def test_processor_with_metrics_pipeline():
    """Verify complete Phase 3 pipeline execution and metric calculation."""
    mock_llm = MockFastLLM()
    processor = ArticleProcessor(llm_provider=mock_llm)

    articles = [
        Article(
            title="OpenAI announces new LLM",
            url="https://ex.com/ai-1",
            source="Ex",
            description="Discussing LLM capabilities.",
        ),
        Article(
            title="Hotel booking discounts for conference",
            url="https://ex.com/hotel-promo",
            source="Ex",
            description="Book your room today.",
        ),
    ]

    results, metrics = processor.process_with_metrics(
        articles=articles,
        enable_extraction=False,
        enable_pre_filter=True,
    )

    assert isinstance(metrics, PipelineMetrics)
    assert metrics.total_rss_articles == 2
    assert metrics.valid_articles == 2
    assert metrics.rejected_pre_filter == 1  # Hotel promo rejected!
    assert metrics.candidates_passed_to_llm == 1  # Only AI article passed!
    assert metrics.qwen_calls == 1
    assert metrics.qwen_calls_saved == 1
    assert metrics.reduction_percentage == 50.0
    assert len(results) == 1
    assert results[0].article.title == "OpenAI announces new LLM"
    assert results[0].classification.is_relevant is True
