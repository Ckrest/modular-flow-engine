"""Literal source - provides inline values."""

from __future__ import annotations

from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("source/literal")
class LiteralSource(Component):
    """
    Provide literal/inline values.

    Useful for constants, test data, or values that don't come from files.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="source/literal",
            description="Provide inline literal values",
            category="source",
            config={
                "value": ConfigSpec(
                    type="any",
                    required=True,
                    description="The literal value to output"
                ),
                "as_list": ConfigSpec(
                    type="boolean",
                    default=False,
                    description="If true, wrap value in a list"
                ),
            },
            inputs={},
            outputs={
                "value": OutputSpec(
                    type="any",
                    description="The literal value"
                ),
                "items": OutputSpec(
                    type="list",
                    description="Value as list (if as_list or already a list)"
                ),
                "count": OutputSpec(
                    type="integer",
                    description="Number of items if value is a list"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        value = self.get_config("value")
        as_list = self.get_config("as_list", False)

        if as_list and not isinstance(value, list):
            items = [value]
        elif isinstance(value, list):
            items = value
        else:
            items = [value]

        return {
            "value": value,
            "items": items,
            "count": len(items)
        }
