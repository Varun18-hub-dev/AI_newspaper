"""Base interface and error types for LLM providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Type, TypeVar
import json
import re
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base exception for LLM provider errors."""
    pass


class LLMUnavailableError(LLMError):
    """Raised when the LLM service/host cannot be reached."""
    pass


class LLMTimeoutError(LLMError):
    """Raised when the LLM request times out."""
    pass


class LLMResponseMalformedError(LLMError):
    """Raised when the LLM returns an empty, unparseable, or invalid response."""
    pass


class LLMProvider(ABC):
    """Abstract base class for all LLM providers."""

    @abstractmethod
    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Generates raw text response for a given prompt.

        Args:
            prompt: Text prompt to send to the model.
            **kwargs: Additional provider-specific parameters (e.g. temperature, max_tokens).

        Returns:
            str: Generated completion text.

        Raises:
            LLMUnavailableError: If the provider is unreachable.
            LLMTimeoutError: If the request times out.
            LLMResponseMalformedError: If the response is empty or invalid.
            LLMError: For any other unhandled errors.
        """
        pass

    def generate_structured(
        self, prompt: str, schema: Type[T], **kwargs: Any
    ) -> T:
        """Generates a response and parses/validates it against a Pydantic schema.

        Args:
            prompt: Text prompt instructing the model to produce JSON.
            schema: Pydantic model class to validate the output against.
            **kwargs: Additional parameters passed to `generate`.

        Returns:
            T: An instance of the validated schema.

        Raises:
            LLMResponseMalformedError: If response cannot be parsed as JSON or fails schema validation.
            LLMError: If generation itself fails.
        """
        raw_text = self.generate(prompt, **kwargs)
        return self.parse_json_to_schema(raw_text, schema)

    @staticmethod
    def extract_json_string(text: str) -> str:
        """Extracts JSON substring from model output, handling markdown blocks if present.

        Args:
            text: Raw output string from LLM.

        Returns:
            str: Extracted JSON string.

        Raises:
            LLMResponseMalformedError: If no JSON structure can be found.
        """
        if not text or not text.strip():
            raise LLMResponseMalformedError("Model returned empty or whitespace response.")

        stripped = text.strip()

        # Check for markdown code blocks e.g. ```json { ... } ``` or ``` { ... } ```
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, re.IGNORECASE)
        if fence_match:
            stripped = fence_match.group(1).strip()

        # Attempt to isolate JSON object { ... } or array [ ... ]
        first_brace = stripped.find("{")
        last_brace = stripped.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            return stripped[first_brace : last_brace + 1]

        first_bracket = stripped.find("[")
        last_bracket = stripped.rfind("]")
        if first_bracket != -1 and last_bracket != -1 and last_bracket > first_bracket:
            return stripped[first_bracket : last_bracket + 1]

        return stripped

    @classmethod
    def parse_json_to_schema(cls, text: str, schema: Type[T]) -> T:
        """Parses and validates a string into a Pydantic schema.

        Args:
            text: Raw string containing JSON.
            schema: Target Pydantic model class.

        Returns:
            T: Instantiated schema.

        Raises:
            LLMResponseMalformedError: If JSON decoding or Pydantic validation fails.
        """
        json_str = cls.extract_json_string(text)
        try:
            parsed_data = json.loads(json_str)
        except json.JSONDecodeError as err:
            raise LLMResponseMalformedError(
                f"Failed to decode JSON from model response: {err}. Raw extracted content: {json_str[:200]}"
            ) from err

        if not isinstance(parsed_data, dict):
            raise LLMResponseMalformedError(
                f"Expected JSON object matching schema {schema.__name__}, got {type(parsed_data).__name__}"
            )

        try:
            return schema.model_validate(parsed_data)
        except ValidationError as err:
            raise LLMResponseMalformedError(
                f"Schema validation failed for {schema.__name__}: {err}"
            ) from err
