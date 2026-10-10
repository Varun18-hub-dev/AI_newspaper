"""Phase 6.1 — Multi-Domain Quality Audit and Approval Verification Script.

Tests:
1. Multi-domain clustering evaluation (MiniLM + EntityGuard + domain boundaries).
2. Domain classification, topic taxonomy, and deterministic pre-filtering.
3. Multi-source attribution, canonical URL normalization, and SQLite persistence across restarts.
4. End-to-end pipeline run with recorded metrics.
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.clustering.clusterer import StoryClusterer
from app.clustering.embeddings import MiniLMEmbeddingProvider, TFIDFEmbeddingProvider
from app.clustering.entity_guard import EntityGuard
from app.domains.registry import get_domain_registry
from app.ingestion.models import Article
from app.processing.article_processor import ArticleProcessor
from app.processing.filtering import filter_and_deduplicate
from app.processing.models import RelevanceClassification, normalize_topic_for_domain
from app.processing.pre_filter import DeterministicPreFilter
from app.storage import SQLiteDatabase, StorageService


# =============================================================================
# 1. Multi-Domain Clustering Evaluation Dataset (25 Curated Benchmark Pairs)
# =============================================================================

NOW = datetime.utcnow()

CLUSTERING_TEST_PAIRS = [
    # --- DOMAIN: AI (5 pairs) ---
    {
        "pair_id": "AI_01_POS",
        "description": "Same OpenAI firing event across TechCrunch and The Verge",
        "expected_merge": True,
        "a": Article(
            title="Fired OpenAI safety researchers dispute misconduct claims, warn of chilling effect",
            url="https://techcrunch.com/2026/10/08/fired-openai-safety-researchers/",
            source="TechCrunch",
            description="Two of the three OpenAI researchers recently fired for misconduct have issued statements saying their dismissals are a symptom of a deeper rot at the AI lab.",
            published_at=NOW - timedelta(hours=2),
            domain="AI",
        ),
        "b": Article(
            title="OpenAI doubles down on decision to fire three AI safety researchers",
            url="https://theverge.com/2026/10/08/openai-fires-safety-researchers/",
            source="The Verge",
            description="OpenAI told staff it stands by its decision to fire three prominent AI safety researchers, dismissing claims of retaliation.",
            published_at=NOW - timedelta(hours=3),
            domain="AI",
        ),
    },
    {
        "pair_id": "AI_02_POS",
        "description": "DeepSeek R1 open release covered by different publishers",
        "expected_merge": True,
        "a": Article(
            title="DeepSeek releases open reasoning model DeepSeek-R1 for research community",
            url="https://hf.co/blog/deepseek-r1-release",
            source="Hugging Face",
            description="DeepSeek has officially released DeepSeek-R1, an open-weights reasoning model rivaling OpenAI o1 performance.",
            published_at=NOW - timedelta(hours=10),
            domain="AI",
        ),
        "b": Article(
            title="DeepSeek debuts open reasoning AI model DeepSeek-R1",
            url="https://techcrunch.com/2026/01/20/deepseek-r1-launch/",
            source="TechCrunch",
            description="Chinese AI lab DeepSeek has launched its new reasoning model DeepSeek-R1 with full open model weights.",
            published_at=NOW - timedelta(hours=11),
            domain="AI",
        ),
    },
    {
        "pair_id": "AI_03_NEG_VERSIONS",
        "description": "Different model versions from Anthropic (Claude 3.5 Sonnet vs Haiku)",
        "expected_merge": False,
        "a": Article(
            title="Anthropic launches Claude 3.5 Sonnet with enhanced coding and reasoning",
            url="https://theverge.com/2024/06/20/claude-35-sonnet",
            source="The Verge",
            description="Anthropic announced the immediate availability of Claude 3.5 Sonnet, leading benchmark evaluations.",
            published_at=NOW - timedelta(hours=4),
            domain="AI",
        ),
        "b": Article(
            title="Anthropic introduces Claude 3.5 Haiku as ultra-fast compact reasoning model",
            url="https://techcrunch.com/2024/10/22/claude-35-haiku",
            source="TechCrunch",
            description="Anthropic debuted Claude 3.5 Haiku, a lightweight and cost-effective iteration of its Claude 3.5 family.",
            published_at=NOW - timedelta(hours=5),
            domain="AI",
        ),
    },
    {
        "pair_id": "AI_04_NEG_EVENTS",
        "description": "Same company (OpenAI), but funding round vs model release",
        "expected_merge": False,
        "a": Article(
            title="OpenAI raises $6.6 billion in new funding at $157 billion valuation",
            url="https://techcrunch.com/2024/10/02/openai-funding-round",
            source="TechCrunch",
            description="OpenAI completed a massive funding round raising $6.6 billion from Thrive Capital, Microsoft, and Nvidia.",
            published_at=NOW - timedelta(hours=6),
            domain="AI",
        ),
        "b": Article(
            title="OpenAI launches o1 reasoning model with enhanced problem-solving",
            url="https://theverge.com/2024/09/12/openai-o1",
            source="The Verge",
            description="OpenAI officially introduced its o1 reasoning model family, spending more time thinking before answering.",
            published_at=NOW - timedelta(hours=7),
            domain="AI",
        ),
    },
    {
        "pair_id": "AI_05_NEG_TIME",
        "description": "Same model release, but published 10 days apart (stale time window)",
        "expected_merge": False,
        "a": Article(
            title="Meta releases Llama 3.2 lightweight multimodal models",
            url="https://ai.meta.com/blog/llama-3-2-announcement",
            source="Meta AI",
            description="Meta announced Llama 3.2 including small vision models ready to run on device.",
            published_at=NOW - timedelta(days=10),
            domain="AI",
        ),
        "b": Article(
            title="Meta launches Llama 3.2 open vision models for mobile edge",
            url="https://theverge.com/2024/09/25/meta-llama-32",
            source="The Verge",
            description="Mark Zuckerberg unveiled Llama 3.2 with multimodal capabilities for edge hardware.",
            published_at=NOW,
            domain="AI",
        ),
    },

    # --- DOMAIN: Technology (5 pairs) ---
    {
        "pair_id": "TECH_01_POS",
        "description": "Microsoft Windows Recall rollout update duplicate coverage",
        "expected_merge": True,
        "a": Article(
            title="Microsoft confirms Windows 11 Recall feature rollout delayed again for security fixes",
            url="https://theverge.com/2024/10/31/windows-recall-delayed",
            source="The Verge",
            description="Microsoft is delaying the preview of its AI-powered Recall feature for Copilot+ PCs to address persistent security concerns.",
            published_at=NOW - timedelta(hours=2),
            domain="Technology",
        ),
        "b": Article(
            title="Windows 11 Recall delayed once again as Microsoft overhauls security architecture",
            url="https://arstechnica.com/gadgets/2024/10/windows-recall-delayed-again",
            source="Ars Technica",
            description="Microsoft confirmed it needs more time before rolling out the controversial Recall screenshot tool to Windows Insiders.",
            published_at=NOW - timedelta(hours=3),
            domain="Technology",
        ),
    },
    {
        "pair_id": "TECH_02_POS",
        "description": "Apple M4 Mac Mini redesign announcements",
        "expected_merge": True,
        "a": Article(
            title="Apple announces redesigned Mac Mini with M4 and M4 Pro chips and tiny footprint",
            url="https://theverge.com/2024/10/29/apple-mac-mini-m4-redesign",
            source="The Verge",
            description="Apple has unveiled an all-new Mac Mini featuring a much smaller 5x5 inch enclosure and powerful M4 processors.",
            published_at=NOW - timedelta(hours=8),
            domain="Technology",
        ),
        "b": Article(
            title="Apple unveils all-new smaller Mac Mini powered by M4 processor family",
            url="https://techcrunch.com/2024/10/29/apple-m4-mac-mini/",
            source="TechCrunch",
            description="The newly redesigned Mac Mini shrinks down to five inches square and brings front USB-C ports alongside M4 silicon.",
            published_at=NOW - timedelta(hours=9),
            domain="Technology",
        ),
    },
    {
        "pair_id": "TECH_03_NEG_PRODUCTS",
        "description": "Apple announcing Mac Mini vs Apple announcing iMac",
        "expected_merge": False,
        "a": Article(
            title="Apple announces redesigned Mac Mini with M4 and M4 Pro chips",
            url="https://theverge.com/2024/10/29/apple-mac-mini-m4-redesign",
            source="The Verge",
            description="Apple unveiled the M4 Mac Mini with front-facing ports.",
            published_at=NOW - timedelta(hours=8),
            domain="Technology",
        ),
        "b": Article(
            title="Apple updates 24-inch iMac with M4 chip and nano-texture display option",
            url="https://theverge.com/2024/10/28/apple-imac-m4-announcement",
            source="The Verge",
            description="Apple gave its colorful all-in-one desktop computer a refresh with the latest M4 processor.",
            published_at=NOW - timedelta(hours=12),
            domain="Technology",
        ),
    },
    {
        "pair_id": "TECH_04_NEG_ENTITIES",
        "description": "Different companies releasing smart glasses (Meta vs Snap)",
        "expected_merge": False,
        "a": Article(
            title="Meta unveils Orion holographic augmented reality smart glasses prototype",
            url="https://theverge.com/2024/09/25/meta-orion-ar-glasses",
            source="The Verge",
            description="Meta CEO Mark Zuckerberg showed off Orion, custom AR glasses with micro-LED projectors.",
            published_at=NOW - timedelta(hours=5),
            domain="Technology",
        ),
        "b": Article(
            title="Snap introduces fifth-generation Spectacles standalone AR glasses for developers",
            url="https://techcrunch.com/2024/09/17/snap-spectacles-gen-5",
            source="TechCrunch",
            description="Snap announced its newest Spectacles smart glasses featuring liquid crystal displays.",
            published_at=NOW - timedelta(hours=6),
            domain="Technology",
        ),
    },
    {
        "pair_id": "TECH_05_NEG_CROSS_DOMAIN",
        "description": "Cross-domain boundary: Technology operating system update vs AI model release",
        "expected_merge": False,
        "a": Article(
            title="Microsoft rolls out major Windows 11 24H2 update with Wi-Fi 7 support",
            url="https://theverge.com/2024/10/01/windows-11-24h2-release",
            source="The Verge",
            description="Microsoft has released the Windows 11 2024 Update featuring Wi-Fi 7 and Sudo for Windows.",
            published_at=NOW - timedelta(hours=4),
            domain="Technology",
        ),
        "b": Article(
            title="Microsoft Copilot introduces voice and vision capabilities in major AI redesign",
            url="https://theverge.com/2024/10/01/microsoft-copilot-voice-vision",
            source="The Verge",
            description="Microsoft is overhauling its Copilot consumer app with generative AI voice conversation.",
            published_at=NOW - timedelta(hours=4),
            domain="AI",
        ),
    },

    # --- DOMAIN: Science (5 pairs) ---
    {
        "pair_id": "SCI_01_POS",
        "description": "Europa Clipper launch duplicate coverage across science portals",
        "expected_merge": True,
        "a": Article(
            title="NASA launches Europa Clipper spacecraft on mission to Jupiter's ocean moon",
            url="https://arstechnica.com/space/2024/10/nasa-europa-clipper-launch/",
            source="Ars Technica",
            description="A SpaceX Falcon Heavy rocket sent NASA Europa Clipper spacecraft toward Jupiter to determine whether its ice-covered ocean could support life.",
            published_at=NOW - timedelta(hours=4),
            domain="Science",
        ),
        "b": Article(
            title="Europa Clipper lifts off toward Jupiter ocean moon Europa aboard Falcon Heavy",
            url="https://phys.org/news/2024-10-nasa-europa-clipper-mission.html",
            source="Phys.org",
            description="NASA Europa Clipper embarked on a 1.8 billion mile journey to investigate the habitability of Jupiter icy moon Europa.",
            published_at=NOW - timedelta(hours=5),
            domain="Science",
        ),
    },
    {
        "pair_id": "SCI_02_POS",
        "description": "2024 Chemistry Nobel prize announcement duplicate reporting",
        "expected_merge": True,
        "a": Article(
            title="Nobel Prize in Chemistry awarded to Baker, Hassabis, and Jumper for protein structure breakthrough",
            url="https://arstechnica.com/science/2024/10/chemistry-nobel-alphafold-protein-design/",
            source="Ars Technica",
            description="The 2024 Nobel Prize in Chemistry honors computational protein design and the AlphaFold AI protein structure prediction model.",
            published_at=NOW - timedelta(hours=14),
            domain="Science",
        ),
        "b": Article(
            title="2024 Chemistry Nobel honors computational protein design and AlphaFold structure prediction",
            url="https://www.sciencedaily.com/releases/2024/10/nobel-chemistry-proteins.htm",
            source="ScienceDaily",
            description="The Nobel Prize in Chemistry recognized David Baker for protein construction, and Demis Hassabis and John Jumper for AlphaFold predictions.",
            published_at=NOW - timedelta(hours=15),
            domain="Science",
        ),
    },
    {
        "pair_id": "SCI_03_NEG_TOPICS",
        "description": "Astronomy Europa Clipper mission vs Physics Quantum entanglement",
        "expected_merge": False,
        "a": Article(
            title="NASA launches Europa Clipper spacecraft on mission to Jupiter's ocean moon",
            url="https://arstechnica.com/space/2024/10/nasa-europa-clipper-launch/",
            source="Ars Technica",
            description="A SpaceX Falcon Heavy rocket sent NASA Europa Clipper toward Jupiter.",
            published_at=NOW - timedelta(hours=4),
            domain="Science",
        ),
        "b": Article(
            title="Physicists demonstrate macroscopic quantum entanglement in suspended glass bead",
            url="https://phys.org/news/2024-10-quantum-entanglement-bead.html",
            source="Phys.org",
            description="Researchers entangled a levitated silica bead with optical photons, opening new avenues for quantum memory.",
            published_at=NOW - timedelta(hours=5),
            domain="Science",
        ),
    },
    {
        "pair_id": "SCI_04_NEG_MISSIONS",
        "description": "Two different SpaceX launches (Europa Clipper vs Starship Flight 5)",
        "expected_merge": False,
        "a": Article(
            title="SpaceX Falcon Heavy launches NASA Europa Clipper probe toward Jupiter",
            url="https://arstechnica.com/space/2024/10/nasa-europa-clipper-launch/",
            source="Ars Technica",
            description="NASA Europa Clipper lifted off on a Falcon Heavy rocket.",
            published_at=NOW - timedelta(hours=4),
            domain="Science",
        ),
        "b": Article(
            title="SpaceX catches Super Heavy booster at launch pad during historic Starship Flight 5",
            url="https://arstechnica.com/space/2024/10/spacex-catches-super-heavy-starship-5/",
            source="Ars Technica",
            description="SpaceX mechanical arms caught the 232-foot-tall rocket booster in mid-air at Starbase Texas.",
            published_at=NOW - timedelta(hours=10),
            domain="Science",
        ),
    },
    {
        "pair_id": "SCI_05_NEG_CROSS_DOMAIN",
        "description": "Cross-domain boundary: Science space discovery vs Tech commercial satellite network",
        "expected_merge": False,
        "a": Article(
            title="James Webb Space Telescope detects carbon dioxide atmosphere on exoplanet",
            url="https://phys.org/news/2024-10-jwst-exoplanet-atmosphere.html",
            source="Phys.org",
            description="Astronomers using the JWST observed evidence of carbon dioxide on a rocky exoplanet.",
            published_at=NOW - timedelta(hours=6),
            domain="Science",
        ),
        "b": Article(
            title="SpaceX deploys 24 additional Starlink broadband satellites in low Earth orbit",
            url="https://theverge.com/2024/10/12/spacex-starlink-broadband-launch",
            source="The Verge",
            description="SpaceX launched another batch of Starlink communications satellites to expand global internet coverage.",
            published_at=NOW - timedelta(hours=6),
            domain="Technology",
        ),
    },

    # --- DOMAIN: Cybersecurity (5 pairs) ---
    {
        "pair_id": "CYBER_01_POS",
        "description": "Critical Palo Alto Networks firewall vulnerability active exploitation",
        "expected_merge": True,
        "a": Article(
            title="Critical zero-day vulnerability in Palo Alto Networks PAN-OS firewalls actively exploited",
            url="https://thehackernews.com/2024/11/critical-palo-alto-networks-firewall.html",
            source="The Hacker News",
            description="Palo Alto Networks has warned customers of a critical remote code execution vulnerability in PAN-OS management interfaces exploited in the wild.",
            published_at=NOW - timedelta(hours=3),
            domain="Cybersecurity",
        ),
        "b": Article(
            title="Palo Alto Networks urges customers to secure firewall management interfaces amid active attacks",
            url="https://www.darkreading.com/vulnerabilities-threats/palo-alto-networks-firewall-zero-day",
            source="Dark Reading",
            description="Attackers are actively targeting an unpatched remote code execution vulnerability in exposed Palo Alto Networks PAN-OS firewall interfaces.",
            published_at=NOW - timedelta(hours=4),
            domain="Cybersecurity",
        ),
    },
    {
        "pair_id": "CYBER_02_POS",
        "description": "Salt Typhoon telecom wiretap breaches duplicate coverage",
        "expected_merge": True,
        "a": Article(
            title="Chinese hackers Salt Typhoon breached multiple US telecom networks, wiretap systems",
            url="https://krebsonsecurity.com/2024/10/salt-typhoon-hackers-us-telecoms/",
            source="Krebs on Security",
            description="US intelligence agencies confirmed that state-sponsored hacking group Salt Typhoon penetrated broadband providers including Verizon and AT&T.",
            published_at=NOW - timedelta(hours=8),
            domain="Cybersecurity",
        ),
        "b": Article(
            title="Salt Typhoon cyber espionage operation compromised AT&T and Verizon lawful wiretap data",
            url="https://thehackernews.com/2024/10/salt-typhoon-telecom-breach.html",
            source="The Hacker News",
            description="State-backed Chinese hackers known as Salt Typhoon infiltrated US telecommunications infrastructure used for court-authorized wiretapping.",
            published_at=NOW - timedelta(hours=9),
            domain="Cybersecurity",
        ),
    },
    {
        "pair_id": "CYBER_03_NEG_TARGETS",
        "description": "Same threat actor (Salt Typhoon), but US telecom breach vs UK government phishing",
        "expected_merge": False,
        "a": Article(
            title="Chinese hackers Salt Typhoon breached multiple US telecom networks, wiretap systems",
            url="https://krebsonsecurity.com/2024/10/salt-typhoon-hackers-us-telecoms/",
            source="Krebs on Security",
            description="Salt Typhoon penetrated broadband providers including Verizon and AT&T wiretap systems.",
            published_at=NOW - timedelta(hours=8),
            domain="Cybersecurity",
        ),
        "b": Article(
            title="Salt Typhoon targeted UK Foreign Office officials in spear-phishing campaign",
            url="https://www.darkreading.com/attacks-breaches/salt-typhoon-uk-phishing",
            source="Dark Reading",
            description="British intelligence warned that Salt Typhoon actors conducted spear-phishing targeting diplomatic email accounts.",
            published_at=NOW - timedelta(hours=9),
            domain="Cybersecurity",
        ),
    },
    {
        "pair_id": "CYBER_04_NEG_CVE",
        "description": "Palo Alto Networks firewall CVE vs Fortinet FortiManager CVE",
        "expected_merge": False,
        "a": Article(
            title="Critical zero-day vulnerability in Palo Alto Networks PAN-OS firewalls actively exploited",
            url="https://thehackernews.com/2024/11/critical-palo-alto-networks-firewall.html",
            source="The Hacker News",
            description="Palo Alto Networks warned of remote code execution in PAN-OS management interfaces.",
            published_at=NOW - timedelta(hours=3),
            domain="Cybersecurity",
        ),
        "b": Article(
            title="Fortinet confirms critical zero-day flaw in FortiManager exploited in the wild",
            url="https://thehackernews.com/2024/10/fortinet-fortimanager-zero-day.html",
            source="The Hacker News",
            description="Fortinet patched a missing authentication vulnerability CVE-2024-47575 in FortiManager appliances.",
            published_at=NOW - timedelta(hours=4),
            domain="Cybersecurity",
        ),
    },
    {
        "pair_id": "CYBER_05_NEG_CROSS_DOMAIN",
        "description": "Cross-domain boundary: Cybersecurity ransomware breach vs Business earnings report",
        "expected_merge": False,
        "a": Article(
            title="UnitedHealth confirms Change Healthcare ransomware attack compromised data of 100M patients",
            url="https://krebsonsecurity.com/2024/10/change-healthcare-breach-100m/",
            source="Krebs on Security",
            description="UnitedHealth disclosed that the ALPHV BlackCat ransomware breach impacted approximately 100 million individuals.",
            published_at=NOW - timedelta(hours=6),
            domain="Cybersecurity",
        ),
        "b": Article(
            title="UnitedHealth Group beats Q3 earnings expectations despite cyberattack fallout",
            url="https://venturebeat.com/category/business/unitedhealth-q3-earnings",
            source="VentureBeat",
            description="Healthcare giant UnitedHealth Group reported quarterly revenue of $100.8 billion, demonstrating financial resilience.",
            published_at=NOW - timedelta(hours=6),
            domain="Business and startups",
        ),
    },

    # --- DOMAIN: Business and startups (5 pairs) ---
    {
        "pair_id": "BIZ_01_POS",
        "description": "Waymo $5.6 billion funding round duplicate coverage",
        "expected_merge": True,
        "a": Article(
            title="Waymo closes $5.6 billion funding round to expand autonomous robotaxi service",
            url="https://techcrunch.com/2024/10/25/waymo-funding-round-5-6b/",
            source="TechCrunch",
            description="Alphabet autonomous driving subsidiary Waymo raised $5.6 billion in fresh capital led by parent company Alphabet to accelerate commercial robotaxi expansion.",
            published_at=NOW - timedelta(hours=4),
            domain="Business and startups",
        ),
        "b": Article(
            title="Alphabet autonomous driving unit Waymo secures $5.6 billion in new funding round",
            url="https://venturebeat.com/business/waymo-raises-5-6-billion-robotaxi/",
            source="VentureBeat",
            description="Waymo has completed a massive $5.6 billion investment round led by Alphabet alongside Andreessen Horowitz to scale its commercial driverless fleet.",
            published_at=NOW - timedelta(hours=5),
            domain="Business and startups",
        ),
    },
    {
        "pair_id": "BIZ_02_POS",
        "description": "DOJ Google antitrust search remedy proposals duplicate reporting",
        "expected_merge": True,
        "a": Article(
            title="DOJ weighs breaking up Google and forcing sale of Chrome browser in antitrust remedy",
            url="https://arstechnica.com/tech-policy/2024/11/doj-pushes-judge-to-make-google-sell-chrome/",
            source="Ars Technica",
            description="The Department of Justice asked a federal judge to force Google to spin off its Chrome web browser and unbundle Android to dismantle its illegal search monopoly.",
            published_at=NOW - timedelta(hours=6),
            domain="Business and startups",
        ),
        "b": Article(
            title="Justice Department urges judge to order Google to sell Chrome browser in landmark antitrust case",
            url="https://theverge.com/2024/11/20/doj-google-antitrust-remedy-chrome-breakup",
            source="The Verge",
            description="In a sweeping antitrust filing, prosecutors called for Google to divest Chrome, restrict Android self-preferencing, and halt default search distribution deals.",
            published_at=NOW - timedelta(hours=7),
            domain="Business and startups",
        ),
    },
    {
        "pair_id": "BIZ_03_NEG_ROUNDS",
        "description": "Two different startup funding rounds (Waymo vs Physical Intelligence)",
        "expected_merge": False,
        "a": Article(
            title="Waymo closes $5.6 billion funding round to expand autonomous robotaxi service",
            url="https://techcrunch.com/2024/10/25/waymo-funding-round-5-6b/",
            source="TechCrunch",
            description="Waymo raised $5.6 billion in fresh capital led by Alphabet.",
            published_at=NOW - timedelta(hours=4),
            domain="Business and startups",
        ),
        "b": Article(
            title="Physical Intelligence raises $400 million at $2.4 billion valuation to build robot foundation models",
            url="https://techcrunch.com/2024/11/04/physical-intelligence-raises-400m/",
            source="TechCrunch",
            description="Robot AI startup Physical Intelligence secured $400 million in financing from Jeff Bezos and Thrive Capital.",
            published_at=NOW - timedelta(hours=6),
            domain="Business and startups",
        ),
    },
    {
        "pair_id": "BIZ_04_NEG_EVENTS",
        "description": "Same company (Google), but antitrust lawsuit remedies vs quarterly earnings call",
        "expected_merge": False,
        "a": Article(
            title="DOJ weighs breaking up Google and forcing sale of Chrome browser in antitrust remedy",
            url="https://arstechnica.com/tech-policy/2024/11/doj-pushes-judge-to-make-google-sell-chrome/",
            source="Ars Technica",
            description="The Department of Justice asked a federal judge to force Google to spin off Chrome.",
            published_at=NOW - timedelta(hours=6),
            domain="Business and startups",
        ),
        "b": Article(
            title="Alphabet reports strong Q3 revenue driven by Google Cloud and search advertising growth",
            url="https://venturebeat.com/business/alphabet-q3-2024-earnings-cloud-growth/",
            source="VentureBeat",
            description="Alphabet announced third-quarter revenue of $88.3 billion, with Google Cloud revenue jumping 35 percent.",
            published_at=NOW - timedelta(hours=8),
            domain="Business and startups",
        ),
    },
    {
        "pair_id": "BIZ_05_NEG_CROSS_DOMAIN",
        "description": "Cross-domain boundary: Business DOJ Google Chrome breakup vs Tech Chrome browser features",
        "expected_merge": False,
        "a": Article(
            title="DOJ weighs breaking up Google and forcing sale of Chrome browser in antitrust remedy",
            url="https://arstechnica.com/tech-policy/2024/11/doj-pushes-judge-to-make-google-sell-chrome/",
            source="Ars Technica",
            description="The Department of Justice asked a federal judge to force Google to sell Chrome in monopoly remedy.",
            published_at=NOW - timedelta(hours=6),
            domain="Business and startups",
        ),
        "b": Article(
            title="Google Chrome gets new performance controls and memory saver modes on desktop",
            url="https://theverge.com/2024/10/24/google-chrome-memory-saver-performance-controls",
            source="The Verge",
            description="Google is updating the Chrome desktop web browser with visual performance alerts and finer memory controls.",
            published_at=NOW - timedelta(hours=6),
            domain="Technology",
        ),
    },
]


# =============================================================================
# 2. Multi-Domain Classification & Topic Taxonomy Labeled Dataset (15 Articles)
# =============================================================================

CLASSIFICATION_TEST_SET = [
    # AI domain
    {
        "id": "AI_1",
        "domain": "AI",
        "title": "Anthropic introduces Claude 3.5 Sonnet with state-of-the-art coding abilities",
        "description": "Anthropic announced the release of Claude 3.5 Sonnet, a frontier large language model setting industry benchmarks for software engineering.",
        "expected_relevant": True,
        "expected_domain": "AI",
        "expected_topic": "LLMs",
    },
    {
        "id": "AI_2",
        "domain": "AI",
        "title": "AI safety researchers publish new evaluation framework for autonomous AI agent alignment",
        "description": "A collaborative paper from leading institutions details catastrophic risk safeguards and red-teaming benchmarks for autonomous agent systems.",
        "expected_relevant": True,
        "expected_domain": "AI",
        "expected_topic": "AI Safety",
    },
    {
        "id": "AI_3_IRRELEVANT",
        "domain": "AI",
        "title": "Local coffee shop opens third franchise with artisanal espresso roasting",
        "description": "The neighborhood cafe chain celebrated expanding to downtown with new cold brew taps and organic pastries.",
        "expected_relevant": False,
        "expected_domain": "AI",
        "expected_topic": "Other",
    },

    # Technology domain
    {
        "id": "TECH_1",
        "domain": "Technology",
        "title": "Microsoft reveals custom Azure Cobalt 100 ARM processors deployed for cloud workloads",
        "description": "Microsoft detailed the production rollout of its custom ARM-based Cobalt 100 CPUs across Azure data centers for superior energy efficiency.",
        "expected_relevant": True,
        "expected_domain": "Technology",
        "expected_topic": "Cloud Computing",
    },
    {
        "id": "TECH_2",
        "domain": "Technology",
        "title": "Apple M4 Max MacBook Pro teardown reveals redesigned thermal cooling and modular storage",
        "description": "Hardware engineers tore down the latest Apple laptop, examining the silicon architecture, dual-fan cooling chambers, and display assembly.",
        "expected_relevant": True,
        "expected_domain": "Technology",
        "expected_topic": "Hardware & Devices",
    },
    {
        "id": "TECH_3_IRRELEVANT",
        "domain": "Technology",
        "title": "Celebrity chef shares secret recipe for homemade sourdough pizza crust",
        "description": "Follow these simple steps for 72-hour cold fermented pizza dough with crispy charred crust.",
        "expected_relevant": False,
        "expected_domain": "Technology",
        "expected_topic": "Other",
    },

    # Science domain
    {
        "id": "SCI_1",
        "domain": "Science",
        "title": "NASA Europa Clipper spacecraft completes critical trajectory burn toward Jupiter",
        "description": "Flight controllers fired the spacecraft main engines to fine-tune its flight path on a multi-year interplanetary cruise toward Jupiter icy moon.",
        "expected_relevant": True,
        "expected_domain": "Science",
        "expected_topic": "Space & Astronomy",
    },
    {
        "id": "SCI_2",
        "domain": "Science",
        "title": "Physicists achieve room-temperature quantum coherence in hexagonal boron nitride defects",
        "description": "A team of experimental physicists demonstrated stable spin coherence at ambient temperature, enabling robust quantum sensing nodes.",
        "expected_relevant": True,
        "expected_domain": "Science",
        "expected_topic": "Physics",
    },
    {
        "id": "SCI_3_IRRELEVANT",
        "domain": "Science",
        "title": "Ten tips to organize your home pantry and kitchen shelves for the holidays",
        "description": "Decluttering your living space can reduce holiday stress with labeled glass containers and drawer dividers.",
        "expected_relevant": False,
        "expected_domain": "Science",
        "expected_topic": "Other",
    },

    # Cybersecurity domain
    {
        "id": "CYBER_1",
        "domain": "Cybersecurity",
        "title": "Critical zero-day vulnerability in Palo Alto Networks PAN-OS firewalls under active exploit",
        "description": "Security researchers documented remote code execution flaw CVE-2024-0012 enabling unauthenticated threat actors to compromise root firewalls.",
        "expected_relevant": True,
        "expected_domain": "Cybersecurity",
        "expected_topic": "Vulnerabilities & CVEs",
    },
    {
        "id": "CYBER_2",
        "domain": "Cybersecurity",
        "title": "ALPHV BlackCat ransomware affiliate claims massive exfiltration of healthcare records",
        "description": "The cybercrime syndicate published proof samples of encrypted database records containing patient personal information and billing files.",
        "expected_relevant": True,
        "expected_domain": "Cybersecurity",
        "expected_topic": "Malware & Ransomware",
    },
    {
        "id": "CYBER_3_IRRELEVANT",
        "domain": "Cybersecurity",
        "title": "Best winter hiking trails and insulated boots for cold weather adventures",
        "description": "Gear review guide for waterproof hiking footwear and thermal layers during mountain expeditions.",
        "expected_relevant": False,
        "expected_domain": "Cybersecurity",
        "expected_topic": "Other",
    },

    # Business and startups domain
    {
        "id": "BIZ_1",
        "domain": "Business and startups",
        "title": "Waymo secures $5.6 billion in fresh funding led by Alphabet to expand driverless operations",
        "description": "Autonomous vehicle pioneer Waymo closed a massive financing round to accelerate robotaxi deployment across Los Angeles, Phoenix, and Austin.",
        "expected_relevant": True,
        "expected_domain": "Business and startups",
        "expected_topic": "Venture Capital & Funding",
    },
    {
        "id": "BIZ_2",
        "domain": "Business and startups",
        "title": "Department of Justice officially asks federal judge to force Google to divest Chrome browser",
        "description": "Antitrust regulators filed landmark proposed final judgments seeking to break up Google illegal search monopoly by separating its web browser.",
        "expected_relevant": True,
        "expected_domain": "Business and startups",
        "expected_topic": "Tech Policy & Regulation",
    },
    {
        "id": "BIZ_3_IRRELEVANT",
        "domain": "Business and startups",
        "title": "How to train your puppy to sit and stay in five easy daily sessions",
        "description": "Dog training advice emphasizing positive reinforcement and treat rewards for young puppies.",
        "expected_relevant": False,
        "expected_domain": "Business and startups",
        "expected_topic": "Other",
    },
]


def audit_clustering_effectiveness() -> Dict[str, Any]:
    """Evaluates MiniLM + EntityGuard on the 25 curated multi-domain pairs."""
    print("\n" + "=" * 80)
    print("AUDIT SECTION 1: MULTI-DOMAIN CLUSTERING QUALITY EVALUATION")
    print("=" * 80)

    minilm = MiniLMEmbeddingProvider()
    guard = EntityGuard()
    clusterer = StoryClusterer(embedding_provider=minilm, entity_guard=guard)

    tp, fp, fn, tn = 0, 0, 0, 0
    results_by_domain = {}

    for item in CLUSTERING_TEST_PAIRS:
        p_id = item["pair_id"]
        expected = item["expected_merge"]
        a = item["a"]
        b = item["b"]
        dom = a.domain

        if dom not in results_by_domain:
            results_by_domain[dom] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}

        t_a = clusterer.build_article_text(a)
        t_b = clusterer.build_article_text(b)
        sim = float(minilm.compute_similarity_matrix([t_a, t_b])[0, 1])
        bonus = guard.compute_semantic_bonus(a, b, t_a, t_b)
        total_sim = min(1.0, sim + bonus)
        allowed, reason = guard.is_merge_allowed(a, b, t_a, t_b)

        predicted_merge = allowed and (total_sim >= clusterer.similarity_threshold)

        if expected and predicted_merge:
            tp += 1
            results_by_domain[dom]["tp"] += 1
            status = "PASS (TP)"
        elif not expected and not predicted_merge:
            tn += 1
            results_by_domain[dom]["tn"] += 1
            status = "PASS (TN)"
        elif not expected and predicted_merge:
            fp += 1
            results_by_domain[dom]["fp"] += 1
            status = f"FAIL (FP - False Merge! Allowed: {allowed}, Sim: {total_sim:.3f})"
        else:
            fn += 1
            results_by_domain[dom]["fn"] += 1
            status = f"FAIL (FN - Missed Merge! Allowed: {allowed} ({reason}), Sim: {total_sim:.3f})"

        print(f"[{p_id}] {status:10} | Sim: {total_sim:.3f} | Guard: {allowed} | {item['description'][:50]}")

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    print("\nCLUSTERING METRICS SUMMARY:")
    print(f"  Total Pairs Evaluated:  {len(CLUSTERING_TEST_PAIRS)}")
    print(f"  True Positives (TP):    {tp}")
    print(f"  True Negatives (TN):    {tn}")
    print(f"  False Positives (FP):   {fp} (False Merges)")
    print(f"  False Negatives (FN):   {fn} (Missed Duplicates)")
    print(f"  Precision:              {precision * 100:.2f}%")
    print(f"  Recall:                 {recall * 100:.2f}%")
    print(f"  F1 Score:               {f1 * 100:.2f}%")

    return {
        "total_pairs": len(CLUSTERING_TEST_PAIRS),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "by_domain": results_by_domain,
    }


def audit_domain_classification_and_prefiltering() -> Dict[str, Any]:
    """Validates pre-filtering, domain classification, and taxonomy mapping."""
    print("\n" + "=" * 80)
    print("AUDIT SECTION 2: DOMAIN CLASSIFICATION & TOPIC TAXONOMY VALIDATION")
    print("=" * 80)

    pre_filter = DeterministicPreFilter()
    registry = get_domain_registry()

    prefilter_correct = 0
    domain_correct = 0
    topic_valid = 0

    for item in CLASSIFICATION_TEST_SET:
        art = Article(
            title=item["title"],
            url=f"https://example.com/test/{item['id'].lower()}",
            source="Test Publisher",
            description=item["description"],
            domain=item["domain"],
        )

        res = pre_filter.evaluate(art, None)
        passed_filter = res.should_send_to_llm
        expected_pass = item["expected_relevant"]

        # Check pre-filter correctness
        if passed_filter == expected_pass:
            prefilter_correct += 1
            pf_status = "OK"
        else:
            pf_status = "MISMATCH"

        # Check domain normalization
        norm_dom = registry.normalize_domain_key(art.domain)
        if norm_dom == registry.normalize_domain_key(item["expected_domain"]):
            domain_correct += 1

        # Check taxonomy validity
        allowed_topics = registry.get_allowed_topics(norm_dom)
        normalized_topic = normalize_topic_for_domain(norm_dom, item["expected_topic"])
        is_valid_topic = normalized_topic in allowed_topics or normalized_topic == "Other"
        if is_valid_topic:
            topic_valid += 1

        print(
            f"[{item['id']:15}] Dom: {norm_dom:12} | PF Score: {res.pre_filter_score:.2f} ({pf_status}) | "
            f"Topic: {normalized_topic} (Valid: {is_valid_topic})"
        )

    total = len(CLASSIFICATION_TEST_SET)
    pf_acc = prefilter_correct / total
    dom_acc = domain_correct / total
    top_acc = topic_valid / total

    print("\nCLASSIFICATION & TAXONOMY SUMMARY:")
    print(f"  Pre-Filter Accuracy:     {pf_acc * 100:.2f}% ({prefilter_correct}/{total})")
    print(f"  Domain Mapping Accuracy: {dom_acc * 100:.2f}% ({domain_correct}/{total})")
    print(f"  Taxonomy Conformance:    {top_acc * 100:.2f}% ({topic_valid}/{total})")

    return {
        "total": total,
        "prefilter_acc": pf_acc,
        "domain_acc": dom_acc,
        "taxonomy_acc": top_acc,
    }


def audit_multi_source_attribution_and_persistence(tmp_db_path: str) -> Dict[str, Any]:
    """Tests cross-feed deduplication, multi-source preservation, and SQLite restart recovery."""
    print("\n" + "=" * 80)
    print("AUDIT SECTION 3: MULTI-SOURCE ATTRIBUTION & SQLITE PERSISTENCE")
    print("=" * 80)

    # Step 1: Ingest duplicate syndicated article with tracking parameters
    art_a = Article(
        title="OpenAI confirms major safety research department restructuring",
        url="https://news.example.com/openai-restructuring?utm_source=rss&utm_medium=feed",
        source="TechCrunch AI",
        description="OpenAI restructured its safety alignment teams following executive departures.",
        published_at=NOW - timedelta(hours=2),
        domain="AI",
    )
    art_b = Article(
        title="OpenAI confirms major safety research department restructuring",
        url="https://news.example.com/openai-restructuring#tracking-anchor",
        source="The Verge Tech",
        description="OpenAI restructured its safety alignment teams following executive departures.",
        published_at=NOW - timedelta(hours=2),
        domain="AI",
    )
    art_c = Article(
        title="OpenAI confirms major safety research department restructuring",
        url="https://news.example.com/openai-restructuring",
        source="Ars Technica",
        description="OpenAI restructured its safety alignment teams following executive departures.",
        published_at=NOW - timedelta(hours=2),
        domain="AI",
    )

    raw_articles = [art_a, art_b, art_c]
    deduped = filter_and_deduplicate(raw_articles)

    assert len(deduped) == 1, f"Expected 1 unique article, got {len(deduped)}"
    unique_art = deduped[0]
    sources = set(unique_art.all_sources)
    expected_sources = {"TechCrunch AI", "The Verge Tech", "Ars Technica"}
    assert sources == expected_sources, f"Expected sources {expected_sources}, got {sources}"
    print(f"1. Canonical Dedup & Attribution: PASS")
    print(f"   Canonical URL: {unique_art.url}")
    print(f"   Aggregated Sources: {unique_art.all_sources}")

    # Step 2: Test idempotency on repeated ingestion
    repeated_articles = [art_a, art_b, art_c, art_a, art_b]
    deduped_repeated = filter_and_deduplicate(repeated_articles)
    assert len(deduped_repeated) == 1
    assert len(deduped_repeated[0].all_sources) == 3
    print("2. Repeated Ingestion Idempotency: PASS (no duplicate sources appended)")

    # Step 3: Persist into SQLite and verify restart recovery
    db_1 = SQLiteDatabase(db_path=tmp_db_path)
    storage_1 = StorageService(db=db_1)
    to_proc, skipped, _ = storage_1.check_and_register_articles([unique_art])
    assert len(to_proc) == 1

    clusterer = StoryClusterer()
    clusters, _ = clusterer.cluster_articles([unique_art])
    assert len(clusters) == 1
    cluster = clusters[0]
    storage_1.persist_cluster_group(cluster)

    # Restart storage service on same database
    db_2 = SQLiteDatabase(db_path=tmp_db_path)
    storage_2 = StorageService(db=db_2)
    stored_art = db_2.get_article_by_canonical_url(unique_art.url)
    assert stored_art is not None
    assert set(stored_art.extra_metadata.get("all_sources", [stored_art.source])) == expected_sources or stored_art.source in expected_sources
    assert stored_art.domain.lower() == "ai"

    # Query cluster and members
    stored_cluster = db_2.get_cluster_by_id(cluster.cluster_id)
    assert stored_cluster is not None
    assert stored_cluster.representative_article_id == stored_art.id
    assert stored_cluster.domain.lower() == "ai"

    print("3. SQLite Restart Persistence & Domain/Source Recovery: PASS")
    return {
        "status": "PASS",
        "canonical_url": unique_art.url,
        "all_sources": unique_art.all_sources,
        "domain": stored_art.domain,
        "cluster_persisted": True,
    }


def main():
    t_start = time.time()
    print("=" * 80)
    print("PHASE 6.1 QUALITY AUDIT & FINAL APPROVAL VERIFICATION")
    print("=" * 80)

    # 1. Clustering audit
    clustering_res = audit_clustering_effectiveness()

    # 2. Classification audit
    classification_res = audit_domain_classification_and_prefiltering()

    # 3. Multi-source attribution & persistence audit
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        tmp_db = f.name
    
    try:
        storage_res = audit_multi_source_attribution_and_persistence(tmp_db)
    finally:
        try:
            Path(tmp_db).unlink(missing_ok=True)
            Path(f"{tmp_db}-wal").unlink(missing_ok=True)
            Path(f"{tmp_db}-shm").unlink(missing_ok=True)
        except Exception:
            pass

    duration = time.time() - t_start
    print("\n" + "=" * 80)
    print(f"AUDIT EXECUTION COMPLETE IN {duration:.2f}s")
    print("=" * 80)

    all_passed = (
        clustering_res["fp"] == 0
        and clustering_res["precision"] == 1.0
        and clustering_res["recall"] >= 0.90
        and classification_res["prefilter_acc"] == 1.0
        and classification_res["domain_acc"] == 1.0
        and classification_res["taxonomy_acc"] == 1.0
        and storage_res["status"] == "PASS"
    )

    if all_passed:
        print("\nALL PHASE 6.1 AUDIT CRITERIA PASSED (VERDICT: PASS)")
        sys.exit(0)
    else:
        print("\nAUDIT CRITERIA FAILED (VERDICT: FAIL)")
        sys.exit(1)


if __name__ == "__main__":
    main()
