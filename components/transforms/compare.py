"""Compare transform - compare two values."""

from __future__ import annotations

from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("transform/compare")
class CompareTransform(Component):
    """
    Compare two values and determine if they match.

    Useful for checking predictions against ground truth.
    Supports various comparison modes and type coercion.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/compare",
            description="Compare two values for equality or other relations",
            category="transform",
            config={
                "mode": ConfigSpec(
                    type="string",
                    default="equals",
                    choices=["equals", "not_equals", "contains", "greater", "less"],
                    description="Comparison mode"
                ),
                "case_sensitive": ConfigSpec(
                    type="boolean",
                    default=False,
                    description="Case-sensitive string comparison"
                ),
                "coerce_bool": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Coerce yes/no/true/false strings to boolean"
                ),
            },
            inputs={
                "actual": InputSpec(
                    type="any",
                    required=True,
                    description="Actual/predicted value"
                ),
                "expected": InputSpec(
                    type="any",
                    required=True,
                    description="Expected/ground truth value"
                ),
            },
            outputs={
                "match": OutputSpec(
                    type="boolean",
                    description="Whether values match according to mode"
                ),
                "actual_normalized": OutputSpec(
                    type="any",
                    description="Normalized actual value"
                ),
                "expected_normalized": OutputSpec(
                    type="any",
                    description="Normalized expected value"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        actual = inputs.get("actual")
        expected = inputs.get("expected")
        mode = self.get_config("mode", "equals")
        case_sensitive = self.get_config("case_sensitive", False)
        coerce_bool = self.get_config("coerce_bool", True)

        # Normalize values
        actual_norm = self._normalize(actual, case_sensitive, coerce_bool)
        expected_norm = self._normalize(expected, case_sensitive, coerce_bool)

        # Compare based on mode
        if mode == "equals":
            match = actual_norm == expected_norm
        elif mode == "not_equals":
            match = actual_norm != expected_norm
        elif mode == "contains":
            match = str(expected_norm) in str(actual_norm)
        elif mode == "greater":
            match = actual_norm > expected_norm
        elif mode == "less":
            match = actual_norm < expected_norm
        else:
            match = actual_norm == expected_norm

        return {
            "match": match,
            "actual_normalized": actual_norm,
            "expected_normalized": expected_norm,
        }

    def _normalize(self, value: Any, case_sensitive: bool, coerce_bool: bool) -> Any:
        """Normalize a value for comparison."""
        if value is None:
            return None

        if isinstance(value, str):
            if not case_sensitive:
                value = value.lower().strip()
            else:
                value = value.strip()

            if coerce_bool:
                if value in ("yes", "true", "1"):
                    return True
                elif value in ("no", "false", "0"):
                    return False

        return value
