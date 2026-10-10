"""Qwen LLM Provider implementation using local Ollama runtime."""

from typing import Any, Dict, Optional
import requests

from app.core.config import Settings, settings as default_settings
from app.core.logging import setup_logger
from app.llm.base import (
    LLMProvider,
    LLMError,
    LLMUnavailableError,
    LLMTimeoutError,
    LLMResponseMalformedError,
)

logger = setup_logger("qwen_provider")


class QwenProvider(LLMProvider):
    """LLM Provider for locally running Qwen model via Ollama."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: Optional[float] = None,
        app_settings: Optional[Settings] = None,
    ):
        """Initializes the Qwen provider with configuration values.

        Args:
            base_url: Base URL for Ollama API (default from settings).
            model_name: Model identifier (default from settings).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            timeout: Request timeout in seconds.
            app_settings: Optional Settings object overriding default_settings.
        """
        cfg = app_settings or default_settings
        self.base_url = (base_url or cfg.ollama_base_url).rstrip("/")
        self.model_name = model_name or cfg.model_name
        self.temperature = temperature if temperature is not None else cfg.temperature
        self.max_tokens = max_tokens if max_tokens is not None else cfg.max_tokens
        self.timeout = timeout if timeout is not None else cfg.request_timeout

        self.generate_endpoint = f"{self.base_url}/api/generate"
        logger.info(
            f"Initialized QwenProvider [endpoint={self.generate_endpoint}, model={self.model_name}]"
        )

    def generate(self, prompt: str, **kwargs: Any) -> str:
        """Sends a completion request to the local Qwen model.

        Args:
            prompt: Text prompt to submit.
            **kwargs: Optional parameter overrides (temperature, max_tokens, timeout).

        Returns:
            str: Generated text output.

        Raises:
            LLMUnavailableError: If Ollama cannot be connected to.
            LLMTimeoutError: If generation times out.
            LLMResponseMalformedError: If the returned response is empty or invalid.
            LLMError: For other unexpected failures.
        """
        if not prompt or not prompt.strip():
            raise LLMResponseMalformedError("Prompt cannot be empty.")

        temp = kwargs.get("temperature", self.temperature)
        timeout = kwargs.get("timeout", self.timeout)
        max_tokens = kwargs.get("max_tokens", self.max_tokens)

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temp,
            },
        }

        if max_tokens:
            payload["options"]["num_predict"] = max_tokens

        logger.debug(f"Calling Ollama with model={self.model_name}, temp={temp}")

        try:
            response = requests.post(
                self.generate_endpoint,
                json=payload,
                timeout=timeout,
            )
        except requests.exceptions.Timeout as err:
            logger.error(f"Timeout communicating with Ollama: {err}")
            raise LLMTimeoutError(f"Request timed out after {timeout}s: {err}") from err
        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout) as err:
            logger.error(f"Could not connect to Ollama at {self.base_url}: {err}")
            raise LLMUnavailableError(
                f"Ollama server is unavailable at {self.base_url}. Please ensure Ollama is running."
            ) from err
        except requests.exceptions.RequestException as err:
            logger.error(f"HTTP request error: {err}")
            raise LLMError(f"Unexpected request error: {err}") from err

        if response.status_code != 200:
            error_msg = f"Ollama returned HTTP {response.status_code}: {response.text}"
            logger.error(error_msg)
            if response.status_code == 404:
                raise LLMUnavailableError(
                    f"Model '{self.model_name}' not found or endpoint invalid ({response.status_code}): {response.text}"
                )
            raise LLMError(error_msg)

        try:
            body = response.json()
        except Exception as err:
            raise LLMResponseMalformedError(
                f"Failed to parse Ollama JSON response: {err}"
            ) from err

        output = body.get("response")
        if output is None or not str(output).strip():
            raise LLMResponseMalformedError("Ollama returned an empty response.")

        return str(output).strip()
