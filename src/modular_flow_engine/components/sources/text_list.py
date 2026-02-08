"""Text list source - loads lines from a text file."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("source/text_list")
class TextListSource(Component):
    """
    Load a text file as a list of lines.

    Useful for loading character lists, question lists, etc.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="source/text_list",
            description="Load text file as list of lines",
            category="source",
            config={
                "path": ConfigSpec(
                    type="string",
                    required=True,
                    description="Path to the text file"
                ),
                "skip_empty": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Skip empty lines"
                ),
                "skip_comments": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Skip comment lines (starting with #, //, or ;)"
                ),
                "comment_prefixes": ConfigSpec(
                    type="list",
                    default=["#", "//", ";"],
                    description="Prefixes that indicate comment lines"
                ),
                "strip": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Strip whitespace from lines"
                ),
            },
            inputs={},  # Sources have no inputs
            outputs={
                "items": OutputSpec(
                    type="list[string]",
                    description="List of lines from the file"
                ),
                "count": OutputSpec(
                    type="integer",
                    description="Number of items loaded"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        path = Path(self.get_config("path"))
        skip_empty = self.get_config("skip_empty", True)
        skip_comments = self.get_config("skip_comments", True)
        comment_prefixes = self.get_config("comment_prefixes", ["#", "//", ";"])
        strip = self.get_config("strip", True)

        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        items = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if strip:
                    line = line.strip()
                else:
                    line = line.rstrip("\n\r")

                if skip_empty and not line:
                    continue
                if skip_comments and any(line.startswith(p) for p in comment_prefixes):
                    continue

                items.append(line)

        return {
            "items": items,
            "count": len(items)
        }
