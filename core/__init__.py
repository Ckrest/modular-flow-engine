"""Core dataflow evaluation framework."""

from .component import (
    Component,
    ComponentManifest,
    InputSpec,
    OutputSpec,
    ConfigSpec,
)
from .registry import ComponentRegistry, register_component
from .context import ExecutionContext, OutputMode
from .errors import (
    DataflowError,
    ValidationError,
    ExecutionError,
    ComponentError,
    ErrorProtocol,
    DEFAULT_ERROR_PROTOCOL,
)
from .engine import DataflowEngine, ExecutionResult, PlanInputSpec
from .tracing import ExecutionTracer, TraceLevel, ExecutionTrace
from .composite import (
    CompositeComponent,
    load_composite,
    register_composite,
    load_and_register_composite,
    load_composites_from_directory,
)
from .validation import (
    PlanValidator,
    ValidationReport,
    ValidationMessage,
    validate_plan,
)

# Aliases for "flow" terminology (plan → flow)
FlowValidator = PlanValidator
validate_flow = validate_plan
FlowInputSpec = PlanInputSpec

__all__ = [
    # Component
    "Component",
    "ComponentManifest",
    "InputSpec",
    "OutputSpec",
    "ConfigSpec",
    # Registry
    "ComponentRegistry",
    "register_component",
    # Context
    "ExecutionContext",
    "OutputMode",
    # Errors
    "DataflowError",
    "ValidationError",
    "ExecutionError",
    "ComponentError",
    "ErrorProtocol",
    "DEFAULT_ERROR_PROTOCOL",
    # Engine
    "DataflowEngine",
    "ExecutionResult",
    "PlanInputSpec",
    "FlowInputSpec",  # Alias
    # Tracing
    "ExecutionTracer",
    "TraceLevel",
    "ExecutionTrace",
    # Composite
    "CompositeComponent",
    "load_composite",
    "register_composite",
    "load_and_register_composite",
    "load_composites_from_directory",
    # Validation
    "PlanValidator",
    "FlowValidator",  # Alias
    "ValidationReport",
    "ValidationMessage",
    "validate_plan",
    "validate_flow",  # Alias
]
