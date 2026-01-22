"""Item progress reporter - shows per-item vote results during execution."""

from __future__ import annotations

from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("transform/item_progress")
class ItemProgressTransform(Component):
    """
    Report progress for a single item after its votes are collected.

    Filters the collector's items for the current item, counts votes,
    and prints a formatted progress line.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/item_progress",
            description="Report per-item vote progress",
            category="transform",
            config={
                "item_field": ConfigSpec(
                    type="string",
                    default="character",
                    description="Field name containing the item identifier"
                ),
                "vote_field": ConfigSpec(
                    type="string",
                    default="is_yes",
                    description="Field name containing the boolean vote"
                ),
                "total_questions": ConfigSpec(
                    type="integer",
                    default=5,
                    description="Total questions per item (for display)"
                ),
                "threshold": ConfigSpec(
                    type="integer",
                    default=2,
                    description="Vote threshold for flagging"
                ),
            },
            inputs={
                "items": InputSpec(
                    type="list",
                    required=True,
                    description="All collected vote items"
                ),
                "current_item": InputSpec(
                    type="string",
                    required=True,
                    description="Current item to report on"
                ),
            },
            outputs={
                "yes_count": OutputSpec(
                    type="integer",
                    description="Number of yes votes for this item"
                ),
                "flagged": OutputSpec(
                    type="boolean",
                    description="Whether item meets threshold"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        items = inputs.get("items", [])
        current_item = inputs.get("current_item", "")
        item_field = self.get_config("item_field", "character")
        vote_field = self.get_config("vote_field", "is_yes")
        total_qs = self.get_config("total_questions", 5)
        threshold = self.get_config("threshold", 2)

        # Filter votes for current item
        item_votes = [
            item for item in items
            if item.get(item_field) == current_item
        ]

        yes_count = sum(1 for v in item_votes if v.get(vote_field))
        no_count = len(item_votes) - yes_count
        is_flagged = yes_count >= threshold

        # Format the item name (remove series suffix if present)
        display_name = current_item.split("_(")[0] if "_(" in current_item else current_item

        # Format status indicator
        if is_flagged:
            status = "🚨 FLAGGED"
            bar = "█" * yes_count + "░" * no_count
        else:
            status = "✓ clear"
            bar = "░" * total_qs

        # Print progress
        self.report(f"  {display_name:<25} {bar} {yes_count}/{total_qs} {status}", context)

        return {
            "yes_count": yes_count,
            "flagged": is_flagged,
        }
