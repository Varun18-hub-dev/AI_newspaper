"""Entity and release guardrails to prevent unsafe story merges."""

import re
from typing import Dict, List, Optional, Set, Tuple
from app.ingestion.models import Article

# Major AI companies and organizations
KNOWN_ENTITIES = [
    "company x",
    "openai",
    "anthropic",
    "google",
    "alphabet",
    "meta",
    "microsoft",
    "apple",
    "mistral",
    "deepseek",
    "nvidia",
    "amazon",
    "aws",
    "xai",
    "cohere",
    "hugging face",
    "stability ai",
    "midjourney",
    "runway",
    "scale ai",
    "perplexity",
    "baidu",
    "alibaba",
    "qwen",
    "tencent",
    "groq",
    # Hardware & Platforms
    "intel",
    "amd",
    "qualcomm",
    "tsmc",
    "arm",
    "broadcom",
    "snap",
    "snapchat",
    "tesla",
    "spacex",
    "waymo",
    "uber",
    "physical intelligence",
    "oracle",
    "salesforce",
    "cisco",
    "ibm",
    # Cybersecurity Entities & Actors
    "palo alto networks",
    "fortinet",
    "crowdstrike",
    "checkpoint",
    "mandiant",
    "sentinelone",
    "salt typhoon",
    "volt typhoon",
    "shinyhunters",
    "lockbit",
    "blackcat",
    "alphv",
    "cisa",
    # Science & Space Agencies
    "nasa",
    "esa",
    "jpl",
    "cern",
]

# Specific AI products, models, and sub-models
KNOWN_PRODUCTS = [
    # Hardware, Devices & OS
    "mac mini",
    "imac",
    "macbook pro",
    "macbook air",
    "mac studio",
    "mac pro",
    "iphone 16",
    "iphone 15",
    "iphone",
    "ipad pro",
    "ipad",
    "apple watch",
    "vision pro",
    "pixel 9",
    "pixel 8",
    "pixel",
    "orion",
    "spectacles",
    "windows 11",
    "windows 10",
    "windows",
    "macos",
    "ios",
    "android",
    "chrome",
    "safari",
    # Cybersecurity & Infrastructure
    "pan-os",
    "fortimanager",
    # Space Missions & Launch Vehicles
    "europa clipper",
    "starship",
    "super heavy",
    "falcon heavy",
    "falcon 9",
    "starlink",
    # OpenAI
    "chatgpt",
    "searchgpt",
    "sora",
    "whisper",
    "dall-e 3",
    "dall-e",
    "o1-preview",
    "o1-mini",
    "o3-mini",
    "o1",
    "o3",
    "gpt-4o mini",
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4",
    "gpt-3.5",
    "gpt-3",
    # Anthropic
    "claude 3.5 sonnet",
    "claude 3.5 haiku",
    "claude 3 opus",
    "claude 3 sonnet",
    "claude 3 haiku",
    "claude 3.5",
    "claude 3",
    "claude 2",
    # Google
    "gemini 1.5 pro",
    "gemini 1.5 flash",
    "gemini 2.0",
    "gemini 1.5",
    "gemini live",
    "gemini",
    "gemma 2",
    "gemma",
    "veo",
    "imagen 3",
    "imagen",
    "alphafold 3",
    "alphafold",
    # Meta
    "llama 3.3",
    "llama 3.2",
    "llama 3.1",
    "llama 3",
    "llama 2",
    "llama",
    "sam 2",
    # Mistral
    "mistral large 2",
    "mistral large",
    "mistral nemo",
    "codestral",
    "pixtral",
    "mixtral 8x22b",
    "mixtral 8x7b",
    "mistral 7b",
    # DeepSeek
    "deepseek-r1",
    "deepseek-v3",
    "deepseek coder",
    "deepseek",
    # Runway / Midjourney / Video
    "gen-3 alpha",
    "gen-3",
    "midjourney v6.1",
    "midjourney v6",
    # Cohere / Enterprise
    "command r+",
    "command r",
    # Other tools
    "copilot studio",
    "copilot workspace",
    "copilot",
    "cursor",
    "apple intelligence",
    "grok 2",
    "grok",
    "flux.1",
    "flux",
    # Stability AI
    "stable diffusion 3.5",
    "stable diffusion 3",
    "stable diffusion xl",
    "stable diffusion",
    # Qwen & Baidu
    "qwen 2.5",
    "qwen 2",
    "ernie 4.0",
    "ernie",
]

EVENT_CATEGORIES: Dict[str, Set[str]] = {
    "funding": {
        "funding",
        "valuation",
        "investment",
        "invests",
        "invested",
        "investing",
        "raises",
        "raised",
        "raising",
        "ipo",
        "seed round",
        "series a",
        "series b",
        "series c",
        "billion round",
        "million round",
    },
    "legal": {
        "lawsuit",
        "lawsuits",
        "sues",
        "sued",
        "suing",
        "suit",
        "litigation",
        "copyright infringement",
        "antitrust",
        "court filing",
        "federal court",
        "district court",
        "supreme court",
        "subpoena",
        "ftc",
        "sec investigation",
        "doj",
    },
    "personnel": {
        "resigns",
        "resigned",
        "resigning",
        "resignation",
        "steps down",
        "stepped down",
        "stepping down",
        "leaves",
        "left",
        "leaving",
        "fired",
        "fire",
        "fires",
        "firing",
        "dismissal",
        "dismissals",
        "dismissed",
        "oust",
        "ousted",
        "ousting",
        "departs",
        "departed",
        "departing",
        "departure",
        "hires",
        "hired",
        "hiring",
        "joins",
        "joined",
        "joining",
        "layoff",
        "layoffs",
        "laid off",
    },
    "infrastructure": {
        "nuclear",
        "power plant",
        "datacenter",
        "data center",
        "gigawatt",
        "megawatt",
        "clean energy",
    },
    "breach": {
        "breached",
        "breach",
        "exfiltration",
        "exfiltrated",
        "wiretap",
        "ransomware",
    },
    "phishing": {
        "phishing",
        "spear-phishing",
        "credential stuffing",
    },
}

RELEASE_TERMS = {
    "releases",
    "released",
    "launches",
    "launched",
    "unveils",
    "unveiled",
    "announces",
    "announced",
    "introduces",
    "introduced",
    "debuts",
    "debuted",
    "reasoning model",
    "latest ai model",
    "ai model",
    "reasoning",
}


def filter_maximal_products(products: Set[str]) -> Set[str]:
    """Retains only the most specific product names, discarding substrings (e.g. keeping 'llama 3.2' over 'llama')."""
    return {p for p in products if not any(p != other and p in other for other in products)}


class EntityGuard:
    """Verifies that two articles do not have conflicting primary entities, distinct products, or incompatible events."""

    def __init__(self, time_window_hours: float = 72.0):
        """Initializes guardrail parameters.

        Args:
            time_window_hours: Maximum allowable publication time difference between articles.
        """
        self.time_window_hours = time_window_hours
        self._sorted_products = sorted(KNOWN_PRODUCTS, key=len, reverse=True)

    def extract_entities(self, text: str) -> Set[str]:
        """Extracts recognized tech companies / organizations mentioned in text."""
        lower_text = text.lower()
        found = set()
        for entity in KNOWN_ENTITIES:
            pattern = rf"\b{re.escape(entity)}\b"
            if re.search(pattern, lower_text):
                found.add(entity)
        return found

    def extract_products(self, text: str) -> Set[str]:
        """Extracts specific model, product, or tool names mentioned in text, retaining only maximal matches."""
        lower_text = text.lower()
        raw_matches = set()
        for prod in self._sorted_products:
            pattern = rf"\b{re.escape(prod)}\b"
            if re.search(pattern, lower_text):
                raw_matches.add(prod)
        return filter_maximal_products(raw_matches)

    def extract_event_category(self, text: str) -> Optional[str]:
        """Identifies specific non-release event categories (funding, legal, executive personnel)."""
        lower_text = text.lower()
        for cat_name, keywords in EVENT_CATEGORIES.items():
            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", lower_text):
                    return cat_name
        return None

    def is_merge_allowed(
        self,
        article_a: Article,
        article_b: Article,
        text_a: Optional[str] = None,
        text_b: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """Determines if two articles are safe to merge into the same story cluster.

        Args:
            article_a: First article.
            article_b: Second article.
            text_a: Combined text for article A (default: title + description).
            text_b: Combined text for article B (default: title + description).

        Returns:
            Tuple[bool, str]: (is_allowed, reason)
        """
        # 1. Exact match check (always allowed)
        if article_a.url == article_b.url:
            return True, "Identical canonical URL"
        if article_a.title.strip().lower() == article_b.title.strip().lower():
            return True, "Identical normalized title"

        # 1.5. Domain boundary check (Prevents merging articles across different domains)
        dom_a = (getattr(article_a, "domain", None) or "AI").strip().lower()
        dom_b = (getattr(article_b, "domain", None) or "AI").strip().lower()
        if dom_a != dom_b:
            return False, f"Cross-domain boundary: '{article_a.domain}' vs '{article_b.domain}'"

        # 2. Time window check
        if article_a.published_at and article_b.published_at:
            time_diff = abs((article_a.published_at - article_b.published_at).total_seconds())
            hours_diff = time_diff / 3600.0
            if hours_diff > self.time_window_hours:
                return (
                    False,
                    f"Time window exceeded ({hours_diff:.1f}h > {self.time_window_hours}h)",
                )

        # Build composite texts if not provided
        str_a = (text_a or f"{article_a.title} {article_a.description or ''}").lower()
        str_b = (text_b or f"{article_b.title} {article_b.description or ''}").lower()

        # 3. Event category check (Funding vs Lawsuit vs Departure vs Model Release)
        cat_a = self.extract_event_category(str_a)
        cat_b = self.extract_event_category(str_b)
        # If either article has an explicit non-release event category, both must share it
        if cat_a != cat_b:
            return False, f"Incompatible event types: '{cat_a}' vs '{cat_b}'"

        # 4. Primary Company / Organization check
        entities_a = self.extract_entities(str_a)
        entities_b = self.extract_entities(str_b)
        if entities_a and entities_b:
            if not entities_a.intersection(entities_b):
                return (
                    False,
                    f"Conflicting primary entities: {entities_a} vs {entities_b}",
                )

        # 5. Product / Model Version check (CRITICAL: prevents merging different releases by same company)
        prods_a = self.extract_products(str_a)
        prods_b = self.extract_products(str_b)

        if prods_a and prods_b:
            # Check for exact product intersection
            common = prods_a.intersection(prods_b)
            if not common:
                # Disallow merge of distinct products or version variants
                return (
                    False,
                    f"Conflicting products/models from same entity: {prods_a} vs {prods_b}",
                )

        return True, "Guardrails satisfied"

    def compute_semantic_bonus(
        self,
        article_a: Article,
        article_b: Article,
        text_a: str,
        text_b: str,
    ) -> float:
        """Calculates a semantic compatibility bonus based on entity and product alignment.

        Args:
            article_a: First article.
            article_b: Second article.
            text_a: Cleaned text for article A.
            text_b: Cleaned text for article B.

        Returns:
            float: Compatibility bonus in range [0.0, 0.60].
        """
        str_a = text_a.lower()
        str_b = text_b.lower()

        prods_a = self.extract_products(str_a)
        prods_b = self.extract_products(str_b)
        common_prods = prods_a.intersection(prods_b)

        entities_a = self.extract_entities(str_a)
        entities_b = self.extract_entities(str_b)
        common_entities = entities_a.intersection(entities_b)

        bonus = 0.0

        # Exact shared product/model: strong boost
        if common_prods:
            bonus += 0.45

        # Shared release phrasing
        shared_terms = sum(1 for term in RELEASE_TERMS if term in str_a and term in str_b)
        if shared_terms >= 2:
            bonus += 0.10

        # Shared company/organization (boosts when combined with shared products or release events)
        if common_entities and (common_prods or shared_terms >= 1):
            bonus += 0.15

        return min(0.60, bonus)
