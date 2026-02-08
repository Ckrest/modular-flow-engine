"""Category parser transform - extract category from text given valid options."""

from __future__ import annotations

from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("transform/category_parser")
class CategoryParserTransform(Component):
    """
    Parse a category from text given a list of valid categories.

    Looks for category names in the response and returns the first match.
    Case-insensitive matching with optional fuzzy support.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/category_parser",
            description="Extract category from text given valid options",
            category="transform",
            config={
                "default_category": ConfigSpec(
                    type="string",
                    default="unknown",
                    description="Category to return if no match found"
                ),
                "case_sensitive": ConfigSpec(
                    type="boolean",
                    default=False,
                    description="Whether matching is case-sensitive"
                ),
            },
            inputs={
                "text": InputSpec(
                    type="string",
                    required=True,
                    description="Text to parse for category"
                ),
                "categories": InputSpec(
                    type="list",
                    required=True,
                    description="List of valid category names"
                ),
            },
            outputs={
                "category": OutputSpec(
                    type="string",
                    description="The matched category"
                ),
                "matched": OutputSpec(
                    type="boolean",
                    description="Whether a category was found"
                ),
                "confidence": OutputSpec(
                    type="string",
                    description="Confidence level: exact, partial, none"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        text = inputs.get("text", "")
        categories = inputs.get("categories", [])
        default = self.get_config("default_category", "unknown")
        case_sensitive = self.get_config("case_sensitive", False)

        if not text or not categories:
            return {
                "category": default,
                "matched": False,
                "confidence": "none",
            }

        # Normalize for comparison
        compare_text = text if case_sensitive else text.lower()

        # First pass: look for exact word matches
        for cat in categories:
            compare_cat = cat if case_sensitive else cat.lower()
            # Check if category appears as a word (not substring)
            if compare_cat in compare_text.split() or compare_text.strip() == compare_cat:
                return {
                    "category": cat,
                    "matched": True,
                    "confidence": "exact",
                }

        # Second pass: look for substring matches
        for cat in categories:
            compare_cat = cat if case_sensitive else cat.lower()
            if compare_cat in compare_text:
                return {
                    "category": cat,
                    "matched": True,
                    "confidence": "partial",
                }

        # No match found
        return {
            "category": default,
            "matched": False,
            "confidence": "none",
        }
