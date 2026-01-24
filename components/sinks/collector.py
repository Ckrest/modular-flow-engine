"""Collector sink - accumulates data during execution."""

from __future__ import annotations

from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("sink/collector")
class CollectorSink(Component):
    """
    Collect data items during execution.

    Call this component multiple times (e.g., in a loop) to accumulate
    results. Configure destinations to control where results are written
    when the sink is finalized.

    Destinations:
    - "return": Include in API response (ExecutionResult.returns)
    - "file": Write to JSON file (requires path config)
    - "console": Print to stdout
    """

    def __init__(self, instance_id: str, config: dict[str, Any]):
        super().__init__(instance_id, config)
        self._collected: list[dict[str, Any]] = []
        self._finalized = False

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="sink/collector",
            description="Collect data items during execution",
            category="sink",
            config={
                "fields": ConfigSpec(
                    type="list",
                    required=False,
                    description="Field names to collect (collects all if not specified)"
                ),
                "destinations": ConfigSpec(
                    type="list",
                    required=False,
                    default=["return"],
                    description="Where to write output: 'return', 'file', 'console'"
                ),
                "path": ConfigSpec(
                    type="string",
                    required=False,
                    description="Output file path (required if 'file' in destinations)"
                ),
            },
            inputs={
                # Dynamic - accepts any inputs
            },
            outputs={
                "items": OutputSpec(
                    type="list[dict]",
                    description="All collected items"
                ),
                "count": OutputSpec(
                    type="integer",
                    description="Number of items collected"
                ),
            }
        )

    def validate(self, inputs: dict[str, Any]) -> "ValidationResult":
        from core.component import ValidationResult
        return ValidationResult(valid=True)

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        fields = self.get_config("fields")

        if fields:
            # Collect only specified fields
            item = {k: inputs.get(k) for k in fields if k in inputs}
        else:
            # Collect all inputs
            item = dict(inputs)

        if item:  # Only add non-empty items
            self._collected.append(item)

        # Build result data
        data = {
            "items": list(self._collected),
            "count": len(self._collected),
        }

        # Write to destinations on finalization (sink step in flow)
        # Finalization is detected by empty inputs (called via {"sink": "name"})
        if not inputs and not self._finalized:
            self._finalized = True
            destinations = self.get_config("destinations", ["return"])

            for dest in destinations:
                if dest == "file":
                    path = self.get_config("path", f"{self.instance_id}_results.json")
                    context.write(data, to="file", path=path)
                elif dest == "return":
                    # Use instance_id as key in return space
                    context.write({self.instance_id: data}, to="return")
                elif dest == "console":
                    context.write(data, to="console")

        return data

    def get_collected(self) -> list[dict[str, Any]]:
        """Get all collected items (for external access)."""
        return list(self._collected)

    def clear(self) -> None:
        """Clear collected items."""
        self._collected.clear()
        self._finalized = False
