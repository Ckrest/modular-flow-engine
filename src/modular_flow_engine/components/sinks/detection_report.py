"""Detection report sink - generates child detection summary reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec, ValidationResult
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("sink/detection_report")
class DetectionReportSink(Component):
    """
    Generate a human-readable detection report from voting results.

    Shows flagged items prominently, with vote breakdowns and confidence levels.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="sink/detection_report",
            description="Generate child detection report from voting results",
            category="sink",
            config={
                "path": ConfigSpec(
                    type="string",
                    required=True,
                    description="Output file path"
                ),
                "title": ConfigSpec(
                    type="string",
                    default="Child Character Detection Report",
                    description="Report title"
                ),
            },
            inputs={
                "results": InputSpec(
                    type="list",
                    required=True,
                    description="Per-item detection results"
                ),
                "flagged": InputSpec(
                    type="list",
                    required=True,
                    description="List of flagged item names"
                ),
                "not_flagged": InputSpec(
                    type="list",
                    required=True,
                    description="List of clear item names"
                ),
                "summary": InputSpec(
                    type="dict",
                    required=True,
                    description="Summary statistics"
                ),
                "questions": InputSpec(
                    type="list",
                    required=False,
                    description="List of questions used"
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
        title = self.get_config("title", "Child Character Detection Report")

        # Use context output_dir if available
        if context.output_dir and not configured_path.is_absolute():
            path = context.output_dir / configured_path.name
        else:
            path = configured_path

        results = inputs.get("results", [])
        flagged = inputs.get("flagged", [])
        not_flagged = inputs.get("not_flagged", [])
        summary = inputs.get("summary", {})
        questions = inputs.get("questions", [])

        lines = []

        # Header
        lines.append(f"# {title}")
        lines.append("")
        lines.append(f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
        lines.append("")

        # Summary box
        lines.append("## 📊 Summary")
        lines.append("")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| Total characters scanned | {summary.get('total_items', 0)} |")
        lines.append(f"| 🚨 **Flagged as child** | **{summary.get('total_flagged', 0)}** |")
        lines.append(f"| ✓ Clear (not flagged) | {summary.get('total_clear', 0)} |")
        lines.append(f"| Detection threshold | ≥{summary.get('threshold_used', 2)} of 5 votes |")
        lines.append(f"| Flag rate | {summary.get('flag_rate', 0) * 100:.1f}% |")
        lines.append("")

        # Questions used
        if questions:
            lines.append("## 🔍 Detection Questions Used")
            lines.append("")
            for i, q in enumerate(questions, 1):
                lines.append(f"{i}. {q}")
            lines.append("")

        # Flagged items (prominent)
        if flagged:
            lines.append("## 🚨 FLAGGED CHARACTERS")
            lines.append("")
            lines.append("These characters met the detection threshold:")
            lines.append("")
            lines.append("| Character | Votes | Confidence | Status |")
            lines.append("|-----------|-------|------------|--------|")

            for r in results:
                if r.get("flagged"):
                    name = r.get("item", "unknown")
                    short_name = name.split("_(")[0] if "_(" in name else name
                    votes = r.get("vote_ratio", "?/?")
                    conf = r.get("confidence", 0) * 100
                    conf_bar = "🔴" if conf >= 80 else "🟠" if conf >= 60 else "🟡"
                    lines.append(f"| {short_name} | {votes} | {conf_bar} {conf:.0f}% | 🚨 FLAGGED |")
            lines.append("")

        # Clear items
        if not_flagged:
            lines.append("## ✓ Clear Characters")
            lines.append("")
            lines.append("These characters did NOT meet the detection threshold:")
            lines.append("")
            lines.append("| Character | Votes | Confidence | Status |")
            lines.append("|-----------|-------|------------|--------|")

            for r in results:
                if not r.get("flagged"):
                    name = r.get("item", "unknown")
                    short_name = name.split("_(")[0] if "_(" in name else name
                    votes = r.get("vote_ratio", "?/?")
                    conf = r.get("confidence", 0) * 100
                    lines.append(f"| {short_name} | {votes} | {conf:.0f}% | ✓ Clear |")
            lines.append("")

        # Full results table
        lines.append("## 📋 Complete Results")
        lines.append("")
        lines.append("| Character | Yes Votes | No Votes | Confidence | Flagged |")
        lines.append("|-----------|-----------|----------|------------|---------|")

        # Sort: flagged first, then by confidence
        sorted_results = sorted(results, key=lambda x: (-x.get("flagged", False), -x.get("confidence", 0)))

        for r in sorted_results:
            name = r.get("item", "unknown")
            short_name = name.split("_(")[0][:25] if "_(" in name else name[:25]
            yes_v = r.get("yes_votes", 0)
            no_v = r.get("no_votes", 0)
            conf = r.get("confidence", 0) * 100
            flag = "🚨 YES" if r.get("flagged") else "✓ No"
            lines.append(f"| {short_name} | {yes_v} | {no_v} | {conf:.0f}% | {flag} |")

        lines.append("")
        lines.append("---")
        lines.append("*Report generated by dataflow-eval child detector*")

        # Write
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(lines)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        # Report summary
        flag_count = summary.get('total_flagged', 0)
        clear_count = summary.get('total_clear', 0)
        flag_rate = summary.get('flag_rate', 0) * 100
        self.report(f"  📊 Report: {flag_count} flagged, {clear_count} clear ({flag_rate:.0f}% flag rate)", context)

        return {"path": str(path)}
