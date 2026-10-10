"""Personalized AI Newspaper - Phase 1 Entry Point.

Validates the local environment, runtime connectivity, structured output generation,
and library dependencies (LangGraph, CrewAI).
"""

import sys
from pathlib import Path
from typing import Literal

# Ensure project root is in sys.path when running as script
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import setup_logger
from app.llm.base import LLMError
from app.llm.qwen import QwenProvider

logger = setup_logger("main")


class ItemClassification(BaseModel):
    """Schema for content classification output."""

    category: Literal["AI", "Cybersecurity", "Cloud", "Open Source", "Other"]
    relevance: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Relevance score between 0.0 and 1.0",
    )
    reason: str = Field(..., description="Explanation for category classification")


CLASSIFICATION_PROMPT_TEMPLATE = """You are an information classification assistant.

Classify the following item into one of:
AI, Cybersecurity, Cloud, Open Source, Other.

Return ONLY valid JSON:

{{
  "category": "...",
  "relevance": 0.0,
  "reason": "..."
}}

Item:
"{item}"
"""


def verify_agent_frameworks() -> dict[str, str]:
    """Verifies that LangGraph and CrewAI can be imported and records their versions."""
    results = {}

    try:
        import langgraph
        import importlib.metadata
        try:
            ver = importlib.metadata.version("langgraph")
        except Exception:
            ver = getattr(langgraph, "__version__", "available")
        results["langgraph"] = ver
        logger.info(f"LangGraph is installed and importable (version: {ver})")
    except ImportError as err:
        results["langgraph"] = f"IMPORT_FAILED: {err}"
        logger.error(f"LangGraph import failed: {err}")

    try:
        import crewai
        ver = getattr(crewai, "__version__", "available")
        results["crewai"] = ver
        logger.info(f"CrewAI is installed and importable (version: {ver})")
    except ImportError as err:
        results["crewai"] = f"IMPORT_FAILED: {err}"
        logger.error(f"CrewAI import failed: {err}")

    return results


def run_classification_demo(
    item_text: str = "OpenAI releases a new reasoning model with improved coding capabilities.",
) -> ItemClassification:
    """Executes structured classification using QwenProvider.

    Args:
        item_text: News item text to classify.

    Returns:
        ItemClassification: Validated structured classification.
    """
    logger.info(f"Connecting to Qwen via Ollama ({settings.ollama_base_url}, model={settings.model_name})...")
    provider = QwenProvider()

    prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(item=item_text)
    logger.info("Submitting prompt to model for structured classification...")
    result = provider.generate_structured(prompt=prompt, schema=ItemClassification)
    return result


def main() -> None:
    """Phase 1 verification and demonstration."""
    print("=" * 60)
    print("Personalized AI Newspaper - Phase 1 Validation")
    print("=" * 60)

    # 1. Agent Frameworks Check
    print("\n[1/3] Checking Agent Frameworks:")
    framework_status = verify_agent_frameworks()
    for fw, ver in framework_status.items():
        print(f"  - {fw}: {ver}")

    # 2. Config Check
    print("\n[2/3] Configuration:")
    print(f"  - Ollama Base URL: {settings.ollama_base_url}")
    print(f"  - Model Name:      {settings.model_name}")
    print(f"  - Temperature:     {settings.temperature}")
    print(f"  - Timeout:         {settings.request_timeout}s")

    # 3. Model Inference & Structured Output Test
    print("\n[3/3] Testing Local Qwen Structured Output:")
    test_item = "OpenAI releases a new reasoning model with improved coding capabilities."
    print(f"  Input Item: \"{test_item}\"")

    try:
        classification = run_classification_demo(test_item)
        print("\n  [SUCCESS] Structured Output Received and Validated:")
        print(f"    Category:  {classification.category}")
        print(f"    Relevance: {classification.relevance}")
        print(f"    Reason:    {classification.reason}")
        print(f"\n  JSON Output:\n{classification.model_dump_json(indent=2)}")
    except LLMError as err:
        print(f"\n  [FAILURE] LLM Error: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
