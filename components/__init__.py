"""Dataflow evaluation components - auto-discovered on import."""

from pathlib import Path
from core.registry import auto_discover_components

# Auto-discover all components in this package
_components_dir = Path(__file__).parent
_discovered = auto_discover_components(_components_dir)
