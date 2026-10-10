"""Multi-domain package export."""

from app.domains.models import DomainConfig, FeedConfig
from app.domains.registry import (
    DomainRegistry,
    get_domain_registry,
    AI_TOPICS,
    TECHNOLOGY_TOPICS,
    SCIENCE_TOPICS,
    CYBERSECURITY_TOPICS,
    BUSINESS_TOPICS,
)

__all__ = [
    "DomainConfig",
    "FeedConfig",
    "DomainRegistry",
    "get_domain_registry",
    "AI_TOPICS",
    "TECHNOLOGY_TOPICS",
    "SCIENCE_TOPICS",
    "CYBERSECURITY_TOPICS",
    "BUSINESS_TOPICS",
]
