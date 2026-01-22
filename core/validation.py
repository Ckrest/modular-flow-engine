"""Pre-runtime validation for plans and type checking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .registry import ComponentRegistry
from .tracing import format_validation_error


@dataclass
class TypeInfo:
    """Information about a type."""
    base: str  # "string", "integer", "list", "dict", "any"
    element_type: str | None = None  # For list[X]
    nullable: bool = False


@dataclass
class ValidationMessage:
    """A validation message (error or warning)."""
    level: str  # "error", "warning", "info"
    message: str
    location: str | None = None
    suggestion: str | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        icon = {"error": "✗", "warning": "⚠", "info": "ℹ"}.get(self.level, "•")
        lines = [f"{icon} {self.message}"]
        if self.location:
            lines.append(f"  Location: {self.location}")
        if self.suggestion:
            lines.append(f"  Suggestion: {self.suggestion}")
        return "\n".join(lines)


@dataclass
class ValidationReport:
    """Complete validation report for a plan."""
    valid: bool
    messages: list[ValidationMessage] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.level == "error"]

    @property
    def warnings(self) -> list[ValidationMessage]:
        return [m for m in self.messages if m.level == "warning"]

    def format(self) -> str:
        """Format the report as a string."""
        if not self.messages:
            return "✓ Validation passed with no issues"

        lines = []
        if self.errors:
            lines.append(f"Errors ({len(self.errors)}):")
            for msg in self.errors:
                lines.append(f"  {msg}")
        if self.warnings:
            lines.append(f"\nWarnings ({len(self.warnings)}):")
            for msg in self.warnings:
                lines.append(f"  {msg}")

        status = "FAILED" if not self.valid else "PASSED with warnings"
        lines.insert(0, f"Validation {status}")
        lines.insert(1, "=" * 50)

        return "\n".join(lines)


class PlanValidator:
    """
    Validates plans before execution.

    Checks:
    1. Schema validity - required fields present
    2. Component existence - all referenced types exist
    3. Reference validity - all variable references resolve
    4. Type compatibility - outputs match expected inputs
    """

    def __init__(self, registry: ComponentRegistry | None = None):
        self.registry = registry or ComponentRegistry.get_instance()
        self.messages: list[ValidationMessage] = []
        self._available_vars: dict[str, TypeInfo] = {}
        self._component_outputs: dict[str, dict[str, TypeInfo]] = {}

    def validate(self, plan: dict) -> ValidationReport:
        """Run all validations and return a report."""
        self.messages = []
        self._available_vars = {}
        self._component_outputs = {}

        # Phase 1: Schema validation
        self._validate_schema(plan)

        # Phase 2: Register plan inputs as available variables
        # These are available throughout the flow as {input_name}
        for input_name, input_spec in plan.get("inputs", {}).items():
            input_type = input_spec.get("type", "string") if isinstance(input_spec, dict) else "string"
            self._available_vars[input_name] = self._parse_type(input_type)

        # Phase 3: Component existence
        self._validate_components(plan)

        # Phase 4: Flow validation
        self._validate_flow(plan)

        return ValidationReport(
            valid=len([m for m in self.messages if m.level == "error"]) == 0,
            messages=self.messages
        )

    def _add_error(self, message: str, location: str = None, suggestion: str = None, **context):
        self.messages.append(ValidationMessage(
            level="error",
            message=message,
            location=location,
            suggestion=suggestion,
            context=context
        ))

    def _add_warning(self, message: str, location: str = None, suggestion: str = None, **context):
        self.messages.append(ValidationMessage(
            level="warning",
            message=message,
            location=location,
            suggestion=suggestion,
            context=context
        ))

    def _validate_schema(self, plan: dict) -> None:
        """Check required plan fields."""
        if "name" not in plan:
            self._add_warning(
                "Plan has no 'name' field",
                suggestion="Add a 'name' field for better identification"
            )

        if "components" not in plan:
            self._add_error(
                "Plan missing 'components' section",
                suggestion="Add a 'components' section defining your components"
            )

        if "flow" not in plan:
            self._add_error(
                "Plan missing 'flow' section",
                suggestion="Add a 'flow' section defining execution steps"
            )

        # Check component definitions
        for comp_id, comp_def in plan.get("components", {}).items():
            if "type" not in comp_def:
                self._add_error(
                    f"Component '{comp_id}' missing 'type'",
                    location=f"components.{comp_id}",
                    suggestion="Add 'type' field (e.g., 'transform/template')"
                )

    def _validate_components(self, plan: dict) -> None:
        """Check all component types exist and store their output types."""
        for comp_id, comp_def in plan.get("components", {}).items():
            comp_type = comp_def.get("type")
            if not comp_type:
                continue

            comp_class = self.registry.get(comp_type)
            if comp_class is None:
                available = self.registry.list_types()
                similar = [t for t in available if comp_type.split("/")[-1] in t]

                self._add_error(
                    f"Unknown component type: '{comp_type}'",
                    location=f"components.{comp_id}",
                    suggestion=f"Similar types: {similar}" if similar else f"Available: {available[:5]}..."
                )
            else:
                # Store output types for this component
                manifest = comp_class.describe()
                self._component_outputs[comp_id] = {
                    name: self._parse_type(spec.type)
                    for name, spec in manifest.outputs.items()
                }

    def _validate_flow(self, plan: dict) -> None:
        """Validate flow steps and variable references."""
        flow = plan.get("flow", [])
        self._validate_steps(flow, "flow", plan.get("components", {}))

    def _validate_steps(self, steps: list, path: str, components: dict) -> None:
        """Recursively validate flow steps."""
        for i, step in enumerate(steps):
            step_path = f"{path}[{i}]"

            if "source" in step:
                self._validate_source_step(step, step_path, components)
            elif "call" in step:
                self._validate_call_step(step, step_path, components)
            elif "sink" in step:
                self._validate_sink_step(step, step_path, components)
            elif "loop" in step:
                self._validate_loop_step(step, step_path, components)
            elif "conditional" in step:
                self._validate_conditional_step(step, step_path, components)
            else:
                self._add_error(
                    f"Unknown step type: {list(step.keys())}",
                    location=step_path,
                    suggestion="Use 'source', 'call', 'sink', 'loop', or 'conditional'"
                )

    def _validate_source_step(self, step: dict, path: str, components: dict) -> None:
        """Validate a source step."""
        source_id = step["source"]
        if source_id not in components:
            self._add_error(
                f"Source references unknown component: '{source_id}'",
                location=path,
                suggestion=f"Available components: {list(components.keys())}"
            )
        else:
            # Register source outputs as available
            if source_id in self._component_outputs:
                for output, type_info in self._component_outputs[source_id].items():
                    self._available_vars[f"{source_id}.{output}"] = type_info

    def _validate_call_step(self, step: dict, path: str, components: dict) -> None:
        """Validate a call step."""
        comp_id = step["call"]
        if comp_id not in components:
            self._add_error(
                f"Call references unknown component: '{comp_id}'",
                location=path,
                suggestion=f"Available components: {list(components.keys())}"
            )
            return

        # Validate input references
        inputs = step.get("inputs", {})
        for input_name, value in inputs.items():
            self._validate_reference(value, f"{path}.inputs.{input_name}")

        # Register outputs as available
        outputs = step.get("outputs", {})
        if outputs:
            for output_name, var_name in outputs.items():
                # Get type from component manifest if available
                if comp_id in self._component_outputs:
                    comp_outputs = self._component_outputs[comp_id]
                    if output_name in comp_outputs:
                        self._available_vars[var_name] = comp_outputs[output_name]
                    else:
                        self._add_warning(
                            f"Component '{comp_id}' may not have output '{output_name}'",
                            location=f"{path}.outputs.{output_name}"
                        )
                else:
                    self._available_vars[var_name] = TypeInfo(base="any")

    def _validate_sink_step(self, step: dict, path: str, components: dict) -> None:
        """Validate a sink step."""
        sink_id = step["sink"]
        if sink_id not in components:
            self._add_error(
                f"Sink references unknown component: '{sink_id}'",
                location=path,
                suggestion=f"Available components: {list(components.keys())}"
            )

        # Validate input references
        inputs = step.get("inputs", {})
        for input_name, value in inputs.items():
            self._validate_reference(value, f"{path}.inputs.{input_name}")

    def _validate_loop_step(self, step: dict, path: str, components: dict) -> None:
        """Validate a loop step."""
        loop_config = step["loop"]

        if "over" not in loop_config:
            self._add_error(
                "Loop missing 'over' field",
                location=f"{path}.loop",
                suggestion="Add 'over' specifying what to iterate"
            )
        else:
            over_ref = loop_config["over"]
            self._validate_reference(f"{{{over_ref}}}", f"{path}.loop.over")

        loop_var = loop_config.get("as", "item")
        index_var = loop_config.get("index")

        # Add loop variables to available vars
        old_vars = dict(self._available_vars)
        self._available_vars[loop_var] = TypeInfo(base="any")
        if index_var:
            self._available_vars[index_var] = TypeInfo(base="integer")

        # Validate inner steps
        inner_steps = loop_config.get("steps", [])
        self._validate_steps(inner_steps, f"{path}.loop.steps", components)

        # Restore vars (loop vars go out of scope)
        # But keep component outputs
        for key in list(self._available_vars.keys()):
            if key not in old_vars and "." not in key:
                del self._available_vars[key]

    def _validate_conditional_step(self, step: dict, path: str, components: dict) -> None:
        """Validate a conditional step."""
        cond_config = step["conditional"]

        if "if" not in cond_config:
            self._add_error(
                "Conditional missing 'if' field",
                location=f"{path}.conditional",
                suggestion="Add 'if' specifying the condition"
            )

        if "then" in cond_config:
            self._validate_steps(cond_config["then"], f"{path}.conditional.then", components)

        if "else" in cond_config:
            self._validate_steps(cond_config["else"], f"{path}.conditional.else", components)

    def _validate_reference(self, value: Any, location: str) -> None:
        """Validate a variable reference."""
        if not isinstance(value, str):
            return

        # Find all {var} references
        refs = re.findall(r"\{([^}]+)\}", value)
        for ref in refs:
            # Skip if it's a known variable or component output
            if ref in self._available_vars:
                continue
            if "." in ref:
                base = ref.split(".")[0]
                if base in self._component_outputs or base in self._available_vars:
                    continue

            # Unknown reference - might be an error or might be defined later
            self._add_warning(
                f"Reference '{{{ref}}}' may not be defined at this point",
                location=location,
                suggestion=f"Available: {list(self._available_vars.keys())[:5]}..."
            )

    def _parse_type(self, type_str: str) -> TypeInfo:
        """Parse a type string like 'list[string]' into TypeInfo."""
        if not type_str:
            return TypeInfo(base="any")

        # Check for list[X] pattern
        match = re.match(r"list\[(\w+)\]", type_str)
        if match:
            return TypeInfo(base="list", element_type=match.group(1))

        return TypeInfo(base=type_str)


def validate_plan(plan: dict) -> ValidationReport:
    """Convenience function to validate a plan."""
    validator = PlanValidator()
    return validator.validate(plan)
