"""Base component class and specification types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class InputSpec:
    """Specification for a component input."""
    type: str  # e.g., "string", "list[string]", "any"
    required: bool = True
    description: str = ""
    default: Any = None


@dataclass
class OutputSpec:
    """Specification for a component output."""
    type: str  # e.g., "string", "boolean", "dict"
    description: str = ""


@dataclass
class ConfigSpec:
    """Specification for a component configuration option."""
    type: str  # "string", "integer", "boolean", "float", "list", "dict"
    required: bool = False
    default: Any = None
    description: str = ""
    choices: list[Any] | None = None  # Allowed values


@dataclass
class ComponentManifest:
    """Self-description of a component's interface."""
    type: str  # e.g., "source/text_list", "transform/openrouter"
    description: str
    config: dict[str, ConfigSpec] = field(default_factory=dict)
    inputs: dict[str, InputSpec] = field(default_factory=dict)
    outputs: dict[str, OutputSpec] = field(default_factory=dict)
    category: Literal["source", "transform", "control", "sink"] = "transform"


@dataclass
class ValidationResult:
    """Result of validating component inputs/config."""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class Component(ABC):
    """
    Base class for all dataflow components.

    Components are the building blocks of evaluation plans. Each component:
    - Declares its inputs, outputs, and configuration via describe()
    - Validates its configuration and inputs via validate()
    - Executes its logic and returns outputs via execute()

    The engine never assumes what fields a component needs - it asks the
    component via describe() and routes data accordingly.
    """

    def __init__(self, instance_id: str, config: dict[str, Any]):
        """
        Initialize component with instance ID and configuration.

        Args:
            instance_id: Unique identifier for this component instance in the plan
            config: Configuration values from the plan
        """
        self.instance_id = instance_id
        self.config = config
        self._validate_config()

    def _validate_config(self) -> None:
        """Validate configuration against manifest."""
        manifest = self.describe()
        for name, spec in manifest.config.items():
            if spec.required and name not in self.config:
                if spec.default is None:
                    raise ValueError(
                        f"Component {self.instance_id}: missing required config '{name}'"
                    )
            if name in self.config and spec.choices:
                if self.config[name] not in spec.choices:
                    raise ValueError(
                        f"Component {self.instance_id}: config '{name}' must be one of {spec.choices}"
                    )

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value with fallback to spec default."""
        if key in self.config:
            return self.config[key]
        manifest = self.describe()
        if key in manifest.config:
            return manifest.config[key].default
        return default

    def report(self, message: str, context: "ExecutionContext") -> None:
        """
        Print a message in NORMAL and DEBUG modes.

        Use for user-facing status messages like:
        - "✓ Wrote 100 rows to results.csv"
        - "Aggregated: 27 flagged (28%)"
        """
        from .context import OutputMode
        if context.output_mode in (OutputMode.NORMAL, OutputMode.DEBUG):
            print(message, flush=True)

    def debug(self, message: str, context: "ExecutionContext") -> None:
        """
        Print a message only in DEBUG mode.

        Use for internal details like:
        - "API response: 'yes' (42ms)"
        - "Resolved {item} → 'anya_forger'"
        """
        from .context import OutputMode
        if context.output_mode == OutputMode.DEBUG:
            print(f"[DEBUG] {message}", flush=True)

    @classmethod
    @abstractmethod
    def describe(cls) -> ComponentManifest:
        """
        Return the component's manifest describing its interface.

        This is the key to the dataflow architecture - the engine
        queries this to understand what the component needs and produces,
        rather than having hardcoded assumptions.
        """
        pass

    def validate(self, inputs: dict[str, Any]) -> ValidationResult:
        """
        Validate that provided inputs satisfy requirements.

        Override for custom validation logic.
        """
        manifest = self.describe()
        errors = []
        warnings = []

        for name, spec in manifest.inputs.items():
            if spec.required and name not in inputs:
                errors.append(f"Missing required input: {name}")

        # Check for unexpected inputs (warning only)
        for name in inputs:
            if name not in manifest.inputs:
                warnings.append(f"Unexpected input: {name}")

        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    @abstractmethod
    async def execute(
        self,
        inputs: dict[str, Any],
        context: "ExecutionContext"
    ) -> dict[str, Any]:
        """
        Execute the component and return outputs.

        Args:
            inputs: Resolved input values
            context: Execution context for accessing engine state

        Returns:
            Dictionary mapping output names to values
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.instance_id!r})"


# Type alias for forward reference
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .context import ExecutionContext
