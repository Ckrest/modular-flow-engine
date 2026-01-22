"""Vote aggregator transform - aggregate yes/no votes and apply threshold."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("transform/vote_aggregator")
class VoteAggregatorTransform(Component):
    """
    Aggregate yes/no votes per item and apply a threshold.

    Takes a list of vote items (each with item_field and vote_field),
    groups by item, counts yes votes, and flags items meeting threshold.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/vote_aggregator",
            description="Aggregate votes and apply threshold detection",
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
                "threshold": ConfigSpec(
                    type="integer",
                    default=2,
                    description="Minimum yes votes to flag as positive"
                ),
                "total_questions": ConfigSpec(
                    type="integer",
                    default=5,
                    description="Total number of questions per item"
                ),
            },
            inputs={
                "items": InputSpec(
                    type="list",
                    required=True,
                    description="List of vote items to aggregate"
                ),
            },
            outputs={
                "results": OutputSpec(
                    type="list[dict]",
                    description="Per-item results with vote counts and flag"
                ),
                "flagged": OutputSpec(
                    type="list[string]",
                    description="List of flagged item names"
                ),
                "not_flagged": OutputSpec(
                    type="list[string]",
                    description="List of non-flagged item names"
                ),
                "summary": OutputSpec(
                    type="dict",
                    description="Summary statistics"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        items = inputs.get("items", [])
        item_field = self.get_config("item_field", "character")
        vote_field = self.get_config("vote_field", "is_yes")
        threshold = self.get_config("threshold", 2)
        total_qs = self.get_config("total_questions", 5)

        # Group votes by item
        votes_by_item = defaultdict(list)
        for item in items:
            item_name = item.get(item_field, "unknown")
            vote = item.get(vote_field, False)
            votes_by_item[item_name].append(vote)

        # Calculate results
        results = []
        flagged = []
        not_flagged = []

        for item_name, votes in sorted(votes_by_item.items()):
            yes_count = sum(1 for v in votes if v)
            no_count = len(votes) - yes_count
            is_flagged = yes_count >= threshold
            confidence = yes_count / len(votes) if votes else 0

            result = {
                "item": item_name,
                "yes_votes": yes_count,
                "no_votes": no_count,
                "total_votes": len(votes),
                "vote_ratio": f"{yes_count}/{len(votes)}",
                "confidence": round(confidence, 2),
                "flagged": is_flagged,
                "status": "🚨 FLAGGED" if is_flagged else "✓ Clear",
            }
            results.append(result)

            if is_flagged:
                flagged.append(item_name)
            else:
                not_flagged.append(item_name)

        summary = {
            "total_items": len(results),
            "total_flagged": len(flagged),
            "total_clear": len(not_flagged),
            "threshold_used": threshold,
            "flag_rate": round(len(flagged) / len(results), 2) if results else 0,
        }

        # Report aggregation results
        flag_rate = summary["flag_rate"] * 100
        self.report(
            f"  🗳️ Aggregated {len(items)} votes → {len(flagged)} flagged ({flag_rate:.0f}%)",
            context
        )

        return {
            "results": results,
            "flagged": flagged,
            "not_flagged": not_flagged,
            "summary": summary,
        }
