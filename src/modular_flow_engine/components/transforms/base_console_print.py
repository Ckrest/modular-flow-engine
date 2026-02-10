"""Console print transform - explicit console output in flows."""

from __future__ import annotations

from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("transform/print")
class ConsolePrintTransform(Component):
    """
    Print a message to the console.

    Use this component when you want explicit output during flow execution,
    such as progress indicators or debug information.

    The message supports variable interpolation from the current context.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/print",
            description="Print a message to the console",
            category="transform",
            config={
                "prefix": ConfigSpec(
                    type="string",
                    default="",
                    description="Optional prefix for the message"
                ),
                "level": ConfigSpec(
                    type="string",
                    default="normal",
                    choices=["normal", "debug"],
                    description="Output level: 'normal' or 'debug'"
                ),
            },
            inputs={
                "message": InputSpec(
                    type="string",
                    required=True,
                    description="The message to print"
                ),
            },
            outputs={
                "message": OutputSpec(
                    type="string",
                    description="The printed message (pass-through)"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        message = inputs.get("message", "")
        prefix = self.get_config("prefix", "")
        level = self.get_config("level", "normal")

        full_message = f"{prefix}{message}" if prefix else message

        if level == "debug":
            self.debug(full_message, context)
        else:
            self.report(full_message, context)

        return {"message": full_message}
