"""Integration tests for Phase 5 persistent storage and cross-day story deduplication."""

from datetime import datetime, timedelta
import pytest

from app.clustering.clusterer import StoryClusterer
from app.extraction.extractor import ContentExtractor
from app.extraction.fetcher import WebPageFetcher
from app.ingestion.models import Article
from app.llm.base import LLMProvider
from app.processing.article_processor import ArticleProcessor
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase


class CountingMockLLM(LLMProvider):
    """Deterministic Mock LLM counting call invocations."""

    def __init__(self):
        self.call_count = 0
        self.prompts = []

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        return (
            '{\n  "is_relevant": true,\n  "relevance_score": 0.95,\n'
            '  "topic": "AI Agents",\n  "reason": "Test article for Phase 5 integration."\n}'
        )


@pytest.fixture
def test_storage():
    """Provides an isolated in-memory StorageService."""
    db = SQLiteDatabase(db_path=":memory:")
    return StorageService(db=db)


# =============================================================================
# 1. Duplicate Article Detection Across Two Runs Saves LLM Calls
# =============================================================================
def test_duplicate_detection_across_two_runs_saves_llm_calls(test_storage):
    """Verify Run 1 executes LLM evaluations, while Run 2 skips them, avoiding redundant calls."""
    mock_llm = CountingMockLLM()
    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=test_storage,
    )

    articles = [
        Article(
            title="OpenAI launches o1 reasoning model with enhanced problem-solving",
            url="https://techcrunch.com/2024/09/12/openai-o1",
            source="TechCrunch",
            description="OpenAI officially announced o1 model.",
        ),
        Article(
            title="Anthropic introduces Claude 3.5 Sonnet with superior coding",
            url="https://theverge.com/2024/06/20/claude-35-sonnet",
            source="The Verge",
            description="Anthropic launched Claude 3.5 Sonnet.",
        ),
    ]

    # Run 1: First ingestion run
    processed_1, m1 = processor.process_with_metrics(
        articles=articles,
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    assert len(processed_1) == 2
    assert m1.qwen_calls == 2
    assert mock_llm.call_count == 2
    assert m1.new_articles_persisted == 2

    # Run 2: Exact same articles ingested on subsequent run
    processed_2, m2 = processor.process_with_metrics(
        articles=articles,
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    # Critical verification: 0 new evaluations, exactly 2 evaluations avoided!
    assert len(processed_2) == 0
    assert m2.qwen_calls == 0
    assert mock_llm.call_count == 2  # Unchanged!
    assert m2.previously_seen_articles_recognized == 2
    assert m2.exact_duplicates_skipped == 2
    assert m2.qwen_evaluations_avoided == 2


# =============================================================================
# 2. Cross-Day Matching to a Stored Historical Cluster
# =============================================================================
def test_cross_day_matching_to_stored_historical_cluster(test_storage):
    """Verify a follow-up article published the next day merges into Day 1's cluster without calling LLM."""
    mock_llm = CountingMockLLM()
    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=test_storage,
    )

    day1_time = datetime(2026, 10, 8, 10, 0, 0)
    day2_time = day1_time + timedelta(hours=3)

    # Day 1: TechCrunch covers Google Gemini Agent
    day1_article = Article(
        title="Google brings agentic AI to Gemini, starting with businesses",
        url="https://techcrunch.com/2026/10/08/google-gemini-agent",
        source="TechCrunch",
        description="Google is introducing new agentic capabilities to Gemini for Workspace.",
        published_at=day1_time,
    )

    p1, m1 = processor.process_with_metrics(
        articles=[day1_article],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    assert len(p1) == 1
    assert mock_llm.call_count == 1
    day1_cluster_id = p1[0].cluster_id
    assert day1_cluster_id is not None

    # Day 2: The Verge publishes duplicate coverage of the same Gemini agent event
    day2_article = Article(
        title="Google is launching a one-stop Gemini agent for your work tasks",
        url="https://theverge.com/2026/10/09/google-gemini-work-agent",
        source="The Verge",
        description="Google announced agentic AI features in Gemini for work workflows.",
        published_at=day2_time,
    )

    p2, m2 = processor.process_with_metrics(
        articles=[day2_article],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    # Day 2 article matched Day 1's historical cluster!
    assert m2.historical_story_matches == 1
    # Avoided calling LLM on the duplicate coverage
    assert m2.qwen_evaluations_avoided == 1
    assert mock_llm.call_count == 1  # Unchanged!
    # Redundant duplicate coverage is not duplicated in newspaper output
    assert len(p2) == 0

    # Verify cluster membership in database
    members = test_storage.db.get_cluster_member_articles(day1_cluster_id)
    assert len(members) == 2
    sources = {m.source for m in members}
    assert sources == {"TechCrunch", "The Verge"}


# =============================================================================
# 3. Distinct Events Remain Separate Across Days
# =============================================================================
def test_distinct_events_remain_separate_cross_day(test_storage):
    """Verify genuinely different events published across days do NOT merge."""
    mock_llm = CountingMockLLM()
    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=test_storage,
    )

    # Day 1: OpenAI event
    art1 = Article(
        title="OpenAI launches o1 reasoning model with enhanced problem-solving",
        url="https://techcrunch.com/openai-o1",
        source="TechCrunch",
        description="OpenAI officially launched o1.",
        published_at=datetime(2026, 10, 8, 9, 0, 0),
    )
    p1, m1 = processor.process_with_metrics(
        articles=[art1],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    assert len(p1) == 1
    assert mock_llm.call_count == 1

    # Day 2: Anthropic event (completely different company & event)
    art2 = Article(
        title="Anthropic introduces Claude 3.5 Sonnet with state-of-the-art coding",
        url="https://theverge.com/claude-35-sonnet",
        source="The Verge",
        description="Anthropic launched Claude 3.5 Sonnet.",
        published_at=datetime(2026, 10, 9, 9, 0, 0),
    )
    p2, m2 = processor.process_with_metrics(
        articles=[art2],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    assert m2.historical_story_matches == 0
    assert m2.new_story_clusters_created == 1
    assert len(p2) == 1
    assert mock_llm.call_count == 2
    assert p1[0].cluster_id != p2[0].cluster_id


# =============================================================================
# 4. Different Model Versions Remain Separate Across Days
# =============================================================================
def test_different_model_versions_remain_separate_cross_day(test_storage):
    """Verify EntityGuard prevents cross-day merge between Llama 3.1 and Llama 3.2."""
    mock_llm = CountingMockLLM()
    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=test_storage,
    )

    # Day 1: Llama 3.1
    art_v1 = Article(
        title="Meta releases Llama 3.1 with 405B parameters and enhanced benchmarks",
        url="https://techcrunch.com/llama-3-1",
        source="TechCrunch",
        description="Meta releases Llama 3.1 405B.",
        published_at=datetime(2026, 10, 8, 9, 0, 0),
    )
    p1, _ = processor.process_with_metrics(
        articles=[art_v1],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    assert len(p1) == 1

    # Day 2: Llama 3.2 (different version from same company!)
    art_v2 = Article(
        title="Meta releases Llama 3.2 with lightweight multimodal vision capabilities",
        url="https://theverge.com/llama-3-2",
        source="The Verge",
        description="Meta releases Llama 3.2 on-device models.",
        published_at=datetime(2026, 10, 9, 9, 0, 0),
    )
    p2, m2 = processor.process_with_metrics(
        articles=[art_v2],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    # EntityGuard MUST block cross-day merge
    assert m2.historical_story_matches == 0
    assert m2.new_story_clusters_created == 1
    assert len(p2) == 1
    assert p1[0].cluster_id != p2[0].cluster_id


# =============================================================================
# 5. Funding Announcement vs Product Release Remain Separate Across Days
# =============================================================================
def test_funding_vs_product_release_separate_cross_day(test_storage):
    """Verify event category guardrail separates funding rounds from product launches."""
    mock_llm = CountingMockLLM()
    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=test_storage,
    )

    # Day 1: Product release
    art_prod = Article(
        title="OpenAI launches o1 reasoning model with enhanced problem-solving",
        url="https://techcrunch.com/openai-o1-launch",
        source="TechCrunch",
        description="OpenAI officially launched o1 model.",
        published_at=datetime(2026, 10, 8, 9, 0, 0),
    )
    p1, _ = processor.process_with_metrics(
        articles=[art_prod],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )

    # Day 2: Financial/funding announcement from same company
    art_fund = Article(
        title="OpenAI closes $6.6 billion funding round at $157 billion valuation",
        url="https://theverge.com/openai-funding-round",
        source="The Verge",
        description="OpenAI raises massive financing round.",
        published_at=datetime(2026, 10, 9, 9, 0, 0),
    )
    p2, m2 = processor.process_with_metrics(
        articles=[art_fund],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    # Event guardrail MUST prevent merging funding with product release
    assert m2.historical_story_matches == 0
    assert m2.new_story_clusters_created == 1
    assert p1[0].cluster_id != p2[0].cluster_id


# =============================================================================
# 6. Meaningful Story Updates Detected in Pipeline
# =============================================================================
def test_meaningful_story_update_detected_in_pipeline(test_storage):
    """Verify headline update marker triggers meaningful update classification."""
    mock_llm = CountingMockLLM()
    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=test_storage,
    )

    # Day 1: Initial event
    art_init = Article(
        title="Google introduces preview of Gemini agent for businesses",
        url="https://tc.com/gemini-preview",
        source="TechCrunch",
        description="Google introduced an early preview of its agent.",
        published_at=datetime(2026, 10, 8, 9, 0, 0),
    )
    p1, _ = processor.process_with_metrics(
        articles=[art_init],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    cl_id = p1[0].cluster_id

    # Day 2: Headline with explicit update marker
    art_update = Article(
        title="Update: Google confirmed general availability of Gemini agent for all enterprise customers",
        url="https://theverge.com/gemini-ga",
        source="The Verge",
        description="Google confirmed the agent is now generally available.",
        published_at=datetime(2026, 10, 9, 14, 0, 0),
    )
    p2, m2 = processor.process_with_metrics(
        articles=[art_update],
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
        enable_storage=True,
    )
    assert m2.historical_story_matches == 1
    assert m2.meaningful_story_updates_detected == 1

    # Downstream newspaper receives meaningful update article without full Qwen re-classification
    assert len(p2) == 1
    assert p2[0].cluster_id == cl_id
    assert "Meaningful update" in p2[0].classification.reason
    assert mock_llm.call_count == 1  # Exactly 0 Qwen calls made on Day 2!

    # Verify cluster lifecycle status updated in SQLite
    cl_rec = test_storage.db.get_cluster_by_id(cl_id)
    assert cl_rec.lifecycle_status == "UPDATED"
