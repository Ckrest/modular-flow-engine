"""Ollama LLM transform component for local model inference."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.errors import ErrorProtocol
from ...core.registry import register_component


@register_component("transform/ollama")
class OllamaTransform(Component):
    """
    Call local Ollama API for LLM completions.

    Supports the Ollama generate and chat endpoints. Uses the chat endpoint
    by default for message-based interactions.
    """

    # Retry on failures (Ollama may be loading model)
    error_protocol = ErrorProtocol(on_error="retry", max_retries=3, retry_delay=2.0)

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/ollama",
            description="Call local Ollama for LLM completions",
            category="transform",
            config={
                "model": ConfigSpec(
                    type="string",
                    required=False,
                    description="Ollama model name (e.g., llama3:8b, mistral)"
                ),
                "base_url": ConfigSpec(
                    type="string",
                    default="http://localhost:11434",
                    description="Ollama API base URL"
                ),
                "temperature": ConfigSpec(
                    type="float",
                    default=0.7,
                    description="Sampling temperature (0.0-2.0)"
                ),
                "num_predict": ConfigSpec(
                    type="integer",
                    default=1024,
                    description="Maximum tokens to generate"
                ),
                "timeout": ConfigSpec(
                    type="float",
                    default=120.0,
                    description="Request timeout in seconds (models may need loading time)"
                ),
                "format": ConfigSpec(
                    type="string",
                    required=False,
                    description="Response format: 'json' for JSON mode"
                ),
            },
            inputs={
                "prompt": InputSpec(
                    type="string",
                    required=True,
                    description="The user prompt to send"
                ),
                "system_prompt": InputSpec(
                    type="string",
                    required=False,
                    description="Optional system prompt"
                ),
                "model": InputSpec(
                    type="string",
                    required=False,
                    description="Model to use (overrides config)"
                ),
                "format": InputSpec(
                    type="string",
                    required=False,
                    description="Response format (overrides config)"
                ),
            },
            outputs={
                "response": OutputSpec(
                    type="string",
                    description="The model's response text"
                ),
                "model": OutputSpec(
                    type="string",
                    description="Model that was used"
                ),
                "eval_count": OutputSpec(
                    type="integer",
                    description="Number of tokens generated"
                ),
                "total_duration": OutputSpec(
                    type="integer",
                    description="Total processing time in nanoseconds"
                ),
                "done_reason": OutputSpec(
                    type="string",
                    description="Why generation stopped"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        # Model priority: input > component config > plan settings
        model = inputs.get("model") or self.get_config("model") or context.get_setting("model")
        if not model:
            raise ValueError(
                "No model specified. Set via:\n"
                "  1. Input 'model'\n"
                "  2. Component config 'model'\n"
                "  3. Plan settings 'model'"
            )

        base_url = self.get_config("base_url", "http://localhost:11434")
        temperature = self.get_config("temperature", 0.7)
        num_predict = self.get_config("num_predict", 1024)
        timeout = self.get_config("timeout", 120.0)
        format_mode = inputs.get("format") or self.get_config("format")

        prompt = inputs.get("prompt", "")
        system_prompt = inputs.get("system_prompt")

        # Build messages for chat endpoint
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Build request payload
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
            }
        }

        if format_mode:
            payload["format"] = format_mode

        start_time = time.time()

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/api/chat",
                json=payload
            )

            if response.status_code != 200:
                error_text = response.text
                raise RuntimeError(
                    f"Ollama API error ({response.status_code}): {error_text}"
                )

            data = response.json()

        elapsed_ms = (time.time() - start_time) * 1000

        # Extract response
        message = data.get("message", {})
        response_text = message.get("content", "")

        # Debug output
        short_response = response_text[:50] + "..." if len(response_text) > 50 else response_text
        model_short = model.split(":")[-1][:15] if ":" in model else model[:15]
        self.debug(f"Ollama: {model_short} → '{short_response}' ({elapsed_ms:.0f}ms)", context)

        return {
            "response": response_text,
            "model": data.get("model", model),
            "eval_count": data.get("eval_count", 0),
            "total_duration": data.get("total_duration", 0),
            "done_reason": data.get("done_reason", "unknown"),
        }
