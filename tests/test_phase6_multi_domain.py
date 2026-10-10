"""Tests for Phase 6 Multi-Domain News Discovery."""

from datetime import datetime, timedelta
from unittest.mock import MagicMock
import pytest

from app.clustering.clusterer import StoryClusterer
from app.clustering.entity_guard import EntityGuard
from app.domains.models import DomainConfig, FeedConfig
from app.domains.registry import (
    DomainRegistry,
    get_domain_registry,
    AI_TOPICS,
    TECHNOLOGY_TOPICS,
    SCIENCE_TOPICS,
    CYBERSECURITY_TOPICS,
    BUSINESS_TOPICS,
)
from app.ingestion.models import Article
from app.ingestion.rss import RSSConnector
from app.llm.base import LLMProvider
from app.processing.article_processor import ArticleProcessor
from app.processing.filtering import filter_and_deduplicate
from app.processing.models import (
    AIRelevanceClassification,
    RelevanceClassification,
    normalize_topic_for_domain,
)
from app.processing.pre_filter import DeterministicPreFilter
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase


class MultiDomainMockLLM(LLMProvider):
    """Deterministic Mock LLM returning valid domain-specific classifications."""

    def __init__(self):
        self.call_count = 0
        self.last_prompt = ""

    def generate(self, prompt: str, **kwargs) -> str:
        self.call_count += 1
        self.last_prompt = prompt

        if "Cybersecurity" in prompt:
            return (
                '{\n  "is_relevant": true,\n  "relevance_score": 0.95,\n'
                '  "topic": "Vulnerabilities & CVEs",\n  "reason": "Critical OpenSSL vulnerability."\n}'
            )
        elif "Science" in prompt:
            return (
                '{\n  "is_relevant": true,\n  "relevance_score": 0.92,\n'
                '  "topic": "Space & Astronomy",\n  "reason": "James Webb galaxy discovery."\n}'
            )
        elif "Business" in prompt:
            return (
                '{\n  "is_relevant": true,\n  "relevance_score": 0.90,\n'
                '  "topic": "Venture Capital & Funding",\n  "reason": "Venture funding round."\n}'
            )
        elif "Technology" in prompt:
            return (
                '{\n  "is_relevant": true,\n  "relevance_score": 0.91,\n'
                '  "topic": "Software & Apps",\n  "reason": "Major operating system release."\n}'
            )
        else:
            return (
                '{\n  "is_relevant": true,\n  "relevance_score": 0.95,\n'
                '  "topic": "AI Agents",\n  "reason": "AI agent innovation."\n}'
            )


# =============================================================================
# 1. Domain Registry & Configuration Tests
# =============================================================================

def test_domain_registry_all_five_domains_configured():
    """Verify all 5 required domains are registered with valid configurations and taxonomies."""
    registry = get_domain_registry()
    domains = registry.list_domains(enabled_only=False)
    domain_ids = {d.domain_id for d in domains}

    assert {"ai", "technology", "science", "cybersecurity", "business"}.issubset(domain_ids)

    # Verify feeds and taxonomies for each
    for d_id in ["ai", "technology", "science", "cybersecurity", "business"]:
        cfg = registry.get_domain(d_id)
        assert cfg is not None
        assert len(cfg.feeds) >= 3
        assert len(cfg.allowed_topics) >= 5
        assert cfg.prompt_template is not None
        assert len(cfg.strong_signals) > 0


def test_domain_enabling_and_disabling():
    """Verify domains can be toggled on/off without affecting other domain states."""
    registry = DomainRegistry()
    assert registry.is_domain_enabled("science") is True

    # Disable science
    registry.set_domain_enabled("science", False)
    assert registry.is_domain_enabled("science") is False

    enabled_ids = [d.domain_id for d in registry.list_domains(enabled_only=True)]
    assert "science" not in enabled_ids
    assert "ai" in enabled_ids
    assert "cybersecurity" in enabled_ids

    # Re-enable science
    registry.set_domain_enabled("science", True)
    assert registry.is_domain_enabled("science") is True


# =============================================================================
# 2. Feed Isolation & Fault Tolerance
# =============================================================================

def test_feed_isolation_on_partial_failure():
    """Verify failure in one feed (HTTP 403 or timeout) does not crash discovery of other feeds."""
    connector = RSSConnector()

    valid_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Cybersecurity News</title>
        <item>
          <title>Critical Zero-Day in OpenSSL Patched</title>
          <link>https://cyber.org/cve-2026-001</link>
          <description>Emergency patch released for remote code execution.</description>
        </item>
      </channel>
    </rss>
    """

    def mock_get(url, **kwargs):
        resp = MagicMock()
        if "failing-feed" in url:
            resp.status_code = 403
            resp.raise_for_status.side_effect = Exception("403 Forbidden")
            return resp
        resp.status_code = 200
        resp.content = valid_xml
        resp.raise_for_status.return_value = None
        return resp

    connector.session.get = mock_get

    articles, statuses = connector.fetch_all(
        urls=["https://failing-feed.com/rss", "https://working-feed.com/rss"],
        domain="Cybersecurity",
    )

    assert len(articles) == 1
    assert articles[0].title == "Critical Zero-Day in OpenSSL Patched"
    assert articles[0].domain == "Cybersecurity"
    assert statuses["https://failing-feed.com/rss"]["status"] == "FAILED"
    assert statuses["https://working-feed.com/rss"]["status"] == "SUCCESS"


# =============================================================================
# 3. Cross-Feed Canonical URL Deduplication & Source Attribution
# =============================================================================

def test_cross_feed_url_deduplication_preserves_multiple_sources():
    """Verify deduplicating identical URLs across feeds retains multi-source attribution."""
    art1 = Article(
        title="Major Tech Merger Announced Between Firm A and Firm B",
        url="https://reuters.com/tech-merger-2026?utm_source=rss",
        source="Reuters Business",
        domain="Business and startups",
    )
    art2 = Article(
        title="Major Tech Merger Announced Between Firm A and Firm B",
        url="https://reuters.com/tech-merger-2026?ref=techcrunch",
        source="TechCrunch Feed",
        domain="Business and startups",
    )

    deduped = filter_and_deduplicate([art1, art2])
    assert len(deduped) == 1
    assert deduped[0].url == "https://reuters.com/tech-merger-2026"
    assert "Reuters Business" in deduped[0].all_sources
    assert "TechCrunch Feed" in deduped[0].all_sources


# =============================================================================
# 4. Domain-Specific Relevance Pre-Filtering
# =============================================================================

def test_domain_specific_pre_filter_relevance():
    """Verify each domain scores strongly for genuine domain stories and rejects noise."""
    pre_filter = DeterministicPreFilter()

    # 1. Cybersecurity article
    cyber_art = Article(
        title="High Severity CVE-2026-9999 Vulnerability Allows Remote Code Execution",
        url="https://krebsonsecurity.com/2026/10/cve-rce",
        source="Krebs on Security",
        description="A newly discovered zero-day flaw enables privilege escalation and malware deployment.",
        domain="Cybersecurity",
    )
    res_cyber = pre_filter.evaluate(cyber_art)
    assert res_cyber.pre_filter_score >= 0.60
    assert res_cyber.tier == "HIGH"
    assert res_cyber.should_send_to_llm is True

    # 2. Science article
    sci_art = Article(
        title="James Webb Space Telescope Identifies Atmospheric Water on Distant Exoplanet",
        url="https://sciencedaily.com/releases/2026/10/webb-exoplanet",
        source="ScienceDaily",
        description="Astronomers use astrophysics spectrometry to detect water vapor in planet atmosphere.",
        domain="Science",
    )
    res_sci = pre_filter.evaluate(sci_art)
    assert res_sci.pre_filter_score >= 0.60
    assert res_sci.tier == "HIGH"
    assert res_sci.should_send_to_llm is True

    # 3. Business article
    biz_art = Article(
        title="Fintech Startup Raises $120M Series C Funding Round at $1.5B Valuation",
        url="https://techcrunch.com/2026/10/fintech-series-c",
        source="TechCrunch Startups",
        description="Venture capital firms lead growth investment round as startups scale revenue.",
        domain="Business and startups",
    )
    res_biz = pre_filter.evaluate(biz_art)
    assert res_biz.pre_filter_score >= 0.60
    assert res_biz.tier == "HIGH"
    assert res_biz.should_send_to_llm is True

    # 4. Technology article
    tech_art = Article(
        title="New Generation Laptop Processors Deliver 40% Better Battery Life and Multitasking",
        url="https://theverge.com/2026/10/new-laptop-processors",
        source="The Verge",
        description="Next-generation CPUs feature improved energy efficiency and enhanced semiconductor architecture.",
        domain="Technology",
    )
    res_tech = pre_filter.evaluate(tech_art)
    assert res_tech.pre_filter_score >= 0.60
    assert res_tech.tier == "HIGH"
    assert res_tech.should_send_to_llm is True

    # 5. Irrelevant noise in Cybersecurity
    noise_art = Article(
        title="Discount Hotel Deals and Airline Ticket Promo Codes for Weekend Travelers",
        url="https://krebsonsecurity.com/promo-deals",
        source="Krebs on Security",
        description="Buy tickets with discount promo code for hotel booking and travel.",
        domain="Cybersecurity",
    )
    res_noise = pre_filter.evaluate(noise_art)
    assert res_noise.pre_filter_score < 0.20
    assert res_noise.tier == "LOW"
    assert res_noise.should_send_to_llm is False


# =============================================================================
# 5. Non-AI Articles Are Not Forced Into AI Categories
# =============================================================================

def test_domain_topic_taxonomies_and_prompt_isolation():
    """Verify non-AI articles receive domain-specific prompt and topic normalization."""
    mock_llm = MultiDomainMockLLM()
    processor = ArticleProcessor(llm_provider=mock_llm)

    # 1. Cybersecurity article
    cyber_art = Article(
        title="Critical Zero-Day Vulnerability Found in Enterprise Firewalls",
        url="https://krebsonsecurity.com/zero-day-firewall",
        source="Krebs on Security",
        description="Security advisory urges immediate patching of critical flaw.",
        domain="Cybersecurity",
    )
    proc_cyber = processor.classify_article(cyber_art)
    assert "Cybersecurity" in mock_llm.last_prompt
    assert proc_cyber.classification.topic == "Vulnerabilities & CVEs"
    assert proc_cyber.classification.topic in CYBERSECURITY_TOPICS
    assert proc_cyber.classification.topic not in AI_TOPICS

    # 2. Science article
    sci_art = Article(
        title="New Study Reveals Supermassive Black Hole Mergers in Deep Space",
        url="https://phys.org/black-hole-merger",
        source="Phys.org",
        description="Astrophysicists observe gravitational radiation from distant black holes.",
        domain="Science",
    )
    proc_sci = processor.classify_article(sci_art)
    assert "Science" in mock_llm.last_prompt
    assert proc_sci.classification.topic == "Space & Astronomy"
    assert proc_sci.classification.topic in SCIENCE_TOPICS


# =============================================================================
# 6. EntityGuard Blocks Cross-Domain Merges
# =============================================================================

def test_entity_guard_blocks_cross_domain_merges():
    """Verify articles from different domains sharing common entity names are NEVER merged."""
    guard = EntityGuard()

    # Article A: AI domain
    art_ai = Article(
        title="OpenAI releases o1 reasoning model with enhanced problem solving",
        url="https://techcrunch.com/openai-o1",
        source="TechCrunch AI",
        description="OpenAI officially launched o1.",
        domain="AI",
    )

    # Article B: Business domain (same company OpenAI, but financial/business event)
    art_biz = Article(
        title="OpenAI closes $6.6 billion funding round at $157 billion valuation",
        url="https://wsj.com/openai-funding",
        source="Wall Street Journal",
        description="OpenAI raises massive private funding round led by Thrive Capital.",
        domain="Business and startups",
    )

    allowed, reason = guard.is_merge_allowed(art_ai, art_biz)
    assert allowed is False
    assert "Cross-domain boundary" in reason


def test_story_clusterer_separates_cross_domain_articles():
    """Verify StoryClusterer preserves strict domain isolation across batch candidate articles."""
    clusterer = StoryClusterer()

    articles = [
        # Cybersecurity event (2 articles on same incident)
        Article(
            title="Global ransomware attack paralyzes major hospital and healthcare systems",
            url="https://krebsonsecurity.com/ransomware-outbreak",
            source="Krebs on Security",
            description="A coordinated global ransomware attack has paralyzed major hospital systems.",
            domain="Cybersecurity",
        ),
        Article(
            title="Coordinated global ransomware attack paralyzes healthcare and hospital networks",
            url="https://darkreading.com/hospital-ransomware",
            source="Dark Reading",
            description="Major hospital and healthcare systems paralyzed by global ransomware attack.",
            domain="Cybersecurity",
        ),
        # Science event (2 articles on same discovery)
        Article(
            title="Astronomers capture groundbreaking high-resolution image of Sagittarius A black hole",
            url="https://phys.org/sagittarius-a-image",
            source="Phys.org",
            description="Astronomers capture groundbreaking high-resolution image of Sagittarius A black hole.",
            domain="Science",
        ),
        Article(
            title="Groundbreaking high-resolution image of Sagittarius A black hole captured by astronomers",
            url="https://sciencedaily.com/galactic-center-photo",
            source="ScienceDaily",
            description="New high-resolution image of Sagittarius A black hole captured by global astronomers.",
            domain="Science",
        ),
    ]

    clusters, metrics = clusterer.cluster_articles(articles)

    assert metrics.total_clusters == 2
    # Verify each cluster contains only items from a single domain
    for c in clusters:
        domains_in_cluster = {a.domain for a in c.member_articles}
        assert len(domains_in_cluster) == 1


# =============================================================================
# 7. SQLite Storage Persists & Recovers Multi-Domain Metadata
# =============================================================================

def test_sqlite_storage_multi_domain_persistence():
    """Verify ArticleRecord and StoryClusterRecord store and recover domain metadata accurately."""
    db = SQLiteDatabase(db_path=":memory:")
    storage = StorageService(db=db)

    articles = [
        Article(
            title="New Quantum Computing Architecture Overcomes Decoherence Flaw",
            url="https://phys.org/quantum-decoherence",
            source="Phys.org",
            domain="Science",
        ),
        Article(
            title="Ransomware Gang Threatens to Leak Stolen Government Data",
            url="https://krebsonsecurity.com/ransomware-leak",
            source="Krebs on Security",
            domain="Cybersecurity",
        ),
    ]

    to_proc, skipped, _ = storage.check_and_register_articles(articles)
    assert len(to_proc) == 2

    # Verify domain stored in SQLite
    all_stored = [db.get_article_by_canonical_url(a.url) for a in articles]

    assert all_stored[0] is not None
    assert all_stored[0].domain == "Science"
    assert all_stored[1] is not None
    assert all_stored[1].domain == "Cybersecurity"

    # Convert back to Article object
    recovered = storage.article_record_to_article(all_stored[0])
    assert recovered.domain == "Science"


# =============================================================================
# 8. Backward Compatibility: AI-Only Pipeline Integrity
# =============================================================================

def test_backward_compatibility_ai_only_pipeline():
    """Verify ArticleProcessor running standard AI-only articles functions identically to Phase 5."""
    mock_llm = MultiDomainMockLLM()
    processor = ArticleProcessor(llm_provider=mock_llm)

    ai_articles = [
        Article(
            title="OpenAI releases o1 reasoning model with enhanced problem-solving",
            url="https://tc.com/o1",
            source="TechCrunch",
            description="OpenAI has launched o1.",
        ),
        Article(
            title="Anthropic introduces Claude 3.5 Sonnet with state-of-the-art coding",
            url="https://theverge.com/sonnet",
            source="The Verge",
            description="Anthropic launched Claude 3.5 Sonnet.",
        ),
    ]

    processed, metrics = processor.process_with_metrics(
        articles=ai_articles,
        enable_extraction=False,
        enable_pre_filter=False,
        enable_clustering=True,
    )

    assert len(processed) == 2
    assert metrics.qwen_calls == 2
    for item in processed:
        assert item.article.domain == "AI"
        assert item.classification.is_relevant is True
        assert item.classification.topic in AI_TOPICS


# =============================================================================
# 9. Phase 6.1 Quality Audit Tests: Clustering Benchmark & Attribution Persistence
# =============================================================================

def test_phase6_1_multi_domain_clustering_benchmark():
    """Verify that MiniLM + EntityGuard achieves 0 false merges and 100% precision on curated pairs."""
    from scripts.verify_phase6_1_quality import CLUSTERING_TEST_PAIRS
    from app.clustering.embeddings import MiniLMEmbeddingProvider

    minilm = MiniLMEmbeddingProvider()
    guard = EntityGuard()
    clusterer = StoryClusterer(embedding_provider=minilm, entity_guard=guard)

    tp, fp, fn, tn = 0, 0, 0, 0
    for item in CLUSTERING_TEST_PAIRS:
        art_a, art_b = item["a"], item["b"]
        expected = item["expected_merge"]

        t_a = clusterer.build_article_text(art_a)
        t_b = clusterer.build_article_text(art_b)
        sim = float(minilm.compute_similarity_matrix([t_a, t_b])[0, 1])
        bonus = guard.compute_semantic_bonus(art_a, art_b, t_a, t_b)
        total_sim = min(1.0, sim + bonus)
        allowed, reason = guard.is_merge_allowed(art_a, art_b, t_a, t_b)

        predicted_merge = allowed and (total_sim >= clusterer.similarity_threshold)

        if expected and predicted_merge:
            tp += 1
        elif not expected and not predicted_merge:
            tn += 1
        elif not expected and predicted_merge:
            fp += 1
        else:
            fn += 1

    assert fp == 0, f"Clustering produced {fp} false merges across multi-domain benchmark!"
    assert tp == 10, f"Clustering missed duplicates: {tp}/10 true positives"
    assert fn == 0


def test_phase6_1_multi_source_attribution_and_restart_recovery(tmp_path):
    """Verify syndicated cross-feed articles preserve all_sources across repeated ingestion and DB restarts."""
    db_path = str(tmp_path / "test_persistence.db")
    now = datetime.utcnow()

    art1 = Article(
        title="OpenAI confirms safety department restructuring",
        url="https://tc.com/safety-update?utm_source=rss",
        source="TechCrunch AI",
        description="OpenAI restructured its safety teams.",
        published_at=now,
        domain="AI",
    )
    art2 = Article(
        title="OpenAI confirms safety department restructuring",
        url="https://tc.com/safety-update#fragment",
        source="The Verge",
        description="OpenAI restructured its safety teams.",
        published_at=now,
        domain="AI",
    )
    art3 = Article(
        title="OpenAI confirms safety department restructuring",
        url="https://tc.com/safety-update",
        source="Ars Technica",
        description="OpenAI restructured its safety teams.",
        published_at=now,
        domain="AI",
    )

    # 1. Deduplication accumulates all sources
    deduped = filter_and_deduplicate([art1, art2, art3])
    assert len(deduped) == 1
    assert set(deduped[0].all_sources) == {"TechCrunch AI", "The Verge", "Ars Technica"}

    # 2. Repeated ingestion idempotency
    repeated = filter_and_deduplicate([art1, art2, art3, art1, art2])
    assert len(repeated) == 1
    assert len(repeated[0].all_sources) == 3

    # 3. Persistence into SQLite
    db1 = SQLiteDatabase(db_path=db_path)
    storage1 = StorageService(db=db1)
    to_proc, skipped, _ = storage1.check_and_register_articles(deduped)
    assert len(to_proc) == 1

    clusterer = StoryClusterer()
    clusters, _ = clusterer.cluster_articles(deduped)
    assert len(clusters) == 1
    storage1.persist_cluster_group(clusters[0])

    # 4. Restart recovery on clean connection
    db2 = SQLiteDatabase(db_path=db_path)
    storage2 = StorageService(db=db2)
    stored = db2.get_article_by_canonical_url(deduped[0].url)
    assert stored is not None
    assert set(stored.extra_metadata.get("all_sources", [])) == {"TechCrunch AI", "The Verge", "Ars Technica"}
    recovered_art = storage2.article_record_to_article(stored)
    assert set(recovered_art.all_sources) == {"TechCrunch AI", "The Verge", "Ars Technica"}

