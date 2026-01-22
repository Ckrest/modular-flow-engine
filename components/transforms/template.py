"""Template transform - string interpolation."""

from __future__ import annotations

import re
from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("transform/template")
class TemplateTransform(Component):
    """
    Perform string template interpolation.

    Takes a template string and substitutes {placeholder} values.
    Useful for building prompts, combining data, etc.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/template",
            description="String template interpolation",
            category="transform",
            config={
                "template": ConfigSpec(
                    type="string",
                    required=False,
                    description="Template string with {placeholders} (can also be provided via input)"
                ),
            },
            inputs={
                "template": InputSpec(
                    type="string",
                    required=False,
                    description="Template string (overrides config if provided)"
                ),
                "values": InputSpec(
                    type="dict",
                    required=False,
                    description="Dictionary of values to substitute",
                    default={}
                ),
            },
            outputs={
                "result": OutputSpec(
                    type="string",
                    description="Interpolated string"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        # Template can come from inputs or config (inputs take precedence)
        template = inputs.get("template") or self.get_config("template")
        if not template:
            raise ValueError("No template provided (via input or config)")

        values = inputs.get("values", {})

        # Merge with any additional inputs (for convenience)
        all_values = {**values}
        for key, val in inputs.items():
            if key != "values":
                all_values[key] = val

        def replace(m: re.Match) -> str:
            key = m.group(1)
            if key in all_values:
                return str(all_values[key])
            # Try context resolution
            ctx_val = context.get(key)
            if ctx_val is not None:
                return str(ctx_val)
            return m.group(0)  # Keep as-is if not found

        result = re.sub(r"\{([^}]+)\}", replace, template)

        return {"result": result}
