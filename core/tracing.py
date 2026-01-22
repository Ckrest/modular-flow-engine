"""Execution tracing and debugging utilities."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any
from enum import Enum


class TraceLevel(Enum):
    """Level of tracing detail."""
    NONE = 0      # No tracing
    ERRORS = 1    # Only trace errors
    STEPS = 2     # Trace each step
    DETAILED = 3  # Trace with full inputs/outputs


@dataclass
class ExecutionTrace:
    """Record of a single execution step."""
    step_index: int
    step_type: str  # "source", "call", "sink", "loop", "conditional"
    component_id: str | None
    timestamp: float
    duration_ms: float = 0.0

    # What went in/out
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)

    # Context at this point
    context_snapshot: dict[str, Any] = field(default_factory=dict)
    loop_context: dict[str, Any] = field(default_factory=dict)  # Current loop variables

    # Status
    success: bool = True
    error: str | None = None
    error_type: str | None = None
    recovered: bool = False

    def __str__(self) -> str:
        status = "✓" if self.success else "✗"
        comp = f" [{self.component_id}]" if self.component_id else ""
        time_str = f"{self.duration_ms:.1f}ms" if self.duration_ms > 0 else ""
        return f"{status} Step {self.step_index}: {self.step_type}{comp} {time_str}"

    def format_detailed(self) -> str:
        """Format trace with full details."""
        lines = [str(self)]

        if self.loop_context:
            lines.append("  Loop context:")
            for k, v in self.loop_context.items():
                v_str = str(v)[:50] + "..." if len(str(v)) > 50 else str(v)
                lines.append(f"    {k} = {v_str}")

        if self.inputs:
            lines.append("  Inputs:")
            for k, v in self.inputs.items():
                v_str = str(v)[:80] + "..." if len(str(v)) > 80 else str(v)
                lines.append(f"    {k}: {v_str}")

        if self.outputs:
            lines.append("  Outputs:")
            for k, v in self.outputs.items():
                v_str = str(v)[:80] + "..." if len(str(v)) > 80 else str(v)
                lines.append(f"    {k}: {v_str}")

        if self.error:
            lines.append(f"  Error: {self.error}")

        return "\n".join(lines)


@dataclass
class ExecutionTracer:
    """Collects execution traces during plan execution."""
    level: TraceLevel = TraceLevel.ERRORS
    traces: list[ExecutionTrace] = field(default_factory=list)
    _step_counter: int = 0
    _current_loop_context: dict[str, Any] = field(default_factory=dict)

    def set_loop_context(self, context: dict[str, Any]) -> None:
        """Update current loop context (called when entering loops)."""
        self._current_loop_context = dict(context)

    def clear_loop_context(self) -> None:
        """Clear loop context (called when exiting loops)."""
        self._current_loop_context = {}

    def start_step(
        self,
        step_type: str,
        component_id: str | None = None,
        inputs: dict[str, Any] | None = None,
    ) -> ExecutionTrace:
        """Start tracing a step."""
        trace = ExecutionTrace(
            step_index=self._step_counter,
            step_type=step_type,
            component_id=component_id,
            timestamp=time.time(),
            inputs=inputs or {},
            loop_context=dict(self._current_loop_context),
        )
        self._step_counter += 1
        return trace

    def end_step(
        self,
        trace: ExecutionTrace,
        outputs: dict[str, Any] | None = None,
        error: Exception | None = None,
        recovered: bool = False,
    ) -> None:
        """Complete a step trace."""
        trace.duration_ms = (time.time() - trace.timestamp) * 1000
        trace.outputs = outputs or {}

        if error:
            trace.success = False
            trace.error = str(error)
            trace.error_type = type(error).__name__
            trace.recovered = recovered

        # Only store based on trace level
        if self.level == TraceLevel.NONE:
            return
        elif self.level == TraceLevel.ERRORS and trace.success:
            return

        self.traces.append(trace)

    def get_recent_traces(self, count: int = 10) -> list[ExecutionTrace]:
        """Get the most recent traces."""
        return self.traces[-count:]

    def get_error_traces(self) -> list[ExecutionTrace]:
        """Get all traces with errors."""
        return [t for t in self.traces if not t.success]

    def format_error_context(self, error_trace: ExecutionTrace) -> str:
        """
        Format detailed error context including surrounding traces.

        This is the key debugging output - shows what happened before the error.
        """
        lines = [
            "=" * 70,
            "ERROR CONTEXT",
            "=" * 70,
            "",
        ]

        # Show loop context if any
        if error_trace.loop_context:
            lines.append("Loop Variables:")
            for k, v in error_trace.loop_context.items():
                lines.append(f"  {k} = {v}")
            lines.append("")

        # Show the failing step
        lines.append("Failed Step:")
        lines.append(error_trace.format_detailed())
        lines.append("")

        # Show recent successful traces for context
        recent = [t for t in self.traces if t.step_index < error_trace.step_index][-5:]
        if recent:
            lines.append("Previous Steps:")
            for t in recent:
                lines.append(f"  {t}")
            lines.append("")

        lines.append("=" * 70)
        return "\n".join(lines)

    def format_summary(self) -> str:
        """Format a summary of all traces."""
        if not self.traces:
            return "No traces recorded"

        total = len(self.traces)
        errors = len([t for t in self.traces if not t.success])
        recovered = len([t for t in self.traces if t.recovered])

        lines = [
            f"Execution Trace Summary:",
            f"  Total steps traced: {total}",
            f"  Errors: {errors}",
            f"  Recovered: {recovered}",
        ]

        if errors > 0:
            lines.append("\nError steps:")
            for t in self.get_error_traces():
                lines.append(f"  {t}")

        return "\n".join(lines)


def format_validation_error(
    error_type: str,
    message: str,
    location: str | None = None,
    suggestion: str | None = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Format a validation error with helpful context."""
    lines = [f"✗ {error_type}: {message}"]

    if location:
        lines.append(f"  Location: {location}")

    if context:
        lines.append("  Context:")
        for k, v in context.items():
            lines.append(f"    {k}: {v}")

    if suggestion:
        lines.append(f"  Suggestion: {suggestion}")

    return "\n".join(lines)
