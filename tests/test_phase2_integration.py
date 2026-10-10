"""Real end-to-end integration test for Phase 2 AI News Discovery Pipeline.

Tests live RSS fetching from real configured feeds and live classification via local Qwen.
No mocks are used in this test suite.
"""

import pytest
from app.core.config import settings
from app.ingestion.rss import RSSConnector
from app.ingestion.models import Article
from app.processing.filtering import filter_and_deduplicate
from app.processing.article_processor import ArticleProcessor
from app.processing.models import ProcessedArticle


@pytest.fixture(scope="module")
def real_rss_connector():
    return RSSConnector(timeout=20.0)


@pytest.fixture(scope="module")
def real_article_processor():
    return ArticleProcessor()


@pytest.fixture(scope="module")
def live_ingested_articles(real_rss_connector):
    """Fetches articles once from configured feeds for the module test suite."""
    articles, statuses = real_rss_connector.fetch_all(settings.ai_rss_feeds)
    assert len(articles) > 0, f"Failed to fetch any articles from configured feeds: {statuses}"
    return articles


def test_live_rss_ingestion(live_ingested_articles):
    """Verify live RSS ingestion fetches and normalizes articles from configured feeds."""
    assert isinstance(live_ingested_articles, list)
    assert len(live_ingested_articles) > 0

    first = live_ingested_articles[0]
    assert isinstance(first, Article)
    assert len(first.title) > 0
    assert first.url.startswith("http")
    assert first.domain == "AI"


def test_live_end_to_end_pipeline(live_ingested_articles, real_article_processor):
    """Verify end-to-end flow: Real Ingested -> Filter -> Real Qwen Inference -> ProcessedArticle."""
    filtered = filter_and_deduplicate(live_ingested_articles)
    assert len(filtered) > 0

    # Classify the first 2 candidates with local Qwen
    test_candidates = filtered[:2]
    results = real_article_processor.process_articles(
        articles=test_candidates,
        max_candidates=2,
    )

    assert len(results) > 0
    assert len(results) <= len(test_candidates)
    for processed in results:
        assert isinstance(processed, ProcessedArticle)
        assert isinstance(processed.classification.is_relevant, bool)
        assert 0.0 <= processed.classification.relevance_score <= 1.0
        assert len(processed.classification.topic.strip()) > 0
        assert len(processed.classification.reason.strip()) > 0
