"""Key-value source - loads key|value pairs from a text file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("source/key_value")
class KeyValueSource(Component):
    """
    Load a file with key|value pairs into a dictionary.

    Useful for ground truth files, configuration mappings, etc.
    Format: key | value (one per line, # for comments)
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="source/key_value",
            description="Load key|value pairs from file into dictionary",
            category="source",
            config={
                "path": ConfigSpec(
                    type="string",
                    required=True,
                    description="Path to the key-value file"
                ),
                "delimiter": ConfigSpec(
                    type="string",
                    default="|",
                    description="Delimiter between key and value"
                ),
                "normalize_values": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Normalize values (lowercase, strip)"
                ),
                "value_type": ConfigSpec(
                    type="string",
                    default="string",
                    choices=["string", "boolean", "integer", "float"],
                    description="Type to convert values to"
                ),
            },
            inputs={},
            outputs={
                "data": OutputSpec(
                    type="dict",
                    description="Dictionary of key-value pairs"
                ),
                "keys": OutputSpec(
                    type="list[string]",
                    description="List of all keys"
                ),
                "count": OutputSpec(
                    type="integer",
                    description="Number of entries"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        path = Path(self.get_config("path"))
        delimiter = self.get_config("delimiter", "|")
        normalize = self.get_config("normalize_values", True)
        value_type = self.get_config("value_type", "string")

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        data = {}
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                if delimiter not in line:
                    continue

                key, value = line.split(delimiter, 1)
                key = key.strip()
                value = value.strip()

                if normalize:
                    value = value.lower()

                # Convert value type
                if value_type == "boolean":
                    value = value in ("yes", "true", "1")
                elif value_type == "integer":
                    value = int(value)
                elif value_type == "float":
                    value = float(value)

                data[key] = value

        return {
            "data": data,
            "keys": list(data.keys()),
            "count": len(data)
        }
