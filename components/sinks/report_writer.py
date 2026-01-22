"""Report writer sink - generates human-readable markdown reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec, ValidationResult
from core.context import ExecutionContext
from core.registry import register_component


@register_component("sink/report_writer")
class ReportWriterSink(Component):
    """
    Generate a human-readable markdown report from evaluation results.

    Accepts raw results and aggregated statistics, formats them into
    a clear report with tables and summaries.
    """

    def __init__(self, instance_id: str, config: dict[str, Any]):
        super().__init__(instance_id, config)
        self._written = False

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="sink/report_writer",
            description="Generate markdown report from results",
            category="sink",
            config={
                "path": ConfigSpec(
                    type="string",
                    required=True,
                    description="Output file path (e.g., 'results/report.md')"
                ),
                "title": ConfigSpec(
                    type="string",
                    required=False,
                    default="Evaluation Report",
                    description="Report title"
                ),
                "show_all_results": ConfigSpec(
                    type="boolean",
                    required=False,
                    default=False,
                    description="Include all individual results (can be long)"
                ),
                "max_sample_results": ConfigSpec(
                    type="integer",
                    required=False,
                    default=10,
                    description="Max sample results to show when show_all_results=false"
                ),
            },
            inputs={
                "raw_results": InputSpec(
                    type="list",
                    required=False,
                    description="List of individual result items"
                ),
                "groups": InputSpec(
                    type="list",
                    required=False,
                    description="Per-group statistics from aggregator"
                ),
                "summary": InputSpec(
                    type="dict",
                    required=False,
                    description="Overall summary statistics"
                ),
            },
            outputs={
                "path": OutputSpec(
                    type="string",
                    description="Path to written report"
                ),
            }
        )

    def validate(self, inputs: dict[str, Any]) -> ValidationResult:
        return ValidationResult(valid=True)

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        configured_path = Path(self.get_config("path"))
        title = self.get_config("title", "Evaluation Report")
        show_all = self.get_config("show_all_results", False)
        max_samples = self.get_config("max_sample_results", 10)

        # Use context output_dir if available, otherwise use configured path as-is
        if context.output_dir and not configured_path.is_absolute():
            # For relative paths, use just the filename in output_dir
            path = context.output_dir / configured_path.name
        else:
            path = configured_path

        raw_results = inputs.get("raw_results", [])
        groups = inputs.get("groups", [])
        summary = inputs.get("summary", {})

        # Build the report
        lines = []

        # Header
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("")

        # Summary section
        if summary:
            lines.append("## Summary")
            lines.append("")
            lines.append(f"- **Total items evaluated:** {summary.get('total_items', 'N/A')}")
            lines.append(f"- **Overall accuracy:** {summary.get('overall_accuracy', 0) * 100:.1f}%")
            lines.append(f"- **Total groups/questions:** {summary.get('total_groups', 'N/A')}")
            if summary.get('best_group') is not None:
                lines.append(f"- **Best performing:** Group {summary.get('best_group')} ({summary.get('best_accuracy', 0) * 100:.1f}%)")
            lines.append("")

        # Per-group performance
        if groups:
            lines.append("## Performance by Group")
            lines.append("")
            lines.append("| Group | Accuracy | Correct | Total | Precision | Recall | F1 |")
            lines.append("|-------|----------|---------|-------|-----------|--------|-----|")

            # Sort by accuracy descending
            sorted_groups = sorted(groups, key=lambda g: g.get('accuracy', 0), reverse=True)

            for g in sorted_groups:
                acc = g.get('accuracy', 0) * 100
                prec = g.get('precision', 0) * 100
                rec = g.get('recall', 0) * 100
                f1 = g.get('f1', 0) * 100
                lines.append(
                    f"| {g.get('group', 'N/A')} | {acc:.1f}% | "
                    f"{g.get('correct', 0)} | {g.get('count', 0)} | "
                    f"{prec:.1f}% | {rec:.1f}% | {f1:.1f}% |"
                )
            lines.append("")

        # Sample results
        if raw_results:
            if show_all:
                lines.append("## All Results")
                results_to_show = raw_results
            else:
                lines.append(f"## Sample Results (first {min(max_samples, len(raw_results))})")
                results_to_show = raw_results[:max_samples]

            lines.append("")

            # Determine columns from first result
            if results_to_show:
                # Key columns to show
                key_cols = ['character', 'item', 'question', 'answer', 'is_yes', 'expected', 'match']
                available_cols = [c for c in key_cols if c in results_to_show[0]]

                if not available_cols:
                    available_cols = list(results_to_show[0].keys())[:6]

                # Header
                lines.append("| " + " | ".join(available_cols) + " |")
                lines.append("| " + " | ".join(["---"] * len(available_cols)) + " |")

                # Rows
                for r in results_to_show:
                    cells = []
                    for col in available_cols:
                        val = r.get(col, "")
                        # Truncate long strings
                        if isinstance(val, str) and len(val) > 30:
                            val = val[:27] + "..."
                        # Format booleans nicely
                        if isinstance(val, bool):
                            val = "✓" if val else "✗"
                        cells.append(str(val))
                    lines.append("| " + " | ".join(cells) + " |")

                lines.append("")

            if not show_all and len(raw_results) > max_samples:
                lines.append(f"*... and {len(raw_results) - max_samples} more results*")
                lines.append("")

        # Errors section (if any)
        # This would need to be passed in as an input

        # Footer
        lines.append("---")
        lines.append("*Report generated by dataflow-eval*")

        # Write the report
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(lines)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        self._written = True

        return {
            "path": str(path),
        }
