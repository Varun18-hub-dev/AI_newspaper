"""Phase 10 — Verification of Image Metadata Extraction and Propagation."""

import xml.etree.ElementTree as ET
from app.ingestion.rss import _extract_image_url, RSSConnector
from app.extraction.extractor import ContentExtractor
from app.storage.publisher import EditionStory
from app.api.models import NewspaperStoryResponse


def test_extract_image_from_rss_enclosure():
    """Verify _extract_image_url extracts image URL from <enclosure> element."""
    xml_str = """
    <item>
      <title>Robotics Breakthrough</title>
      <enclosure url="https://images.example.com/robot.jpg" type="image/jpeg" length="12345" />
    </item>
    """
    elem = ET.fromstring(xml_str)
    img_url = _extract_image_url(elem)
    assert img_url == "https://images.example.com/robot.jpg"


def test_extract_image_from_media_content():
    """Verify _extract_image_url extracts image URL from Yahoo Media RSS tag."""
    xml_str = """
    <item xmlns:media="http://search.yahoo.com/mrss/">
      <title>Quantum Computing</title>
      <media:content url="https://images.example.com/quantum.webp" medium="image" />
    </item>
    """
    elem = ET.fromstring(xml_str)
    img_url = _extract_image_url(elem)
    assert img_url == "https://images.example.com/quantum.webp"


def test_extract_image_from_embedded_html():
    """Verify _extract_image_url extracts image URL from embedded <img> tag in description."""
    xml_str = "<item><title>AI Model Release</title></item>"
    raw_desc = '<p>Company unveils new architecture. <img src="https://images.example.com/arch.png?size=large" alt="diagram"/> Full story below.</p>'
    elem = ET.fromstring(xml_str)
    img_url = _extract_image_url(elem, raw_html=raw_desc)
    assert img_url == "https://images.example.com/arch.png?size=large"


def test_extract_image_returns_none_when_absent():
    """Verify _extract_image_url returns None when no images are declared."""
    xml_str = "<item><title>Plain Text Headline</title><description>Plain summary without graphics.</description></item>"
    elem = ET.fromstring(xml_str)
    img_url = _extract_image_url(elem, raw_html="Plain summary without graphics.")
    assert img_url is None


def test_extract_image_ignores_audio_enclosures():
    """Verify audio/podcast enclosures are not parsed as images."""
    xml_str = """
    <item>
      <title>Podcast Episode</title>
      <enclosure url="https://podcast.example.com/episode1.mp3" type="audio/mpeg" />
    </item>
    """
    elem = ET.fromstring(xml_str)
    img_url = _extract_image_url(elem)
    assert img_url is None


def test_article_extractor_extracts_og_image():
    """Verify ArticleExtractor extracts og:image and twitter:image from HTML header."""
    html_doc = """
    <!DOCTYPE html>
    <html>
      <head>
        <title>New Supercomputer Announced</title>
        <meta property="og:image" content="https://cdn.example.com/supercomputer.jpg">
      </head>
      <body>
        <article>
          <p>The national lab has deployed an exascale machine capable of trillions of calculations.</p>
        </article>
      </body>
    </html>
    """
    extractor = ContentExtractor()
    extracted = extractor.extract_from_html(html_doc, url="https://lab.example.com/news")
    assert extracted.image_url == "https://cdn.example.com/supercomputer.jpg"
    assert "exascale machine" in extracted.text


def test_edition_story_and_api_model_support_image_url():
    """Verify EditionStory and NewspaperStoryResponse serialize optional image_url properly."""
    story = EditionStory(
        story_id="s_img_1",
        title="Headline with Photo",
        url="https://example.com/photo",
        domain="AI",
        summary="Summary text describing the photo.",
        sources=["Tech News"],
        first_seen_at="2026-10-10T06:00:00",
        image_url="https://images.example.com/photo.jpg",
    )
    assert story.image_url == "https://images.example.com/photo.jpg"

    resp = NewspaperStoryResponse(
        cluster_id=story.story_id,
        headline=story.title,
        summary=story.summary,
        domain=story.domain,
        representative_source="Tech News",
        representative_url=story.url,
        image_url=story.image_url,
    )
    assert resp.image_url == "https://images.example.com/photo.jpg"
