"""Execution context with hierarchical variable scoping."""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .engine import DataflowEngine


class OutputMode(Enum):
    """Controls what components print to console."""
    QUIET = 0   # Nothing (for tests, scripts, piped output)
    NORMAL = 1  # Component-chosen output only (default)
    DEBUG = 2   # Everything + internal details


class ExecutionContext:
    """
    Hierarchical execution context for variable resolution.

    Supports:
    - Nested scopes (for loops create child contexts)
    - Variable interpolation: {variable}, {component.output}
    - Access to component outputs
    - Current execution state
    """

    def __init__(
        self,
        engine: "DataflowEngine | None" = None,
        parent: "ExecutionContext | None" = None,
        variables: dict[str, Any] | None = None,
        output_dir: Path | None = None,
        output_mode: OutputMode | None = None,
        settings: dict[str, Any] | None = None
    ):
        self._engine = engine
        self._parent = parent
        self._variables: dict[str, Any] = variables or {}
        self._component_outputs: dict[str, dict[str, Any]] = {}
        self._output_dir: Path | None = output_dir
        self._output_mode: OutputMode | None = output_mode
        self._settings: dict[str, Any] = settings or {}
        self._finalized_sinks: set[str] = set()
        self._warned_sinks: set[str] = set()  # Avoid repeated warnings
        self._sink_ids: set[str] = set()  # Track which components are sinks
        self._returns: dict[str, Any] = {}  # Return destination accumulator

    @property
    def engine(self) -> "DataflowEngine | None":
        """Get the engine, walking up parent chain if needed."""
        if self._engine is not None:
            return self._engine
        if self._parent is not None:
            return self._parent.engine
        return None

    @property
    def output_dir(self) -> "Path | None":
        """Get the output directory, walking up parent chain if needed."""
        from pathlib import Path
        if self._output_dir is not None:
            return self._output_dir
        if self._parent is not None:
            return self._parent.output_dir
        return None

    @property
    def output_mode(self) -> OutputMode:
        """Get output mode, walking up parent chain. Defaults to NORMAL."""
        if self._output_mode is not None:
            return self._output_mode
        if self._parent is not None:
            return self._parent.output_mode
        return OutputMode.NORMAL

    @property
    def settings(self) -> dict[str, Any]:
        """Get plan settings, walking up parent chain."""
        if self._settings:
            return self._settings
        if self._parent is not None:
            return self._parent.settings
        return {}

    def get_setting(self, key: str, default: Any = None) -> Any:
        """Get a specific setting value."""
        return self.settings.get(key, default)

    def child(self, variables: dict[str, Any] | None = None) -> "ExecutionContext":
        """Create a child context with additional variables."""
        child_ctx = ExecutionContext(
            engine=None,  # Will use parent's engine
            parent=self,
            variables=variables
        )
        return child_ctx

    def set(self, name: str, value: Any) -> None:
        """Set a variable in this context."""
        self._variables[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        """
        Get a variable, searching up the parent chain.

        Supports:
        - Simple names: "variable"
        - Dotted names: "component.output"
        - Array indexing: "results[0]"
        - Combined: "results[0].field"
        """
        # Handle array indexing anywhere in the path
        if "[" in name:
            return self._get_with_indexing(name, default)

        # Check for dotted notation
        if "." in name:
            parts = name.split(".", 1)
            component_id = parts[0]
            field = parts[1]

            # Warn if accessing .items on unfinalized sink (only for actual sinks)
            if field == "items" and self.is_sink(component_id) and not self.is_sink_finalized(component_id):
                if component_id not in self._warned_sinks:
                    self._warned_sinks.add(component_id)
                    print(f"[Warning] Accessing '{component_id}.items' before sink finalization. "
                          f"Add {{\"sink\": \"{component_id}\"}} to flow before using .items")

            base = self.get(parts[0])
            if base is None:
                # Try component outputs
                if parts[0] in self._component_outputs:
                    outputs = self._component_outputs[parts[0]]
                    return outputs.get(parts[1], default)
                # Check parent
                if self._parent:
                    return self._parent.get(name, default)
                return default
            if isinstance(base, dict):
                return base.get(parts[1], default)
            return getattr(base, parts[1], default)

        # Simple variable lookup
        if name in self._variables:
            return self._variables[name]

        # Check component outputs
        if name in self._component_outputs:
            return self._component_outputs[name]

        # Check parent
        if self._parent is not None:
            return self._parent.get(name, default)

        return default

    def _get_with_indexing(self, name: str, default: Any = None) -> Any:
        """
        Handle paths with array indexing like "results[0].field".

        Parses the path into segments and navigates step by step.
        """
        import re

        # Parse path into segments: "results[0].field" -> ["results", 0, "field"]
        segments = []
        current = name

        while current:
            # Check for array index at start
            if current.startswith("["):
                match = re.match(r"\[(\d+)\](.*)", current)
                if match:
                    segments.append(int(match.group(1)))
                    current = match.group(2)
                    if current.startswith("."):
                        current = current[1:]
                    continue

            # Find next delimiter (. or [)
            dot_pos = current.find(".")
            bracket_pos = current.find("[")

            if dot_pos == -1 and bracket_pos == -1:
                segments.append(current)
                break
            elif dot_pos == -1:
                segments.append(current[:bracket_pos])
                current = current[bracket_pos:]
            elif bracket_pos == -1:
                segments.append(current[:dot_pos])
                current = current[dot_pos + 1:]
            elif dot_pos < bracket_pos:
                segments.append(current[:dot_pos])
                current = current[dot_pos + 1:]
            else:
                segments.append(current[:bracket_pos])
                current = current[bracket_pos:]

        # Navigate through segments
        if not segments:
            return default

        # Get the base value
        value = self.get(segments[0], default)
        if value is default:
            return default

        # Navigate remaining segments
        for segment in segments[1:]:
            if value is None:
                return default
            if isinstance(segment, int):
                if isinstance(value, (list, tuple)) and segment < len(value):
                    value = value[segment]
                else:
                    return default
            elif isinstance(value, dict):
                value = value.get(segment, default)
                if value is default:
                    return default
            else:
                value = getattr(value, segment, default)
                if value is default:
                    return default

        return value

    def set_component_output(
        self,
        component_id: str,
        outputs: dict[str, Any]
    ) -> None:
        """Store outputs from a component execution."""
        self._component_outputs[component_id] = outputs

    def register_sink(self, sink_id: str) -> None:
        """Register a component as a sink (needs finalization before using .items)."""
        self._sink_ids.add(sink_id)

    def is_sink(self, component_id: str) -> bool:
        """Check if a component is a sink."""
        if component_id in self._sink_ids:
            return True
        if self._parent:
            return self._parent.is_sink(component_id)
        return False

    def mark_sink_finalized(self, sink_id: str) -> None:
        """Mark a sink as finalized (safe to read .items)."""
        self._finalized_sinks.add(sink_id)
        if self._parent:
            self._parent.mark_sink_finalized(sink_id)

    def is_sink_finalized(self, sink_id: str) -> bool:
        """Check if a sink has been finalized."""
        if sink_id in self._finalized_sinks:
            return True
        if self._parent:
            return self._parent.is_sink_finalized(sink_id)
        return False

    def get_component_output(
        self,
        component_id: str,
        output_name: str | None = None
    ) -> Any:
        """Get output(s) from a component."""
        if component_id not in self._component_outputs:
            if self._parent:
                return self._parent.get_component_output(component_id, output_name)
            return None

        outputs = self._component_outputs[component_id]
        if output_name is None:
            return outputs
        return outputs.get(output_name)

    def resolve(self, value: Any) -> Any:
        """
        Resolve a value, performing variable interpolation.

        Handles:
        - Strings with {var} placeholders
        - Lists (recursively)
        - Dicts (recursively)
        - Passthrough for other types
        """
        if isinstance(value, str):
            return self._resolve_string(value)
        elif isinstance(value, list):
            return [self.resolve(item) for item in value]
        elif isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        return value

    def _resolve_string(self, template: str) -> Any:
        """
        Resolve a string template with {var} placeholders.

        If the entire string is a single placeholder, return the raw value.
        Otherwise, perform string interpolation.
        """
        # Check if entire string is a single placeholder
        match = re.fullmatch(r"\{([^}]+)\}", template)
        if match:
            var_name = match.group(1)
            result = self.get(var_name)
            if result is not None:
                return result
            # If not found, return template as-is (might be literal)
            return template

        # Multiple placeholders or mixed content - string interpolation
        def replace(m: re.Match) -> str:
            var_name = m.group(1)
            val = self.get(var_name)
            return str(val) if val is not None else m.group(0)

        return re.sub(r"\{([^}]+)\}", replace, template)

    def resolve_inputs(self, inputs_spec: dict[str, Any]) -> dict[str, Any]:
        """Resolve all input specifications to actual values."""
        return {
            name: self.resolve(value)
            for name, value in inputs_spec.items()
        }

    def all_variables(self) -> dict[str, Any]:
        """Get all variables including from parents (for debugging)."""
        result = {}
        if self._parent:
            result.update(self._parent.all_variables())
        result.update(self._variables)
        result.update({
            f"{cid}.{out}": val
            for cid, outputs in self._component_outputs.items()
            for out, val in outputs.items()
        })
        return result

    # === Destination Writers ===

    def write(self, data: dict[str, Any], to: str, **kwargs) -> None:
        """
        Write data to a destination.

        Args:
            data: Data to write (must be JSON-serializable dict)
            to: Destination - "return", "file", or "console"
            **kwargs: Destination-specific options:
                - path: Required for "file" destination

        The "return" destination accumulates data in the context's return space,
        which is collected by the engine and returned in ExecutionResult.returns.
        """
        if to == "return":
            # Write to return space (propagate to root context)
            self._write_return(data)
        elif to == "file":
            path = kwargs.get("path")
            if not path:
                raise ValueError("File destination requires 'path' argument")
            self._write_file(data, path)
        elif to == "console":
            self._write_console(data)
        else:
            raise ValueError(f"Unknown destination: {to!r}")

    def _write_return(self, data: dict[str, Any]) -> None:
        """Write data to the return accumulator (propagates to root)."""
        # Propagate to root context so returns are globally accessible
        if self._parent is not None:
            self._parent._write_return(data)
        else:
            self._returns.update(data)

    def _write_file(self, data: dict[str, Any], path: str) -> None:
        """Write data to a JSON file."""
        full_path = Path(path)

        # Resolve relative paths against output_dir
        if self.output_dir and not full_path.is_absolute():
            full_path = self.output_dir / full_path

        # Ensure parent directory exists
        full_path.parent.mkdir(parents=True, exist_ok=True)

        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    def _write_console(self, data: dict[str, Any]) -> None:
        """Write data to console (respects output_mode)."""
        if self.output_mode in (OutputMode.NORMAL, OutputMode.DEBUG):
            print(json.dumps(data, indent=2, ensure_ascii=False, default=str))

    def get_returns(self) -> dict[str, Any]:
        """Get accumulated return data from all sinks."""
        # Walk to root context to get all returns
        if self._parent is not None:
            return self._parent.get_returns()
        return dict(self._returns)
