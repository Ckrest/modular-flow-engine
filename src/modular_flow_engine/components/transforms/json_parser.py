"""JSON parser transform - extracts and parses JSON from text."""

from __future__ import annotations

import json
import re
from typing import Any

from ...core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from ...core.context import ExecutionContext
from ...core.registry import register_component


@register_component("transform/json_parser")
class JsonParserTransform(Component):
    """
    Extract and parse JSON from text, handling common LLM response patterns.

    Handles:
    - Plain JSON
    - JSON in markdown code blocks (```json ... ```)
    - JSON with surrounding text
    - Partial/truncated JSON (with lenient mode)
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/json_parser",
            description="Extract and parse JSON from text",
            category="transform",
            config={
                "lenient": ConfigSpec(
                    type="boolean",
                    default=True,
                    description="Try to fix common JSON errors (missing quotes, trailing commas)"
                ),
                "default": ConfigSpec(
                    type="dict",
                    required=False,
                    description="Default value if parsing fails (null = raise error)"
                ),
            },
            inputs={
                "text": InputSpec(
                    type="string",
                    required=True,
                    description="Text containing JSON to parse"
                ),
            },
            outputs={
                "data": OutputSpec(
                    type="dict",
                    description="Parsed JSON object (or default if failed)"
                ),
                "success": OutputSpec(
                    type="boolean",
                    description="Whether parsing succeeded"
                ),
                "error": OutputSpec(
                    type="string",
                    description="Error message if parsing failed"
                ),
                "raw_json": OutputSpec(
                    type="string",
                    description="The extracted JSON string before parsing"
                ),
            }
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        text = inputs.get("text", "")
        lenient = self.get_config("lenient", True)
        default = self.get_config("default")

        if not text:
            if default is not None:
                return {
                    "data": default,
                    "success": False,
                    "error": "Empty input",
                    "raw_json": "",
                }
            raise ValueError("Empty input text and no default provided")

        # Try to extract JSON from text
        json_str = self._extract_json(text)

        if not json_str:
            if default is not None:
                return {
                    "data": default,
                    "success": False,
                    "error": "No JSON found in text",
                    "raw_json": "",
                }
            raise ValueError("No JSON found in text")

        # Try to parse
        try:
            data = json.loads(json_str)
            return {
                "data": data,
                "success": True,
                "error": "",
                "raw_json": json_str,
            }
        except json.JSONDecodeError as e:
            if lenient:
                # Try to fix common issues
                fixed = self._fix_json(json_str)
                try:
                    data = json.loads(fixed)
                    return {
                        "data": data,
                        "success": True,
                        "error": "",
                        "raw_json": fixed,
                    }
                except json.JSONDecodeError:
                    pass

            if default is not None:
                return {
                    "data": default,
                    "success": False,
                    "error": str(e),
                    "raw_json": json_str,
                }
            raise ValueError(f"Failed to parse JSON: {e}")

    def _extract_json(self, text: str) -> str | None:
        """Extract JSON from text, handling code blocks and mixed content."""
        text = text.strip()

        # Try markdown code block first
        code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if code_block:
            return code_block.group(1).strip()

        # Try to find object or array bounds
        # Start from first { or [
        obj_start = text.find("{")
        arr_start = text.find("[")

        if obj_start == -1 and arr_start == -1:
            return None

        # Use whichever comes first
        if arr_start != -1 and (obj_start == -1 or arr_start < obj_start):
            start = arr_start
            open_char, close_char = "[", "]"
        else:
            start = obj_start
            open_char, close_char = "{", "}"

        # Find matching closing bracket
        depth = 0
        in_string = False
        escape_next = False
        end = start

        for i, char in enumerate(text[start:], start=start):
            if escape_next:
                escape_next = False
                continue

            if char == "\\":
                escape_next = True
                continue

            if char == '"' and not escape_next:
                in_string = not in_string
                continue

            if in_string:
                continue

            if char == open_char:
                depth += 1
            elif char == close_char:
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if depth != 0:
            # Unbalanced, return what we have (lenient mode may fix it)
            return text[start:]

        return text[start:end + 1]

    def _fix_json(self, json_str: str) -> str:
        """Attempt to fix common JSON errors from LLMs."""
        fixed = json_str

        # Remove trailing commas before } or ]
        fixed = re.sub(r",\s*([}\]])", r"\1", fixed)

        # Fix unquoted keys (simple cases)
        fixed = re.sub(r"(\{|,)\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', fixed)

        # Fix single quotes to double quotes (careful with apostrophes)
        # Only do this if there are no double quotes in strings
        if '"' not in fixed.replace('\\"', ''):
            fixed = fixed.replace("'", '"')

        # Remove control characters that might have leaked in
        fixed = re.sub(r"[\x00-\x1f]", " ", fixed)

        return fixed
