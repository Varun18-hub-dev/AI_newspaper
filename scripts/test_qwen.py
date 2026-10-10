"""Standalone script to test Qwen inference and structured output."""

import sys
from pathlib import Path

# Ensure project root is in sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from app.core.config import settings
from app.llm.qwen import QwenProvider
from app.llm.base import LLMError
from app.main import ItemClassification, CLASSIFICATION_PROMPT_TEMPLATE


def main() -> None:
    print("=" * 60)
    print("Testing Local Qwen 4B (3.1B) via Ollama")
    print(f"Base URL: {settings.ollama_base_url}")
    print(f"Model:    {settings.model_name}")
    print("=" * 60)

    provider = QwenProvider()
    test_item = "OpenAI releases a new reasoning model with improved coding capabilities."
    prompt = CLASSIFICATION_PROMPT_TEMPLATE.format(item=test_item)

    print("\n--- Submitting Structured Classification Prompt ---")
    print(f"Input Item: {test_item}\n")

    try:
        # Step 1 & 2: Send prompt to Qwen & receive response
        raw_response = provider.generate(prompt)
        print("Raw Response received:")
        print("-" * 40)
        print(raw_response)
        print("-" * 40)

        # Step 3, 4, 5: Parse response as JSON, validate schema, print result
        parsed = provider.parse_json_to_schema(raw_response, ItemClassification)
        print("\nValidated Pydantic Schema Output:")
        print(f"  Category:  {parsed.category}")
        print(f"  Relevance: {parsed.relevance}")
        print(f"  Reason:    {parsed.reason}")
        print("\nSerialized JSON:")
        print(parsed.model_dump_json(indent=2))
        print("\n[PASS] Qwen inference and structured JSON validation succeeded!")
    except LLMError as err:
        print(f"\n[FAIL] Test encountered LLMError: {err}")
        sys.exit(1)
    except Exception as err:
        print(f"\n[FAIL] Unexpected error: {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
