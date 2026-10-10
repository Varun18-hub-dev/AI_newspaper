"""Unit tests for QwenProvider and LLM base abstractions."""

from unittest.mock import MagicMock, patch
import pytest
import requests
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.llm.base import (
    LLMProvider,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMResponseMalformedError,
    LLMError,
)
from app.llm.qwen import QwenProvider
from app.main import ItemClassification, verify_agent_frameworks


class SimpleTestSchema(BaseModel):
    category: str
    relevance: float
    reason: str


# ==========================================
# Test 1: Provider Initialization
# ==========================================
def test_qwen_provider_initialization_defaults():
    """Verify Qwen provider initializes correctly with default configuration."""
    provider = QwenProvider()
    assert provider.base_url == "http://127.0.0.1:11434"
    assert provider.model_name == "qwen2.5:3b"
    assert provider.generate_endpoint == "http://127.0.0.1:11434/api/generate"
    assert provider.temperature == 0.0
    assert provider.timeout == 180.0


def test_qwen_provider_initialization_custom():
    """Verify Qwen provider initialization with custom parameters."""
    custom_settings = Settings(
        ollama_base_url="http://custom-host:11434",
        model_name="qwen-custom",
        temperature=0.5,
        max_tokens=512,
        request_timeout=30.0,
    )
    provider = QwenProvider(app_settings=custom_settings)
    assert provider.base_url == "http://custom-host:11434"
    assert provider.model_name == "qwen-custom"
    assert provider.temperature == 0.5
    assert provider.max_tokens == 512
    assert provider.timeout == 30.0


# ==========================================
# Test 2: Prompt Can Be Sent Successfully (Mock)
# ==========================================
@patch("requests.post")
def test_prompt_send_success(mock_post):
    """Verify a prompt is sent to Ollama API and parsed correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "Hello world from model"}
    mock_post.return_value = mock_response

    provider = QwenProvider()
    result = provider.generate("Test prompt")

    assert result == "Hello world from model"
    mock_post.assert_called_once()
    payload = mock_post.call_args[1]["json"]
    assert payload["prompt"] == "Test prompt"
    assert payload["model"] == "qwen2.5:3b"


# ==========================================
# Test 3: Response Non-Empty & Empty Handling
# ==========================================
@patch("requests.post")
def test_empty_prompt_rejection(mock_post):
    """Verify empty prompt throws an error immediately without calling API."""
    provider = QwenProvider()
    with pytest.raises(LLMResponseMalformedError):
        provider.generate("   ")
    mock_post.assert_not_called()


@patch("requests.post")
def test_empty_model_response_handling(mock_post):
    """Verify empty or whitespace response from model raises LLMResponseMalformedError."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"response": "   "}
    mock_post.return_value = mock_response

    provider = QwenProvider()
    with pytest.raises(LLMResponseMalformedError) as exc_info:
        provider.generate("Say something")
    assert "empty" in str(exc_info.value).lower()


# ==========================================
# Test 4: Structured Classification Parsing
# ==========================================
def test_structured_classification_parsing_clean_json():
    """Verify structured parsing from clean JSON string."""
    raw_json = '{"category": "AI", "relevance": 0.95, "reason": "Focuses on AI advancements"}'
    parsed = LLMProvider.parse_json_to_schema(raw_json, ItemClassification)
    assert parsed.category == "AI"
    assert parsed.relevance == 0.95
    assert parsed.reason == "Focuses on AI advancements"


def test_structured_classification_parsing_markdown_fences():
    """Verify structured parsing correctly handles markdown code fences."""
    raw_response = """
Here is your classification:
```json
{
  "category": "Cybersecurity",
  "relevance": 0.85,
  "reason": "Vulnerability discovered in network driver"
}
```
Hope this helps!
"""
    parsed = LLMProvider.parse_json_to_schema(raw_response, ItemClassification)
    assert parsed.category == "Cybersecurity"
    assert parsed.relevance == 0.85
    assert "network driver" in parsed.reason


# ==========================================
# Test 5: Invalid JSON Handled Gracefully
# ==========================================
def test_invalid_json_handling():
    """Verify malformed JSON raises LLMResponseMalformedError."""
    malformed_json = '{"category": "AI", "relevance": 0.95, reason: unquoted}'
    with pytest.raises(LLMResponseMalformedError) as exc_info:
        LLMProvider.parse_json_to_schema(malformed_json, ItemClassification)
    assert "Failed to decode JSON" in str(exc_info.value)


def test_schema_mismatch_handling():
    """Verify JSON with invalid category or missing fields raises LLMResponseMalformedError."""
    mismatched_json = '{"category": "Cooking", "relevance": 0.95, "reason": "Not in enum"}'
    with pytest.raises(LLMResponseMalformedError) as exc_info:
        LLMProvider.parse_json_to_schema(mismatched_json, ItemClassification)
    assert "Schema validation failed" in str(exc_info.value)


# ==========================================
# Robustness & Failure Mode Tests
# ==========================================
@patch("requests.post")
def test_provider_connection_failure(mock_post):
    """Verify connection failure raises LLMUnavailableError."""
    mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

    provider = QwenProvider()
    with pytest.raises(LLMUnavailableError) as exc_info:
        provider.generate("Hello")
    assert "unavailable" in str(exc_info.value).lower()


@patch("requests.post")
def test_provider_timeout_failure(mock_post):
    """Verify timeout raises LLMTimeoutError."""
    mock_post.side_effect = requests.exceptions.Timeout("Request timed out")

    provider = QwenProvider()
    with pytest.raises(LLMTimeoutError) as exc_info:
        provider.generate("Hello")
    assert "timed out" in str(exc_info.value).lower()


@patch("requests.post")
def test_provider_http_404_model_missing(mock_post):
    """Verify HTTP 404 from Ollama raises LLMUnavailableError."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_response.text = "model 'qwen2.5:3b' not found"
    mock_post.return_value = mock_response

    provider = QwenProvider()
    with pytest.raises(LLMUnavailableError) as exc_info:
        provider.generate("Hello")
    assert "not found" in str(exc_info.value).lower()


# ==========================================
# Step 8 Verification: Framework Importability
# ==========================================
def test_agent_frameworks_installed():
    """Verify LangGraph and CrewAI are installed and importable."""
    status = verify_agent_frameworks()
    assert "langgraph" in status
    assert not status["langgraph"].startswith("IMPORT_FAILED")
    assert "crewai" in status
    assert not status["crewai"].startswith("IMPORT_FAILED")
