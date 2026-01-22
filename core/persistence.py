"""Persistent execution engine with checkpoint/resume support.

This module provides a PersistentEngine that extends DataflowEngine with:
- Automatic state logging (every call, every loop iteration)
- Resume capability by loading existing state and skipping completed work
- Event-sourcing style: state.jsonl is an append-only log of all events

Design Philosophy:
    The engine is "smart" about persistence so plans don't need to be.
    Every state change is logged automatically. On resume, completed
    work is skipped by checking a cache built from the state log.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .engine import DataflowEngine, ExecutionResult
from .context import ExecutionContext, OutputMode
from .errors import ErrorRecord
from .tracing import TraceLevel


@dataclass
class RunState:
    """In-memory representation of run state built from event log."""

    run_id: str = ""
    plan_name: str = ""
    started_at: str = ""

    # Cache of completed calls: hash -> outputs
    # Hash is computed from (component_id, serialized_inputs)
    completed_calls: dict[str, dict] = field(default_factory=dict)

    # Track loop progress: "loop_path:index" -> completed
    completed_iterations: set[str] = field(default_factory=set)

    # Pending calls (started but not completed - indicates crash point)
    pending_calls: set[str] = field(default_factory=set)

    # Statistics
    total_events: int = 0
    calls_cached: int = 0
    iterations_cached: int = 0


class PersistentEngine(DataflowEngine):
    """
    Dataflow engine with automatic checkpoint/resume support.

    All execution state is logged to a JSONL file. On crash and resume,
    the engine reloads the state and skips already-completed work.

    Usage:
        engine = PersistentEngine(run_id="my_run")
        engine.load_plan(plan)
        result = await engine.execute(output_dir=Path("runs/my_run"))

        # On crash, restart with same run_id to resume:
        engine = PersistentEngine(run_id="my_run")  # Loads existing state
        engine.load_plan(plan)
        result = await engine.execute(...)  # Skips completed work
    """

    def __init__(
        self,
        run_id: str | None = None,
        trace_level: TraceLevel = TraceLevel.ERRORS,
        on_complete: Callable[[dict], None] | None = None,
    ):
        """
        Initialize persistent engine.

        Args:
            run_id: Unique identifier for this run. If None, generates UUID.
                    Pass the same run_id to resume a crashed run.
            trace_level: Tracing verbosity level.
            on_complete: Optional callback fired when run completes (for DB hooks).
        """
        super().__init__(trace_level=trace_level)

        self.run_id = run_id or str(uuid4())[:8]
        self.state = RunState(run_id=self.run_id)
        self.state_file: Path | None = None
        self._on_complete = on_complete
        self._current_loop_path: list[str] = []
        self._is_resuming = False

    def _get_state_path(self, output_dir: Path) -> Path:
        """Get path to state file."""
        return output_dir / "state.jsonl"

    def _log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Append an event to the state log."""
        if self.state_file is None:
            return

        event = {
            "timestamp": datetime.now().isoformat(),
            "type": event_type,
            **data
        }

        with open(self.state_file, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

        self.state.total_events += 1

    def _load_existing_state(self, state_path: Path) -> bool:
        """
        Load existing state from file and rebuild caches.

        Returns True if state was loaded (resuming), False otherwise.
        """
        if not state_path.exists():
            return False

        self.state = RunState(run_id=self.run_id)
        events_loaded = 0

        with open(state_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                    self._apply_event(event)
                    events_loaded += 1
                except json.JSONDecodeError:
                    # Skip malformed lines (could happen on crash mid-write)
                    continue

        self.state.total_events = events_loaded
        return events_loaded > 0

    def _apply_event(self, event: dict) -> None:
        """Apply a loaded event to rebuild state."""
        event_type = event.get("type")

        if event_type == "run_start":
            self.state.plan_name = event.get("plan_name", "")
            self.state.started_at = event.get("timestamp", "")

        elif event_type == "call_start":
            # Track pending calls
            call_hash = event.get("call_hash", "")
            if call_hash:
                self.state.pending_calls.add(call_hash)

        elif event_type == "call_complete":
            # Move from pending to completed
            call_hash = event.get("call_hash", "")
            outputs = event.get("outputs", {})
            if call_hash:
                self.state.pending_calls.discard(call_hash)
                self.state.completed_calls[call_hash] = outputs
                self.state.calls_cached += 1

        elif event_type == "iteration_start":
            # Track which iteration we're in (for crash detection)
            iter_key = event.get("iteration_key", "")
            # Not adding to completed yet

        elif event_type == "iteration_complete":
            iter_key = event.get("iteration_key", "")
            if iter_key:
                self.state.completed_iterations.add(iter_key)
                self.state.iterations_cached += 1

    def _compute_call_hash(self, comp_id: str, inputs: dict) -> str:
        """Compute a stable hash for a component call."""
        # Create a deterministic representation
        key = f"{comp_id}:{json.dumps(inputs, sort_keys=True, default=str)}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    def _get_iteration_key(self, loop_var: str, item: Any, index: int) -> str:
        """Get a unique key for a loop iteration."""
        loop_path = "/".join(self._current_loop_path)
        return f"{loop_path}/{loop_var}[{index}]:{item}"

    async def execute(
        self,
        output_dir: Path | None = None,
        output_mode: OutputMode = OutputMode.NORMAL
    ) -> ExecutionResult:
        """
        Execute the plan with checkpoint/resume support.

        If state.jsonl exists in output_dir, completed work will be skipped.
        """
        if output_dir is None:
            output_dir = Path("runs") / self.run_id

        output_dir.mkdir(parents=True, exist_ok=True)

        # Set up state file and check for existing state
        self.state_file = self._get_state_path(output_dir)
        self._is_resuming = self._load_existing_state(self.state_file)

        if self._is_resuming:
            print(f"[Resume] Loaded state with {self.state.calls_cached} cached calls, "
                  f"{self.state.iterations_cached} cached iterations")
            if self.state.pending_calls:
                print(f"[Resume] {len(self.state.pending_calls)} calls were in-progress (will retry)")
        else:
            # Fresh run - log start event
            plan_name = self.plan.get("name", "unnamed")
            self._log_event("run_start", {
                "run_id": self.run_id,
                "plan_name": plan_name,
            })

        # Execute using parent
        start_time = time.time()
        result = await super().execute(output_dir=output_dir, output_mode=output_mode)

        # Log completion
        self._log_event("run_complete", {
            "success": result.success,
            "duration_seconds": result.duration_seconds,
            "errors_count": len(result.errors),
            "stats": result.stats,
        })

        # Fire completion callback for DB hook
        if self._on_complete:
            self._on_complete({
                "run_id": self.run_id,
                "plan_name": self.plan.get("name", "unnamed"),
                "success": result.success,
                "duration_seconds": result.duration_seconds,
                "output_dir": str(output_dir),
                "stats": {
                    **result.stats,
                    "calls_cached": self.state.calls_cached,
                    "iterations_cached": self.state.iterations_cached,
                    "resumed": self._is_resuming,
                }
            })

        return result

    async def _execute_call(
        self,
        step: dict,
        context: ExecutionContext
    ) -> None:
        """Execute a component call with caching support."""
        comp_id = step["call"]
        component = self.components[comp_id]

        # Resolve inputs
        inputs_spec = step.get("inputs", {})
        inputs = context.resolve_inputs(inputs_spec)

        # Compute call hash
        call_hash = self._compute_call_hash(comp_id, inputs)

        # Check cache
        if call_hash in self.state.completed_calls:
            cached_outputs = self.state.completed_calls[call_hash]

            # Apply cached outputs to context
            outputs_mapping = step.get("outputs", {})
            if outputs_mapping:
                for output_name, var_name in outputs_mapping.items():
                    if output_name in cached_outputs:
                        context.set(var_name, cached_outputs[output_name])

            # Store in component outputs
            self.context.set_component_output(comp_id, cached_outputs)
            self._stats["components_executed"] += 1
            return

        # Not cached - execute normally
        # Log start
        self._log_event("call_start", {
            "component": comp_id,
            "call_hash": call_hash,
        })

        # Start tracing
        trace = self.tracer.start_step("call", comp_id, inputs)

        try:
            # Validate and execute
            validation = component.validate(inputs)
            if not validation.valid:
                from .errors import ComponentError
                raise ComponentError(
                    f"Input validation failed: {validation.errors}",
                    component_id=comp_id,
                    inputs=inputs
                )

            outputs = await component.execute(inputs, context)

            # Log completion
            self._log_event("call_complete", {
                "component": comp_id,
                "call_hash": call_hash,
                "outputs": outputs,
            })

            # Add to cache
            self.state.completed_calls[call_hash] = outputs

            # Map outputs to context
            outputs_mapping = step.get("outputs", {})
            if outputs_mapping:
                for output_name, var_name in outputs_mapping.items():
                    if output_name in outputs:
                        context.set(var_name, outputs[output_name])

            self.context.set_component_output(comp_id, outputs)
            self._stats["components_executed"] += 1

            self.tracer.end_step(trace, outputs)

        except Exception as e:
            self.tracer.end_step(trace, error=e)
            raise

    async def _execute_loop(
        self,
        step: dict,
        context: ExecutionContext,
        errors: list[ErrorRecord],
    ) -> None:
        """Execute a loop with iteration-level checkpointing."""
        loop_config = step["loop"]

        # Get collection
        over_ref = loop_config["over"]
        collection = context.resolve(f"{{{over_ref}}}")

        if collection is None:
            from .errors import ExecutionError
            raise ExecutionError(
                f"Loop 'over' reference '{over_ref}' resolved to None",
                step=step
            )

        if not hasattr(collection, "__iter__"):
            from .errors import ExecutionError
            raise ExecutionError(
                f"Loop 'over' reference '{over_ref}' is not iterable",
                step=step
            )

        loop_var = loop_config.get("as", "item")
        index_var = loop_config.get("index")
        inner_steps = loop_config.get("steps", [])

        for i, item in enumerate(collection):
            # Build iteration-specific path entry BEFORE getting iter_key
            # This ensures nested loops get unique keys per outer iteration
            loop_path_entry = f"{loop_var}[{i}]:{item}"
            self._current_loop_path.append(loop_path_entry)

            iter_key = self._get_iteration_key(loop_var, item, i)

            # Check if iteration already completed
            if iter_key in self.state.completed_iterations:
                self._current_loop_path.pop()
                continue

            # Log iteration start
            self._log_event("iteration_start", {
                "iteration_key": iter_key,
                "loop_var": loop_var,
                "index": i,
            })

            # Create child context
            loop_vars = {loop_var: item}
            if index_var:
                loop_vars[index_var] = i

            child_context = context.child(loop_vars)
            self.tracer.set_loop_context(loop_vars)

            # Execute inner steps
            await self._execute_steps(inner_steps, child_context, errors)

            # Log iteration complete
            self._log_event("iteration_complete", {
                "iteration_key": iter_key,
            })
            self.state.completed_iterations.add(iter_key)

            # Pop this iteration's path entry
            self._current_loop_path.pop()

        self.tracer.clear_loop_context()


def create_persistent_engine(
    run_id: str | None = None,
    trace_level: TraceLevel = TraceLevel.ERRORS,
    db_hook: bool = False,
) -> PersistentEngine:
    """
    Factory function to create a persistent engine with optional DB hook.

    Args:
        run_id: Run identifier (generates UUID if None)
        trace_level: Tracing verbosity
        db_hook: If True, enables database logging via systems_history

    Returns:
        Configured PersistentEngine instance
    """
    on_complete = None

    if db_hook:
        try:
            from .db_hook import create_db_callback
            on_complete = create_db_callback()
        except ImportError:
            print("[Warning] Database hook requested but db_hook module not available")

    return PersistentEngine(
        run_id=run_id,
        trace_level=trace_level,
        on_complete=on_complete,
    )
