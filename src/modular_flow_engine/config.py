"""Configuration helpers for modular-flow-engine."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Optional


PACKAGE_ROOT = Path(__file__).parent.parent.parent
LOCAL_CONFIG_PATH = PACKAGE_ROOT / "config.local.yaml"

DEFAULT_CONFIG = {
    "data_dir": "~/.local/share/modular-flow-engine",
    "cache_dir": "~/.cache/modular-flow-engine",
    "server": {
        "host": "127.0.0.1",
        "port": 9847,
    },
    "execution": {
        "timeout": 300,
        "max_concurrent": 4,
    },
}


def config_defaults() -> dict:
    """Return default configuration values."""
    return copy.deepcopy(DEFAULT_CONFIG)


def config_schema() -> dict:
    """Return JSON Schema for configuration."""
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "data_dir": {"type": "string"},
            "cache_dir": {"type": "string"},
            "server": {
                "type": "object",
                "properties": {
                    "host": {"type": "string"},
                    "port": {"type": "integer", "minimum": 1, "maximum": 65535},
                },
                "additionalProperties": False,
            },
            "execution": {
                "type": "object",
                "properties": {
                    "timeout": {"type": "integer", "minimum": 1},
                    "max_concurrent": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
        },
        "additionalProperties": False,
    }


def _deep_merge(base: dict, update: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in update.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _load_config_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        import yaml
        data = yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def load_config(config_path: Optional[Path] = None) -> dict:
    """Load resolved configuration (defaults merged with config file)."""
    path = config_path or LOCAL_CONFIG_PATH
    base = config_defaults()
    file_config = _load_config_file(path)
    return _deep_merge(base, file_config)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_config_dict(data: Any) -> list[str]:
    """Validate a config dict against the schema."""
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Config must be a mapping/object"]

    allowed_top = {"data_dir", "cache_dir", "server", "execution"}
    for key in data:
        if key not in allowed_top:
            errors.append(f"Unknown config key: {key}")

    if "server" in data and isinstance(data["server"], dict):
        for key in data["server"]:
            if key not in {"host", "port"}:
                errors.append(f"Unknown server key: {key}")
        port = data["server"].get("port")
        if port is not None and (_is_int(port) and not (1 <= port <= 65535)):
            errors.append("server.port must be between 1 and 65535")
    elif "server" in data:
        errors.append("server must be an object")

    if "execution" in data and isinstance(data["execution"], dict):
        for key in data["execution"]:
            if key not in {"timeout", "max_concurrent"}:
                errors.append(f"Unknown execution key: {key}")
    elif "execution" in data:
        errors.append("execution must be an object")

    return errors


def validate_config_file(config_path: Optional[Path] = None) -> list[str]:
    """Validate the config file. Returns list of errors (empty = valid)."""
    path = config_path or LOCAL_CONFIG_PATH
    if not path.exists():
        return []
    data = _load_config_file(path)
    return validate_config_dict(data)
