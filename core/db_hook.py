"""Database hook for logging runs to systems_history PostgreSQL database.

This module provides integration with the Systems History database,
logging each evaluation run as an Operation with linked artifacts.

The database is at: postgresql:///systems_history
Schema defined in: ~/Systems/database/
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Callable

# Add Systems database to path
SYSTEMS_DB_PATH = Path.home() / "Systems" / "database"
if str(SYSTEMS_DB_PATH) not in sys.path:
    sys.path.insert(0, str(SYSTEMS_DB_PATH))


def create_db_callback() -> Callable[[dict], None]:
    """
    Create a callback function for logging run completion to the database.

    Returns a function that takes a run summary dict and logs it.
    The callback is fire-and-forget (errors are printed but don't fail the run).
    """
    def log_run_to_db(run_summary: dict[str, Any]) -> None:
        """Log a completed run to the systems_history database."""
        try:
            from repository import HistoryRepository

            with HistoryRepository() as repo:
                # Create main operation
                operation = repo.start_operation(
                    operation_type="eval_run",
                    tool_name="dataflow-eval",
                    config={
                        "run_id": run_summary.get("run_id"),
                        "plan_name": run_summary.get("plan_name"),
                        "stats": run_summary.get("stats", {}),
                        "resumed": run_summary.get("stats", {}).get("resumed", False),
                    },
                    tags=["dataflow-eval", run_summary.get("plan_name", "unknown")]
                )

                # Register output directory as artifact
                output_dir = run_summary.get("output_dir")
                if output_dir:
                    output_path = Path(output_dir)

                    # Register the results.json if it exists
                    results_file = output_path / "results.json"
                    if results_file.exists():
                        artifact = repo.register_artifact(
                            file_path=str(results_file),
                            file_type="json",
                            metadata={
                                "run_id": run_summary.get("run_id"),
                                "plan_name": run_summary.get("plan_name"),
                            }
                        )
                        repo.add_operation_output(operation.id, artifact.id)

                    # Register the state.jsonl (our checkpoint file)
                    state_file = output_path / "state.jsonl"
                    if state_file.exists():
                        artifact = repo.register_artifact(
                            file_path=str(state_file),
                            file_type="log",
                            metadata={"purpose": "checkpoint/resume state"}
                        )
                        repo.add_operation_output(operation.id, artifact.id)

                # Mark complete
                repo.complete_operation(
                    operation.id,
                    success=run_summary.get("success", False),
                    error_message=None if run_summary.get("success") else "Run failed"
                )

                print(f"[DB] Logged run {run_summary.get('run_id')} to systems_history")

        except ImportError as e:
            print(f"[DB Warning] Could not import database modules: {e}")
        except Exception as e:
            print(f"[DB Warning] Failed to log to database: {e}")
            # Don't fail the run because of DB issues

    return log_run_to_db


def log_run_sync(
    run_id: str,
    plan_name: str,
    success: bool,
    duration_seconds: float,
    output_dir: str | Path,
    stats: dict[str, Any] | None = None,
) -> None:
    """
    Synchronously log a run to the database.

    Use this for simple one-shot logging without the callback pattern.

    Args:
        run_id: Unique run identifier
        plan_name: Name of the plan that was executed
        success: Whether the run succeeded
        duration_seconds: How long the run took
        output_dir: Where outputs were written
        stats: Optional execution statistics
    """
    callback = create_db_callback()
    callback({
        "run_id": run_id,
        "plan_name": plan_name,
        "success": success,
        "duration_seconds": duration_seconds,
        "output_dir": str(output_dir),
        "stats": stats or {},
    })


def query_runs(
    plan_name: str | None = None,
    limit: int = 20
) -> list[dict]:
    """
    Query previous runs from the database.

    Args:
        plan_name: Optional filter by plan name
        limit: Maximum runs to return

    Returns:
        List of run summaries
    """
    try:
        from repository import HistoryRepository

        with HistoryRepository() as repo:
            if plan_name:
                operations = repo.find_operations_by_tag(plan_name)[:limit]
            else:
                operations = [
                    op for op in repo.get_recent_operations(limit)
                    if op.tool_name == "dataflow-eval"
                ]

            return [
                {
                    "id": str(op.id),
                    "run_id": op.config.get("run_id"),
                    "plan_name": op.config.get("plan_name"),
                    "status": op.status,
                    "started_at": op.started_at.isoformat() if op.started_at else None,
                    "completed_at": op.completed_at.isoformat() if op.completed_at else None,
                    "duration_seconds": op.duration_seconds,
                }
                for op in operations
            ]

    except ImportError:
        print("[DB Warning] Database modules not available")
        return []
    except Exception as e:
        print(f"[DB Warning] Failed to query database: {e}")
        return []
