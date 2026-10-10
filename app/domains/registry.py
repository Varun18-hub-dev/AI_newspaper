"""Registry managing domain definitions, feed configurations, and taxonomies for Multi-Domain Discovery."""

from typing import Dict, List, Optional
from app.domains.models import DomainConfig, FeedConfig


# =============================================================================
# 1. Controlled Subtopic Taxonomies
# =============================================================================

AI_TOPICS = [
    "AI Agents",
    "LLMs",
    "Generative AI",
    "AI Safety",
    "Machine Learning",
    "Computer Vision",
    "NLP",
    "Robotics",
    "AI Infrastructure",
    "AI Hardware",
    "AI Research",
    "AI Startups",
    "Other",
]

TECHNOLOGY_TOPICS = [
    "Software & Apps",
    "Hardware & Devices",
    "Consumer Tech",
    "Cloud Computing",
    "Mobile & Telecom",
    "Operating Systems",
    "Semiconductors",
    "Internet & Web",
    "Other",
]

SCIENCE_TOPICS = [
    "Space & Astronomy",
    "Physics",
    "Biology & Genetics",
    "Medicine & Health",
    "Climate & Earth",
    "Materials Science",
    "Neuroscience",
    "Other",
]

CYBERSECURITY_TOPICS = [
    "Vulnerabilities & CVEs",
    "Data Breaches",
    "Malware & Ransomware",
    "Threat Actors & APTs",
    "Application Security",
    "Network & Cloud Security",
    "Security Policy & Compliance",
    "Other",
]

BUSINESS_TOPICS = [
    "Venture Capital & Funding",
    "Startups",
    "M&A and IPOs",
    "Tech Giants & Big Tech",
    "Regulation & Antitrust",
    "Leadership & Executive",
    "Markets & Economy",
    "Other",
]

DOMAIN_TOPICS_MAP: Dict[str, List[str]] = {
    "ai": AI_TOPICS,
    "technology": TECHNOLOGY_TOPICS,
    "science": SCIENCE_TOPICS,
    "cybersecurity": CYBERSECURITY_TOPICS,
    "business": BUSINESS_TOPICS,
}


# =============================================================================
# 2. Compact Prompt Templates (under 250 tokens for fast CPU inference)
# =============================================================================

AI_PROMPT_TEMPLATE = """Classify if this article is genuinely about Artificial Intelligence (including LLMs, AI agents, machine learning, AI models, NLP/speech, computer vision, AI safety/policy, AI chips/hardware, and AI research).

Return ONLY valid JSON matching this schema:
{{
  "is_relevant": true,
  "relevance_score": 0.95,
  "topic": "AI Agents",
  "reason": "Short explanation under 20 words."
}}

Allowed topics (select EXACTLY one):
{topics}

Title: {title}
Source: {source}
Description: {description}
Article Excerpt:
{content}
"""

TECHNOLOGY_PROMPT_TEMPLATE = """Classify if this article is genuinely about Technology (including software, computer hardware, consumer electronics, gadgets, cloud computing, operating systems, and semiconductors).

Return ONLY valid JSON matching this schema:
{{
  "is_relevant": true,
  "relevance_score": 0.95,
  "topic": "Software & Apps",
  "reason": "Short explanation under 20 words."
}}

Allowed topics (select EXACTLY one):
{topics}

Title: {title}
Source: {source}
Description: {description}
Article Excerpt:
{content}
"""

SCIENCE_PROMPT_TEMPLATE = """Classify if this article is genuinely about Science (including space/astronomy, physics, biology, medicine/health, climate/earth science, materials science, and neuroscience).

Return ONLY valid JSON matching this schema:
{{
  "is_relevant": true,
  "relevance_score": 0.95,
  "topic": "Space & Astronomy",
  "reason": "Short explanation under 20 words."
}}

Allowed topics (select EXACTLY one):
{topics}

Title: {title}
Source: {source}
Description: {description}
Article Excerpt:
{content}
"""

CYBERSECURITY_PROMPT_TEMPLATE = """Classify if this article is genuinely about Cybersecurity (including vulnerabilities, data breaches, malware/ransomware, cyber threats, authentication, and security patches).

Return ONLY valid JSON matching this schema:
{{
  "is_relevant": true,
  "relevance_score": 0.95,
  "topic": "Vulnerabilities & CVEs",
  "reason": "Short explanation under 20 words."
}}

Allowed topics (select EXACTLY one):
{topics}

Title: {title}
Source: {source}
Description: {description}
Article Excerpt:
{content}
"""

BUSINESS_PROMPT_TEMPLATE = """Classify if this article is genuinely about Business and Startups (including venture funding, startup launches, mergers/acquisitions, IPOs, corporate earnings, and tech regulation).

Return ONLY valid JSON matching this schema:
{{
  "is_relevant": true,
  "relevance_score": 0.95,
  "topic": "Venture Capital & Funding",
  "reason": "Short explanation under 20 words."
}}

Allowed topics (select EXACTLY one):
{topics}

Title: {title}
Source: {source}
Description: {description}
Article Excerpt:
{content}
"""


# =============================================================================
# 3. Default Domain Configurations
# =============================================================================

DEFAULT_DOMAINS: List[DomainConfig] = [
    DomainConfig(
        domain_id="ai",
        display_name="Artificial Intelligence",
        description="Artificial intelligence, machine learning, foundation models, and autonomous agents.",
        enabled=True,
        feeds=[
            FeedConfig(url="https://techcrunch.com/category/artificial-intelligence/feed/", source_name="TechCrunch AI"),
            FeedConfig(url="https://theverge.com/rss/ai-artificial-intelligence/index.xml", source_name="The Verge AI"),
            FeedConfig(url="https://huggingface.co/blog/feed.xml", source_name="HuggingFace"),
            FeedConfig(url="https://feeds.arstechnica.com/arstechnica/technology-lab", source_name="Ars Technica AI"),
            FeedConfig(url="https://bair.berkeley.edu/blog/feed.xml", source_name="BAIR Blog"),
        ],
        allowed_topics=AI_TOPICS,
        pre_filter_threshold=0.20,
        strong_signals=[
            r"\blarge language models?\b", r"\bllms?\b", r"\bgenerative ai\b", r"\bgenai\b",
            r"\bmachine learning\b", r"\bdeep learning\b", r"\bneural networks?\b", r"\bfoundation models?\b",
            r"\breasoning models?\b", r"\bdiffusion models?\b", r"\btransformers?\b", r"\bcomputer vision\b",
            r"\bnlp\b", r"\bnatural language processing\b", r"\breinforcement learning\b", r"\bai agents?\b",
            r"\bagentic\b", r"\bagents?\b", r"\bfine-?tuning\b", r"\brag\b", r"\bretrieval-?augmented\b",
            r"\bchatgpt\b", r"\bclaude\b", r"\bopenai\b", r"\bgemini\b", r"\bdeepseek\b", r"\bmistral\b",
            r"\banthropic\b", r"\bhugging face\b", r"\bqwen\b", r"\bcopilot\b", r"\bllama\s*[234]?\b",
            r"\bai hardware\b", r"\bai chips?\b", r"\bai infrastructure\b", r"\bagi\b",
        ],
        standalone_signals=[
            r"\bartificial intelligence\b", r"\bai\b", r"\brobotics\b", r"\brobots?\b",
            r"\bprompting\b", r"\bhallucinations?\b", r"\bautonomous\b", r"\brl\b",
        ],
        prompt_template=AI_PROMPT_TEMPLATE,
    ),
    DomainConfig(
        domain_id="technology",
        display_name="Technology",
        description="Consumer electronics, computing platforms, software engineering, and digital infrastructure.",
        enabled=True,
        feeds=[
            FeedConfig(url="https://feeds.arstechnica.com/arstechnica/index", source_name="Ars Technica"),
            FeedConfig(url="https://theverge.com/rss/index.xml", source_name="The Verge"),
            FeedConfig(url="https://techcrunch.com/feed/", source_name="TechCrunch"),
        ],
        allowed_topics=TECHNOLOGY_TOPICS,
        pre_filter_threshold=0.20,
        strong_signals=[
            r"\bsmartphones?\b", r"\blaptops?\b", r"\bsmartwatches?\b", r"\btablets?\b",
            r"\bandroid\b", r"\bios\b", r"\bmacos\b", r"\bwindows 1[01]\b", r"\blinux\b",
            r"\bweb browsers?\b", r"\bchrome\b", r"\bfirefox\b", r"\bsafari\b",
            r"\bprocessors?\b", r"\bcpus?\b", r"\bgpus?\b", r"\bsemiconductors?\b",
            r"\bcloud storage\b", r"\bcloud computing\b", r"\bbluetooth\b", r"\bwi-fi\s*[67]?\b",
            r"\bwearables?\b", r"\bsmart home\b", r"\bopen[- ]source software\b",
        ],
        standalone_signals=[
            r"\btechnology\b", r"\btech\b", r"\bgadgets?\b", r"\bdevices?\b",
            r"\bsoftware\b", r"\bhardware\b", r"\boperating systems?\b", r"\bcomputing\b",
        ],
        prompt_template=TECHNOLOGY_PROMPT_TEMPLATE,
    ),
    DomainConfig(
        domain_id="science",
        display_name="Science",
        description="Physical sciences, astronomy, biological discoveries, clinical health, and earth science.",
        enabled=True,
        feeds=[
            FeedConfig(url="https://feeds.arstechnica.com/arstechnica/science", source_name="Ars Technica Science"),
            FeedConfig(url="https://phys.org/rss-feed/", source_name="Phys.org"),
            FeedConfig(url="https://www.sciencedaily.com/rss/top/science.xml", source_name="ScienceDaily"),
            FeedConfig(url="https://www.nature.com/nature.rss", source_name="Nature News"),
            FeedConfig(url="https://www.quantamagazine.org/feed/", source_name="Quanta Magazine"),
        ],
        allowed_topics=SCIENCE_TOPICS,
        pre_filter_threshold=0.20,
        strong_signals=[
            r"\bastronomy\b", r"\bastrophysics\b", r"\bjames webb\b", r"\bhubble\b",
            r"\bexoplanets?\b", r"\bblack holes?\b", r"\bgalaxies?\b", r"\bsupernovas?\b",
            r"\bparticle physics\b", r"\bquantum physics\b", r"\bquantum\b", r"\bquantum computing\b",
            r"\bcern\b", r"\blarge hadron collider\b",
            r"\bcrispr\b", r"\bgene editing\b", r"\bgenomics?\b", r"\bclinical trials?\b",
            r"\bvaccines?\b", r"\bneuroscience\b", r"\bclimate change\b", r"\bpaleontology\b",
            r"\bgeology\b", r"\bmaterials science\b", r"\bsuperconductors?\b",
        ],
        standalone_signals=[
            r"\bscience\b", r"\bscientific\b", r"\bresearchers?\b", r"\bscientists?\b",
            r"\bphysicists?\b", r"\bphysics\b", r"\bchemistry\b", r"\blaboratory\b",
            r"\bexperiments?\b", r"\bnasa\b", r"\besa\b",
        ],
        prompt_template=SCIENCE_PROMPT_TEMPLATE,
    ),
    DomainConfig(
        domain_id="cybersecurity",
        display_name="Cybersecurity",
        description="Vulnerabilities, exploit analysis, malware, data breaches, and threat intelligence.",
        enabled=True,
        feeds=[
            FeedConfig(url="https://krebsonsecurity.com/feed/", source_name="Krebs on Security"),
            FeedConfig(url="https://www.darkreading.com/rss.xml", source_name="Dark Reading"),
            FeedConfig(url="https://feeds.feedburner.com/TheHackersNews", source_name="The Hacker News"),
            FeedConfig(url="https://www.schneier.com/feed/atom/", source_name="Schneier on Security"),
            FeedConfig(url="https://www.bleepingcomputer.com/feed/", source_name="BleepingComputer"),
            FeedConfig(url="https://www.securityweek.com/feed/", source_name="SecurityWeek"),
        ],
        allowed_topics=CYBERSECURITY_TOPICS,
        pre_filter_threshold=0.20,
        strong_signals=[
            r"\bcybersecurity\b", r"\bransomware\b", r"\bmalware\b", r"\bzero-?day\b",
            r"\bcve-\d{4}-\d+\b", r"\bdata breaches?\b", r"\bdata leaks?\b", r"\bphishing\b",
            r"\bddos\b", r"\bbotnets?\b", r"\binfostealer\b", r"\btrojans?\b", r"\bspyware\b",
            r"\bapt\d+\b", r"\bthreat actors?\b", r"\bpatch tuesday\b", r"\bvulnerability\b",
            r"\bvulnerabilities\b", r"\bsecurity advisory\b", r"\bcredential stuffing\b",
            r"\bbackdoors?\b", r"\bprivilege escalation\b", r"\bremote code execution\b",
            r"\brce\b", r"\bcisa\b",
        ],
        standalone_signals=[
            r"\bsecurity\b", r"\bhackers?\b", r"\bhacking\b", r"\bbreached\b",
            r"\bexploits?\b", r"\bexploited\b", r"\bcyber\b", r"\bpayload\b",
            r"\bcompromised\b", r"\bfirewall\b", r"\bencryption\b",
        ],
        prompt_template=CYBERSECURITY_PROMPT_TEMPLATE,
    ),
    DomainConfig(
        domain_id="business",
        display_name="Business and startups",
        description="Venture financing, corporate strategy, executive leadership, M&A, and market regulation.",
        enabled=True,
        feeds=[
            FeedConfig(url="https://techcrunch.com/category/startups/feed/", source_name="TechCrunch Startups"),
            FeedConfig(url="https://venturebeat.com/category/business/feed/", source_name="VentureBeat Business"),
            FeedConfig(url="https://feeds.arstechnica.com/arstechnica/tech-policy", source_name="Ars Technica Business"),
            FeedConfig(url="https://siliconangle.com/feed/", source_name="SiliconANGLE"),
        ],
        allowed_topics=BUSINESS_TOPICS,
        pre_filter_threshold=0.20,
        strong_signals=[
            r"\bventure capital\b", r"\bseed funding\b", r"\bseries [a-e]\b",
            r"\braised \$\d+\b", r"\bfunding round\b", r"\bvaluations?\b",
            r"\bacquisitions?\b", r"\bacquired by\b", r"\bmergers?\b", r"\bipos?\b",
            r"\binitial public offering\b", r"\bstartups?\b", r"\bfounders?\b",
            r"\bco-founders?\b", r"\bventure debt\b", r"\baccelerators?\b",
            r"\by combinator\b", r"\bantitrust\b", r"\bsec filing\b",
            r"\bquarterly earnings\b", r"\brevenue growth\b", r"\blayoffs?\b",
            r"\bchief executive\b", r"\bceo departure\b", r"\bprivate equity\b",
        ],
        standalone_signals=[
            r"\bbusiness\b", r"\bfunding\b", r"\binvestors?\b", r"\binvestment\b",
            r"\braised\b", r"\bshares\b", r"\bvaluation\b", r"\bmarket\b",
            r"\bdeal\b", r"\bexecutives?\b", r"\bcapital\b",
        ],
        prompt_template=BUSINESS_PROMPT_TEMPLATE,
    ),
]


# =============================================================================
# 4. Domain Registry Class
# =============================================================================

class DomainRegistry:
    """Central registry and lookup table for configured news domains."""

    def __init__(self, domains: Optional[List[DomainConfig]] = None):
        self._domains: Dict[str, DomainConfig] = {}
        source = domains if domains is not None else DEFAULT_DOMAINS
        for d in source:
            self._domains[d.domain_id.lower()] = d

    def normalize_domain_key(self, domain_key: str) -> str:
        """Normalizes a raw domain key or alias to canonical domain_id."""
        cleaned = domain_key.strip().lower()
        if cleaned in ("ai", "artificial intelligence"):
            return "ai"
        elif cleaned in ("technology", "tech"):
            return "technology"
        elif cleaned in ("science",):
            return "science"
        elif cleaned in ("cybersecurity", "security", "infosec"):
            return "cybersecurity"
        elif cleaned in ("business", "startups", "business and startups", "business & startups"):
            return "business"
        return cleaned

    def get_domain(self, domain_key: str) -> Optional[DomainConfig]:
        """Retrieves domain configuration by key or alias."""
        key = self.normalize_domain_key(domain_key)
        return self._domains.get(key)

    def is_domain_enabled(self, domain_key: str) -> bool:
        """Checks if a domain is active."""
        d = self.get_domain(domain_key)
        return d.enabled if d else False

    def set_domain_enabled(self, domain_key: str, enabled: bool) -> bool:
        """Enables or disables a domain."""
        d = self.get_domain(domain_key)
        if d:
            d.enabled = enabled
            return True
        return False

    def list_domains(self, enabled_only: bool = True) -> List[DomainConfig]:
        """Lists registered domain configurations."""
        if enabled_only:
            return [d for d in self._domains.values() if d.enabled]
        return list(self._domains.values())

    def get_canonical_name(self, domain_key: str) -> str:
        """Returns the canonical display name for a domain key."""
        d = self.get_domain(domain_key)
        if d:
            return d.display_name
        return domain_key.strip().title()

    def get_allowed_topics(self, domain_key: str) -> List[str]:
        """Returns the controlled topics for a domain."""
        d = self.get_domain(domain_key)
        if d and d.allowed_topics:
            return d.allowed_topics
        return ["Other"]

    def get_prompt_template(self, domain_key: str) -> str:
        """Returns the compact prompt template for a domain."""
        d = self.get_domain(domain_key)
        if d and d.prompt_template:
            return d.prompt_template
        return AI_PROMPT_TEMPLATE


# Global default registry singleton
_GLOBAL_REGISTRY: Optional[DomainRegistry] = None


def get_domain_registry() -> DomainRegistry:
    """Returns the shared DomainRegistry singleton."""
    global _GLOBAL_REGISTRY
    if _GLOBAL_REGISTRY is None:
        _GLOBAL_REGISTRY = DomainRegistry()
    return _GLOBAL_REGISTRY
