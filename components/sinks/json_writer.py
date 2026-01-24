"""JSON writer sink - writes collected data to JSON file."""

from __future__ import annotations

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
    all data when the sink is finalized.

    Destinations:
    - "file": Write to JSON file (default, always enabled)
    - "return": Also include in API response
    - "console": Also print to stdout
    """

    def __init__(self, instance_id: str, config: dict[str, Any]):
        super().__init__(instance_id, config)
        self._collected: list[dict[str, Any]] = []
        self._finalized = False

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
                "destinations": ConfigSpec(
                    type="list",
                    required=False,
                    default=["file"],
                    description="Where to write output: 'file' (default), 'return', 'console'"
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

        # Get configured path (context.write will resolve against output_dir)
        configured_path = self.get_config("path")
        include_metadata = self.get_config("include_metadata", True)

        # Build output structure
        output = {
            "results": self._collected,
        }

        if include_metadata:
            output["metadata"] = {
                "timestamp": datetime.now().isoformat(),
                "count": len(self._collected),
            }

        # Write to destinations on finalization
        if not inputs and not self._finalized:
            self._finalized = True
            destinations = self.get_config("destinations", ["file"])

            for dest in destinations:
                if dest == "file":
                    context.write(output, to="file", path=configured_path)
                elif dest == "return":
                    context.write({self.instance_id: output}, to="return")
                elif dest == "console":
                    context.write(output, to="console")

        # Compute actual path for return value
        path = Path(configured_path)
        if context.output_dir and not path.is_absolute():
            path = context.output_dir / path

        return {
            "path": str(path),
            "count": len(self._collected),
        }
