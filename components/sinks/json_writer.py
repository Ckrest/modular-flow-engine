"""JSON writer sink - writes collected data to JSON file."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("sink/json_writer")
class JsonWriterSink(Component):
    """
    Write collected data to a JSON file.

    Can be called multiple times to accumulate data, then writes
    all data when finalize() is called (or on final sink step).
    """

    def __init__(self, instance_id: str, config: dict[str, Any]):
        super().__init__(instance_id, config)
        self._collected: list[dict[str, Any]] = []
        self._written = False

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="sink/json_writer",
            description="Write data to JSON file",
            category="sink",
            config={
                "path": ConfigSpec(
                    type="string",
                    required=True,
                    description="Output file path"
                ),
                "pretty": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Pretty-print JSON"
                ),
                "include_metadata": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Include execution metadata"
                ),
            },
            inputs={},
            outputs={
                "path": OutputSpec(
                    type="string",
                    description="Path to written file"
                ),
                "count": OutputSpec(
                    type="integer",
                    description="Number of items written"
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
        # Collect inputs if provided
        if inputs:
            self._collected.append(dict(inputs))

        # Write to file
        configured_path = Path(self.get_config("path"))
        pretty = self.get_config("pretty", True)
        include_metadata = self.get_config("include_metadata", True)

        # Use context output_dir if available, otherwise use configured path as-is
        if context.output_dir and not configured_path.is_absolute():
            path = context.output_dir / configured_path.name
        else:
            path = configured_path

        # Build output structure
        output = {
            "results": self._collected,
        }

        if include_metadata:
            output["metadata"] = {
                "timestamp": datetime.now().isoformat(),
                "count": len(self._collected),
            }

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write file
        with open(path, "w", encoding="utf-8") as f:
            if pretty:
                json.dump(output, f, indent=2, ensure_ascii=False)
            else:
                json.dump(output, f, ensure_ascii=False)

        self._written = True

        return {
            "path": str(path),
            "count": len(self._collected),
        }
