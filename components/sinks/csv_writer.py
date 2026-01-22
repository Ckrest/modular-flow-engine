"""CSV writer sink - exports results to CSV format."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec, ValidationResult
from core.context import ExecutionContext
from core.registry import register_component


@register_component("sink/csv_writer")
class CsvWriterSink(Component):
    """
    Export results to CSV format for spreadsheet analysis.

    Takes a list of items and writes them to a CSV file with headers
    automatically derived from the first item's keys.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="sink/csv_writer",
            description="Export results to CSV file",
            category="sink",
            config={
                "path": ConfigSpec(
                    type="string",
                    required=True,
                    description="Output file path (e.g., 'results.csv')"
                ),
                "columns": ConfigSpec(
                    type="list",
                    required=False,
                    description="Specific columns to include (default: all)"
                ),
            },
            inputs={
                "items": InputSpec(
                    type="list",
                    required=True,
                    description="List of items to export"
                ),
            },
            outputs={
                "path": OutputSpec(
                    type="string",
                    description="Path to written file"
                ),
                "count": OutputSpec(
                    type="integer",
                    description="Number of rows written"
                ),
            }
        )

    def validate(self, inputs: dict[str, Any]) -> ValidationResult:
        items = inputs.get("items")
        if items is not None and not isinstance(items, list):
            return ValidationResult(valid=False, errors=["'items' must be a list"])
        return ValidationResult(valid=True)

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        items = inputs.get("items", [])
        if not items:
            return {"path": "", "count": 0}

        configured_path = Path(self.get_config("path"))
        columns = self.get_config("columns")

        # Use context output_dir if available
        if context.output_dir and not configured_path.is_absolute():
            path = context.output_dir / configured_path.name
        else:
            path = configured_path

        # Determine columns from first item if not specified
        if not columns:
            first_item = items[0]
            if isinstance(first_item, dict):
                columns = list(first_item.keys())
            else:
                columns = ["value"]

        # Write CSV
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(columns)

            for item in items:
                if isinstance(item, dict):
                    row = [item.get(col, "") for col in columns]
                else:
                    row = [item]
                writer.writerow(row)

        self.report(f"  ✓ CSV: {len(items)} rows → {path.name}", context)

        return {
            "path": str(path),
            "count": len(items),
        }
