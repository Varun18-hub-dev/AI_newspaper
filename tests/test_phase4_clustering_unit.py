"""Unit tests for Phase 4 semantic story deduplication and clustering."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import numpy as np
import pytest

from app.clustering.clusterer import StoryClusterer
from app.clustering.embeddings import (
    MiniLMEmbeddingProvider,
    TFIDFEmbeddingProvider,
    get_embedding_provider,
)
from app.clustering.entity_guard import EntityGuard
from app.clustering.models import StoryCluster
from app.clustering.representative import (
    RepresentativeSelector,
    compute_article_representative_score,
)
from app.extraction.models import ExtractedContent
from app.ingestion.models import Article
from app.llm.base import LLMProvider
from app.processing.article_processor import ArticleProcessor
from app.processing.models import ProcessedArticle


# =====================================================================
# 1. Embeddings & Representation Tests
# =====================================================================
def test_tfidf_embedding_provider_shape_and_similarity():
    """Verify TF-IDF embedding outputs normalized representations and valid cosine similarity."""
    provider = TFIDFEmbeddingProvider()

    # Empty and single text edge cases
    assert provider.embed_texts([]).size == 0
    assert provider.compute_similarity_matrix([]).shape == (0, 0)

    sim_single = provider.compute_similarity_matrix(["Single article headline."])
    assert sim_single.shape == (1, 1)
    assert sim_single[0, 0] == 1.0

    # Multi-text embedding
    texts = [
        "OpenAI releases new reasoning model today",
        "OpenAI announces latest reasoning AI model",
        "Stock markets rally as economic indicators rise",
    ]
    sim_mat = provider.compute_similarity_matrix(texts)
    assert sim_mat.shape == (3, 3)
    # Diagonal is 1.0
    for i in range(3):
        assert sim_mat[i, i] == pytest.approx(1.0, abs=1e-5)
    # Symmetric
    assert sim_mat[0, 1] == pytest.approx(sim_mat[1, 0], abs=1e-5)
    # OpenAI pairs have higher similarity than market news
    assert sim_mat[0, 1] > sim_mat[0, 2]


def test_minilm_embedding_provider_shape_and_similarity():
    """Verify local ONNX MiniLMEmbeddingProvider outputs 384-d normalized representations."""
    provider = MiniLMEmbeddingProvider()
    if not provider.is_available:
        pytest.skip("Local ONNX MiniLM model not present in cache.")

    # Dimension and edge cases
    assert provider.embed_texts([]).shape == (0, 384)
    sim_single = provider.compute_similarity_matrix(["Single article headline."])
    assert sim_single.shape == (1, 1)
    assert sim_single[0, 0] == 1.0

    texts = [
        "OpenAI releases new reasoning model today",
        "OpenAI announces latest reasoning AI model",
        "Stock markets rally as economic indicators rise",
    ]
    embs = provider.embed_texts(texts)
    assert embs.shape == (3, 384)

    # L2 normalized
    for row in embs:
        assert np.linalg.norm(row) == pytest.approx(1.0, abs=1e-3)

    sim_mat = provider.compute_similarity_matrix(texts)
    assert sim_mat.shape == (3, 3)
    assert sim_mat[0, 1] > sim_mat[0, 2]


# =====================================================================
# 2. EntityGuard Tests
# =====================================================================
def test_entity_guard_maximal_product_filtering():
    """Verify EntityGuard extracts maximal products without substring redundancy."""
    guard = EntityGuard()
    prods = guard.extract_products("Meta releases Llama 3.2 with enhanced vision")
    assert "llama 3.2" in prods
    assert "llama 3" not in prods
    assert "llama" not in prods


def test_entity_guard_blocks_conflicting_products():
    """Verify EntityGuard prevents merging different models or sub-models from the same company."""
    guard = EntityGuard()

    # OpenAI o1 vs SearchGPT
    art_a = Article(
        title="OpenAI launches o1 reasoning model",
        url="https://openai.com/o1",
        source="OpenAI",
    )
    art_b = Article(
        title="OpenAI announces SearchGPT prototype",
        url="https://openai.com/searchgpt",
        source="OpenAI",
    )
    allowed, reason = guard.is_merge_allowed(art_a, art_b)
    assert allowed is False
    assert "Conflicting products" in reason

    # Claude 3.5 Sonnet vs Claude 3.5 Haiku
    art_c = Article(
        title="Anthropic releases Claude 3.5 Sonnet",
        url="https://anthropic.com/sonnet",
        source="Anthropic",
    )
    art_d = Article(
        title="Anthropic introduces Claude 3.5 Haiku",
        url="https://anthropic.com/haiku",
        source="Anthropic",
    )
    allowed_claude, reason_claude = guard.is_merge_allowed(art_c, art_d)
    assert allowed_claude is False
    assert "Conflicting products" in reason_claude


def test_entity_guard_blocks_conflicting_events():
    """Verify EntityGuard prevents merging corporate funding, legal, or departures with model releases."""
    guard = EntityGuard()
    art_model = Article(
        title="OpenAI launches o1 reasoning model",
        url="https://openai.com/o1",
        source="OpenAI",
    )
    art_funding = Article(
        title="OpenAI closes $6.6 billion funding round at $157 billion valuation",
        url="https://theverge.com/openai-funding",
        source="The Verge",
    )
    allowed, reason = guard.is_merge_allowed(art_model, art_funding)
    assert allowed is False
    assert "Incompatible event types" in reason


def test_entity_guard_blocks_conflicting_companies():
    """Verify EntityGuard blocks merging stories focused on different primary companies."""
    guard = EntityGuard()
    art_google = Article(
        title="Google announces Gemini 1.5 Pro update",
        url="https://google.com/gemini",
        source="Google",
    )
    art_openai = Article(
        title="OpenAI unveils GPT-4o with multimodal reasoning",
        url="https://openai.com/gpt4o",
        source="OpenAI",
    )
    allowed, reason = guard.is_merge_allowed(art_google, art_openai)
    assert allowed is False
    assert "Conflicting primary entities" in reason


def test_entity_guard_time_window_enforcement():
    """Verify EntityGuard disallows merging articles published further apart than the time window."""
    guard = EntityGuard(time_window_hours=48.0)
    now = datetime.utcnow()
    art_old = Article(
        title="OpenAI launches o1 reasoning model",
        url="https://openai.com/o1-scoop",
        source="OpenAI",
        published_at=now - timedelta(days=5),
    )
    art_new = Article(
        title="OpenAI officially unveils new o1 AI model",
        url="https://theverge.com/o1-late",
        source="The Verge",
        published_at=now,
    )
    allowed, reason = guard.is_merge_allowed(art_old, art_new)
    assert allowed is False
    assert "Time window exceeded" in reason


# =====================================================================
# 3. Representative Selection Tests
# =====================================================================
def test_representative_selector_prioritizes_authority_and_completeness():
    """Verify representative selection deterministically elects the most authoritative and complete article."""
    art_low = Article(
        title="Short headline",
        url="https://aggregator.xyz/item",
        source="Unknown Aggregator",
        description="Brief snippet.",
    )
    art_high = Article(
        title="Anthropic officially releases Claude 3.5 Sonnet with enhanced coding benchmarks",
        url="https://arstechnica.com/claude-3-5-sonnet",
        source="Ars Technica",
        description="Anthropic today announced Claude 3.5 Sonnet, demonstrating dramatic leaps in reasoning, coding, and benchmark performance across the board.",
    )
    ext_high = ExtractedContent(
        url=art_high.url,
        text="Long authoritative extracted body text with multiple detailed paragraphs..." * 20,
        word_count=450,
        extraction_success=True,
    )

    score_low = compute_article_representative_score(art_low)
    score_high = compute_article_representative_score(art_high, ext_high)
    assert score_high > score_low

    rep = RepresentativeSelector.select_representative(
        [art_low, art_high],
        extracted_map={art_high.url: ext_high},
    )
    assert rep.url == art_high.url


# =====================================================================
# 4. StoryClusterer Core Tests
# =====================================================================
def test_story_clusterer_exact_duplicates():
    """Verify identical URLs or normalized titles are grouped immediately."""
    clusterer = StoryClusterer()
    articles = [
        Article(title="DeepSeek-R1 Released", url="https://deepseek.com/r1", source="DeepSeek"),
        Article(title="DeepSeek-R1 Released", url="https://deepseek.com/r1-mirror", source="Mirror"),
    ]
    clusters, metrics = clusterer.cluster_articles(articles)
    assert len(clusters) == 1
    assert clusters[0].source_count == 2
    assert metrics.deduplication_ratio == 50.0


def test_story_clusterer_batch_multi_event():
    """Verify clustering a heterogeneous batch correctly creates distinct story clusters."""
    clusterer = StoryClusterer()
    articles = [
        # Event 1: OpenAI o1 (2 articles)
        Article(
            title="OpenAI launches o1 reasoning model with enhanced problem-solving",
            url="https://tc.com/o1",
            source="TechCrunch",
            description="OpenAI officially launched o1.",
        ),
        Article(
            title="OpenAI officially unveils new o1 AI model capable of complex reasoning",
            url="https://verge.com/o1",
            source="The Verge",
            description="The new o1 model from OpenAI excels at reasoning.",
        ),
        # Event 2: Anthropic Claude 3.5 Sonnet (2 articles)
        Article(
            title="Anthropic releases Claude 3.5 Sonnet with state-of-the-art coding abilities",
            url="https://ars.com/sonnet",
            source="Ars Technica",
            description="Anthropic announced Claude 3.5 Sonnet.",
        ),
        Article(
            title="Claude 3.5 Sonnet launched by Anthropic, outperforming competitors",
            url="https://tc.com/sonnet",
            source="TechCrunch",
            description="Claude 3.5 Sonnet is now available across Anthropic API.",
        ),
        # Event 3: Meta Llama 3.2 (2 articles)
        Article(
            title="Meta releases Llama 3.2 with lightweight multimodal vision capabilities",
            url="https://verge.com/llama32",
            source="The Verge",
            description="Meta has released Llama 3.2 multimodal models.",
        ),
        Article(
            title="Meta unveils Llama 3.2 open models designed for mobile edge devices",
            url="https://hf.co/llama32",
            source="Hugging Face",
            description="Llama 3.2 arrives with 1B, 3B and vision models.",
        ),
    ]

    clusters, metrics = clusterer.cluster_articles(articles)

    # Must form exactly 3 distinct clusters (1 per event)
    assert len(clusters) == 3
    assert metrics.total_clusters == 3
    assert metrics.multi_source_clusters == 3
    assert metrics.deduplication_ratio == 50.0

    # Ensure no event cross-contamination
    for c in clusters:
        assert len(c.member_articles) == 2
        titles = [a.title.lower() for a in c.member_articles]
        if "o1" in titles[0]:
            assert all("o1" in t for t in titles)
        elif "sonnet" in titles[0]:
            assert all("sonnet" in t for t in titles)
        elif "llama 3.2" in titles[0]:
            assert all("llama 3.2" in t for t in titles)


# =====================================================================
# 5. Dataset Precision, Recall & Zero False Merges Benchmark
# =====================================================================
def test_clustering_evaluation_dataset_metrics():
    """Verify clustering achieves 0 false merges and >= 90% recall on the evaluation dataset."""
    eval_file = Path(__file__).resolve().parent / "data" / "clustering_eval_dataset.json"
    with open(eval_file, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    clusterer = StoryClusterer()
    tp, fp, tn, fn = 0, 0, 0, 0

    for item in dataset:
        art_a = Article(**item["article_a"])
        art_b = Article(**item["article_b"])
        expected = item["expected_cluster"]

        clusters, _ = clusterer.cluster_articles([art_a, art_b])
        predicted = (len(clusters) == 1)

        if expected and predicted:
            tp += 1
        elif not expected and not predicted:
            tn += 1
        elif not expected and predicted:
            fp += 1
        else:
            fn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0

    # Critical project requirement: 0 false merges
    assert fp == 0, f"Expected 0 false merges, but got {fp}"
    # Target high recall
    assert recall >= 0.90, f"Expected recall >= 0.90, but got {recall:.2f}"
    assert precision == 1.0


# =====================================================================
# 6. Pipeline Integration & LLM Call Savings
# =====================================================================
class MockLLM(LLMProvider):
    def __init__(self):
        self.call_count = 0

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        return (
            '{\n  "is_relevant": true,\n  "relevance_score": 0.95,\n'
            '  "topic": "AI Agents",\n  "reason": "Test article."\n}'
        )


def test_article_processor_clustering_integration_saves_llm_calls():
    """Verify ArticleProcessor runs clustering to evaluate only cluster representatives, saving LLM compute."""
    mock_llm = MockLLM()
    processor = ArticleProcessor(llm_provider=mock_llm)

    # 4 articles covering 2 events (2 articles each)
    articles = [
        # Event 1
        Article(
            title="OpenAI launches o1 reasoning model with enhanced problem-solving",
            url="https://tc.com/o1",
            source="TechCrunch",
            description="OpenAI has officially launched o1.",
        ),
        Article(
            title="OpenAI officially unveils new o1 AI model capable of complex reasoning",
            url="https://theverge.com/o1",
            source="The Verge",
            description="The new o1 model from OpenAI excels at reasoning.",
        ),
        # Event 2
        Article(
            title="Anthropic releases Claude 3.5 Sonnet with state-of-the-art coding abilities",
            url="https://ars.com/sonnet",
            source="Ars Technica",
            description="Anthropic announced Claude 3.5 Sonnet.",
        ),
        Article(
            title="Claude 3.5 Sonnet launched by Anthropic, outperforming competitors",
            url="https://tc.com/sonnet",
            source="TechCrunch",
            description="Claude 3.5 Sonnet is now available across Anthropic API.",
        ),
    ]

    processed, metrics = processor.process_with_metrics(
        articles=articles,
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
    )

    # 4 articles clustered into 2 story clusters
    assert metrics.total_clusters == 2
    assert metrics.multi_source_clusters == 2
    assert metrics.clustering_saved_calls == 2

    # Exactly 2 LLM evaluations performed (1 per story cluster), NOT 4!
    assert metrics.qwen_calls == 2
    assert mock_llm.call_count == 2
    assert len(processed) == 2

    # Verify cluster tracking fields are populated
    for p in processed:
        assert p.cluster_id is not None
        assert p.cluster_source_count == 2
        assert len(p.cluster_sources) == 2


# =====================================================================
# 7. Phase 4.1 Benchmark Dataset v2 Verification (100 Pairs)
# =====================================================================
def test_clustering_eval_dataset_v2_benchmarks():
    """Verify Phase 4.1 100-pair dataset achieves zero false merges and high recall."""
    eval_file = Path(__file__).resolve().parent / "data" / "clustering_eval_dataset_v2.json"
    assert eval_file.exists(), "clustering_eval_dataset_v2.json must exist"

    with open(eval_file, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    assert len(dataset) == 100, f"Expected 100 evaluation pairs, got {len(dataset)}"
    pos_count = sum(1 for d in dataset if d.get("expected_cluster", d.get("expected_merge")))
    neg_count = sum(1 for d in dataset if not d.get("expected_cluster", d.get("expected_merge")))
    assert pos_count == 50
    assert neg_count == 50

    # 1. TF-IDF baseline verification
    clusterer_tfidf = StoryClusterer(embedding_provider=TFIDFEmbeddingProvider())
    fp_tfidf, fn_tfidf, tp_tfidf = 0, 0, 0

    for item in dataset:
        art_a = Article(**item["article_a"])
        art_b = Article(**item["article_b"])
        expected = item.get("expected_cluster", item.get("expected_merge"))

        clusters, _ = clusterer_tfidf.cluster_articles([art_a, art_b])
        predicted = (len(clusters) == 1)

        if expected and predicted:
            tp_tfidf += 1
        elif not expected and predicted:
            fp_tfidf += 1
        elif expected and not predicted:
            fn_tfidf += 1

    precision_tfidf = tp_tfidf / (tp_tfidf + fp_tfidf) if (tp_tfidf + fp_tfidf) > 0 else 0.0
    recall_tfidf = tp_tfidf / (tp_tfidf + fn_tfidf) if (tp_tfidf + fn_tfidf) > 0 else 0.0

    # TF-IDF MUST achieve 0 false merges and >= 90% recall
    assert fp_tfidf == 0, f"TF-IDF produced {fp_tfidf} false merges!"
    assert precision_tfidf == 1.0
    assert recall_tfidf >= 0.90, f"TF-IDF recall {recall_tfidf:.2f} below 0.90 threshold"

    # 2. MiniLM ONNX verification (if model available)
    minilm = MiniLMEmbeddingProvider()
    if minilm.is_available:
        clusterer_minilm = StoryClusterer(
            embedding_provider=minilm,
            similarity_threshold=0.55,
        )
        fp_minilm, fn_minilm, tp_minilm = 0, 0, 0

        for item in dataset:
            art_a = Article(**item["article_a"])
            art_b = Article(**item["article_b"])
            expected = item.get("expected_cluster", item.get("expected_merge"))

            clusters, _ = clusterer_minilm.cluster_articles([art_a, art_b])
            predicted = (len(clusters) == 1)

            if expected and predicted:
                tp_minilm += 1
            elif not expected and predicted:
                fp_minilm += 1
            elif expected and not predicted:
                fn_minilm += 1

        assert fp_minilm == 0, f"Guarded MiniLM produced {fp_minilm} false merges!"
        assert tp_minilm >= 48, f"Guarded MiniLM recall dropped: {tp_minilm}/50"
