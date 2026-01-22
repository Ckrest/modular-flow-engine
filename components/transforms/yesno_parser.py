"""Yes/No parser transform."""

from __future__ import annotations

import re
from typing import Any

from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component


@register_component("transform/yesno_parser")
class YesNoParserTransform(Component):
    """
    Parse text to determine if it contains yes/no answer.

    Useful for processing LLM classification responses.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/yesno_parser",
            description="Parse yes/no answers from text",
            category="transform",
            config={
                "strict": ConfigSpec(
                    type="boolean",
                    default=False,
                    description="If true, only match exact 'yes' or 'no'"
                ),
                "default": ConfigSpec(
                    type="string",
                    default=None,
                    choices=["yes", "no", None],
                    description="Default if no answer detected"
                ),
            },
            inputs={
                "text": InputSpec(
                    type="string",
                    required=True,
                    description="Text to parse for yes/no"
                ),
            },
            outputs={
                "answer": OutputSpec(
                    type="string",
                    description="Parsed answer: 'yes', 'no', or 'unknown'"
                ),
                "is_yes": OutputSpec(
                    type="boolean",
                    description="True if answer is yes"
                ),
                "is_no": OutputSpec(
                    type="boolean",
                    description="True if answer is no"
                ),
                "confidence": OutputSpec(
                    type="string",
                    description="Confidence level: 'high', 'medium', 'low'"
                ),
                "raw_text": OutputSpec(
                    type="string",
                    description="Original input text"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        text = inputs.get("text", "")
        strict = self.get_config("strict", False)
        default = self.get_config("default")

        if not text:
            return self._make_result("unknown", text, "low", default)

        text_lower = text.lower().strip()

        if strict:
            # Exact match only
            if text_lower == "yes":
                return self._make_result("yes", text, "high", default)
            elif text_lower == "no":
                return self._make_result("no", text, "high", default)
            else:
                return self._make_result("unknown", text, "low", default)

        # Flexible parsing
        # High confidence: starts with yes/no
        if re.match(r"^yes\b", text_lower):
            return self._make_result("yes", text, "high", default)
        if re.match(r"^no\b", text_lower):
            return self._make_result("no", text, "high", default)

        # Medium confidence: contains yes/no
        has_yes = bool(re.search(r"\byes\b", text_lower))
        has_no = bool(re.search(r"\bno\b", text_lower))

        if has_yes and not has_no:
            return self._make_result("yes", text, "medium", default)
        if has_no and not has_yes:
            return self._make_result("no", text, "medium", default)

        # Both or neither - ambiguous
        if has_yes and has_no:
            # Check which comes first
            yes_pos = text_lower.find("yes")
            no_pos = text_lower.find("no")
            if yes_pos < no_pos:
                return self._make_result("yes", text, "low", default)
            else:
                return self._make_result("no", text, "low", default)

        return self._make_result("unknown", text, "low", default)

    def _make_result(
        self,
        answer: str,
        raw_text: str,
        confidence: str,
        default: str | None
    ) -> dict[str, Any]:
        """Build the result dictionary."""
        if answer == "unknown" and default:
            answer = default
            confidence = "low"

        return {
            "answer": answer,
            "is_yes": answer == "yes",
            "is_no": answer == "no",
            "confidence": confidence,
            "raw_text": raw_text,
        }
