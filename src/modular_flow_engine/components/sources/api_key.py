"""API key loader component."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec, ValidationResult
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("source/api_key")
class APIKeySource(Component):
    """
    Load API keys from config file or environment variables.

    Checks in order:
    1. Config file (config/api_keys.json by default)
    2. Environment variable (e.g., OPENROUTER_API_KEY)

    This keeps secrets out of plan files and allows flexible deployment.
    """

    # Default config file path (relative to runner)
    DEFAULT_CONFIG_PATH = "config/api_keys.json"

    # Mapping of key names to environment variable names
    ENV_VAR_MAPPING = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="source/api_key",
            description="Load API key from config file or environment",
            category="source",
            config={
                "key_name": ConfigSpec(
                    type="string",
                    required=True,
                    description="Name of the API key to load (e.g., 'openrouter', 'openai')",
                ),
                "config_path": ConfigSpec(
                    type="string",
                    required=False,
                    default="config/api_keys.json",
                    description="Path to API keys config file",
                ),
                "env_var": ConfigSpec(
                    type="string",
                    required=False,
                    description="Override environment variable name to check",
                ),
                "required": ConfigSpec(
                    type="boolean",
                    required=False,
                    default=True,
                    description="Whether to error if key is not found",
                ),
            },
            inputs={},
            outputs={
                "key": OutputSpec(
                    type="string",
                    description="The API key value",
                ),
                "source": OutputSpec(
                    type="string",
                    description="Where the key was loaded from ('config', 'env', or 'not_found')",
                ),
            },
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        key_name = self.get_config("key_name")
        config_path = self.get_config("config_path", self.DEFAULT_CONFIG_PATH)
        env_var_override = self.get_config("env_var")
        required = self.get_config("required", True)

        key_value = None
        source = "not_found"

        # Try config file first
        config_file = Path(config_path)
        if config_file.exists():
            try:
                with open(config_file, "r") as f:
                    config_data = json.load(f)
                if key_name in config_data and config_data[key_name]:
                    key_value = config_data[key_name]
                    source = "config"
            except (json.JSONDecodeError, IOError) as e:
                # Log warning but continue to try env var
                pass

        # Try environment variable if not found in config
        if key_value is None:
            env_var = env_var_override or self.ENV_VAR_MAPPING.get(
                key_name,
                f"{key_name.upper()}_API_KEY"
            )
            env_value = os.environ.get(env_var)
            if env_value:
                key_value = env_value
                source = "env"

        # Handle missing key
        if key_value is None:
            if required:
                env_var = env_var_override or self.ENV_VAR_MAPPING.get(
                    key_name,
                    f"{key_name.upper()}_API_KEY"
                )
                raise ValueError(
                    f"API key '{key_name}' not found.\n"
                    f"Set it in '{config_path}' or environment variable '{env_var}'"
                )
            key_value = ""

        return {
            "key": key_value,
            "source": source,
        }
