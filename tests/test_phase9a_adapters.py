"""Unit and integration tests for Phase 9A Multi-Source News Ingestion Integration."""

from datetime import datetime, timedelta
import json
from unittest.mock import MagicMock, patch
import pytest

from app.core.config import settings
from app.domains.registry import DEFAULT_DOMAINS, get_domain_registry
from app.ingestion.adapters.arxiv import ArxivAdapter
from app.ingestion.adapters.github import GitHubAdapter
from app.ingestion.adapters.hackernews import HackerNewsAdapter
from app.ingestion.adapters.nvd import NVDAdapter
from app.ingestion.coordinator import MultiSourceDiscoveryCoordinator
from app.ingestion.models import Article
from app.processing.filtering import filter_and_deduplicate
from app.storage.models import ArticleRecord
from app.storage.service import StorageService
from app.storage.sqlite import SQLiteDatabase


# =============================================================================
# 1. arXiv Adapter Tests
# =============================================================================

ARXIV_ATOM_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>cs.AI updates on arXiv.org</title>
  <entry>
    <id>http://arxiv.org/abs/2610.01234v1</id>
    <title>Agentic Reasoning Frameworks for Multi-Domain Intelligence</title>
    <summary>Abstract: We introduce a novel agentic reasoning framework with self-reflection.</summary>
    <author>
      <name>Alice Smith</name>
    </author>
    <author>
      <name>Bob Jones</name>
    </author>
    <link rel="alternate" type="text/html" href="https://arxiv.org/abs/2610.01234"/>
    <published>2026-10-08T12:00:00Z</published>
    <updated>2026-10-08T12:00:00Z</updated>
  </entry>
</feed>
"""

ARXIV_RSS_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/"
         xmlns:dc="http://purl.org/dc/elements/1.1/">
  <channel>
    <title>physics.gen-ph updates on arXiv.org</title>
  </channel>
  <item>
    <title>Quantum Gravity Entanglement in Curved Spacetime</title>
    <link>https://arxiv.org/abs/2610.05678</link>
    <description>arXiv:2610.05678v1 Announce Type: new Abstract: Theoretical formulation of entanglement entropy.</description>
    <dc:creator>Dr. Elena Rostova</dc:creator>
    <dc:date>2026-10-09T08:00:00Z</dc:date>
  </item>
</rdf:RDF>
"""


def test_arxiv_atom_parsing():
    """Verify arXiv Atom XML parses title, abstract, authors, canonical URL, and domain."""
    adapter = ArxivAdapter()
    articles = adapter.parse_arxiv_xml(ARXIV_ATOM_XML, category="cs.AI")

    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Agentic Reasoning Frameworks for Multi-Domain Intelligence"
    assert art.url == "https://arxiv.org/abs/2610.01234"
    assert art.domain == "AI"
    assert art.source == "arXiv"
    assert "Alice Smith" in art.author
    assert "Bob Jones" in art.author
    assert art.raw_metadata["arxiv_id"] == "2610.01234"
    assert "novel agentic reasoning framework" in art.description


def test_arxiv_rss_parsing_and_domain_mapping():
    """Verify arXiv RSS parses physics paper and maps to Science domain."""
    adapter = ArxivAdapter()
    articles = adapter.parse_arxiv_xml(ARXIV_RSS_XML, category="physics.gen-ph")

    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Quantum Gravity Entanglement in Curved Spacetime"
    assert art.url == "https://arxiv.org/abs/2610.05678"
    assert art.domain == "Science"
    assert art.author == "Dr. Elena Rostova"
    assert art.raw_metadata["arxiv_id"] == "2610.05678"
    assert "Theoretical formulation" in art.description


def test_arxiv_malformed_xml_handling():
    """Verify malformed XML returns an empty list without raising."""
    adapter = ArxivAdapter()
    articles = adapter.parse_arxiv_xml(b"<invalid><broken xml", category="cs.AI")
    assert articles == []


def test_arxiv_http_failure_fault_isolation():
    """Verify arXiv network failure is handled gracefully with error status in telemetry."""
    adapter = ArxivAdapter(categories=["cs.AI"])
    with patch.object(adapter.session, "get", side_effect=Exception("Connection refused")):
        articles, telemetry = adapter.fetch()
        assert articles == []
        assert telemetry["status"] == "FAILED"
        assert "Connection refused" in telemetry["error"]


# =============================================================================
# 2. Hacker News Adapter Tests
# =============================================================================

def test_hackernews_item_parsing_and_score_filtering():
    """Verify Hacker News parses story, filters by score, and maps domains."""
    adapter = HackerNewsAdapter(min_score=50, lookback_hours=72.0)

    # High score story with external link
    item_high = {
        "id": 1001,
        "type": "story",
        "title": "OpenAI Releases New Frontier Agent Architecture",
        "url": "https://example.com/openai-frontier-agent",
        "score": 120,
        "by": "dang",
        "time": int(datetime.utcnow().timestamp()) - 3600,
        "descendants": 45,
    }

    # Low score story
    item_low = {
        "id": 1002,
        "type": "story",
        "title": "My personal website redesign",
        "url": "https://example.com/blog",
        "score": 15,
        "by": "user123",
        "time": int(datetime.utcnow().timestamp()) - 3600,
        "descendants": 2,
    }

    art_high = adapter.parse_hn_item(item_high)
    art_low = adapter.parse_hn_item(item_low)

    assert art_high is not None
    assert art_high.title == "OpenAI Releases New Frontier Agent Architecture"
    assert art_high.url == "https://example.com/openai-frontier-agent"
    assert art_high.domain == "AI"  # Keyword matched
    assert art_high.source == "Hacker News"
    assert art_high.raw_metadata["score"] == 120
    assert art_high.raw_metadata["hn_id"] == 1001

    # Low score is rejected
    assert art_low is None


def test_hackernews_internal_discussion_fallback():
    """Verify Ask HN / Show HN without external URL falls back to news.ycombinator.com link."""
    adapter = HackerNewsAdapter(min_score=10)
    item_ask_hn = {
        "id": 2002,
        "type": "story",
        "title": "Ask HN: What cybersecurity tools do you use in 2026?",
        "text": "Looking for recommendations on vulnerability scanners.",
        "score": 85,
        "by": "sec_researcher",
        "time": int(datetime.utcnow().timestamp()) - 1800,
        "descendants": 60,
    }

    art = adapter.parse_hn_item(item_ask_hn)
    assert art is not None
    assert art.url == "https://news.ycombinator.com/item?id=2002"
    assert art.domain == "Cybersecurity"
    assert "Looking for recommendations" in art.description


def test_hackernews_fetch_mocked_flow():
    """Verify fetch retrieves top stories and individual items."""
    adapter = HackerNewsAdapter(min_score=20, max_items=2)
    mock_ids_resp = MagicMock()
    mock_ids_resp.status_code = 200
    mock_ids_resp.json.return_value = [3001, 3002]

    mock_item_resp = MagicMock()
    mock_item_resp.status_code = 200
    mock_item_resp.json.return_value = {
        "id": 3001,
        "type": "story",
        "title": "Major Startup Funding Announced in Silicon Valley",
        "url": "https://techfunding.com/announcement",
        "score": 90,
        "by": "vc_watcher",
        "time": int(datetime.utcnow().timestamp()) - 1000,
    }

    with patch.object(adapter.session, "get") as mock_get:
        mock_get.side_effect = [mock_ids_resp, mock_item_resp, mock_item_resp]
        articles, telemetry = adapter.fetch()
        assert len(articles) >= 1
        assert telemetry["status"] == "SUCCESS"
        assert articles[0].domain == "Business and startups"


# =============================================================================
# 3. GitHub Adapter Tests
# =============================================================================

def test_github_repo_parsing_and_stars_filter():
    """Verify GitHub repository item parses correctly and respects star threshold."""
    adapter = GitHubAdapter(min_stars=500)

    repo_data = {
        "full_name": "vllm-project/vllm",
        "html_url": "https://github.com/vllm-project/vllm",
        "stargazers_count": 32000,
        "forks_count": 4500,
        "description": "High-throughput and memory-efficient LLM serving engine",
        "language": "Python",
        "topics": ["llm", "machine-learning", "serving"],
        "owner": {"login": "vllm-project"},
        "pushed_at": "2026-10-09T15:30:00Z",
    }

    art = adapter.parse_repo_item(repo_data)
    assert art is not None
    assert "vllm-project/vllm" in art.title
    assert art.url == "https://github.com/vllm-project/vllm"
    assert art.domain == "AI"
    assert art.source == "GitHub"
    assert art.author == "vllm-project"
    assert art.raw_metadata["stars"] == 32000
    assert "Stars: 32,000" in art.description

    # Low stars repo rejected
    repo_low = dict(repo_data, stargazers_count=50)
    assert adapter.parse_repo_item(repo_low) is None


def test_github_rate_limiting_handled_gracefully():
    """Verify HTTP 403 / 429 rate limit is handled without exception and marked RATE_LIMITED."""
    adapter = GitHubAdapter()
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.headers = {"X-RateLimit-Reset": "1790000000"}

    with patch.object(adapter.session, "get", return_value=mock_resp):
        articles, telemetry = adapter.fetch()
        assert articles == []
        assert telemetry["status"] == "RATE_LIMITED"
        assert "rate limit reached" in telemetry["error"]


def test_github_token_authentication_header():
    """Verify optional GITHUB_TOKEN is passed in Authorization header."""
    adapter = GitHubAdapter(token="ghp_testtoken12345")
    assert adapter.session.headers.get("Authorization") == "Bearer ghp_testtoken12345"


# =============================================================================
# 4. NVD Adapter Tests
# =============================================================================

def test_nvd_cve_parsing_and_cvss_severity():
    """Verify NVD CVE item parses ID, CVSS score, severity, and canonical URL."""
    adapter = NVDAdapter()

    cve_data = {
        "cve": {
            "id": "CVE-2026-9999",
            "sourceIdentifier": "cve@mitre.org",
            "published": "2026-10-09T04:15:00.000",
            "vulnStatus": "Analyzed",
            "descriptions": [
                {
                    "lang": "en",
                    "value": "Buffer overflow in OpenSSH server allows remote unauthenticated code execution.",
                }
            ],
            "metrics": {
                "cvssMetricV31": [
                    {
                        "cvssData": {
                            "baseScore": 9.8,
                            "baseSeverity": "CRITICAL",
                        }
                    }
                ]
            },
        }
    }

    art = adapter.parse_cve_item(cve_data)
    assert art is not None
    assert "CVE-2026-9999 (CVSS 9.8 CRITICAL)" in art.title
    assert art.url == "https://nvd.nist.gov/vuln/detail/CVE-2026-9999"
    assert art.domain == "Cybersecurity"
    assert art.source == "NVD"
    assert art.author == "cve@mitre.org"
    assert art.raw_metadata["cvss_score"] == 9.8
    assert art.raw_metadata["cvss_severity"] == "CRITICAL"
    assert "[CVSS 9.8 CRITICAL]" in art.description


def test_nvd_domain_filter_skips_non_cybersecurity():
    """Verify NVD adapter skips fetching when non-cybersecurity domain is requested."""
    adapter = NVDAdapter()
    articles, telemetry = adapter.fetch(domain="AI")
    assert articles == []
    assert telemetry["status"] == "SKIPPED_DOMAIN"


def test_nvd_api_key_header():
    """Verify optional NVD_API_KEY is passed in apiKey header."""
    adapter = NVDAdapter(api_key="test-nvd-api-key-12345")
    assert adapter.session.headers.get("apiKey") == "test-nvd-api-key-12345"


# =============================================================================
# 5. Publisher Feeds & Domain Coverage
# =============================================================================

def test_all_23_configured_feeds_preserve_original_17():
    """Verify registry contains 23 total feeds, preserving all 17 original feeds intact."""
    registry = get_domain_registry()
    all_domains = registry.list_domains()

    total_feeds = sum(len(d.feeds) for d in all_domains)
    assert total_feeds == 23, f"Expected 23 total feeds across domains, got {total_feeds}"

    # Verify original 17 feeds exist
    expected_original_urls = [
        "https://techcrunch.com/category/artificial-intelligence/feed/",
        "https://theverge.com/rss/ai-artificial-intelligence/index.xml",
        "https://huggingface.co/blog/feed.xml",
        "https://feeds.arstechnica.com/arstechnica/technology-lab",
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://theverge.com/rss/index.xml",
        "https://techcrunch.com/feed/",
        "https://feeds.arstechnica.com/arstechnica/science",
        "https://phys.org/rss-feed/",
        "https://www.sciencedaily.com/rss/top/science.xml",
        "https://krebsonsecurity.com/feed/",
        "https://www.darkreading.com/rss.xml",
        "https://feeds.feedburner.com/TheHackersNews",
        "https://www.schneier.com/feed/atom/",
        "https://techcrunch.com/category/startups/feed/",
        "https://venturebeat.com/category/business/feed/",
        "https://feeds.arstechnica.com/arstechnica/tech-policy",
    ]

    all_configured_urls = [f.url for d in all_domains for f in d.feeds]
    for url in expected_original_urls:
        assert url in all_configured_urls, f"Original feed missing: {url}"

    # Verify 6 validated additions exist
    added_urls = [
        "https://bair.berkeley.edu/blog/feed.xml",
        "https://www.nature.com/nature.rss",
        "https://www.quantamagazine.org/feed/",
        "https://www.bleepingcomputer.com/feed/",
        "https://www.securityweek.com/feed/",
        "https://siliconangle.com/feed/",
    ]
    for url in added_urls:
        assert url in all_configured_urls, f"Added feed missing: {url}"


# =============================================================================
# 6. Multi-Source Discovery Coordinator & Fault Isolation
# =============================================================================

def test_coordinator_fault_isolation_partial_failures():
    """Verify coordinator collects articles from healthy sources even when others fail."""
    mock_rss = MagicMock()
    mock_rss.fetch_all_domains.return_value = (
        [Article(title="RSS Article 1", url="https://rss.com/1", source="TechCrunch", domain="Technology")],
        {"https://rss.com/feed": {"status": "SUCCESS"}},
    )

    mock_arxiv = MagicMock()
    mock_arxiv.name = "arXiv"
    mock_arxiv.enabled = True
    mock_arxiv.fetch.side_effect = Exception("arXiv service timeout")

    mock_hn = MagicMock()
    mock_hn.name = "Hacker News"
    mock_hn.enabled = True
    mock_hn.fetch.return_value = (
        [Article(title="HN Article 1", url="https://hn.com/1", source="Hacker News", domain="AI")],
        {"status": "SUCCESS", "count": 1},
    )

    mock_github = MagicMock()
    mock_github.name = "GitHub"
    mock_github.enabled = True
    mock_github.fetch.return_value = (
        [],
        {"status": "RATE_LIMITED", "count": 0, "error": "rate limit reached"},
    )

    mock_nvd = MagicMock()
    mock_nvd.name = "NVD"
    mock_nvd.enabled = True
    mock_nvd.fetch.return_value = (
        [Article(title="CVE-2026-1111: Critical Bug", url="https://nvd.nist.gov/vuln/detail/CVE-2026-1111", source="NVD", domain="Cybersecurity")],
        {"status": "SUCCESS", "count": 1},
    )

    coordinator = MultiSourceDiscoveryCoordinator(
        rss_connector=mock_rss,
        arxiv_adapter=mock_arxiv,
        hn_adapter=mock_hn,
        github_adapter=mock_github,
        nvd_adapter=mock_nvd,
    )

    articles, statuses = coordinator.discover_all()

    # RSS (1) + HN (1) + NVD (1) = 3 articles
    assert len(articles) == 3
    assert statuses["arxiv"]["status"] == "FAILED"
    assert statuses["github"]["status"] == "RATE_LIMITED"
    assert statuses["hacker_news"]["status"] == "SUCCESS"
    assert statuses["nvd"]["status"] == "SUCCESS"


def test_coordinator_source_disabled_switch():
    """Verify disabled adapters are skipped without network calls."""
    mock_arxiv = MagicMock()
    mock_arxiv.name = "arXiv"
    mock_arxiv.enabled = False

    coordinator = MultiSourceDiscoveryCoordinator(
        arxiv_adapter=mock_arxiv,
        hn_adapter=MagicMock(name="Hacker News", enabled=False),
        github_adapter=MagicMock(name="GitHub", enabled=False),
        nvd_adapter=MagicMock(name="NVD", enabled=False),
    )

    articles, statuses = coordinator.discover_all(domains=["AI"])
    assert statuses["arxiv"]["status"] == "DISABLED"
    mock_arxiv.fetch.assert_not_called()


# =============================================================================
# 7. Cross-Source Deduplication & Multi-Source Attribution
# =============================================================================

def test_cross_source_deduplication_rss_and_hackernews():
    """Verify story syndicated across RSS and Hacker News retains single canonical article with both sources."""
    shared_url = "https://example.com/deepseek-breakthrough"

    rss_art = Article(
        title="DeepSeek Unveils New Open Reasoning Weights",
        url=f"{shared_url}?utm_source=rss",
        source="TechCrunch AI",
        domain="AI",
    )

    hn_art = Article(
        title="DeepSeek Unveils New Open Reasoning Weights (HN Discussion)",
        url=f"{shared_url}?ref=hackernews",
        source="Hacker News",
        domain="AI",
        raw_metadata={"score": 350},
    )

    deduped = filter_and_deduplicate([rss_art, hn_art])
    assert len(deduped) == 1
    assert "TechCrunch AI" in deduped[0].all_sources
    assert "Hacker News" in deduped[0].all_sources


# =============================================================================
# 8. SQLite Storage & Extra Metadata Persistence
# =============================================================================

def test_sqlite_persistence_preserves_source_raw_metadata():
    """Verify multi-source raw_metadata (CVE ID, HN score, arXiv paper) is persisted in SQLite."""
    mem_db = SQLiteDatabase(db_path=":memory:")
    service = StorageService(db=mem_db)

    cve_art = Article(
        title="CVE-2026-5555 (CVSS 9.1 CRITICAL): Critical OpenSSL Flaw",
        url="https://nvd.nist.gov/vuln/detail/CVE-2026-5555",
        source="NVD",
        domain="Cybersecurity",
        description="Critical buffer overflow vulnerability.",
        raw_metadata={
            "cve_id": "CVE-2026-5555",
            "cvss_score": 9.1,
            "cvss_severity": "CRITICAL",
        },
    )

    to_process, skipped, metrics = service.check_and_register_articles([cve_art])
    assert len(to_process) == 1
    assert metrics.new_articles_persisted == 1

    # Verify extra_metadata stored in DB
    rec = mem_db.get_article_by_canonical_url(cve_art.url)
    assert rec is not None
    assert rec.extra_metadata.get("cve_id") == "CVE-2026-5555"
    assert rec.extra_metadata.get("cvss_score") == 9.1
    assert rec.extra_metadata.get("cvss_severity") == "CRITICAL"

    # Verify round-trip conversion back to Article model
    restored = service.article_record_to_article(rec)
    assert restored.raw_metadata.get("cve_id") == "CVE-2026-5555"
    assert restored.domain == "Cybersecurity"
