"""Unit tests for Phase 2: Ingestion, Article Model, Filtering, and Article Processor."""

from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest
import requests
from pydantic import ValidationError

from app.ingestion.models import Article
from app.ingestion.rss import RSSConnector, _clean_html, _parse_date
from app.llm.base import (
    LLMProvider,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMResponseMalformedError,
)
from app.processing.filtering import (
    normalize_url,
    is_valid_article,
    filter_and_deduplicate,
)
from app.processing.models import AIRelevanceClassification, ProcessedArticle
from app.processing.article_processor import ArticleProcessor


# =====================================================================
# 1. Article Model Tests
# =====================================================================
def test_article_model_valid():
    """Verify Article creation with all required and optional fields."""
    art = Article(
        title="OpenAI announces GPT-5",
        url="https://openai.com/blog/gpt-5",
        source="OpenAI Blog",
        author="OpenAI Team",
        published_at=datetime(2026, 10, 8, 12, 0, 0),
        description="An overview of reasoning advancements.",
        content="Full text here",
        domain="AI",
    )
    assert art.title == "OpenAI announces GPT-5"
    assert art.url == "https://openai.com/blog/gpt-5"
    assert art.source == "OpenAI Blog"
    assert art.author == "OpenAI Team"
    assert art.domain == "AI"
    assert isinstance(art.discovered_at, datetime)


def test_article_model_optional_fields_missing():
    """Verify Article allows omission of optional fields."""
    art = Article(
        title="Minimal Article",
        url="https://example.com/item",
        source="Example",
    )
    assert art.author is None
    assert art.published_at is None
    assert art.description is None
    assert art.content is None
    assert art.domain == "AI"


def test_article_model_empty_required_fields():
    """Verify validation fails when required fields are empty strings."""
    with pytest.raises(ValidationError):
        Article(title="   ", url="https://example.com", source="Source")

    with pytest.raises(ValidationError):
        Article(title="Title", url="   ", source="Source")

    with pytest.raises(ValidationError):
        Article(title="Title", url="https://example.com", source="   ")


# =====================================================================
# 2. RSS Connector Tests
# =====================================================================
SAMPLE_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>AI Tech News</title>
    <link>https://ainews.example.com</link>
    <item>
      <title>Autonomous Agents Milestone</title>
      <link>https://ainews.example.com/agents</link>
      <pubDate>Thu, 08 Oct 2026 12:00:00 GMT</pubDate>
      <author>Jane Doe</author>
      <description>&lt;p&gt;Breakthrough in agentic reasoning.&lt;/p&gt;</description>
    </item>
    <item>
      <title>Missing Link Item</title>
      <description>No link provided</description>
    </item>
    <item>
      <link>https://ainews.example.com/no-title</link>
      <description>No title provided</description>
    </item>
  </channel>
</rss>
"""

SAMPLE_ATOM_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Deep Learning Feed</title>
  <entry>
    <title>Scaling Laws for Transformers</title>
    <link href="https://dlfeed.example.com/scaling" rel="alternate"/>
    <published>2026-10-08T14:30:00Z</published>
    <author><name>Alan Turing</name></author>
    <summary>Empirical study on parameter scaling.</summary>
  </entry>
  <entry>
    <title>Entry Without Link</title>
    <summary>Missing link entry</summary>
  </entry>
</feed>
"""


def test_rss_parsing_success_and_skips_invalid_items():
    """Verify RSS 2.0 parsing extracts valid items and gracefully skips items missing title or link."""
    connector = RSSConnector()
    articles = connector.parse_feed_xml(SAMPLE_RSS_XML)
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Autonomous Agents Milestone"
    assert art.url == "https://ainews.example.com/agents"
    assert art.source == "AI Tech News"
    assert art.author == "Jane Doe"
    assert art.description == "Breakthrough in agentic reasoning."
    assert art.published_at is not None


def test_atom_parsing_success():
    """Verify Atom 1.0 parsing extracts entries correctly."""
    connector = RSSConnector()
    articles = connector.parse_feed_xml(SAMPLE_ATOM_XML)
    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Scaling Laws for Transformers"
    assert art.url == "https://dlfeed.example.com/scaling"
    assert art.source == "Deep Learning Feed"
    assert art.author == "Alan Turing"
    assert art.description == "Empirical study on parameter scaling."
    assert art.published_at is not None


def test_rss_malformed_xml():
    """Verify malformed XML raises ValueError or ParseError."""
    connector = RSSConnector()
    malformed_bytes = b"<rss><channel><title>Broken<item>"
    with pytest.raises(Exception):
        connector.parse_feed_xml(malformed_bytes)


@patch.object(requests.Session, "get")
def test_rss_network_failure(mock_get):
    """Verify network exception is raised on fetch_feed."""
    mock_get.side_effect = requests.exceptions.ConnectionError("Network down")
    connector = RSSConnector()
    with pytest.raises(requests.exceptions.ConnectionError):
        connector.fetch_feed("https://invalid-feed.example.com/rss")


@patch.object(requests.Session, "get")
def test_rss_fetch_all_resilience(mock_get):
    """Verify fetch_all continues even if one feed throws a network error."""
    # First URL fails, second succeeds
    mock_resp = MagicMock()
    mock_resp.content = SAMPLE_RSS_XML
    mock_resp.raise_for_status.return_value = None

    def get_side_effect(url, **kwargs):
        if "bad" in url:
            raise requests.exceptions.ConnectionError("Feed down")
        return mock_resp

    mock_get.side_effect = get_side_effect
    connector = RSSConnector()
    articles, statuses = connector.fetch_all(
        ["https://bad-feed.example.com", "https://good-feed.example.com"]
    )
    assert len(articles) == 1
    assert statuses["https://bad-feed.example.com"]["status"] == "FAILED"
    assert statuses["https://good-feed.example.com"]["status"] == "SUCCESS"


# =====================================================================
# 3. Filtering & URL Normalization Tests
# =====================================================================
def test_normalize_url():
    """Verify URL normalization strips tracking params, trailing slashes, and lowercases domain."""
    raw = "HTTPS://TechCrunch.COM/article-name/?utm_source=twitter&utm_medium=social&utm_campaign=launch#comments"
    norm = normalize_url(raw)
    assert norm == "https://techcrunch.com/article-name"

    # Root trailing slash preserved
    assert normalize_url("https://example.com/") == "https://example.com/"


def test_filtering_removes_duplicates_and_invalids():
    """Verify deduplication removes duplicate URLs and invalid articles."""
    raw_articles = [
        Article(
            title="AI Revolution Begins",
            url="https://news.ai/item-1?utm_source=newsletter",
            source="NewsAI",
        ),
        Article(
            title="AI Revolution Begins Duplicate",
            url="https://news.ai/item-1/",
            source="NewsAI",
        ),
        Article(
            title="Second AI Article",
            url="https://news.ai/item-2",
            source="NewsAI",
        ),
        Article(
            title="Tiny",  # Too short (< 5 chars)
            url="https://news.ai/item-3",
            source="NewsAI",
        ),
    ]

    filtered = filter_and_deduplicate(raw_articles)
    assert len(filtered) == 2
    assert filtered[0].title == "AI Revolution Begins"
    assert filtered[0].url == "https://news.ai/item-1"
    assert filtered[1].title == "Second AI Article"


# =====================================================================
# 4. Article Processor & Qwen Classification Tests (Mocked LLM)
# =====================================================================
class MockLLMProvider(LLMProvider):
    def __init__(self, mode="success"):
        self.mode = mode

    def generate(self, prompt: str, **kwargs) -> str:
        if self.mode == "unavailable":
            raise LLMUnavailableError("Ollama service down")
        elif self.mode == "timeout":
            raise LLMTimeoutError("Inference timed out")
        elif self.mode == "malformed":
            return "This is not JSON at all."
        elif self.mode == "invalid_schema":
            return '{"something_else": 123}'
        return (
            '{\n  "is_relevant": true,\n  "relevance_score": 0.95,\n'
            '  "topic": "Large Language Models",\n  "reason": "Discusses reasoning capabilities."\n}'
        )


def test_processor_valid_classification():
    """Verify processor returns ProcessedArticle when LLM outputs valid JSON."""
    mock_llm = MockLLMProvider(mode="success")
    processor = ArticleProcessor(llm_provider=mock_llm)
    art = Article(
        title="OpenAI releases reasoning model",
        url="https://openai.com/reasoning",
        source="OpenAI",
    )
    result = processor.classify_article(art)
    assert isinstance(result, ProcessedArticle)
    assert result.classification.is_relevant is True
    assert result.classification.relevance_score == 0.95
    assert result.classification.topic == "Large Language Models"


def test_processor_malformed_json_handling():
    """Verify processor raises LLMResponseMalformedError on bad JSON from LLM."""
    mock_llm = MockLLMProvider(mode="malformed")
    processor = ArticleProcessor(llm_provider=mock_llm)
    art = Article(
        title="Sample Article",
        url="https://sample.com/1",
        source="Sample",
    )
    with pytest.raises(LLMResponseMalformedError):
        processor.classify_article(art)


def test_processor_invalid_schema_handling():
    """Verify processor raises LLMResponseMalformedError when JSON does not match schema."""
    mock_llm = MockLLMProvider(mode="invalid_schema")
    processor = ArticleProcessor(llm_provider=mock_llm)
    art = Article(
        title="Sample Article",
        url="https://sample.com/1",
        source="Sample",
    )
    with pytest.raises(LLMResponseMalformedError):
        processor.classify_article(art)


def test_processor_batch_resilience_on_llm_failure():
    """Verify process_articles skips failing articles without aborting the batch."""
    mock_llm = MockLLMProvider(mode="unavailable")
    processor = ArticleProcessor(llm_provider=mock_llm)
    articles = [
        Article(title="Article 1", url="https://ex.com/1", source="Ex"),
        Article(title="Article 2", url="https://ex.com/2", source="Ex"),
    ]
    # Shouldn't raise; logs errors and returns empty list
    results = processor.process_articles(articles)
    assert len(results) == 0
