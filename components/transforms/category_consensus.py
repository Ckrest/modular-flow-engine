"""Category consensus transform - analyze votes and detect agreement/disagreement."""

from __future__ import annotations

from collections import defaultdict, Counter
from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("transform/category_consensus")
class CategoryConsensusTransform(Component):
    """
    Analyze category votes per item and determine consensus.

    Takes a list of votes (each with item identifier and voted category),
    groups by item, and determines:
    - unanimous: all models agree
    - majority: most models agree (> threshold)
    - disputed: no clear winner, needs debate

    Returns per-item consensus results and lists items needing arbitration.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/category_consensus",
            description="Check consensus across category votes per item",
            category="transform",
            config={
                "item_field": ConfigSpec(
                    type="string",
                    default="tag",
                    description="Field containing the item identifier"
                ),
                "category_field": ConfigSpec(
                    type="string",
                    default="category",
                    description="Field containing the voted category"
                ),
                "model_field": ConfigSpec(
                    type="string",
                    default="model",
                    description="Field containing the model name"
                ),
                "majority_threshold": ConfigSpec(
                    type="float",
                    default=0.5,
                    description="Fraction of votes needed for majority (> threshold)"
                ),
            },
            inputs={
                "votes": InputSpec(
                    type="list",
                    required=True,
                    description="List of vote dicts with item, category, model"
                ),
            },
            outputs={
                "results": OutputSpec(
                    type="list[dict]",
                    description="Per-item consensus results"
                ),
                "agreed": OutputSpec(
                    type="list[dict]",
                    description="Items where consensus was reached"
                ),
                "disputed": OutputSpec(
                    type="list[dict]",
                    description="Items needing arbitration"
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
        votes = inputs.get("votes", [])
        item_field = self.get_config("item_field", "tag")
        category_field = self.get_config("category_field", "category")
        model_field = self.get_config("model_field", "model")
        majority_threshold = self.get_config("majority_threshold", 0.5)

        # Group votes by item
        votes_by_item: dict[str, list[dict]] = defaultdict(list)
        for vote in votes:
            item = vote.get(item_field, "unknown")
            votes_by_item[item].append(vote)

        results = []
        agreed = []
        disputed = []

        for item, item_votes in votes_by_item.items():
            # Count categories
            categories = [v.get(category_field, "unknown") for v in item_votes]
            category_counts = Counter(categories)
            total_votes = len(categories)

            # Find winner
            most_common = category_counts.most_common()
            top_category, top_count = most_common[0]
            top_ratio = top_count / total_votes if total_votes > 0 else 0

            # Determine consensus type
            if top_count == total_votes:
                consensus_type = "unanimous"
            elif top_ratio > majority_threshold:
                consensus_type = "majority"
            else:
                consensus_type = "disputed"

            # Build votes summary
            votes_summary = {
                cat: count for cat, count in category_counts.items()
            }

            # Get model votes detail
            model_votes = {
                v.get(model_field, "?"): v.get(category_field, "?")
                for v in item_votes
            }

            result = {
                "item": item,
                "consensus_type": consensus_type,
                "winning_category": top_category if consensus_type != "disputed" else None,
                "top_category": top_category,
                "top_ratio": round(top_ratio, 2),
                "vote_counts": votes_summary,
                "model_votes": model_votes,
                "total_votes": total_votes,
            }
            results.append(result)

            if consensus_type in ("unanimous", "majority"):
                result["final_category"] = top_category
                agreed.append(result)
            else:
                disputed.append(result)

        # Summary
        summary = {
            "total_items": len(results),
            "unanimous": len([r for r in results if r["consensus_type"] == "unanimous"]),
            "majority": len([r for r in results if r["consensus_type"] == "majority"]),
            "disputed": len(disputed),
            "agreement_rate": round((len(agreed) / len(results)) if results else 0, 2),
        }

        # Report
        self.report(
            f"  🗳️ Consensus: {summary['unanimous']} unanimous, "
            f"{summary['majority']} majority, {summary['disputed']} disputed",
            context
        )

        return {
            "results": results,
            "agreed": agreed,
            "disputed": disputed,
            "summary": summary,
        }
