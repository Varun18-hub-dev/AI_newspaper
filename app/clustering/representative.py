"""Deterministic representative article selection for story clusters."""

from typing import Dict, List, Optional
from app.extraction.models import ExtractedContent
from app.ingestion.models import Article

# Domain authority weights
SOURCE_TIER_SCORES: Dict[str, float] = {
    # Official / Primary tech blogs
    "openai": 12.0,
    "anthropic": 12.0,
    "google": 12.0,
    "hugging face": 11.0,
    "hugging face blog": 11.0,
    "ars technica": 10.0,
    "the verge": 10.0,
    "techcrunch": 9.5,
    "mit technology review": 9.5,
    "reuters": 9.0,
    "bloomberg": 9.0,
    "wired": 8.5,
    "venturebeat": 8.0,
}


def compute_article_representative_score(
    article: Article,
    extracted_content: Optional[ExtractedContent] = None,
) -> float:
    """Computes a deterministic quality score to elect the canonical representative article of a cluster.

    Factors:
    1. Source tier and journalistic reputation (0-12 pts)
    2. Title informativeness (length between 30 and 130 characters) (0-5 pts)
    3. Description quality (has detailed summary text) (0-4 pts)
    4. Full extracted body length (has long comprehensive text) (0-6 pts)
    5. Recency / publication validity (0-3 pts)

    Args:
        article: Ingested article metadata.
        extracted_content: Optional extracted HTML prose.

    Returns:
        float: Deterministic representative score.
    """
    score = 0.0

    # 1. Source Tier
    source_lower = article.source.lower().strip()
    tier_found = False
    for src_key, src_val in SOURCE_TIER_SCORES.items():
        if src_key in source_lower:
            score += src_val
            tier_found = True
            break
    if not tier_found:
        score += 5.0  # Default baseline for unknown sources

    # 2. Title length & structure
    t_len = len(article.title.strip())
    if 35 <= t_len <= 120:
        score += 5.0
    elif 20 <= t_len < 35 or 120 < t_len <= 160:
        score += 3.0
    elif t_len > 15:
        score += 1.0

    # 3. Description informativeness
    desc = (article.description or "").strip()
    d_len = len(desc)
    if d_len >= 180:
        score += 4.0
    elif d_len >= 80:
        score += 2.5
    elif d_len >= 20:
        score += 1.0

    # 4. Extracted full text completeness
    if extracted_content and extracted_content.extraction_success:
        words = extracted_content.word_count
        if words >= 400:
            score += 6.0
        elif words >= 200:
            score += 4.0
        elif words >= 50:
            score += 2.0
    elif article.content and len(article.content.split()) >= 150:
        score += 3.0

    # 5. Timestamp presence
    if article.published_at is not None:
        score += 2.0

    return round(score, 3)


class RepresentativeSelector:
    """Selects the best representative article from a cluster of candidate articles."""

    @staticmethod
    def select_representative(
        articles: List[Article],
        extracted_map: Optional[Dict[str, ExtractedContent]] = None,
    ) -> Article:
        """Selects the single most authoritative, informative article from a list.

        Args:
            articles: Non-empty list of articles belonging to the same cluster.
            extracted_map: Mapping of canonical URL -> ExtractedContent.

        Returns:
            Article: The chosen representative article.
        """
        if not articles:
            raise ValueError("Cannot select representative from an empty list of articles.")
        if len(articles) == 1:
            return articles[0]

        extracted_map = extracted_map or {}

        def sort_key(art: Article):
            ext = extracted_map.get(art.url)
            score = compute_article_representative_score(art, ext)
            # Timestamp sort: earlier scoop preferred in tiebreak
            pub_ts = art.published_at.timestamp() if art.published_at else 0.0
            # Higher score first, earlier published first, deterministic URL tiebreak
            return (score, -pub_ts, art.url)

        # Sort descending by representative score
        sorted_articles = sorted(articles, key=sort_key, reverse=True)
        return sorted_articles[0]
