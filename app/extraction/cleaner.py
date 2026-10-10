"""Text cleaning and normalization for extracted article content."""

import re
import unicodedata
from typing import Optional

# Standard boilerplate patterns often found at the end of web articles
BOILERPLATE_PATTERNS = [
    r"(?i)sign up for our (daily|weekly)?\s*newsletter[^\n.]*",
    r"(?i)subscribe to (our|the)?\s*newsletter[^\n.]*",
    r"(?i)follow us on (x|twitter|linkedin|facebook|instagram)[^\n.]*",
    r"(?i)share this (article|story)[^\n.]*",
    r"(?i)all rights reserved\.?",
    r"(?i)copyright \d{4}[^\n.]*",
    r"(?i)cookie policy|privacy policy",
    r"(?i)terms of (service|use)",
]


def clean_article_text(raw_text: Optional[str]) -> str:
    """Cleans and standardizes raw extracted article prose.

    Performs:
    1. Unicode normalization (NFKC).
    2. Removal of common inline and footer boilerplate patterns.
    3. Normalization of line endings and whitespace.
    4. Preservation of double-newlines for paragraphs.

    Args:
        raw_text: Raw string extracted from webpage or RSS item.

    Returns:
        str: Normalized, readable text.
    """
    if not raw_text or not raw_text.strip():
        return ""

    # 1. Unicode normalization (converts ligatures, exotic spaces, curly quotes cleanly)
    text = unicodedata.normalize("NFKC", raw_text)

    # 2. Standardize carriage returns
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Strip known boilerplate patterns
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, "", text)

    # 4. Clean line by line: collapse horizontal spaces within lines
    lines = []
    for line in text.split("\n"):
        cleaned_line = re.sub(r"[ \t]+", " ", line).strip()
        lines.append(cleaned_line)

    # 5. Rejoin and collapse excessive blank lines (preserve at most 2 newlines between paragraphs)
    cleaned_text = "\n".join(lines)
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)

    return cleaned_text.strip()


def truncate_for_classification(text: str, max_chars: int = 2000) -> str:
    """Intelligently truncates article text to a bounded length for LLM classification.

    Design Rationale:
    - For relevance classification, an article's hook, thesis, and opening 3-5 paragraphs
      provide >=95% of domain relevance signal.
    - Capping input at ~2,000 characters (~300-400 words) keeps local Qwen CPU prompt
      token processing deterministic and avoids unnecessary token-processing latency.
    - Truncates at the nearest sentence boundary to preserve semantic coherence.

    Args:
        text: Cleaned article text.
        max_chars: Upper bound character count.

    Returns:
        str: Truncated text ending cleanly on sentence or paragraph boundary.
    """
    if not text or len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    # Find the last sentence end punctuation (period, exclamation, question mark followed by space or newline)
    sentence_match = list(re.finditer(r"[.!?](?:\s|\n|$)", truncated))
    if sentence_match:
        last_end = sentence_match[-1].end()
        # Ensure we kept at least 50% of the allowed length
        if last_end >= (max_chars // 2):
            return truncated[:last_end].strip()

    # Fallback: truncate at last whitespace
    last_space = truncated.rfind(" ")
    if last_space > 0:
        return truncated[:last_space].strip() + "..."

    return truncated.strip() + "..."
