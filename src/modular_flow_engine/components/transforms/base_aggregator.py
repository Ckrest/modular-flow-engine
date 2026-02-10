"""Aggregator transform - group items and calculate statistics."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("transform/aggregator")
class AggregatorTransform(Component):
    """
    Group items by a key and calculate statistics per group.

    Takes a list of items, groups by specified field, and calculates
    metrics like count, accuracy (if match field exists), etc.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/aggregator",
            description="Group items and calculate per-group statistics",
            category="transform",
            config={
                "group_by": ConfigSpec(
                    type="string",
                    required=True,
                    description="Field name to group by"
                ),
                "match_field": ConfigSpec(
                    type="string",
                    default="match",
                    description="Field containing boolean match/correct value"
                ),
                "count_field": ConfigSpec(
                    type="string",
                    default=None,
                    description="Field to count (count all if not specified)"
                ),
            },
            inputs={
                "items": InputSpec(
                    type="list",
                    required=True,
                    description="List of items to aggregate"
                ),
            },
            outputs={
                "groups": OutputSpec(
                    type="list[dict]",
                    description="List of group statistics"
                ),
                "summary": OutputSpec(
                    type="dict",
                    description="Overall summary statistics"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        items = inputs.get("items", [])
        group_by = self.get_config("group_by")
        match_field = self.get_config("match_field", "match")

        # Group items
        grouped = defaultdict(list)
        for item in items:
            if isinstance(item, dict):
                key = item.get(group_by, "unknown")
                grouped[key].append(item)

        # Calculate stats per group
        groups = []
        total_correct = 0
        total_count = 0

        for group_key, group_items in grouped.items():
            count = len(group_items)
            correct = sum(1 for item in group_items if item.get(match_field, False))
            accuracy = correct / count if count > 0 else 0.0

            # Calculate true positives, false positives, etc. if applicable
            tp = sum(1 for item in group_items
                     if item.get(match_field) and item.get("is_yes", item.get("actual")))
            tn = sum(1 for item in group_items
                     if item.get(match_field) and not item.get("is_yes", item.get("actual")))
            fp = sum(1 for item in group_items
                     if not item.get(match_field) and item.get("is_yes", item.get("actual")))
            fn = sum(1 for item in group_items
                     if not item.get(match_field) and not item.get("is_yes", item.get("actual")))

            # Precision, recall, F1
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

            groups.append({
                "group": group_key,
                "count": count,
                "correct": correct,
                "accuracy": round(accuracy, 4),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
                "tp": tp,
                "tn": tn,
                "fp": fp,
                "fn": fn,
            })

            total_correct += correct
            total_count += count

        # Sort by accuracy descending
        groups.sort(key=lambda x: (x["accuracy"], x["f1"]), reverse=True)

        # Overall summary
        summary = {
            "total_items": total_count,
            "total_groups": len(groups),
            "total_correct": total_correct,
            "overall_accuracy": round(total_correct / total_count, 4) if total_count > 0 else 0.0,
            "best_group": groups[0]["group"] if groups else None,
            "best_accuracy": groups[0]["accuracy"] if groups else 0.0,
        }

        return {
            "groups": groups,
            "summary": summary,
        }
