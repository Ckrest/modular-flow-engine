"""Dataflow execution engine."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .component import Component
from .context import ExecutionContext, OutputMode
from .errors import (
    ValidationError,
    ExecutionError,
    ComponentError,
    ErrorProtocol,
    ErrorRecord,
    DEFAULT_ERROR_PROTOCOL,
)
from .registry import ComponentRegistry
from .tracing import ExecutionTracer, TraceLevel, ExecutionTrace


@dataclass
class PlanInputSpec:
    """Specification for a plan-level input."""
    type: str  # "string", "path", "integer", "boolean", "list"
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass
class ExecutionResult:
    """Result of executing a plan."""
    success: bool
    outputs: dict[str, Any] = field(default_factory=dict)
    errors: list[ErrorRecord] = field(default_factory=list)
    duration_seconds: float = 0.0
    stats: dict[str, Any] = field(default_factory=dict)
    traces: list[ExecutionTrace] = field(default_factory=list)


class DataflowEngine:
    """
    Executes dataflow evaluation plans.

    The engine is intentionally "dumb" - it has no hardcoded knowledge
    of specific fields or component behaviors. It:

    1. Loads a plan (JSON)
    2. Instantiates components from the registry
    3. Validates all wiring
    4. Executes flow steps, routing data between components
    """

    def __init__(self, trace_level: TraceLevel = TraceLevel.ERRORS):
        self.components: dict[str, Component] = {}
        self.plan: dict[str, Any] = {}
        self.context: ExecutionContext | None = None
        self.registry = ComponentRegistry.get_instance()
        self.error_protocol = DEFAULT_ERROR_PROTOCOL
        self.tracer = ExecutionTracer(level=trace_level)
        self._stats = {
            "components_executed": 0,
            "steps_executed": 0,
            "errors_recovered": 0,
        }
        self._plan_inputs: dict[str, Any] = {}  # User-provided input values

    def load_plan(self, plan: dict[str, Any] | str | Path) -> None:
        """
        Load a plan from dict, JSON string, or file path.
        """
        if isinstance(plan, (str, Path)):
            path = Path(plan)
            if path.exists():
                with open(path, "r") as f:
                    plan = json.load(f)
            else:
                plan = json.loads(str(plan))

        self.plan = plan
        self._instantiate_components()

        # Set error handling from plan
        if "error_handling" in plan:
            eh = plan["error_handling"]
            self.error_protocol = ErrorProtocol(
                on_error=eh.get("default", "stop"),
                max_retries=eh.get("max_retries", 3),
                default_value=eh.get("default_value"),
            )

    def get_input_schema(self) -> dict[str, PlanInputSpec]:
        """Get the plan's declared inputs with their specifications."""
        schema = {}
        for name, spec in self.plan.get("inputs", {}).items():
            if isinstance(spec, dict):
                schema[name] = PlanInputSpec(
                    type=spec.get("type", "string"),
                    required=spec.get("required", True),
                    default=spec.get("default"),
                    description=spec.get("description", ""),
                )
            else:
                # Simple string type shorthand: "inputs": {"name": "string"}
                schema[name] = PlanInputSpec(type=spec, required=True)
        return schema

    def set_inputs(self, inputs: dict[str, Any]) -> None:
        """Set plan input values. Call before execute()."""
        self._plan_inputs.update(inputs)
        # Re-instantiate components with new input values
        if self.plan:
            self._instantiate_components()

    def get_missing_inputs(self) -> list[tuple[str, PlanInputSpec]]:
        """Get list of required inputs that haven't been provided."""
        missing = []
        for name, spec in self.get_input_schema().items():
            if spec.required and name not in self._plan_inputs:
                if spec.default is None:
                    missing.append((name, spec))
        return missing

    def _resolve_input_references(self, value: Any) -> Any:
        """Resolve {$inputs.X} references in a value."""
        import re

        if isinstance(value, str):
            # Check for full replacement: "{$inputs.name}"
            match = re.fullmatch(r"\{\$inputs\.([^}]+)\}", value)
            if match:
                input_name = match.group(1)
                if input_name in self._plan_inputs:
                    return self._plan_inputs[input_name]
                # Check for default in schema
                schema = self.get_input_schema()
                if input_name in schema and schema[input_name].default is not None:
                    return schema[input_name].default
                return value  # Leave unresolved for validation to catch

            # Partial replacement: "prefix_{$inputs.name}_suffix"
            def replace_input(m: re.Match) -> str:
                input_name = m.group(1)
                if input_name in self._plan_inputs:
                    return str(self._plan_inputs[input_name])
                schema = self.get_input_schema()
                if input_name in schema and schema[input_name].default is not None:
                    return str(schema[input_name].default)
                return m.group(0)  # Leave unresolved

            return re.sub(r"\{\$inputs\.([^}]+)\}", replace_input, value)

        elif isinstance(value, dict):
            return {k: self._resolve_input_references(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._resolve_input_references(v) for v in value]

        return value

    def _instantiate_components(self) -> None:
        """Create component instances from plan definitions."""
        self.components.clear()

        components_def = self.plan.get("components", {})
        for instance_id, comp_def in components_def.items():
            comp_type = comp_def.get("type")
            if not comp_type:
                raise ValidationError(
                    f"Component '{instance_id}' missing 'type'",
                    errors=[f"Component '{instance_id}' has no type specified"]
                )

            # Resolve {$inputs.X} references in config
            config = comp_def.get("config", {})
            resolved_config = self._resolve_input_references(config)

            component = self.registry.create(comp_type, instance_id, resolved_config)
            self.components[instance_id] = component

    def validate(self) -> list[str]:
        """
        Validate the plan before execution.

        Returns list of error messages (empty if valid).
        """
        errors = []

        # Check all component types exist
        for instance_id, comp_def in self.plan.get("components", {}).items():
            comp_type = comp_def.get("type")
            if not self.registry.get(comp_type):
                errors.append(f"Unknown component type: {comp_type}")

        # Check flow references valid components
        def check_flow(steps: list, path: str = "flow"):
            for i, step in enumerate(steps):
                step_path = f"{path}[{i}]"

                if "call" in step:
                    comp_id = step["call"]
                    if comp_id not in self.components:
                        errors.append(
                            f"{step_path}: references unknown component '{comp_id}'"
                        )

                if "source" in step:
                    src_id = step["source"]
                    if src_id not in self.components:
                        errors.append(
                            f"{step_path}: references unknown source '{src_id}'"
                        )

                if "sink" in step:
                    sink_id = step["sink"]
                    if sink_id not in self.components:
                        errors.append(
                            f"{step_path}: references unknown sink '{sink_id}'"
                        )

                # Recurse into control structures
                if "loop" in step:
                    inner_steps = step["loop"].get("steps", [])
                    check_flow(inner_steps, f"{step_path}.loop.steps")

                if "conditional" in step:
                    for branch in ["then", "else"]:
                        if branch in step["conditional"]:
                            check_flow(
                                step["conditional"][branch],
                                f"{step_path}.conditional.{branch}"
                            )

        check_flow(self.plan.get("flow", []))

        return errors

    async def execute(
        self,
        output_dir: Path | None = None,
        output_mode: OutputMode = OutputMode.NORMAL
    ) -> ExecutionResult:
        """
        Execute the loaded plan.

        Args:
            output_dir: Directory where sinks should write output files.
            output_mode: Controls what components print to console.

        Returns ExecutionResult with outputs and any errors.
        """
        if not self.plan:
            raise ExecutionError("No plan loaded")

        # Validate first
        validation_errors = self.validate()
        if validation_errors:
            raise ValidationError(
                "Plan validation failed",
                errors=validation_errors
            )

        # Initialize context and tracer
        settings = self.plan.get("settings", {})

        # Include plan inputs as initial context variables
        initial_vars = dict(self._plan_inputs)

        self.context = ExecutionContext(
            engine=self,
            output_dir=output_dir,
            output_mode=output_mode,
            settings=settings,
            variables=initial_vars,
        )

        # Register sink components for finalization tracking
        for instance_id, comp_def in self.plan.get("components", {}).items():
            comp_type = comp_def.get("type", "")
            if comp_type.startswith("sink/"):
                self.context.register_sink(instance_id)
        self.tracer = ExecutionTracer(level=self.tracer.level)  # Reset tracer
        self._stats = {
            "components_executed": 0,
            "steps_executed": 0,
            "errors_recovered": 0,
        }
        errors: list[ErrorRecord] = []
        start_time = time.time()

        try:
            # Execute flow
            flow = self.plan.get("flow", [])
            await self._execute_steps(flow, self.context, errors)

            # Collect outputs
            outputs = self._collect_outputs()

            return ExecutionResult(
                success=len([e for e in errors if not e.recovered]) == 0,
                outputs=outputs,
                errors=errors,
                duration_seconds=time.time() - start_time,
                stats=dict(self._stats),
                traces=self.tracer.traces,
            )

        except Exception as e:
            # Print error context if we have traces
            error_traces = self.tracer.get_error_traces()
            if error_traces:
                print(self.tracer.format_error_context(error_traces[-1]))

            errors.append(ErrorRecord(
                error_type=type(e).__name__,
                message=str(e),
                recovered=False,
            ))
            return ExecutionResult(
                success=False,
                outputs={},
                errors=errors,
                duration_seconds=time.time() - start_time,
                stats=dict(self._stats),
                traces=self.tracer.traces,
            )

    async def _execute_steps(
        self,
        steps: list[dict],
        context: ExecutionContext,
        errors: list[ErrorRecord],
    ) -> None:
        """Execute a list of flow steps."""
        for i, step in enumerate(steps):
            self._stats["steps_executed"] += 1

            try:
                await self._execute_step(step, context, errors)
            except Exception as e:
                error_record = ErrorRecord(
                    error_type=type(e).__name__,
                    message=str(e),
                    step_index=i,
                    context={"step": step},
                )

                # Check error protocol
                if self.error_protocol.on_error == "stop":
                    errors.append(error_record)
                    raise ExecutionError(
                        f"Step {i} failed: {e}",
                        step=step,
                        cause=e
                    )
                elif self.error_protocol.on_error == "skip":
                    error_record.recovered = True
                    error_record.recovery_action = "skipped"
                    errors.append(error_record)
                    self._stats["errors_recovered"] += 1

    async def _execute_step(
        self,
        step: dict,
        context: ExecutionContext,
        errors: list[ErrorRecord],
    ) -> None:
        """Execute a single flow step."""

        # Source step - load data from source component
        if "source" in step:
            await self._execute_source(step, context)

        # Call step - execute a transform component
        elif "call" in step:
            await self._execute_call(step, context)

        # Sink step - send data to sink component
        elif "sink" in step:
            await self._execute_sink(step, context)

        # Loop step - iterate over a collection
        elif "loop" in step:
            await self._execute_loop(step, context, errors)

        # Conditional step
        elif "conditional" in step:
            await self._execute_conditional(step, context, errors)

        else:
            raise ExecutionError(
                f"Unknown step type: {list(step.keys())}",
                step=step
            )

    async def _execute_source(
        self,
        step: dict,
        context: ExecutionContext
    ) -> None:
        """Execute a source component."""
        source_id = step["source"]
        component = self.components[source_id]

        try:
            # Sources have no inputs
            outputs = await component.execute({}, context)
            # Store at ROOT context so outputs persist across all scopes
            self.context.set_component_output(source_id, outputs)
            self._stats["components_executed"] += 1
        except Exception as e:
            raise ComponentError(
                f"Error loading source '{source_id}': {type(e).__name__}: {e}",
                component_id=source_id,
                cause=e
            ) from e

    async def _execute_call(
        self,
        step: dict,
        context: ExecutionContext
    ) -> None:
        """Execute a transform component call."""
        comp_id = step["call"]
        component = self.components[comp_id]

        # Resolve inputs from step spec
        inputs_spec = step.get("inputs", {})
        inputs = context.resolve_inputs(inputs_spec)

        # Start tracing
        trace = self.tracer.start_step("call", comp_id, inputs)

        try:
            # Validate inputs
            validation = component.validate(inputs)
            if not validation.valid:
                raise ComponentError(
                    f"Input validation failed: {validation.errors}",
                    component_id=comp_id,
                    inputs=inputs
                )

            # Execute
            outputs = await component.execute(inputs, context)

            # Map outputs to context variables (in current scope for local use)
            outputs_mapping = step.get("outputs", {})
            if outputs_mapping:
                for output_name, var_name in outputs_mapping.items():
                    if output_name in outputs:
                        context.set(var_name, outputs[output_name])

            # ALWAYS store component outputs at ROOT context
            # This ensures collectors/sinks are accessible after loops end
            self.context.set_component_output(comp_id, outputs)

            self._stats["components_executed"] += 1

            # End trace successfully
            self.tracer.end_step(trace, outputs)

        except ComponentError as e:
            # Already wrapped, just re-raise
            self.tracer.end_step(trace, error=e)
            raise
        except Exception as e:
            # Wrap with component context for better error messages
            self.tracer.end_step(trace, error=e)
            raise ComponentError(
                f"Error in '{comp_id}': {type(e).__name__}: {e}",
                component_id=comp_id,
                inputs=inputs,
                cause=e
            ) from e

    async def _execute_sink(
        self,
        step: dict,
        context: ExecutionContext
    ) -> None:
        """Execute a sink component (finalization step)."""
        sink_id = step["sink"]
        component = self.components[sink_id]

        # Sinks may have inputs to collect
        inputs_spec = step.get("inputs", {})
        inputs = context.resolve_inputs(inputs_spec)

        try:
            outputs = await component.execute(inputs, context)
            # Store at ROOT context for global access
            self.context.set_component_output(sink_id, outputs)
            # Mark sink as finalized - safe to access .items
            self.context.mark_sink_finalized(sink_id)
            self._stats["components_executed"] += 1
        except Exception as e:
            raise ComponentError(
                f"Error finalizing sink '{sink_id}': {type(e).__name__}: {e}",
                component_id=sink_id,
                inputs=inputs,
                cause=e
            ) from e

    async def _execute_loop(
        self,
        step: dict,
        context: ExecutionContext,
        errors: list[ErrorRecord],
    ) -> None:
        """Execute a loop over a collection."""
        loop_config = step["loop"]

        # Get the collection to iterate over
        over_ref = loop_config["over"]
        collection = context.resolve(f"{{{over_ref}}}")

        if collection is None:
            raise ExecutionError(
                f"Loop 'over' reference '{over_ref}' resolved to None",
                step=step
            )

        if not hasattr(collection, "__iter__"):
            raise ExecutionError(
                f"Loop 'over' reference '{over_ref}' is not iterable",
                step=step
            )

        loop_var = loop_config.get("as", "item")
        index_var = loop_config.get("index")
        inner_steps = loop_config.get("steps", [])

        # Get collection size for progress reporting
        try:
            total = len(collection)
        except TypeError:
            total = None

        # Determine progress interval (show every 10% or every 10 items, whichever is larger)
        show_progress = context.output_mode != OutputMode.QUIET and total and total > 10
        progress_interval = max(total // 10, 10) if show_progress else 0

        for i, item in enumerate(collection):
            # Create child context for loop iteration
            loop_vars = {loop_var: item}
            if index_var:
                loop_vars[index_var] = i

            child_context = context.child(loop_vars)

            # Set loop context for tracing (helps debug which iteration failed)
            self.tracer.set_loop_context(loop_vars)

            # Execute inner steps
            await self._execute_steps(inner_steps, child_context, errors)

            # Progress output (every N iterations)
            if show_progress and (i + 1) % progress_interval == 0:
                pct = ((i + 1) / total) * 100
                print(f"  [{loop_var}] {i + 1}/{total} ({pct:.0f}%)")

        # Final progress message
        if show_progress and total % progress_interval != 0:
            print(f"  [{loop_var}] {total}/{total} (100%)")

        # Clear loop context after loop completes
        self.tracer.clear_loop_context()

    async def _execute_conditional(
        self,
        step: dict,
        context: ExecutionContext,
        errors: list[ErrorRecord],
    ) -> None:
        """Execute a conditional branch."""
        cond_config = step["conditional"]

        condition = context.resolve(cond_config.get("if", "false"))

        # Evaluate condition
        if self._is_truthy(condition):
            then_steps = cond_config.get("then", [])
            await self._execute_steps(then_steps, context, errors)
        else:
            else_steps = cond_config.get("else", [])
            if else_steps:
                await self._execute_steps(else_steps, context, errors)

    def _is_truthy(self, value: Any) -> bool:
        """Determine if a value is truthy."""
        if isinstance(value, str):
            return value.lower() not in ("false", "no", "0", "")
        return bool(value)

    def _collect_outputs(self) -> dict[str, Any]:
        """Collect final outputs from sink components."""
        outputs = {}

        # Find all sink components and get their collected data
        for comp_id, component in self.components.items():
            manifest = component.describe()
            if manifest.category == "sink":
                comp_outputs = self.context.get_component_output(comp_id)
                if comp_outputs:
                    outputs[comp_id] = comp_outputs

        return outputs
