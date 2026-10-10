"""Live Integration tests connecting to local Ollama Qwen instance.

Verifies end-to-end inference against the locally running Qwen model.
"""

import pytest
from app.core.config import settings
from app.llm.qwen import QwenProvider
from app.llm.base import LLMUnavailableError
from app.main import ItemClassification, CLASSIFICATION_PROMPT_TEMPLATE


@pytest.fixture(scope="module")
def qwen_provider():
    """Initializes a real QwenProvider instance."""
    return QwenProvider()


def test_live_qwen_initialization(qwen_provider):
    """Verify provider initializes and points to configured local Ollama instance."""
    assert qwen_provider.base_url == settings.ollama_base_url
    assert qwen_provider.model_name == settings.model_name


def test_live_qwen_prompt_and_non_empty_response(qwen_provider):
    """Verify real prompt can be sent to local Qwen and returns non-empty output."""
    try:
        response = qwen_provider.generate("Respond with the exact word 'PONG'.", temperature=0.0)
    except Exception as err:
        pytest.fail(f"Local Ollama Qwen model failed: {err}")

    assert isinstance(response, str)
    assert len(response.strip()) > 0
    assert "PONG" in response.upper()


def test_live_qwen_structured_classification(qwen_provider):
    """Verify local Qwen produces structured JSON that validates against Pydantic schema."""
    item = "OpenAI releases a new reasoning model with improved coding capabilities."
    prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(item=item)

    try:
        result = qwen_provider.generate_structured(prompt=prompt, schema=ItemClassification)
    except Exception as err:
        pytest.fail(f"Live structured output failed: {err}")

    assert isinstance(result, ItemClassification)
    assert result.category in ["AI", "Cybersecurity", "Cloud", "Open Source", "Other"]
    assert result.category == "AI"  # OpenAI release must be classified as AI
    assert 0.0 <= result.relevance <= 1.0
    assert len(result.reason.strip()) > 0
