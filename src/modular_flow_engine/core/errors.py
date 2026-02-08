"""Error types and error handling protocols."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ErrorProtocol:
    """
    Defines how errors should be handled.

    Components can specify their own error protocol, or the system
    default will be used.
    """
    on_error: Literal["stop", "skip", "retry", "default"] = "stop"
    max_retries: int = 3
    retry_delay: float = 1.0  # seconds
    default_value: Any = None

    def should_retry(self, attempt: int) -> bool:
        """Check if another retry should be attempted."""
        return self.on_error == "retry" and attempt < self.max_retries


# System default - stop on any error
DEFAULT_ERROR_PROTOCOL = ErrorProtocol(on_error="stop")


class DataflowError(Exception):
    """Base exception for all dataflow errors."""
    pass


class ValidationError(DataflowError):
    """Error during plan or component validation."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


class ExecutionError(DataflowError):
    """Error during plan execution."""

    def __init__(
        self,
        message: str,
        component_id: str | None = None,
        step: dict | None = None,
        cause: Exception | None = None
    ):
        super().__init__(message)
        self.component_id = component_id
        self.step = step
        self.cause = cause


class ComponentError(DataflowError):
    """Error within a component's execution."""

    def __init__(
        self,
        message: str,
        component_id: str,
        inputs: dict[str, Any] | None = None,
        cause: Exception | None = None
    ):
        super().__init__(message)
        self.component_id = component_id
        self.inputs = inputs
        self.cause = cause


@dataclass
class ErrorRecord:
    """Record of an error that occurred during execution."""
    error_type: str
    message: str
    component_id: str | None = None
    step_index: int | None = None
    context: dict[str, Any] = field(default_factory=dict)
    recovered: bool = False
    recovery_action: str | None = None  # "skipped", "used_default", "retried"
