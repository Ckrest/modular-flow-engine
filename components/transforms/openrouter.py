"""OpenRouter LLM transform component."""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import httpx

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.errors import ErrorProtocol
from core.registry import register_component


@register_component("transform/openrouter")
class OpenRouterTransform(Component):
    """
    Call OpenRouter API to get LLM completions.

    This component supports any field the plan wants to pass - it doesn't
    have hardcoded assumptions about what inputs mean.
    """

    # Override default error protocol to retry on failures
    error_protocol = ErrorProtocol(on_error="retry", max_retries=3, retry_delay=2.0)

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/openrouter",
            description="Call OpenRouter API for LLM completions",
            category="transform",
            config={
                "model": ConfigSpec(
                    type="string",
                    required=False,
                    description="OpenRouter model identifier (or use plan settings.model)"
                ),
                "api_key": ConfigSpec(
                    type="string",
                    required=False,
                    description="API key (or use OPENROUTER_API_KEY env var)"
                ),
                "temperature": ConfigSpec(
                    type="float",
                    default=0.7,
                    description="Sampling temperature"
                ),
                "max_tokens": ConfigSpec(
                    type="integer",
                    default=1024,
                    description="Maximum tokens to generate"
                ),
                "timeout": ConfigSpec(
                    type="float",
                    default=60.0,
                    description="Request timeout in seconds"
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
                "api_key": InputSpec(
                    type="string",
                    required=False,
                    description="API key (overrides config and env var)"
                ),
                "model": InputSpec(
                    type="string",
                    required=False,
                    description="Model to use (overrides config)"
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
                "usage": OutputSpec(
                    type="dict",
                    description="Token usage statistics"
                ),
                "finish_reason": OutputSpec(
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
        temperature = self.get_config("temperature", 0.7)
        max_tokens = self.get_config("max_tokens", 1024)
        timeout = self.get_config("timeout", 60.0)

        # API key priority: input > config > environment
        api_key = (
            inputs.get("api_key")
            or self.get_config("api_key")
            or os.environ.get("OPENROUTER_API_KEY")
        )

        if not api_key:
            raise ValueError(
                "No API key provided. Set via:\n"
                "  1. Input from source/api_key component\n"
                "  2. Component config 'api_key'\n"
                "  3. OPENROUTER_API_KEY environment variable"
            )

        prompt = inputs.get("prompt", "")
        system_prompt = inputs.get("system_prompt")

        # Build messages
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        # Make API call
        start_time = time.time()

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
            )

            if response.status_code != 200:
                error_text = response.text
                raise RuntimeError(
                    f"OpenRouter API error ({response.status_code}): {error_text}"
                )

            data = response.json()

        elapsed_ms = (time.time() - start_time) * 1000

        # Extract response
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        response_text = message.get("content", "")

        # Debug output for API calls
        short_response = response_text[:30] + "..." if len(response_text) > 30 else response_text
        model_short = model.split("/")[-1][:20]
        self.debug(f"API: {model_short} → '{short_response}' ({elapsed_ms:.0f}ms)", context)

        return {
            "response": response_text,
            "model": data.get("model", model),
            "usage": data.get("usage", {}),
            "finish_reason": choice.get("finish_reason", "unknown"),
        }
