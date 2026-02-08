"""Model Manager LLM transform - call local Ollama via Model Manager API."""

from __future__ import annotations

import time
from typing import Any

import httpx

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.errors import ErrorProtocol
from ...core.registry import register_component


@register_component("transform/model_manager")
class ModelManagerTransform(Component):
    """
    Call local Ollama via Model Manager API.

    Model Manager provides job queuing and prioritization for local LLM inference.
    This component submits a job and polls for the result.
    """

    # Retry on failures
    error_protocol = ErrorProtocol(on_error="retry", max_retries=3, retry_delay=2.0)

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/model_manager",
            description="Call local Ollama via Model Manager API",
            category="transform",
            config={
                "model": ConfigSpec(
                    type="string",
                    default="qwen2.5:0.5b",
                    description="Ollama model to use"
                ),
                "base_url": ConfigSpec(
                    type="string",
                    default="http://localhost:5001",
                    description="Model Manager API URL"
                ),
                "priority": ConfigSpec(
                    type="string",
                    default="normal",
                    description="Job priority: low, normal, high"
                ),
                "timeout": ConfigSpec(
                    type="float",
                    default=120.0,
                    description="Max seconds to wait for result"
                ),
                "poll_interval": ConfigSpec(
                    type="float",
                    default=0.5,
                    description="Seconds between status polls"
                ),
            },
            inputs={
                "prompt": InputSpec(
                    type="string",
                    required=True,
                    description="The prompt to send"
                ),
                "system_prompt": InputSpec(
                    type="string",
                    required=False,
                    description="Optional system prompt"
                ),
                "model": InputSpec(
                    type="string",
                    required=False,
                    description="Override model (optional)"
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
                "job_id": OutputSpec(
                    type="string",
                    description="Model Manager job ID"
                ),
                "duration_ms": OutputSpec(
                    type="float",
                    description="Total request duration in milliseconds"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        # Get config
        model = inputs.get("model") or self.get_config("model", "qwen2.5:0.5b")
        base_url = self.get_config("base_url", "http://localhost:5001")
        priority = self.get_config("priority", "normal")
        timeout = self.get_config("timeout", 120.0)
        poll_interval = self.get_config("poll_interval", 0.5)

        prompt = inputs.get("prompt", "")
        system_prompt = inputs.get("system_prompt")

        start_time = time.time()

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Submit job
            submit_payload = {
                "model": model,
                "prompt": prompt,
                "priority": priority,
            }
            if system_prompt:
                submit_payload["system_prompt"] = system_prompt

            response = await client.post(
                f"{base_url}/api/submit",
                json=submit_payload
            )

            if response.status_code != 200:
                raise RuntimeError(f"Model Manager submit failed: {response.text}")

            data = response.json()
            job_id = data.get("job_id")

            if not job_id:
                raise RuntimeError("No job_id returned from Model Manager")

            # Poll for result
            elapsed = 0
            while elapsed < timeout:
                status_response = await client.get(f"{base_url}/api/job/{job_id}")

                if status_response.status_code != 200:
                    raise RuntimeError(f"Failed to get job status: {status_response.text}")

                job_data = status_response.json()
                status = job_data.get("status")

                if status == "complete":
                    duration_ms = (time.time() - start_time) * 1000
                    result_text = job_data.get("result", "")

                    # Debug output
                    short_response = result_text[:30] + "..." if len(result_text) > 30 else result_text
                    self.debug(f"Local: {model} → '{short_response}' ({duration_ms:.0f}ms)", context)

                    return {
                        "response": result_text,
                        "model": model,
                        "job_id": job_id,
                        "duration_ms": duration_ms,
                    }

                elif status == "failed":
                    error = job_data.get("error", "Unknown error")
                    raise RuntimeError(f"Model Manager job failed: {error}")

                elif status in ("queued", "pending", "running"):
                    await asyncio.sleep(poll_interval)
                    elapsed = time.time() - start_time
                else:
                    raise RuntimeError(f"Unknown job status: {status}")

            raise TimeoutError(f"Model Manager job timed out after {timeout}s")


# Need asyncio for sleep
import asyncio
