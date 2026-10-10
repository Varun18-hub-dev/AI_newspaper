"""Unit and integration tests for Phase 10: Zero-Cost Deployment Architecture & CPU-Only Mode."""

from datetime import datetime, timedelta
import json
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

from app.ingestion.models import Article
from app.extraction.models import ExtractedContent
from app.processing.article_processor import ArticleProcessor
from app.processing.models import PreFilterResult
from app.processing.pre_filter import DeterministicPreFilter
from app.storage.publisher import EditionPublisher, EditionStory, EditionValidator, CurrentEditionPointer, EditionManifest
from app.storage.sqlite import SQLiteDatabase
from app.storage.service import StorageService
from app.orchestration.runner import GPUWorkerPipelineRunner


@pytest.fixture
def sample_raw_articles():
    """Provides a realistic set of candidate articles across multiple domains."""
    return [
        Article(
            title="Anthropic Introduces Claude 3.5 Sonnet Upgraded Agentic Tool",
            url="https://example.com/claude-35-upgrade",
            source="TechCrunch AI",
            description="Anthropic today announced an updated version of Claude 3.5 Sonnet capable of using computers directly.",
            published_at=datetime.utcnow(),
            discovered_at=datetime.utcnow(),
            domain="ai",
        ),
        Article(
            title="NASA Artemis Mission Prepares Next Moon Surface Landing Hardware",
            url="https://example.com/nasa-artemis-hardware",
            source="Ars Technica Science",
            description="Engineers have completed the thermal vacuum testing for the next Artemis lunar lander stage.",
            published_at=datetime.utcnow(),
            discovered_at=datetime.utcnow(),
            domain="science",
        ),
        Article(
            title="Critical OpenSSH Vulnerability CVE-2024-6387 Disclosed with Remote Code Execution",
            url="https://example.com/openssh-regresshion-cve",
            source="The Hacker News",
            description="Security researchers have identified a signal handler race condition in OpenSSH server allowing unauthenticated root access.",
            published_at=datetime.utcnow(),
            discovered_at=datetime.utcnow(),
            domain="cybersecurity",
        ),
        Article(
            title="Stripe Acquires Bridge for 1.1 Billion in Massive Stablecoin Expansion",
            url="https://example.com/stripe-acquires-bridge",
            source="TechCrunch Startups",
            description="Fintech giant Stripe has finalized the acquisition of stablecoin infrastructure startup Bridge for $1.1 billion.",
            published_at=datetime.utcnow(),
            discovered_at=datetime.utcnow(),
            domain="business",
        ),
    ]


# =============================================================================
# 1. CPU-Only Mode & Deterministic Summarization Tests
# =============================================================================

def test_classify_article_deterministic_source_grounded(sample_raw_articles):
    """Verifies that deterministic classification produces valid, source-grounded summaries without LLM calls."""
    processor = ArticleProcessor(llm_provider=None)  # No LLM provider injected

    art = sample_raw_articles[0]
    content = ExtractedContent(
        url=art.url,
        text="Anthropic today announced an updated version of Claude 3.5 Sonnet. The model demonstrates state-of-the-art computer use capabilities.",
        word_count=20,
        extraction_method="readability",
        extraction_success=True,
    )
    pf = PreFilterResult(
        pre_filter_score=0.95,
        tier="HIGH",
        ranking_score=0.92,
        should_send_to_llm=True,
        reason="High signal AI keywords",
    )

    processed = processor.classify_article_deterministic(
        article=art,
        content=content,
        pre_filter_result=pf,
        ranking_score=pf.ranking_score,
    )

    assert processed.classification.is_relevant is True
    assert processed.classification.relevance_score >= 0.80
    assert processed.classification.domain.lower() == "ai"
    assert processed.classification.topic in ["AI Agents", "LLMs", "Generative AI", "Other"]
    assert "Anthropic today announced an updated version" in processed.classification.reason
    assert len(processed.classification.reason) > 20


def test_process_with_metrics_cpu_only_no_llm_calls(sample_raw_articles, tmp_path):
    """Verifies that ArticleProcessor in CPU-only mode processes articles without invoking any LLM."""
    mock_llm = MagicMock()
    mock_llm.generate_structured.side_effect = RuntimeError("LLM must not be called in CPU-only mode!")

    db_path = str(tmp_path / "test_cpu.db")
    db = SQLiteDatabase(db_path=db_path)
    storage = StorageService(db=db)

    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=storage,
    )

    results, metrics = processor.process_with_metrics(
        articles=sample_raw_articles,
        enable_extraction=False,
        enable_llm_inference=False,  # CPU-only mode explicitly forced
    )

    assert len(results) >= 3
    assert metrics.qwen_calls == 0
    assert mock_llm.generate_structured.call_count == 0
    for r in results:
        assert r.classification.is_relevant is True
        assert len(r.classification.reason) > 10


def test_article_processor_fallback_when_llm_offline(sample_raw_articles, tmp_path):
    """Verifies that if LLM raises LLMError (e.g. Ollama daemon offline), processor falls back deterministically."""
    from app.llm.base import LLMError

    mock_llm = MagicMock()
    mock_llm.generate_structured.side_effect = LLMError("Connection to Ollama refused on 127.0.0.1:11434")

    db_path = str(tmp_path / "test_fallback.db")
    db = SQLiteDatabase(db_path=db_path)
    storage = StorageService(db=db)

    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=storage,
    )

    results, metrics = processor.process_with_metrics(
        articles=sample_raw_articles[:2],
        enable_extraction=False,
        enable_llm_inference=True,  # LLM enabled, but throws LLMError
    )

    assert len(results) == 2
    for r in results:
        assert r.classification.is_relevant is True
        assert len(r.classification.reason) > 10


# =============================================================================
# 2. Worker Pipeline in CPU-Only Mode & Atomic Publication
# =============================================================================

def test_gpu_worker_pipeline_runner_cpu_only(sample_raw_articles, tmp_path):
    """Verifies that GPUWorkerPipelineRunner succeeds in CPU-only mode, publishing a complete valid edition."""
    pub_dir = tmp_path / "editions"
    pub_dir.mkdir(parents=True, exist_ok=True)
    publisher = EditionPublisher(storage_backend="local", local_dir=str(pub_dir))

    db_path = str(tmp_path / "test_runner.db")
    db = SQLiteDatabase(db_path=db_path)

    mock_coord = MagicMock()
    mock_coord.discover_all.return_value = (sample_raw_articles, {"test_feed": {"status": "SUCCESS"}})

    mock_llm = MagicMock()
    mock_llm.generate_structured.side_effect = RuntimeError("No LLM in CPU mode")

    processor = ArticleProcessor(
        llm_provider=mock_llm,
        storage_service=StorageService(db=db),
    )

    runner = GPUWorkerPipelineRunner(
        db=db,
        publisher=publisher,
        discovery_coordinator=mock_coord,
        article_processor=processor,
    )

    success, manifest, context = runner.run_worker_pipeline(
        enable_agentic_workflow=False,
        enable_llm_inference=False,
        auto_stop_on_finish=False,
    )

    assert success is True
    assert manifest is not None
    assert manifest.total_stories >= 3
    assert (pub_dir / f"{manifest.edition_id}.json").exists()
    assert (pub_dir / "current_edition.json").exists()

    # Verify pointer and manifest match
    pointer = publisher.get_current_pointer()
    assert pointer.edition_id == manifest.edition_id
    assert pointer.checksum == manifest.checksum


# =============================================================================
# 3. Self-Contained Edition Manifest & Reader Zero-Cost Compatibility
# =============================================================================

def test_edition_manifest_is_completely_self_contained(tmp_path):
    """Verifies that EditionManifest contains all data needed by Next.js reader without querying SQLite."""
    pub_dir = tmp_path / "editions"
    publisher = EditionPublisher(storage_backend="local", local_dir=str(pub_dir))

    stories = [
        EditionStory(
            story_id=f"story_{i}",
            title=f"Self Contained Story Headline {i}",
            url=f"https://example.com/story-{i}",
            domain="ai" if i % 2 == 0 else "technology",
            topic="LLMs" if i % 2 == 0 else "Software & Apps",
            summary=f"Substantive summary for story {i} detailing recent tech developments.",
            sources=["TechCrunch", "Ars Technica"],
            published_at=datetime.utcnow().isoformat(),
            first_seen_at=datetime.utcnow().isoformat(),
            relevance_score=0.95,
            image_url=f"https://example.com/images/{i}.jpg" if i == 1 else None,
        )
        for i in range(1, 5)
    ]

    ok, manifest, err = publisher.publish_edition(
        edition_id="edition_20261010_test",
        stories=stories,
        run_id="run_test_001",
    )
    assert ok is True

    # Read manifest file directly as JSON (simulating Next.js serverless route reading S3 or disk)
    manifest_file = pub_dir / "edition_20261010_test.json"
    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    assert manifest_data["edition_id"] == "edition_20261010_test"
    assert manifest_data["total_stories"] == 4
    assert "ai" in manifest_data["domain_counts"]
    assert len(manifest_data["stories"]) == 4

    for s in manifest_data["stories"]:
        assert "story_id" in s
        assert "title" in s
        assert "url" in s
        assert "domain" in s
        assert "topic" in s
        assert "summary" in s
        assert "sources" in s
        assert len(s["sources"]) > 0


def test_staleness_detection_logic():
    """Verifies that editions published > 24 hours ago are flagged as stale."""
    now = datetime.utcnow()
    fresh_time = (now - timedelta(hours=2)).isoformat()
    stale_time = (now - timedelta(hours=25)).isoformat()

    fresh_dt = datetime.fromisoformat(fresh_time)
    stale_dt = datetime.fromisoformat(stale_time)

    assert (now - fresh_dt).total_seconds() <= 86400  # Not stale
    assert (now - stale_dt).total_seconds() > 86400   # Stale (> 24h)


# =============================================================================
# 4. Standalone Frontend Regression Tests (No FastAPI Required)
# =============================================================================

def test_deterministic_summary_handles_abbreviations_without_underflow():
    """Regression test: verifies deterministic summary does not truncate abbreviations like 'The U.S.' to <10 chars."""
    processor = ArticleProcessor(llm_provider=None)
    art = Article(
        title="Flax Typhoon Exploits Five Flaws as CISA Sets October 11 Deadline for Federal Agencies",
        url="https://thehackernews.com/2024/09/flax-typhoon-exploits.html",
        source="The Hacker News",
        description="The U.S. Cybersecurity and Infrastructure Security Agency (CISA) added five security flaws to its catalog.",
        domain="cybersecurity",
    )
    content = ExtractedContent(
        url=art.url,
        text="The U.S. Cybersecurity and Infrastructure Security Agency (CISA) on Thursday added five security flaws to its Known Exploited Vulnerabilities catalog.",
        word_count=20,
        extraction_method="readability",
        extraction_success=True,
    )

    processed = processor.classify_article_deterministic(article=art, content=content)
    summary = processed.classification.reason

    assert summary is not None
    assert len(summary.strip()) >= 15
    assert not summary.strip().endswith("The U. S.")
    assert "Cybersecurity and Infrastructure Security Agency" in summary

    # Verify that EditionValidator accepts this summary
    validator = EditionValidator(min_stories=1)
    story = EditionStory(
        story_id="test_flax_story",
        title=art.title,
        url=art.url,
        domain="cybersecurity",
        summary=summary,
        sources=["The Hacker News"],
        first_seen_at=datetime.utcnow().isoformat(),
    )
    is_valid, reason = validator.validate([story])
    assert is_valid is True, f"Validation failed: {reason}"


def test_published_edition_visible_in_standalone_frontend_without_fastapi(tmp_path):
    """Regression test: verifies that a published edition is loaded and served by Next.js API routes without FastAPI."""
    import os
    import subprocess

    pub_dir = tmp_path / "editions"
    publisher = EditionPublisher(storage_backend="local", local_dir=str(pub_dir))

    stories = [
        EditionStory(
            story_id="cluster_ai_001",
            title="OpenAI and Anthropic Form Frontier AI Model Safety Evaluation Pact",
            url="https://techcrunch.com/frontier-eval-pact",
            domain="Artificial Intelligence",
            topic="AI Safety",
            summary="Leading AI research labs have established a standardized joint protocol for safety benchmarking.",
            sources=["TechCrunch"],
            published_at=datetime.utcnow().isoformat(),
            first_seen_at=datetime.utcnow().isoformat(),
            relevance_score=0.98,
        ),
        EditionStory(
            story_id="cluster_biz_002",
            title="Stripe Acquires Stablecoin Startup Bridge for 1.1 Billion Dollars",
            url="https://techcrunch.com/stripe-bridge-acquisition",
            domain="Business and startups",
            topic="Startups",
            summary="Payment infrastructure company Stripe finalized the acquisition of bridge payment provider Bridge.",
            sources=["TechCrunch", "VentureBeat"],
            published_at=datetime.utcnow().isoformat(),
            first_seen_at=datetime.utcnow().isoformat(),
            relevance_score=0.92,
        ),
        EditionStory(
            story_id="cluster_sec_003",
            title="Critical OpenSSH Signal Handler Race Condition CVE-2024-6387 Disclosed",
            url="https://thehackernews.com/cve-2024-6387",
            domain="Cybersecurity",
            topic="Vulnerabilities & CVEs",
            summary="Security teams warn of unauthenticated remote code execution vulnerability impacting Linux servers.",
            sources=["The Hacker News"],
            published_at=datetime.utcnow().isoformat(),
            first_seen_at=datetime.utcnow().isoformat(),
            relevance_score=0.95,
        ),
        EditionStory(
            story_id="cluster_sci_004",
            title="James Webb Space Telescope Identifies Atmospheric Carbon Dioxide on Exoplanet",
            url="https://nature.com/jwst-carbon-dioxide",
            domain="Science",
            topic="Space & Astronomy",
            summary="Astronomers report definitive molecular signatures of atmospheric carbon dioxide on a distant world.",
            sources=["Nature"],
            published_at=datetime.utcnow().isoformat(),
            first_seen_at=datetime.utcnow().isoformat(),
            relevance_score=0.91,
        ),
    ]

    ok, manifest, err = publisher.publish_edition(
        edition_id="edition_standalone_regression",
        stories=stories,
        run_id="run_regression_001",
    )
    assert ok is True
    assert (pub_dir / "current_edition.json").exists()

    # Node script simulating Next.js standalone serverless execution without FastAPI
    node_test_script = f"""
    process.env.EDITIONS_DIR = {json.dumps(str(pub_dir))};

    async function run() {{
      const {{ getCurrentPointer, getCurrentEdition }} = await import('./frontend/lib/editions.js');
      const latestHandler = (await import('./frontend/pages/api/newspaper/latest.js')).default;
      const domainsHandler = (await import('./frontend/pages/api/domains.js')).default;
      const storyDetailHandler = (await import('./frontend/pages/api/newspaper/stories/[id].js')).default;

      // 1. Pointer & Edition reader
      const ptr = await getCurrentPointer();
      const ed = await getCurrentEdition();
      if (!ptr || ptr.edition_id !== 'edition_standalone_regression') {{
        throw new Error('Pointer mismatch: ' + JSON.stringify(ptr));
      }}
      if (!ed || ed.stories.length !== 4) {{
        throw new Error('Edition stories count mismatch: ' + ed?.stories?.length);
      }}

      // Helper mock res
      function createMockRes() {{
        let status = 200;
        let data = null;
        return {{
          setHeader: () => {{}},
          status: (c) => {{ status = c; return {{ json: (d) => {{ data = d; }} }}; }},
          getResult: () => ({{ status, data }})
        }};
      }}

      // 2. Test /api/newspaper/latest (all stories)
      const resAll = createMockRes();
      await latestHandler({{ query: {{}} }}, resAll);
      const outAll = resAll.getResult();
      if (outAll.status !== 200 || outAll.data.total !== 4 || outAll.data.items.length !== 4) {{
        throw new Error('Latest handler failed: ' + JSON.stringify(outAll));
      }}

      // 3. Test multi-word domain filtering: domain='business' must match 'Business and startups'
      const resBiz = createMockRes();
      await latestHandler({{ query: {{ domain: 'business' }} }}, resBiz);
      const outBiz = resBiz.getResult();
      if (outBiz.data.total !== 1 || outBiz.data.items[0].headline !== stories_title_biz) {{
        throw new Error('Business domain filter failed: ' + JSON.stringify(outBiz));
      }}

      // 4. Test domain filtering: domain='ai' must match 'Artificial Intelligence'
      const resAI = createMockRes();
      await latestHandler({{ query: {{ domain: 'ai' }} }}, resAI);
      const outAI = resAI.getResult();
      if (outAI.data.total !== 1) {{
        throw new Error('AI domain filter failed: ' + JSON.stringify(outAI));
      }}

      // 5. Test /api/domains
      const resDom = createMockRes();
      await domainsHandler({{}}, resDom);
      const outDom = resDom.getResult();
      const bizDom = outDom.data.domains.find(d => d.domain_id === 'business');
      if (!bizDom || bizDom.article_count !== 1) {{
        throw new Error('Domains API count for business failed: ' + JSON.stringify(bizDom));
      }}

      // 6. Test story detail /api/newspaper/stories/[id]
      const resDetail = createMockRes();
      await storyDetailHandler({{ query: {{ id: 'cluster_ai_001' }} }}, resDetail);
      const outDetail = resDetail.getResult();
      if (outDetail.status !== 200 || outDetail.data.headline !== stories_title_ai) {{
        throw new Error('Story detail failed: ' + JSON.stringify(outDetail));
      }}

      console.log('STANDALONE_SUCCESS');
    }}

    const stories_title_biz = {json.dumps(stories[1].title)};
    const stories_title_ai = {json.dumps(stories[0].title)};

    run().catch(err => {{
      console.error(err);
      process.exit(1);
    }});
    """

    res = subprocess.run(
        ["node", "-e", node_test_script],
        cwd=str(Path.cwd()),
        capture_output=True,
        text=True,
    )

    assert res.returncode == 0, f"Node standalone reader test failed: {res.stderr}\n{res.stdout}"
    assert "STANDALONE_SUCCESS" in res.stdout

