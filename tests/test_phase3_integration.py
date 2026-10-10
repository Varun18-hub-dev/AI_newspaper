"""Real end-to-end integration test for Phase 3 Content Extraction & Pre-filtering.

Tests live RSS ingestion -> live webpage fetching -> live content extraction ->
deterministic pre-filter -> live Qwen inference.
No mocks are used in this test suite.
"""

import pytest
from app.core.config import settings
from app.ingestion.rss import RSSConnector
from app.ingestion.models import Article
from app.extraction.fetcher import WebPageFetcher
from app.extraction.extractor import ContentExtractor
from app.extraction.models import ExtractedContent
from app.processing.pre_filter import DeterministicPreFilter
from app.processing.article_processor import ArticleProcessor
from app.processing.models import ProcessedArticle, PipelineMetrics


@pytest.fixture(scope="module")
def live_article():
    """Fetches a real article from live RSS feed."""
    connector = RSSConnector(timeout=20.0)
    articles, _ = connector.fetch_all(["https://techcrunch.com/category/artificial-intelligence/feed/"])
    assert len(articles) > 0, "Failed to ingest live test article"
    return articles[0]


def test_live_webpage_fetch_and_extraction(live_article):
    """Verify real HTTP fetch and HTML extraction on a live webpage."""
    fetcher = WebPageFetcher(timeout=20.0)
    extractor = ContentExtractor()

    html, err = fetcher.fetch_html(live_article.url)
    assert html is not None, f"Failed to fetch webpage HTML: {err}"
    assert len(html) > 100

    extracted = extractor.extract_from_html(
        html_str=html,
        url=live_article.url,
        fallback_text=live_article.description,
    )

    assert isinstance(extracted, ExtractedContent)
    assert extracted.extraction_success is True
    assert extracted.word_count > 0
    assert len(extracted.text.strip()) > 0


def test_live_phase3_pipeline_with_qwen(live_article):
    """Verify live Phase 3 pipeline with real content extraction, pre-filter, and Qwen inference."""
    processor = ArticleProcessor()

    # Process 1 real candidate through Phase 3 pipeline
    results, metrics = processor.process_with_metrics(
        articles=[live_article],
        max_candidates=1,
        enable_extraction=True,
        enable_pre_filter=True,
    )

    assert isinstance(metrics, PipelineMetrics)
    assert metrics.total_rss_articles == 1
    assert metrics.valid_articles == 1
    assert metrics.extraction_success == 1

    # Check if passed pre-filter
    if metrics.candidates_passed_to_llm == 1:
        assert len(results) == 1
        item = results[0]
        assert isinstance(item, ProcessedArticle)
        assert item.extracted_content is not None
        assert item.pre_filter is not None
        assert isinstance(item.classification.is_relevant, bool)
        assert 0.0 <= item.classification.relevance_score <= 1.0
        assert len(item.classification.topic.strip()) > 0
