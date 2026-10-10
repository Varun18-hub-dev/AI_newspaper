"""Main article content extractor using BeautifulSoup and heuristic fallback logic."""

import re
from typing import Optional
from bs4 import BeautifulSoup, Comment

from app.core.logging import setup_logger
from app.extraction.cleaner import clean_article_text
from app.extraction.models import ExtractedContent

logger = setup_logger("content_extractor")

# Tags that never contain article body prose
DISCARD_TAGS = [
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "noscript",
    "svg",
    "iframe",
    "button",
    "input",
    "select",
    "textarea",
]

# Patterns for classes or IDs that indicate noise/clutter
CLUTTER_CLASS_ID_REGEX = re.compile(
    r"(?i)(cookie|banner|sidebar|widget|promo|newsletter|share|social|comment|advertisement|disclaimer|popup|modal)",
    re.IGNORECASE,
)


class ContentExtractor:
    """Extracts cleaned article body prose from raw HTML."""

    def __init__(self):
        """Initializes the extractor."""
        # Check parser availability (lxml preferred, fallback to html.parser)
        try:
            import lxml
            self.parser = "lxml"
        except ImportError:
            self.parser = "html.parser"

    def extract_from_html(
        self,
        html_str: str,
        url: str,
        fallback_text: Optional[str] = None,
    ) -> ExtractedContent:
        """Parses HTML and extracts the main article prose.

        Args:
            html_str: Raw HTML markup string.
            url: Article URL.
            fallback_text: Optional fallback text (e.g., RSS item description).

        Returns:
            ExtractedContent: Extracted and cleaned content model.
        """
        if not html_str or not html_str.strip():
            return self._create_fallback(
                url=url,
                fallback_text=fallback_text,
                error="Empty HTML string provided",
            )

        try:
            soup = BeautifulSoup(html_str, self.parser)
        except Exception as err:
            logger.warning(f"HTML parsing failed for {url}: {err}")
            return self._create_fallback(
                url=url,
                fallback_text=fallback_text,
                error=f"HTML parsing error: {err}",
            )

        # 1. Extract HTML document title and optional top/og image
        page_title = None
        if soup.title and soup.title.string:
            page_title = soup.title.string.strip()
        elif soup.find("h1"):
            page_title = soup.find("h1").get_text(strip=True)

        extracted_image_url = None
        og_img = soup.find("meta", property=re.compile(r"^(og:image|twitter:image)$", re.IGNORECASE))
        if not og_img:
            og_img = soup.find("meta", attrs={"name": re.compile(r"^(og:image|twitter:image)$", re.IGNORECASE)})
        if og_img and og_img.get("content"):
            c_url = og_img.get("content").strip()
            if c_url.startswith("http://") or c_url.startswith("https://"):
                extracted_image_url = c_url

        # 2. Remove comments and unwanted tags
        for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
            comment.extract()

        for tag_name in DISCARD_TAGS:
            for el in soup.find_all(tag_name):
                el.decompose()

        # 3. Remove clutter based on class and id heuristics
        for el in soup.find_all(attrs={"class": CLUTTER_CLASS_ID_REGEX}):
            el.decompose()
        for el in soup.find_all(attrs={"id": CLUTTER_CLASS_ID_REGEX}):
            el.decompose()

        # 4. Search for main article container
        method = "none"
        main_container = soup.find("article")
        if main_container:
            method = "article_tag"
        else:
            main_container = soup.find("main") or soup.find(attrs={"role": "main"})
            if main_container:
                method = "main_tag"
            else:
                # Look for common article body class patterns
                body_candidate = soup.find(
                    attrs={"class": re.compile(r"(?i)(article-body|post-content|entry-content|story-body|article__content)")}
                )
                if body_candidate:
                    main_container = body_candidate
                    method = "content_class"

        # 5. Extract text from container or fallback to paragraph collection
        extracted_text = ""
        if main_container:
            paragraphs = [p.get_text(strip=True) for p in main_container.find_all("p")]
            # Filter trivial or 1-word paragraphs
            meaningful_p = [p for p in paragraphs if len(p.split()) >= 3]
            if meaningful_p:
                extracted_text = "\n\n".join(meaningful_p)
            else:
                extracted_text = main_container.get_text(separator="\n", strip=True)
        else:
            # Fallback: extract all paragraphs with substance across body
            paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
            meaningful_p = [p for p in paragraphs if len(p.split()) >= 5]
            if meaningful_p:
                extracted_text = "\n\n".join(meaningful_p)
                method = "paragraphs"

        cleaned_text = clean_article_text(extracted_text)
        word_count = len(cleaned_text.split())

        # If extracted content is too thin, fall back to RSS description
        if word_count < 15:
            if fallback_text and len(fallback_text.strip().split()) >= 5:
                cleaned_fallback = clean_article_text(fallback_text)
                return ExtractedContent(
                    url=url,
                    title=page_title,
                    text=cleaned_fallback,
                    word_count=len(cleaned_fallback.split()),
                    extraction_method="rss_fallback",
                    extraction_success=True,
                    error_message="Extracted HTML content was sparse; used RSS description fallback",
                    image_url=extracted_image_url,
                )
            elif word_count == 0:
                return ExtractedContent(
                    url=url,
                    title=page_title,
                    text="",
                    word_count=0,
                    extraction_method="none",
                    extraction_success=False,
                    error_message="No substantive article body found in HTML",
                    image_url=extracted_image_url,
                )

        return ExtractedContent(
            url=url,
            title=page_title,
            text=cleaned_text,
            word_count=word_count,
            extraction_method=method,
            extraction_success=True,
            image_url=extracted_image_url,
        )

    def _create_fallback(
        self,
        url: str,
        fallback_text: Optional[str],
        error: str,
    ) -> ExtractedContent:
        """Constructs an ExtractedContent instance using available fallback text."""
        if fallback_text and fallback_text.strip():
            cleaned = clean_article_text(fallback_text)
            return ExtractedContent(
                url=url,
                title=None,
                text=cleaned,
                word_count=len(cleaned.split()),
                extraction_method="rss_fallback",
                extraction_success=True,
                error_message=f"Webpage fetch failed ({error}); used RSS description fallback",
            )
        return ExtractedContent(
            url=url,
            title=None,
            text="",
            word_count=0,
            extraction_method="none",
            extraction_success=False,
            error_message=error,
        )
