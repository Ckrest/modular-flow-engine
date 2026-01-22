"""Component registry for type-based instantiation with auto-discovery."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Type, TYPE_CHECKING

if TYPE_CHECKING:
    from .component import Component


class ComponentRegistry:
    """
    Registry mapping component type strings to component classes.

    This allows plans to reference components by type string (e.g.,
    "source/text_list") and have the engine instantiate the correct class.
    """

    _instance: "ComponentRegistry | None" = None

    def __init__(self):
        self._components: dict[str, Type["Component"]] = {}

    @classmethod
    def get_instance(cls) -> "ComponentRegistry":
        """Get the singleton registry instance."""
        if cls._instance is None:
            cls._instance = ComponentRegistry()
        return cls._instance

    def register(self, component_type: str, component_class: Type["Component"]) -> None:
        """
        Register a component class under a type string.

        Args:
            component_type: Type identifier (e.g., "source/text_list")
            component_class: The component class to register
        """
        if component_type in self._components:
            raise ValueError(f"Component type already registered: {component_type}")
        self._components[component_type] = component_class

    def get(self, component_type: str) -> Type["Component"] | None:
        """Get a component class by type string."""
        return self._components.get(component_type)

    def create(
        self,
        component_type: str,
        instance_id: str,
        config: dict
    ) -> "Component":
        """
        Create a component instance.

        Args:
            component_type: Type identifier
            instance_id: Unique ID for this instance
            config: Configuration dict

        Returns:
            Instantiated component

        Raises:
            ValueError: If component type is not registered
        """
        component_class = self.get(component_type)
        if component_class is None:
            raise ValueError(f"Unknown component type: {component_type}")
        return component_class(instance_id, config)

    def list_types(self) -> list[str]:
        """List all registered component types."""
        return sorted(self._components.keys())

    def list_by_category(self, category: str) -> list[str]:
        """List component types in a category (source, transform, etc.)."""
        return [t for t in self._components if t.startswith(f"{category}/")]

    def get_manifest(self, component_type: str) -> dict | None:
        """Get the manifest for a component type."""
        component_class = self.get(component_type)
        if component_class is None:
            return None
        manifest = component_class.describe()
        return {
            "type": manifest.type,
            "description": manifest.description,
            "category": manifest.category,
            "config": {k: {"type": v.type, "required": v.required, "default": v.default, "description": v.description}
                      for k, v in manifest.config.items()},
            "inputs": {k: {"type": v.type, "required": v.required, "description": v.description}
                      for k, v in manifest.inputs.items()},
            "outputs": {k: {"type": v.type, "description": v.description}
                       for k, v in manifest.outputs.items()},
        }

    def generate_docs(self, category: str | None = None) -> str:
        """Generate markdown documentation for registered components."""
        lines = []

        types = self.list_by_category(category) if category else self.list_types()

        # Group by category
        by_category: dict[str, list[str]] = {}
        for t in types:
            cat = t.split("/")[0]
            by_category.setdefault(cat, []).append(t)

        for cat in sorted(by_category.keys()):
            lines.append(f"## {cat.title()}s\n")

            for comp_type in sorted(by_category[cat]):
                manifest = self.get_manifest(comp_type)
                if not manifest:
                    continue

                lines.append(f"### `{comp_type}`")
                lines.append(f"{manifest['description']}\n")

                # Config
                if manifest['config']:
                    lines.append("**Config:**")
                    for name, spec in manifest['config'].items():
                        req = " (required)" if spec['required'] else ""
                        default = f" = `{spec['default']}`" if spec['default'] is not None else ""
                        lines.append(f"- `{name}`: {spec['type']}{req}{default} - {spec['description']}")
                    lines.append("")

                # Inputs
                if manifest['inputs']:
                    lines.append("**Inputs:**")
                    for name, spec in manifest['inputs'].items():
                        req = " (required)" if spec['required'] else ""
                        lines.append(f"- `{name}`: {spec['type']}{req} - {spec['description']}")
                    lines.append("")

                # Outputs
                if manifest['outputs']:
                    lines.append("**Outputs:**")
                    for name, spec in manifest['outputs'].items():
                        lines.append(f"- `{name}`: {spec['type']} - {spec['description']}")
                    lines.append("")

                lines.append("---\n")

        return "\n".join(lines)


def register_component(component_type: str):
    """
    Decorator to register a component class.

    Usage:
        @register_component("source/text_list")
        class TextListSource(Component):
            ...
    """
    def decorator(cls: Type["Component"]) -> Type["Component"]:
        ComponentRegistry.get_instance().register(component_type, cls)
        return cls
    return decorator


def auto_discover_components(components_path: Path | str) -> list[str]:
    """
    Auto-discover and register all components in a package.

    Recursively imports all Python modules under the given path.
    Components with @register_component decorators will be registered.

    Args:
        components_path: Path to the components package directory

    Returns:
        List of discovered component type strings
    """
    components_path = Path(components_path)
    if not components_path.exists():
        return []

    # Get the package name from path
    # Assumes structure like: .../components/sources/my_source.py
    package_parts = []
    current = components_path
    while current.name and current.name != current.anchor:
        package_parts.insert(0, current.name)
        if (current / "__init__.py").exists() or current == components_path:
            break
        current = current.parent

    base_package = ".".join(package_parts)

    discovered = []
    before = set(ComponentRegistry.get_instance().list_types())

    # Walk through all subpackages
    for category_dir in components_path.iterdir():
        if not category_dir.is_dir() or category_dir.name.startswith("_"):
            continue

        category_package = f"{base_package}.{category_dir.name}"

        # Import all .py files in category
        for py_file in category_dir.glob("*.py"):
            if py_file.name.startswith("_"):
                continue

            module_name = py_file.stem
            full_module = f"{category_package}.{module_name}"

            try:
                importlib.import_module(full_module)
            except Exception as e:
                print(f"[Warning] Failed to import {full_module}: {e}")

    after = set(ComponentRegistry.get_instance().list_types())
    discovered = list(after - before)

    return sorted(discovered)
