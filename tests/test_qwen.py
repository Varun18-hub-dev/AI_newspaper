"""Composite test suite for Qwen provider tests."""

# Re-export test cases from test_qwen_unit and test_qwen_integration
from tests.test_qwen_unit import (
    test_qwen_provider_initialization_defaults,
    test_qwen_provider_initialization_custom,
    test_prompt_send_success,
    test_empty_prompt_rejection,
    test_empty_model_response_handling,
    test_structured_classification_parsing_clean_json,
    test_structured_classification_parsing_markdown_fences,
    test_invalid_json_handling,
    test_schema_mismatch_handling,
    test_provider_connection_failure,
    test_provider_timeout_failure,
    test_provider_http_404_model_missing,
    test_agent_frameworks_installed,
)
from tests.test_qwen_integration import (
    qwen_provider,
    test_live_qwen_initialization,
    test_live_qwen_prompt_and_non_empty_response,
    test_live_qwen_structured_classification,
)

__all__ = [
    "test_qwen_provider_initialization_defaults",
    "test_qwen_provider_initialization_custom",
    "test_prompt_send_success",
    "test_empty_prompt_rejection",
    "test_empty_model_response_handling",
    "test_structured_classification_parsing_clean_json",
    "test_structured_classification_parsing_markdown_fences",
    "test_invalid_json_handling",
    "test_schema_mismatch_handling",
    "test_provider_connection_failure",
    "test_provider_timeout_failure",
    "test_provider_http_404_model_missing",
    "test_agent_frameworks_installed",
    "qwen_provider",
    "test_live_qwen_initialization",
    "test_live_qwen_prompt_and_non_empty_response",
    "test_live_qwen_structured_classification",
]
