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
from .persistence import PersistentEngine, RunState, create_persistent_engine
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
    # Persistence
    "PersistentEngine",
    "RunState",
    "create_persistent_engine",
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
    "ValidationReport",
    "ValidationMessage",
    "validate_plan",
]
