"""Lookup transform - retrieve value from dictionary."""

from __future__ import annotations

from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("transform/lookup")
class LookupTransform(Component):
    """
    Look up a value from a dictionary using a key.

    Essential for dynamic lookups like getting ground truth for current character.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/lookup",
            description="Look up value from dictionary by key",
            category="transform",
            config={
                "default": ConfigSpec(
                    type="any",
                    default=None,
                    description="Default value if key not found"
                ),
            },
            inputs={
                "dict": InputSpec(
                    type="dict",
                    required=True,
                    description="Dictionary to look up from"
                ),
                "key": InputSpec(
                    type="string",
                    required=True,
                    description="Key to look up"
                ),
            },
            outputs={
                "value": OutputSpec(
                    type="any",
                    description="The looked-up value"
                ),
                "found": OutputSpec(
                    type="boolean",
                    description="Whether the key was found"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        lookup_dict = inputs.get("dict", {})
        key = inputs.get("key", "")
        default = self.get_config("default")

        found = key in lookup_dict
        value = lookup_dict.get(key, default)

        return {
            "value": value,
            "found": found,
        }
