"""Composite components - reusable groups of components acting as one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TYPE_CHECKING

from .component import (
    Component,
    ComponentManifest,
    InputSpec,
    OutputSpec,
    ConfigSpec,
    ValidationResult,
)
from .context import ExecutionContext
from .registry import ComponentRegistry

if TYPE_CHECKING:
    from .engine import DataflowEngine


class CompositeComponent(Component):
    """
    A component composed of other components wired together.

    Composites allow reusable patterns to be packaged as a single component.
    They have their own inputs/outputs and encapsulate internal wiring.

    Definition structure:
    {
        "name": "composite_name",
        "type": "composite",
        "description": "What this composite does",
        "inputs": {
            "input_name": {"type": "string", "required": true, "description": "..."}
        },
        "outputs": {
            "output_name": {"type": "boolean", "description": "..."}
        },
        "config": {
            "config_name": {"type": "string", "default": "value"}
        },
        "internal": {
            "components": { ... },
            "flow": [ ... ],
            "output_mappings": {
                "output_name": "{internal_var}"
            }
        }
    }
    """

    # Class-level storage for composite definitions
    _definitions: dict[str, dict] = {}

    def __init__(self, instance_id: str, config: dict[str, Any]):
        # Get the definition for this composite type
        # The type is stored during registration
        self._definition = self._get_definition_for_instance(instance_id, config)
        super().__init__(instance_id, config)

        # Internal engine for executing the composite's flow
        self._internal_engine: DataflowEngine | None = None

    @classmethod
    def _get_definition_for_instance(cls, instance_id: str, config: dict) -> dict:
        """Get the definition, checking config for composite_type."""
        composite_type = config.get("_composite_type")
        if composite_type and composite_type in cls._definitions:
            return cls._definitions[composite_type]
        raise ValueError(f"No composite definition found for {instance_id}")

    @classmethod
    def register_definition(cls, name: str, definition: dict) -> None:
        """Register a composite definition."""
        cls._definitions[name] = definition

    @classmethod
    def get_definition(cls, name: str) -> dict | None:
        """Get a registered composite definition."""
        return cls._definitions.get(name)

    @classmethod
    def describe(cls) -> ComponentManifest:
        """Default describe - overridden per-instance."""
        return ComponentManifest(
            type="composite",
            description="Composite component (see instance for details)",
            category="transform",
        )

    def describe_instance(self) -> ComponentManifest:
        """Describe this specific composite instance."""
        defn = self._definition

        # Build inputs from definition
        inputs = {}
        for name, spec in defn.get("inputs", {}).items():
            inputs[name] = InputSpec(
                type=spec.get("type", "any"),
                required=spec.get("required", True),
                description=spec.get("description", ""),
                default=spec.get("default"),
            )

        # Build outputs from definition
        outputs = {}
        for name, spec in defn.get("outputs", {}).items():
            outputs[name] = OutputSpec(
                type=spec.get("type", "any"),
                description=spec.get("description", ""),
            )

        # Build config from definition
        config = {}
        for name, spec in defn.get("config", {}).items():
            config[name] = ConfigSpec(
                type=spec.get("type", "string"),
                required=spec.get("required", False),
                default=spec.get("default"),
                description=spec.get("description", ""),
            )

        return ComponentManifest(
            type=f"composite/{defn.get('name', 'unknown')}",
            description=defn.get("description", ""),
            category="transform",
            inputs=inputs,
            outputs=outputs,
            config=config,
        )

    def validate(self, inputs: dict[str, Any]) -> ValidationResult:
        """Validate inputs against the composite's input spec."""
        manifest = self.describe_instance()
        errors = []
        warnings = []

        for name, spec in manifest.inputs.items():
            if spec.required and name not in inputs:
                errors.append(f"Missing required input: {name}")

        return ValidationResult(valid=len(errors) == 0, errors=errors, warnings=warnings)

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        """Execute the composite's internal flow."""
        from .engine import DataflowEngine

        defn = self._definition
        internal = defn.get("internal", {})

        # Create internal engine
        internal_engine = DataflowEngine()

        # Build internal plan
        internal_plan = {
            "name": f"{self.instance_id}_internal",
            "components": internal.get("components", {}),
            "flow": internal.get("flow", []),
        }

        # Merge composite config into component configs
        for comp_id, comp_def in internal_plan["components"].items():
            if "config" not in comp_def:
                comp_def["config"] = {}
            # Allow composite config to override internal component config
            for key, value in self.config.items():
                if not key.startswith("_"):  # Skip internal keys
                    if key in comp_def.get("config", {}):
                        comp_def["config"][key] = value

        internal_engine.load_plan(internal_plan)

        # Pass inputs as plan inputs (they'll be available as initial context variables)
        internal_engine.set_inputs(inputs)

        # Execute internal flow
        result = await internal_engine.execute()

        if not result.success:
            error_msgs = [e.message for e in result.errors if not e.recovered]
            raise RuntimeError(f"Composite execution failed: {error_msgs}")

        # Map internal outputs to composite outputs
        output_mappings = internal.get("output_mappings", {})
        outputs = {}

        for output_name, mapping in output_mappings.items():
            # Resolve the mapping from internal context
            value = internal_engine.context.resolve(mapping)
            outputs[output_name] = value

        return outputs


def load_composite(path: Path | str) -> str:
    """
    Load a composite definition from a JSON file and register it.

    Returns the composite name for reference.
    """
    path = Path(path)
    with open(path, "r") as f:
        definition = json.load(f)

    name = definition.get("name")
    if not name:
        raise ValueError(f"Composite definition missing 'name': {path}")

    CompositeComponent.register_definition(name, definition)
    return name


def create_composite_class(name: str) -> type:
    """
    Create a component class for a specific composite.

    This creates a class that can be registered in the component registry.
    """
    definition = CompositeComponent.get_definition(name)
    if not definition:
        raise ValueError(f"Unknown composite: {name}")

    class SpecificComposite(CompositeComponent):
        _composite_name = name

        def __init__(self, instance_id: str, config: dict[str, Any]):
            config["_composite_type"] = name
            super().__init__(instance_id, config)

        @classmethod
        def describe(cls) -> ComponentManifest:
            defn = CompositeComponent.get_definition(name)
            inputs = {
                n: InputSpec(
                    type=s.get("type", "any"),
                    required=s.get("required", True),
                    description=s.get("description", ""),
                )
                for n, s in defn.get("inputs", {}).items()
            }
            outputs = {
                n: OutputSpec(
                    type=s.get("type", "any"),
                    description=s.get("description", ""),
                )
                for n, s in defn.get("outputs", {}).items()
            }
            return ComponentManifest(
                type=f"composite/{name}",
                description=defn.get("description", ""),
                category="transform",
                inputs=inputs,
                outputs=outputs,
            )

    SpecificComposite.__name__ = f"Composite_{name}"
    return SpecificComposite


def register_composite(name: str) -> None:
    """Register a loaded composite in the component registry."""
    cls = create_composite_class(name)
    registry = ComponentRegistry.get_instance()
    registry.register(f"composite/{name}", cls)


def load_and_register_composite(path: Path | str) -> str:
    """Load a composite from file and register it. Returns the composite name."""
    name = load_composite(path)
    register_composite(name)
    return name


def load_composites_from_directory(directory: Path | str) -> list[str]:
    """Load all composite definitions from a directory."""
    directory = Path(directory)
    loaded = []

    for path in directory.glob("*.json"):
        try:
            name = load_and_register_composite(path)
            loaded.append(name)
        except Exception as e:
            print(f"Warning: Failed to load composite {path}: {e}")

    return loaded
