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
    results. The collected items are available in the final outputs.
    """

    def __init__(self, instance_id: str, config: dict[str, Any]):
        super().__init__(instance_id, config)
        self._collected: list[dict[str, Any]] = []

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
                    description="List of field names to collect (optional, collects all if not specified)"
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
        # Accept any inputs
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

        return {
            "items": list(self._collected),
            "count": len(self._collected),
        }

    def get_collected(self) -> list[dict[str, Any]]:
        """Get all collected items (for external access)."""
        return list(self._collected)

    def clear(self) -> None:
        """Clear collected items."""
        self._collected.clear()
