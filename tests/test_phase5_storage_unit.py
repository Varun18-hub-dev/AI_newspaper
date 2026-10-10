"""Unit tests for Phase 5 SQLite persistent storage, schema versioning, and deduplication."""

from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
import pytest

from app.ingestion.models import Article
from app.clustering.models import StoryCluster
from app.storage.fingerprint import (
    compute_content_fingerprint,
    compute_story_fingerprint,
    generate_article_id,
    is_meaningful_update,
)
from app.storage.models import ArticleRecord, StoryClusterRecord
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase


@pytest.fixture
def mem_db():
    """Provides an isolated in-memory SQLite database instance for unit testing."""
    return SQLiteDatabase(db_path=":memory:")


@pytest.fixture
def tmp_db_path(tmp_path):
    """Provides a temporary file path for disk-based SQLite testing."""
    return str(tmp_path / "test_newspaper.db")


# =============================================================================
# 1. Database Initialization & Schema Versioning
# =============================================================================
def test_database_initialization_and_schema_versioning(mem_db):
    """Verify tables, indexes, and schema version are correctly initialized."""
    assert mem_db.get_schema_version() >= 1

    with mem_db.get_connection() as conn:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            ).fetchall()
        ]
        assert "schema_version" in tables
        assert "articles" in tables
        assert "story_clusters" in tables
        assert "cluster_members" in tables

        # Verify indexes exist
        indexes = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index';"
            ).fetchall()
        ]
        assert "idx_articles_canonical_url" in indexes
        assert "idx_articles_fingerprint" in indexes
        assert "idx_clusters_last_seen" in indexes


# =============================================================================
# 2. Article Insertion and Retrieval
# =============================================================================
def test_article_insertion_and_retrieval(mem_db):
    """Verify inserting and querying article records across multiple keys."""
    now = datetime.utcnow()
    pub = now - timedelta(hours=2)
    art_rec = ArticleRecord(
        id="art_12345",
        canonical_url="https://techcrunch.com/2026/10/09/gemini-ai-agent",
        original_url="https://techcrunch.com/2026/10/09/gemini-ai-agent?utm_source=rss",
        normalized_title="Google brings agentic AI to Gemini",
        source="TechCrunch",
        author="Tech Reporter",
        published_at=pub,
        first_seen_at=now,
        last_seen_at=now,
        content_fingerprint="fp_abcde123",
        processing_status="PENDING",
        domain="AI",
        extra_metadata={"description": "Gemini agent details"},
    )

    success = mem_db.insert_article(art_rec)
    assert success is True

    # Retrieval by ID
    by_id = mem_db.get_article_by_id("art_12345")
    assert by_id is not None
    assert by_id.canonical_url == art_rec.canonical_url
    assert by_id.normalized_title == art_rec.normalized_title
    assert by_id.source == "TechCrunch"

    # Retrieval by Canonical URL
    by_url = mem_db.get_article_by_canonical_url(art_rec.canonical_url)
    assert by_url is not None
    assert by_url.id == "art_12345"

    # Retrieval by Content Fingerprint
    by_fp = mem_db.get_article_by_fingerprint("fp_abcde123")
    assert by_fp is not None
    assert by_fp.id == "art_12345"

    # Retrieval by Title and Source
    by_title = mem_db.get_article_by_title_and_source(
        "Google brings agentic AI to Gemini", "TechCrunch"
    )
    assert by_title is not None
    assert by_title.id == "art_12345"


# =============================================================================
# 3. Canonical URL Uniqueness Enforced
# =============================================================================
def test_canonical_url_uniqueness_enforced(mem_db):
    """Verify that duplicate canonical URLs cannot be inserted."""
    now = datetime.utcnow()
    art_rec1 = ArticleRecord(
        id="art_001",
        canonical_url="https://theverge.com/ai-story",
        original_url="https://theverge.com/ai-story",
        normalized_title="AI Story Title",
        source="The Verge",
        first_seen_at=now,
        last_seen_at=now,
    )
    assert mem_db.insert_article(art_rec1) is True

    # Attempt second insert with same canonical URL but different ID
    art_rec2 = ArticleRecord(
        id="art_002",
        canonical_url="https://theverge.com/ai-story",
        original_url="https://theverge.com/ai-story?ref=news",
        normalized_title="AI Story Title Duplicate",
        source="The Verge",
        first_seen_at=now,
        last_seen_at=now,
    )
    assert mem_db.insert_article(art_rec2) is False


# =============================================================================
# 4. Idempotent Repeated Ingestion
# =============================================================================
def test_idempotent_repeated_ingestion(mem_db):
    """Verify that repeatedly ingesting identical articles updates timestamp without duplicates."""
    service = StorageService(db=mem_db)
    articles = [
        Article(
            title="OpenAI launches o1 reasoning model",
            url="https://techcrunch.com/2024/09/12/openai-o1",
            source="TechCrunch",
            description="OpenAI officially announced o1 model.",
        ),
        Article(
            title="Anthropic introduces Claude 3.5 Sonnet",
            url="https://theverge.com/2024/06/20/claude-35-sonnet",
            source="The Verge",
            description="Claude 3.5 Sonnet outperforms competitors.",
        ),
    ]

    # Ingestion 1
    to_proc_1, skipped_1, m1 = service.check_and_register_articles(articles)
    assert len(to_proc_1) == 2
    assert len(skipped_1) == 0
    assert m1.new_articles_persisted == 2

    # Mark the first article as processed/classified
    service.db.update_article_status(
        article_id=generate_article_id(articles[0].url),
        status="CLASSIFIED_RELEVANT",
        relevance_score=0.98,
        topic="LLMs",
    )

    # Ingestion 2 (Same feed items)
    to_proc_2, skipped_2, m2 = service.check_and_register_articles(articles)
    # Article 0 is now skipped; Article 1 was pending so it remains to_process
    assert len(skipped_2) == 1
    assert skipped_2[0].url == articles[0].url
    assert m2.previously_seen_recognized == 1
    assert m2.new_articles_persisted == 0


# =============================================================================
# 5. Transaction Rollback & Failure Safety
# =============================================================================
def test_transaction_rollback_failure_safety(mem_db):
    """Verify that atomic transactions roll back on exception without partial writes."""
    initial_count = mem_db.get_database_stats()["total_articles"]

    try:
        with mem_db.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO articles (id, canonical_url, original_url, normalized_title, source, first_seen_at, last_seen_at)
                VALUES ('art_valid', 'https://example.com/valid', 'https://example.com/valid', 'Valid Title', 'Src', '2026-10-09', '2026-10-09');
                """
            )
            # Intentionally trigger an error
            raise ValueError("Intentional simulated transaction failure!")
    except ValueError:
        pass

    # Verify art_valid was NOT committed
    after_count = mem_db.get_database_stats()["total_articles"]
    assert after_count == initial_count
    assert mem_db.get_article_by_id("art_valid") is None


# =============================================================================
# 6. Cluster Persistence, Membership, and Representative Selection
# =============================================================================
def test_cluster_persistence_membership_and_representative(mem_db):
    """Verify StoryCluster, members, and representative relationships are persisted."""
    service = StorageService(db=mem_db)

    art1 = Article(
        title="Google brings agentic AI to Gemini",
        url="https://techcrunch.com/gemini-agent",
        source="TechCrunch",
        description="Google launched agentic tools.",
    )
    art2 = Article(
        title="Google launches Gemini work agent",
        url="https://theverge.com/gemini-agent",
        source="The Verge",
        description="Gemini work agent unveiled.",
    )

    # Register articles first
    service.check_and_register_articles([art1, art2])

    cluster = StoryCluster(
        cluster_id="cluster_gemini_test",
        representative_article=art1,
        member_articles=[art1, art2],
        source_count=2,
        sources=["TechCrunch", "The Verge"],
        similarity_score=0.88,
    )

    service.persist_cluster_group(cluster)

    # Retrieve cluster
    cl_rec = service.db.get_cluster_by_id("cluster_gemini_test")
    assert cl_rec is not None
    assert cl_rec.representative_article_id == generate_article_id(art1.url)
    assert cl_rec.source_count == 2
    assert "TechCrunch" in cl_rec.sources
    assert "The Verge" in cl_rec.sources

    # Retrieve member records
    members = service.db.get_cluster_member_articles("cluster_gemini_test")
    assert len(members) == 2
    urls = {m.canonical_url for m in members}
    assert art1.url in urls
    assert art2.url in urls


# =============================================================================
# 7. Meaningful Update vs Redundant Repeats Detection
# =============================================================================
def test_meaningful_update_detection_vs_redundant_repeats():
    """Verify conservative policy distinguishes updates from redundant reporting."""
    base_art = Article(
        title="OpenAI announces preview of new reasoning model",
        url="https://tc.com/o1-preview",
        source="TechCrunch",
        description="OpenAI shared an early preview of its reasoning system.",
    )

    # 1. Explicit editorial marker in headline
    update_art = Article(
        title="Update: OpenAI confirmed full public launch of reasoning model",
        url="https://theverge.com/o1-update",
        source="The Verge",
        description="OpenAI confirmed the reasoning model is now live for everyone.",
    )
    is_up, reason = is_meaningful_update(
        old_article=base_art,
        new_article=update_art,
        time_diff_hours=12.0,
    )
    assert is_up is True
    assert "explicit update marker" in reason

    # 2. Substantial vocabulary expansion after 18 hours
    expanded_art = Article(
        title="OpenAI reasoning system benchmarks detailed with code execution and security audit",
        url="https://ars.com/o1-benchmarks",
        source="Ars Technica",
        description="Comprehensive technical deep-dive into mathematical performance, safety evals, latency profile, and jailbreak prevention.",
    )
    is_up_text, reason_text = is_meaningful_update(
        old_article=base_art,
        new_article=expanded_art,
        time_diff_hours=18.0,
        old_text=base_art.description,
        new_text=expanded_art.description,
        jaccard_threshold=0.30,
        time_threshold_hours=6.0,
    )
    assert is_up_text is True

    # 3. Redundant / duplicate coverage of same event
    redundant_art = Article(
        title="OpenAI announces preview of reasoning model for developers",
        url="https://reuters.com/o1-preview",
        source="Reuters",
        description="OpenAI shared an early preview of its reasoning system.",
    )
    is_up_red, reason_red = is_meaningful_update(
        old_article=base_art,
        new_article=redundant_art,
        time_diff_hours=2.0,
        old_text=base_art.description,
        new_text=redundant_art.description,
    )
    assert is_up_red is False
    assert "Redundant or duplicate coverage" in reason_red


# =============================================================================
# 8. Retry of Previously Failed Processing
# =============================================================================
def test_retry_of_previously_failed_processing(mem_db):
    """Verify that an article marked as FAILED in an earlier run is retried."""
    service = StorageService(db=mem_db)
    art = Article(
        title="DeepSeek releases open reasoning model DeepSeek-R1",
        url="https://hf.co/deepseek-ai/r1",
        source="HuggingFace",
        description="DeepSeek-R1 open weights available.",
    )

    to_proc, _, _ = service.check_and_register_articles([art])
    assert len(to_proc) == 1

    # Simulate network failure or timeout during LLM evaluation
    service.mark_article_failed(art, "Connection timed out during Ollama call")

    # In a subsequent run, same article is submitted
    to_proc_retry, skipped_retry, metrics = service.check_and_register_articles([art])
    assert len(to_proc_retry) == 1
    assert len(skipped_retry) == 0
    assert metrics.failed_articles_retried == 1


# =============================================================================
# 9. Application Restart & State Recovery
# =============================================================================
def test_restart_application_state_recovery(tmp_db_path):
    """Verify that persistent state survives application restarts across instances."""
    # Instance 1: Create DB and write records
    db1 = SQLiteDatabase(db_path=tmp_db_path)
    service1 = StorageService(db=db1)

    art = Article(
        title="Anthropic releases Claude 3.5 Sonnet",
        url="https://anthropic.com/sonnet",
        source="Anthropic",
        description="Claude 3.5 Sonnet is now available.",
    )
    service1.check_and_register_articles([art])
    service1.db.update_article_status(
        article_id=generate_article_id(art.url),
        status="CLASSIFIED_RELEVANT",
        relevance_score=0.99,
        topic="LLMs",
    )

    # Disconnect instance 1
    del service1
    del db1

    # Instance 2: Connect fresh instance to the same DB file
    db2 = SQLiteDatabase(db_path=tmp_db_path)
    service2 = StorageService(db=db2)

    stats = db2.get_database_stats()
    assert stats["total_articles"] == 1
    assert stats["classified_articles"] == 1

    retrieved = service2.db.get_article_by_canonical_url(art.url)
    assert retrieved is not None
    assert retrieved.normalized_title == art.title
    assert retrieved.processing_status == "CLASSIFIED_RELEVANT"
    assert retrieved.relevance_score == 0.99


# =============================================================================
# 10. Changed URLs: Source Attribution, Fingerprints & Cluster Membership
# =============================================================================
def test_changed_urls_preserves_source_attribution_and_cluster_membership(mem_db):
    """Verify that an article whose URL changed does not lose source attribution or cluster membership."""
    service = StorageService(db=mem_db)

    # Initial publication
    art_orig = Article(
        title="Google introduces enterprise agent in Gemini Workspace",
        url="https://techcrunch.com/2026/10/08/gemini-enterprise-agent",
        source="TechCrunch",
        description="Google introduced enterprise agent features in Workspace.",
        content="Google is introducing agentic capabilities in Gemini Workspace for business customers.",
    )
    to_proc, _, _ = service.check_and_register_articles([art_orig])
    assert len(to_proc) == 1
    art_id = generate_article_id(art_orig.url)

    # Associate with a cluster
    cluster = StoryCluster(
        cluster_id="cluster_tc_gemini",
        representative_article=art_orig,
        member_articles=[art_orig],
        sources=["TechCrunch"],
        source_count=1,
    )
    service.persist_cluster_group(cluster)
    service.db.update_article_status(
        article_id=art_id,
        status="CLASSIFIED_RELEVANT",
        relevance_score=0.96,
        topic="AI Agents",
    )

    # Later: Feed delivers the article with a changed URL slug on the same source
    art_changed_url = Article(
        title="Google introduces enterprise agent in Gemini Workspace",
        url="https://techcrunch.com/2026/10/08/gemini-enterprise-agent-updated-slug",
        source="TechCrunch",
        description="Google introduced enterprise agent features in Workspace.",
        content="Google is introducing agentic capabilities in Gemini Workspace for business customers.",
    )

    to_proc2, skipped2, m2 = service.check_and_register_articles([art_changed_url])

    # 1. Recognized as previously seen article
    assert len(skipped2) == 1
    assert m2.previously_seen_recognized == 1

    # 2. Canonical URL uniqueness: exactly 1 article record in database
    stats = mem_db.get_database_stats()
    assert stats["total_articles"] == 1

    # 3. Source attribution preserved
    stored_art = mem_db.get_article_by_id(art_id)
    assert stored_art is not None
    assert stored_art.source == "TechCrunch"

    # 4. Alternate URL tracked in metadata
    assert "alternate_urls" in stored_art.extra_metadata
    assert art_changed_url.url in stored_art.extra_metadata["alternate_urls"]

    # 5. Cluster membership preserved
    cluster_members = mem_db.get_cluster_member_articles("cluster_tc_gemini")
    assert len(cluster_members) == 1
    assert cluster_members[0].id == art_id
    assert cluster_members[0].source == "TechCrunch"
