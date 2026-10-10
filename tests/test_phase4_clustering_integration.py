"""Integration tests for Phase 4 semantic story deduplication and clustering."""

import pytest
from app.clustering.clusterer import StoryClusterer
from app.extraction.extractor import ContentExtractor
from app.extraction.fetcher import WebPageFetcher
from app.ingestion.models import Article
from app.ingestion.rss import RSSConnector
from app.processing.article_processor import ArticleProcessor
from app.processing.filtering import filter_and_deduplicate


@pytest.mark.integration
def test_real_rss_ingestion_and_clustering():
    """Verify that real RSS feed articles can be ingested and clustered without error."""
    from app.core.config import settings
    connector = RSSConnector(timeout=15.0, max_items_per_feed=5)
    # Fetch a small slice of real articles from configured feeds
    articles, _ = connector.fetch_all(settings.ai_rss_feeds)
    assert len(articles) > 0, "Expected at least one article from RSS feeds"

    clean_articles = filter_and_deduplicate(articles)
    assert len(clean_articles) > 0

    clusterer = StoryClusterer()
    clusters, metrics = clusterer.cluster_articles(clean_articles)

    assert metrics.total_input_articles == len(clean_articles)
    assert metrics.total_clusters == len(clusters)
    assert len(clusters) <= len(clean_articles)
    assert metrics.clustering_runtime_seconds >= 0.0

    # Verify each formed cluster has a valid representative article
    for cluster in clusters:
        assert cluster.representative_article is not None
        assert cluster.cluster_id.startswith("cluster_")
        assert cluster.source_count >= 1
        assert len(cluster.member_articles) >= 1
        assert cluster.representative_article in cluster.member_articles


@pytest.mark.integration
def test_processor_pipeline_with_clustering_real_components():
    """Verify ArticleProcessor runs extraction, pre-filtering, and clustering cleanly."""
    fetcher = WebPageFetcher(timeout=5.0)
    extractor = ContentExtractor()
    clusterer = StoryClusterer()

    articles = [
        Article(
            title="OpenAI announces new AI reasoning benchmark results",
            url="https://openai.com/benchmark-test",
            source="OpenAI",
            description="OpenAI shared new benchmark evaluations for reasoning models.",
        ),
        Article(
            title="OpenAI announces new AI reasoning benchmark results",
            url="https://news.ycombinator.com/item?id=9999",
            source="HackerNews",
            description="Discussion on OpenAI's new reasoning benchmark results.",
        ),
        Article(
            title="Anthropic launches upgraded developer console for Claude models",
            url="https://anthropic.com/console",
            source="Anthropic",
            description="Anthropic launched new developer tools and workspace controls.",
        ),
    ]

    processor = ArticleProcessor(
        web_fetcher=fetcher,
        extractor=extractor,
        clusterer=clusterer,
    )

    clusters, c_metrics = processor.cluster_articles(articles)
    assert len(clusters) == 2  # The 2 duplicate OpenAI benchmark articles cluster together
    assert c_metrics.multi_source_clusters == 1
