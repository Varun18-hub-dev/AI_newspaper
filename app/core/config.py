"""Configuration management module."""

import os
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field

# Load .env if present
try:
    from dotenv import load_dotenv

    # Root of the project
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    pass


class Settings(BaseModel):
    """Application settings loaded from environment variables."""

    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    )
    model_name: str = Field(
        default_factory=lambda: os.getenv("MODEL_NAME", "qwen2.5:3b")
    )
    temperature: float = Field(
        default_factory=lambda: float(os.getenv("TEMPERATURE", "0.0"))
    )
    max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("MAX_TOKENS", "128"))
    )
    request_timeout: float = Field(
        default_factory=lambda: float(os.getenv("REQUEST_TIMEOUT", "180.0"))
    )
    log_level: str = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )

    # Ingestion Configuration (Multi-Domain Phase 6)
    enabled_domains: list[str] = Field(
        default_factory=lambda: [
            d.strip().lower()
            for d in os.getenv(
                "ENABLED_DOMAINS",
                "ai,technology,science,cybersecurity,business",
            ).split(",")
            if d.strip()
        ]
    )
    ai_rss_feeds: list[str] = Field(
        default_factory=lambda: [
            url.strip()
            for url in os.getenv(
                "AI_RSS_FEEDS",
                "https://techcrunch.com/category/artificial-intelligence/feed/,"
                "https://theverge.com/rss/ai-artificial-intelligence/index.xml,"
                "https://huggingface.co/blog/feed.xml,"
                "https://feeds.arstechnica.com/arstechnica/technology-lab",
            ).split(",")
            if url.strip()
        ]
    )
    domain_rss_feeds: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "ai": [
                "https://techcrunch.com/category/artificial-intelligence/feed/",
                "https://theverge.com/rss/ai-artificial-intelligence/index.xml",
                "https://huggingface.co/blog/feed.xml",
                "https://feeds.arstechnica.com/arstechnica/technology-lab",
                "https://bair.berkeley.edu/blog/feed.xml",
            ],
            "technology": [
                "https://feeds.arstechnica.com/arstechnica/index",
                "https://theverge.com/rss/index.xml",
                "https://techcrunch.com/feed/",
            ],
            "science": [
                "https://feeds.arstechnica.com/arstechnica/science",
                "https://phys.org/rss-feed/",
                "https://www.sciencedaily.com/rss/top/science.xml",
                "https://www.nature.com/nature.rss",
                "https://www.quantamagazine.org/feed/",
            ],
            "cybersecurity": [
                "https://krebsonsecurity.com/feed/",
                "https://www.darkreading.com/rss.xml",
                "https://feeds.feedburner.com/TheHackersNews",
                "https://www.schneier.com/feed/atom/",
                "https://www.bleepingcomputer.com/feed/",
                "https://www.securityweek.com/feed/",
            ],
            "business": [
                "https://techcrunch.com/category/startups/feed/",
                "https://venturebeat.com/category/business/feed/",
                "https://feeds.arstechnica.com/arstechnica/tech-policy",
                "https://siliconangle.com/feed/",
            ],
        }
    )
    max_items_per_feed: int = Field(
        default_factory=lambda: int(os.getenv("MAX_ITEMS_PER_FEED", "15"))
    )
    max_classify_candidates: int = Field(
        default_factory=lambda: int(os.getenv("MAX_CLASSIFY_CANDIDATES", "10"))
    )
    qwen_max_candidates: int = Field(
        default_factory=lambda: int(os.getenv("QWEN_MAX_CANDIDATES", "10"))
    )

    # Multi-Source Ingestion Integration Configuration (Phase 9A)
    enable_arxiv: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_ARXIV", "true").lower() in ("true", "1", "yes")
    )
    arxiv_categories: list[str] = Field(
        default_factory=lambda: [
            c.strip()
            for c in os.getenv("ARXIV_CATEGORIES", "cs.AI,cs.LG,physics.gen-ph").split(",")
            if c.strip()
        ]
    )
    arxiv_max_results: int = Field(
        default_factory=lambda: int(os.getenv("ARXIV_MAX_RESULTS", "10"))
    )

    enable_hackernews: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_HACKERNEWS", "true").lower() in ("true", "1", "yes")
    )
    hackernews_min_score: int = Field(
        default_factory=lambda: int(os.getenv("HACKERNEWS_MIN_SCORE", "20"))
    )
    hackernews_max_items: int = Field(
        default_factory=lambda: int(os.getenv("HACKERNEWS_MAX_ITEMS", "15"))
    )

    enable_github: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_GITHUB", "true").lower() in ("true", "1", "yes")
    )
    github_token: Optional[str] = Field(
        default_factory=lambda: os.getenv("GITHUB_TOKEN", None)
    )
    github_min_stars: int = Field(
        default_factory=lambda: int(os.getenv("GITHUB_MIN_STARS", "200"))
    )
    github_max_items: int = Field(
        default_factory=lambda: int(os.getenv("GITHUB_MAX_ITEMS", "10"))
    )

    enable_nvd: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_NVD", "true").lower() in ("true", "1", "yes")
    )
    nvd_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("NVD_API_KEY", None)
    )
    nvd_results_per_page: int = Field(
        default_factory=lambda: int(os.getenv("NVD_RESULTS_PER_PAGE", "15"))
    )

    # Clustering & Deduplication Configuration (Phase 4)
    clustering_similarity_threshold: float = Field(
        default_factory=lambda: float(os.getenv("CLUSTERING_SIMILARITY_THRESHOLD", "0.45"))
    )
    clustering_time_window_hours: float = Field(
        default_factory=lambda: float(os.getenv("CLUSTERING_TIME_WINDOW_HOURS", "72.0"))
    )
    clustering_embedding_provider: str = Field(
        default_factory=lambda: os.getenv("CLUSTERING_EMBEDDING_PROVIDER", "minilm")
    )

    # Persistence & Cross-Day Deduplication Configuration (Phase 5)
    db_path: str = Field(
        default_factory=lambda: os.getenv("DB_PATH", "data/newspaper.db")
    )
    storage_history_lookback_days: float = Field(
        default_factory=lambda: float(os.getenv("STORAGE_HISTORY_LOOKBACK_DAYS", "7.0"))
    )
    enable_storage: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_STORAGE", "true").lower() in ("true", "1", "yes")
    )
    meaningful_update_jaccard_threshold: float = Field(
        default_factory=lambda: float(os.getenv("MEANINGFUL_UPDATE_JACCARD_THRESHOLD", "0.35"))
    )
    meaningful_update_time_threshold_hours: float = Field(
        default_factory=lambda: float(os.getenv("MEANINGFUL_UPDATE_TIME_THRESHOLD_HOURS", "6.0"))
    )

    # Scheduling & Automation Configuration (Phase 7)
    schedule_enabled: bool = Field(
        default_factory=lambda: os.getenv("SCHEDULE_ENABLED", "true").lower() in ("true", "1", "yes")
    )
    schedule_time: str = Field(
        default_factory=lambda: os.getenv("SCHEDULE_TIME", "06:00")
    )
    schedule_timezone: str = Field(
        default_factory=lambda: os.getenv("SCHEDULE_TIMEZONE", "Asia/Kolkata")
    )
    schedule_lock_file: str = Field(
        default_factory=lambda: os.getenv("SCHEDULE_LOCK_FILE", "data/pipeline.lock")
    )
    schedule_run_on_startup: bool = Field(
        default_factory=lambda: os.getenv("SCHEDULE_RUN_ON_STARTUP", "false").lower() in ("true", "1", "yes")
    )

    # Agentic Intelligence & Compute Configuration (Phases 8.1 & 10)
    enable_agentic_intelligence: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_AGENTIC_INTELLIGENCE", "false").lower() in ("true", "1", "yes")
    )
    enable_llm_inference: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_LLM_INFERENCE", "true").lower() in ("true", "1", "yes")
    )
    enable_gpu_inference: bool = Field(
        default_factory=lambda: os.getenv("ENABLE_GPU_INFERENCE", "false").lower() in ("true", "1", "yes")
    )
    cpu_only_mode: bool = Field(
        default_factory=lambda: os.getenv("CPU_ONLY_MODE", "false").lower() in ("true", "1", "yes")
    )

    # Phase 9B Daily GPU Worker Orchestration & S3 Publication Configuration
    storage_backend: str = Field(
        default_factory=lambda: os.getenv("STORAGE_BACKEND", "local").lower()
    )
    editions_dir: str = Field(
        default_factory=lambda: os.getenv("EDITIONS_DIR", "data/editions")
    )
    s3_bucket_name: Optional[str] = Field(
        default_factory=lambda: os.getenv("S3_BUCKET_NAME", None)
    )
    aws_region: str = Field(
        default_factory=lambda: os.getenv("AWS_REGION", "ap-south-1")
    )
    ec2_instance_id: Optional[str] = Field(
        default_factory=lambda: os.getenv("EC2_INSTANCE_ID", None)
    )
    auto_stop_worker: bool = Field(
        default_factory=lambda: os.getenv("AUTO_STOP_WORKER", "false").lower() in ("true", "1", "yes")
    )
    target_runtime_minutes: float = Field(
        default_factory=lambda: float(os.getenv("TARGET_RUNTIME_MINUTES", "20.0"))
    )
    max_worker_runtime_minutes: float = Field(
        default_factory=lambda: float(os.getenv("MAX_WORKER_RUNTIME_MINUTES", "30.0"))
    )
    shutdown_grace_period_seconds: float = Field(
        default_factory=lambda: float(os.getenv("SHUTDOWN_GRACE_PERIOD_SECONDS", "120.0"))
    )
    admin_api_key: Optional[str] = Field(
        default_factory=lambda: os.getenv("ADMIN_API_KEY", None)
    )
    min_edition_stories: int = Field(
        default_factory=lambda: int(os.getenv("MIN_EDITION_STORIES", "3"))
    )
    edition_retention_days: int = Field(
        default_factory=lambda: int(os.getenv("EDITION_RETENTION_DAYS", "30"))
    )


# Global settings singleton
settings = Settings()
