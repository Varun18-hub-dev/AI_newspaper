"""Cheap deterministic relevance pre-filter and candidate ranking for articles."""

from datetime import datetime, timezone
import re
from typing import List, Literal, Optional, Set, Tuple
from pydantic import BaseModel, Field

from app.core.logging import setup_logger
from app.ingestion.models import Article
from app.extraction.models import ExtractedContent

logger = setup_logger("pre_filter")

# 1. Strong compound signals: highly specific to Artificial Intelligence
STRONG_AI_SIGNALS = [
    r"\blarge language models?\b",
    r"\bllms?\b",
    r"\bgenerative ai\b",
    r"\bgenai\b",
    r"\bmachine learning\b",
    r"\bdeep learning\b",
    r"\bneural networks?\b",
    r"\bfoundation models?\b",
    r"\breasoning models?\b",
    r"\bdiffusion models?\b",
    r"\btransformers?\b",
    r"\bcomputer vision\b",
    r"\bnlp\b",
    r"\bnatural language processing\b",
    r"\breinforcement learning\b",
    r"\bai agents?\b",
    r"\bagentic\b",
    r"\bagents?\b",
    r"\bfine-?tuning\b",
    r"\brag\b",
    r"\bretrieval-?augmented\b",
    r"\bopen-?source models?\b",
    r"\bdecision models?\b",
    r"\bchatgpt\b",
    r"\bclaude\b",
    r"\bopenai\b",
    r"\bgemini\b",
    r"\bdeepseek\b",
    r"\bmistral\b",
    r"\banthropic\b",
    r"\bhugging face\b",
    r"\bqwen\b",
    r"\bcopilot\b",
    r"\bllama\s*[234]?\b",
    r"\bai hardware\b",
    r"\bai chips?\b",
    r"\bai infrastructure\b",
    r"\bsynthetic data\b",
    r"\bmcp\b",
    r"\bagi\b",
    r"\bmultimodal\b",
    r"\btokenizers?\b",
    r"\bvoice cloning\b",
    r"\btext-to-speech\b",
    r"\btts\b",
    r"\basr\b",
]

# 2. Standalone / contextual signals (requires word boundary)
STANDALONE_AI_SIGNALS = [
    r"\bartificial intelligence\b",
    r"\bai\b",
    r"\brobotics\b",
    r"\brobots?\b",
    r"\bmodels?\b",
    r"\bprompting\b",
    r"\bhallucinations?\b",
    r"\bmodel weights\b",
    r"\bautonomous\b",
    r"\brl\b",
    r"\bbenchmarks?\b",
    r"\bcompute\b",
]

# 3. Promotional noise patterns (used to penalize pure event/ticket noise)
NOISE_PATTERNS = [
    r"\bticket sales?\b",
    r"\bbuy tickets?\b",
    r"\bpass for disrupt\b",
    r"\bdiscount codes?\b",
    r"\bcoupon codes?\b",
    r"\bpromo codes?\b",
    r"\bregister for webinar\b",
    r"\bhotel booking\b",
]

# Source domain baseline credibility / domain relevance
SOURCE_DOMAIN_WEIGHTS = {
    "huggingface.co": 1.0,
    "techcrunch.com": 0.90,
    "theverge.com": 0.85,
    "arstechnica.com": 0.75,
}


class PreFilterResult(BaseModel):
    """Result of deterministic relevance scoring and tiered ranking."""

    pre_filter_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Deterministic relevance score between 0.0 and 1.0",
    )
    tier: Literal["HIGH", "MEDIUM", "LOW"] = Field(
        default="LOW",
        description="Confidence tier: HIGH (strong AI), MEDIUM (ambiguous), LOW (reject)",
    )
    ranking_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Multi-factor candidate priority score used for Top-K ordering",
    )
    signals: List[str] = Field(
        default_factory=list,
        description="List of detected AI signal terms",
    )
    should_send_to_llm: bool = Field(
        ...,
        description="Whether article passes threshold to be evaluated by LLM",
    )
    reason: str = Field(
        ...,
        description="Explainable breakdown of scoring decision",
    )


class DeterministicPreFilter:
    """Inexpensive multi-signal pre-filter and ranker for AI domain relevance."""

    def __init__(self, threshold: float = 0.20):
        """Initializes the filter.

        Args:
            threshold: Minimum score required to pass candidate to LLM.
                       Default 0.20 is conservative to avoid false negatives.
        """
        self.threshold = threshold
        self._strong_regexes = [re.compile(p, re.IGNORECASE) for p in STRONG_AI_SIGNALS]
        self._standalone_regexes = [re.compile(p, re.IGNORECASE) for p in STANDALONE_AI_SIGNALS]
        self._noise_regexes = [re.compile(p, re.IGNORECASE) for p in NOISE_PATTERNS]

        # Multi-domain signal caches
        from app.domains.registry import get_domain_registry
        self._registry = get_domain_registry()
        self._domain_regexes: dict = {}
        for d in self._registry.list_domains(enabled_only=False):
            self._domain_regexes[d.domain_id] = {
                "strong": [re.compile(p, re.IGNORECASE) for p in d.strong_signals],
                "standalone": [re.compile(p, re.IGNORECASE) for p in d.standalone_signals],
            }

    def _find_matches(self, text: str, regex_list: list) -> List[str]:
        if not text:
            return []
        matches = []
        for rx in regex_list:
            found = rx.findall(text)
            if found:
                matches.append(rx.pattern.strip(r"\b").replace(r"\s*", " ").replace(r"\s+", " "))
        return matches

    def _compute_source_weight(self, url: str) -> float:
        """Determines source credibility weight from article URL."""
        url_lower = url.lower()
        for domain, weight in SOURCE_DOMAIN_WEIGHTS.items():
            if domain in url_lower:
                return weight
        return 0.80

    def _compute_freshness_bonus(self, published_at: Optional[datetime]) -> float:
        """Awards a small recency bonus (0.0 to 0.05) for articles published recently."""
        if not published_at:
            return 0.0
        try:
            # Handle naive datetime
            now = datetime.now() if published_at.tzinfo is None else datetime.now(timezone.utc)
            age_hours = (now - published_at).total_seconds() / 3600.0
            if age_hours <= 24:
                return 0.05
            elif age_hours <= 48:
                return 0.03
            elif age_hours <= 168:  # 7 days
                return 0.01
        except Exception:
            pass
        return 0.0

    def evaluate(
        self,
        article: Article,
        content: Optional[ExtractedContent] = None,
    ) -> PreFilterResult:
        """Evaluates an article using multi-signal scoring and assigns a tier + ranking score.

        Scoring formula:
        - Title Strong AI Signal: +0.50
        - Title Standalone Signal: +0.25
        - Description Strong AI Signal: +0.30
        - Description Standalone Signal: +0.15
        - Content density (>=3 matches: +0.25, 1-2 matches: +0.15)
        - Promotional Noise Penalty: -0.40
        - Final score clamped to [0.0, 1.0]

        Tiers:
        - HIGH:   Score >= 0.60 (clear AI story)
        - MEDIUM: 0.20 <= Score < 0.60 (ambiguous / contextual)
        - LOW:    Score < 0.20 (clearly irrelevant)

        Ranking score:
        - Combines relevance (70%), source authority (25%), and freshness (5%)

        Args:
            article: Ingested article metadata.
            content: Extracted content if available.

        Returns:
            PreFilterResult: Scored result with tier and ranking.
        """
        score = 0.0
        detected_signals: Set[str] = set()

        title_text = article.title
        desc_text = article.description or ""
        body_text = content.text if content and content.extraction_success else ""

        # Normalize domain
        norm_dom = self._registry.normalize_domain_key(article.domain or "ai")
        domain_cfg = self._registry.get_domain(norm_dom)

        if norm_dom == "ai":
            # Baseline Phase 3 AI evaluation
            # Source baseline boost for dedicated AI feeds / categories
            low_url = article.url.lower()
            low_src = article.source.lower()
            if "huggingface.co" in low_url or "hugging face" in low_src:
                score += 0.30
                detected_signals.add("hugging face source")
            elif "artificial-intelligence" in low_url or "artificial intelligence" in low_src or "/ai/" in low_url:
                score += 0.20
                detected_signals.add("ai source feed")

            # 1. Analyze Title
            title_strong = self._find_matches(title_text, self._strong_regexes)
            title_standalone = self._find_matches(title_text, self._standalone_regexes)

            if title_strong:
                score += 0.50
                detected_signals.update(title_strong)
            elif title_standalone:
                score += 0.25
                detected_signals.update(title_standalone)

            # 2. Analyze Description
            desc_strong = self._find_matches(desc_text, self._strong_regexes)
            desc_standalone = self._find_matches(desc_text, self._standalone_regexes)

            if desc_strong:
                score += 0.30
                detected_signals.update(desc_strong)
            elif desc_standalone:
                score += 0.20
                detected_signals.update(desc_standalone)

            # 3. Analyze Body Content (keyword density)
            if body_text:
                body_strong = self._find_matches(body_text, self._strong_regexes)
                body_standalone = self._find_matches(body_text, self._standalone_regexes)
                total_body_matches = len(body_strong) + len(body_standalone)

                if total_body_matches >= 3:
                    score += 0.25
                elif total_body_matches >= 1:
                    score += 0.15

                detected_signals.update(body_strong)
                detected_signals.update(body_standalone)

            # 4. Check for Promotional Noise Penalty
            noise_matches = self._find_matches(title_text + " " + desc_text, self._noise_regexes)
            if noise_matches and not title_strong:
                score = max(0.0, score - 0.40)
        else:
            # Multi-domain deterministic evaluation for Technology, Science, Cybersecurity, Business
            reg_strong = self._domain_regexes.get(norm_dom, {}).get("strong", [])
            reg_standalone = self._domain_regexes.get(norm_dom, {}).get("standalone", [])

            # Source baseline boost for dedicated domain feeds
            low_url = article.url.lower()
            low_src = article.source.lower()
            if norm_dom == "cybersecurity" and any(k in low_url or k in low_src for k in ("krebsonsecurity", "darkreading", "hackersnews", "schneier", "security")):
                score += 0.25
                detected_signals.add("cybersecurity source feed")
            elif norm_dom == "science" and any(k in low_url or k in low_src for k in ("phys.org", "sciencedaily", "science", "nature")):
                score += 0.25
                detected_signals.add("science source feed")
            elif norm_dom == "business" and any(k in low_url or k in low_src for k in ("startups", "venturebeat", "tech-policy", "business")):
                score += 0.25
                detected_signals.add("business source feed")
            elif norm_dom == "technology" and (
                any(d in low_url for d in ("arstechnica.com", "theverge.com", "techcrunch.com"))
                or any(s in low_src for s in ("arstechnica", "the verge", "techcrunch"))
            ):
                score += 0.20
                detected_signals.add("technology source feed")

            # 1. Analyze Title
            title_strong = self._find_matches(title_text, reg_strong)
            title_standalone = self._find_matches(title_text, reg_standalone)

            if title_strong:
                score += 0.50
                detected_signals.update(title_strong)
            elif title_standalone:
                score += 0.25
                detected_signals.update(title_standalone)

            # 2. Analyze Description
            desc_strong = self._find_matches(desc_text, reg_strong)
            desc_standalone = self._find_matches(desc_text, reg_standalone)

            if desc_strong:
                score += 0.30
                detected_signals.update(desc_strong)
            elif desc_standalone:
                score += 0.20
                detected_signals.update(desc_standalone)

            # 3. Analyze Body Content (keyword density)
            if body_text:
                body_strong = self._find_matches(body_text, reg_strong)
                body_standalone = self._find_matches(body_text, reg_standalone)
                total_body_matches = len(body_strong) + len(body_standalone)

                if total_body_matches >= 3:
                    score += 0.25
                elif total_body_matches >= 1:
                    score += 0.15

                detected_signals.update(body_strong)
                detected_signals.update(body_standalone)

            # 4. Check for Promotional Noise Penalty
            noise_matches = self._find_matches(title_text + " " + desc_text, self._noise_regexes)
            if noise_matches and not title_strong:
                score = max(0.0, score - 0.40)

        # Clamp between 0.0 and 1.0
        relevance_score = round(min(1.0, max(0.0, score)), 2)
        effective_thresh = domain_cfg.pre_filter_threshold if domain_cfg else self.threshold
        should_send = relevance_score >= effective_thresh

        # Determine Tier
        if relevance_score >= 0.60:
            tier: Literal["HIGH", "MEDIUM", "LOW"] = "HIGH"
        elif relevance_score >= self.threshold:
            tier = "MEDIUM"
        else:
            tier = "LOW"

        # Calculate Candidate Ranking Score (for Top-K candidate prioritization)
        source_weight = self._compute_source_weight(article.url)
        freshness_bonus = self._compute_freshness_bonus(article.published_at)

        ranking_score = round(
            min(1.0, max(0.0, (relevance_score * 0.70) + (source_weight * 0.25) + freshness_bonus)),
            3,
        )

        sorted_signals = sorted(list(detected_signals))
        if should_send:
            reason = (
                f"Passed pre-filter [{tier}] (score={relevance_score:.2f}, rank={ranking_score:.3f}): "
                f"detected {sorted_signals[:4]}"
            )
        else:
            reason = (
                f"Rejected pre-filter [{tier}] (score={relevance_score:.2f} < {self.threshold}): "
                f"insufficient AI signals"
            )

        return PreFilterResult(
            pre_filter_score=relevance_score,
            tier=tier,
            ranking_score=ranking_score,
            signals=sorted_signals,
            should_send_to_llm=should_send,
            reason=reason,
        )

    def rank_candidates(
        self,
        candidates: List[Tuple[Article, PreFilterResult]],
    ) -> List[Tuple[Article, PreFilterResult]]:
        """Ranks candidates in descending order of priority (tier, ranking_score, relevance_score).

        Args:
            candidates: List of (Article, PreFilterResult) pairs that passed pre-filtering.

        Returns:
            List[Tuple[Article, PreFilterResult]]: Sorted list from highest to lowest priority.
        """
        tier_weights = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

        def sort_key(item: Tuple[Article, PreFilterResult]):
            art, pf = item
            return (
                tier_weights.get(pf.tier, 0),
                pf.ranking_score,
                pf.pre_filter_score,
            )

        return sorted(candidates, key=sort_key, reverse=True)
