#!/usr/bin/env python3
"""
Dataflow Evaluation Runner

Usage:
    python runner.py                     # Interactive mode
    python runner.py <plan.json>         # Run a plan
    python runner.py --list-plans        # List available plans
    python runner.py --list-runs         # List resumable runs

Options:
    --dry-run       Validate plan without executing
    --output DIR    Output directory (default: results/)
    --run-id ID     Name for checkpoint/resume support
    --resume [NAME] Resume a previous run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent))


def get_available_plans() -> list[dict]:
    """Get all available plans with metadata."""
    plans_dir = Path("plans")
    if not plans_dir.exists():
        return []

    plans = []
    for f in sorted(plans_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            plans.append({
                "path": f,
                "name": data.get("name", f.stem),
                "description": data.get("description", "No description"),
                "data": data,
            })
        except (json.JSONDecodeError, IOError):
            continue
    return plans


def analyze_plan(plan_data: dict) -> dict:
    """Analyze a plan and return useful metadata."""
    components = plan_data.get("components", {})

    # Count by category
    sources = []
    transforms = []
    sinks = []
    uses_api = False
    api_key_name = None

    for comp_id, comp_def in components.items():
        comp_type = comp_def.get("type", "")
        if comp_type.startswith("source/"):
            sources.append(comp_id)
            if comp_type == "source/api_key":
                api_key_name = comp_def.get("config", {}).get("key_name")
        elif comp_type.startswith("transform/"):
            transforms.append(comp_id)
            if "openrouter" in comp_type or "llm" in comp_type:
                uses_api = True
        elif comp_type.startswith("sink/"):
            sinks.append(comp_id)

    # Check for loops (suggests long-running)
    has_loops = False
    def check_flow(steps):
        nonlocal has_loops
        for step in steps:
            if "loop" in step:
                has_loops = True
                inner = step["loop"].get("steps", [])
                check_flow(inner)
            if "conditional" in step:
                for branch in ["then", "else"]:
                    if branch in step["conditional"]:
                        check_flow(step["conditional"][branch])

    check_flow(plan_data.get("flow", []))

    return {
        "sources": sources,
        "transforms": transforms,
        "sinks": sinks,
        "total": len(components),
        "uses_api": uses_api,
        "api_key_name": api_key_name,
        "has_loops": has_loops,
    }


def check_api_key(key_name: str) -> bool:
    """Check if an API key exists in config."""
    config_path = Path("config/api_keys.json")
    if not config_path.exists():
        return False
    try:
        keys = json.loads(config_path.read_text())
        return key_name in keys and bool(keys[key_name])
    except (json.JSONDecodeError, IOError):
        return False


def parse_input_args(input_args: list[str] | None) -> dict[str, Any]:
    """Parse --input key=value arguments into a dict."""
    if not input_args:
        return {}

    inputs = {}
    for arg in input_args:
        if "=" not in arg:
            print(f"Warning: Invalid input format '{arg}', expected KEY=VALUE")
            continue
        key, value = arg.split("=", 1)

        # Try to parse as JSON for complex types, otherwise keep as string
        try:
            parsed = json.loads(value)
            inputs[key] = parsed
        except json.JSONDecodeError:
            inputs[key] = value

    return inputs


def get_plan_inputs_schema(plan_data: dict) -> dict[str, dict]:
    """Get the input schema from a plan dict."""
    schema = {}
    for name, spec in plan_data.get("inputs", {}).items():
        if isinstance(spec, dict):
            schema[name] = {
                "type": spec.get("type", "string"),
                "required": spec.get("required", True),
                "default": spec.get("default"),
                "description": spec.get("description", ""),
            }
        else:
            # Simple shorthand: "inputs": {"name": "string"}
            schema[name] = {"type": spec, "required": True, "default": None, "description": ""}
    return schema


def prompt_for_inputs(schema: dict[str, dict]) -> dict[str, Any]:
    """Interactively prompt for plan inputs."""
    inputs = {}

    required_inputs = [(k, v) for k, v in schema.items() if v["required"] and v["default"] is None]
    optional_inputs = [(k, v) for k, v in schema.items() if not v["required"] or v["default"] is not None]

    if required_inputs:
        print("This plan requires the following inputs:\n")

        for name, spec in required_inputs:
            type_hint = spec["type"]
            desc = f" ({spec['description']})" if spec["description"] else ""

            try:
                value = input(f"  {name} [{type_hint}]{desc}: ").strip()
                if not value:
                    print(f"  Error: {name} is required")
                    return None  # Signal cancellation

                # Parse based on type
                if spec["type"] == "integer":
                    inputs[name] = int(value)
                elif spec["type"] == "boolean":
                    inputs[name] = value.lower() in ("true", "yes", "1", "y")
                elif spec["type"] == "path":
                    # Validate path exists
                    path = Path(value).expanduser()
                    if not path.exists():
                        print(f"  Warning: Path '{value}' does not exist")
                    inputs[name] = str(path)
                else:
                    inputs[name] = value

            except (KeyboardInterrupt, EOFError):
                print("\nCancelled.")
                return None

        print()

    # For optional inputs with defaults, just use defaults (don't prompt)
    for name, spec in optional_inputs:
        if spec["default"] is not None and name not in inputs:
            inputs[name] = spec["default"]

    return inputs


def get_latest_resumable_run() -> tuple[str, Path] | None:
    """Get the most recent resumable run, if any."""
    runs_dir = Path("runs")
    if not runs_dir.exists():
        return None

    run_folders = [
        d for d in runs_dir.iterdir()
        if d.is_dir() and not d.is_symlink() and (d / "state.jsonl").exists()
    ]
    if not run_folders:
        return None

    latest = max(run_folders, key=lambda d: d.stat().st_mtime)
    return (latest.name, latest)


def get_run_info(run_name: str) -> dict | None:
    """Get info about a run from its results.json."""
    run_path = Path("runs") / run_name
    results_file = run_path / "results.json"

    if not results_file.exists():
        return None

    try:
        data = json.loads(results_file.read_text())
        return {
            "run_name": run_name,
            "run_path": run_path,
            "plan_name": data.get("plan_name"),
            "success": data.get("success"),
            "duration": data.get("duration_seconds"),
        }
    except (json.JSONDecodeError, IOError):
        return None


def find_plan_path(plan_name: str) -> Path | None:
    """Find a plan file by name."""
    plans = get_available_plans()
    for p in plans:
        if p["name"] == plan_name or p["path"].stem == plan_name:
            return p["path"]
    return None


def resume_run(
    run_name: str | None = None,
    plan_path: Path | None = None,
    output_mode: "OutputMode | None" = None,
) -> int:
    """
    Resume a previous run.

    Args:
        run_name: Name of run to resume. If None, uses latest.
        plan_path: Plan file path. If None, auto-detects from run.
        output_mode: Output verbosity. If None, uses NORMAL.

    Returns:
        Exit code (0 = success)
    """
    from core import OutputMode as OM

    # Find the run
    if run_name is None:
        latest = get_latest_resumable_run()
        if not latest:
            print("Error: No resumable runs found in runs/", file=sys.stderr)
            return 1
        run_name, run_path = latest
        print(f"Resuming latest run: {run_name}")
    else:
        run_path = Path("runs") / run_name
        if not run_path.exists():
            print(f"Error: Run '{run_name}' not found in runs/", file=sys.stderr)
            return 1
        print(f"Resuming run: {run_name}")

    # Find the plan
    if plan_path is None:
        run_info = get_run_info(run_name)
        if run_info and run_info["plan_name"]:
            plan_path = find_plan_path(run_info["plan_name"])

        if not plan_path:
            print(f"Error: Could not determine plan for run '{run_name}'", file=sys.stderr)
            print("Specify the plan explicitly: python runner.py <plan.json> --resume", file=sys.stderr)
            return 1

    if output_mode is None:
        output_mode = OM.NORMAL

    setup_logging(output_mode)

    return asyncio.run(run_plan(
        plan_path,
        dry_run=False,
        output_mode=output_mode,
        output_dir=run_path,
        run_id=run_name,
        resume=True,
        db_hook=False,
    ))


def interactive_mode() -> int:
    """Run interactive plan selection and execution."""
    print("\n=== Dataflow Evaluation Runner ===\n")

    # Check for resumable runs
    latest_run = get_latest_resumable_run()

    # Get available plans
    plans = get_available_plans()
    if not plans:
        print("No plans found in plans/ directory.")
        return 1

    # Show resume option if available
    if latest_run:
        run_name, run_path = latest_run
        print(f"  0. [Resume] {run_name}")
        print()

    # Show plans
    print("Available plans:")
    for i, plan in enumerate(plans, 1):
        desc = plan["description"][:50] + "..." if len(plan["description"]) > 50 else plan["description"]
        print(f"  {i:2}. {plan['name']:<25} {desc}")

    print()

    # Select plan
    try:
        prompt = f"Select plan [0-{len(plans)}]: " if latest_run else f"Select plan [1-{len(plans)} or name]: "
        selection = input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    # Handle resume option
    if selection == "0" and latest_run:
        run_name, _ = latest_run
        return resume_run(run_name)

    # Parse selection
    selected_plan = None
    if selection.isdigit():
        idx = int(selection) - 1
        if 0 <= idx < len(plans):
            selected_plan = plans[idx]
    else:
        # Search by name
        for plan in plans:
            if plan["name"] == selection or plan["path"].stem == selection:
                selected_plan = plan
                break

    if not selected_plan:
        print(f"Invalid selection: {selection}")
        return 1

    # Analyze plan
    analysis = analyze_plan(selected_plan["data"])

    print()
    print(f"─── {selected_plan['name']} ───")
    print(selected_plan["description"])
    print()

    # Check API requirements - only show if there's a problem
    if analysis["uses_api"] and analysis["api_key_name"]:
        if not check_api_key(analysis["api_key_name"]):
            print(f"⚠ API key '{analysis['api_key_name']}' not found")
            print(f"  Add it to config/api_keys.json before running")
            print()

    # Check for required inputs
    input_schema = get_plan_inputs_schema(selected_plan["data"])
    plan_inputs = {}
    if input_schema:
        plan_inputs = prompt_for_inputs(input_schema)
        if plan_inputs is None:
            return 0  # User cancelled

    # Collect options
    run_id = None

    # Suggest run-id for plans with loops (enables resume)
    if analysis["has_loops"]:
        try:
            run_id_input = input("Name this run (enables resume if interrupted)? [blank to skip]: ").strip()
            if run_id_input:
                run_id = run_id_input
        except (KeyboardInterrupt, EOFError):
            print("\nCancelled.")
            return 0
        print()

    # Build the command for display at the end
    cmd_parts = ["python runner.py", str(selected_plan["path"])]
    for key, value in plan_inputs.items():
        if isinstance(value, str) and " " in value:
            cmd_parts.append(f'--input {key}="{value}"')
        else:
            cmd_parts.append(f"--input {key}={value}")
    if run_id:
        cmd_parts.append(f"--run-id {run_id}")

    # Determine output mode from plan
    settings = selected_plan["data"].get("settings", {})
    output_mode_str = settings.get("output_mode", "normal").lower()
    if output_mode_str == "quiet":
        output_mode = OutputMode.QUIET
    elif output_mode_str == "debug":
        output_mode = OutputMode.DEBUG
    else:
        output_mode = OutputMode.NORMAL

    setup_logging(output_mode)

    # Run the plan
    print("=" * 50)
    print(f"Running {selected_plan['name']}...")
    print("=" * 50)
    print()

    exit_code = asyncio.run(run_plan(
        selected_plan["path"],
        dry_run=False,
        output_mode=output_mode,
        output_dir=None,
        plan_args=None,
        run_id=run_id,
        resume=False,
        db_hook=False,
        plan_inputs=plan_inputs,
    ))

    # Show the command to run again
    print()
    print("═" * 50)
    print("To run again:")
    print(f"  {' '.join(cmd_parts)}")
    if run_id:
        print(f"\nTo resume if interrupted:")
        print(f"  python runner.py {selected_plan['path']} --resume {run_id}")
    print("═" * 50)

    return exit_code


from core import (
    DataflowEngine,
    ValidationError,
    ExecutionError,
    load_composites_from_directory,
    TraceLevel,
    validate_plan,
    OutputMode,
    PersistentEngine,
    create_persistent_engine,
)


def setup_logging(output_mode: OutputMode) -> None:
    """Configure logging based on output mode."""
    import logging

    # Determine log level for our code
    if output_mode == OutputMode.QUIET:
        level = logging.WARNING
    elif output_mode == OutputMode.DEBUG:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )

    # Suppress library loggers unless in debug mode
    if output_mode != OutputMode.DEBUG:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


async def run_plan(
    plan_path: Path,
    dry_run: bool = False,
    output_mode: OutputMode = OutputMode.NORMAL,
    output_dir: Path | None = None,
    plan_args: list[str] | None = None,
    run_id: str | None = None,
    resume: bool = False,
    db_hook: bool = False,
    plan_inputs: dict[str, Any] | None = None,
) -> int:
    """Run a plan and return exit code."""
    import logging
    logger = logging.getLogger(__name__)

    # Load plan
    logger.info(f"Loading plan: {plan_path}")
    with open(plan_path, "r") as f:
        plan = json.load(f)

    plan_name = plan.get("name", plan_path.stem)
    logger.info(f"Plan: {plan_name}")
    logger.info(f"Description: {plan.get('description', 'No description')}")

    # Import components to register them
    import components  # noqa: F401

    # Load composites from composites directory
    composites_dir = Path(__file__).parent / "composites"
    if composites_dir.exists():
        loaded_composites = load_composites_from_directory(composites_dir)
        if loaded_composites:
            logger.info(f"Loaded composites: {', '.join(loaded_composites)}")

    # Determine trace level
    if output_mode == OutputMode.DEBUG:
        trace_level = TraceLevel.DETAILED
    elif output_mode == OutputMode.NORMAL:
        trace_level = TraceLevel.STEPS
    else:
        trace_level = TraceLevel.ERRORS

    # Create engine - use PersistentEngine for resume support or DB logging
    if resume or db_hook or run_id:
        engine = create_persistent_engine(
            run_id=run_id,
            trace_level=trace_level,
            db_hook=db_hook,
        )
        logger.info(f"Using persistent engine (run_id: {engine.run_id})")
    else:
        engine = DataflowEngine(trace_level=trace_level)

    engine.load_plan(plan)

    # Set plan inputs if provided
    if plan_inputs:
        engine.set_inputs(plan_inputs)

    # Check for missing required inputs
    missing = engine.get_missing_inputs()
    if missing:
        logger.error("Missing required inputs:")
        for name, spec in missing:
            desc = f" - {spec.description}" if spec.description else ""
            logger.error(f"  {name} ({spec.type}){desc}")
        logger.error("Provide inputs with: --input name=value")
        return 1

    # Show components
    logger.info(f"Components: {len(engine.components)}")
    for comp_id, comp in engine.components.items():
        manifest = comp.describe()
        logger.debug(f"  - {comp_id}: {manifest.type}")

    # Enhanced validation
    logger.info("Validating plan...")
    validation_report = validate_plan(plan)

    if validation_report.warnings:
        for warning in validation_report.warnings:
            logger.warning(str(warning))

    if not validation_report.valid:
        print(validation_report.format())
        return 1

    # Basic engine validation
    errors = engine.validate()
    if errors:
        logger.error("Engine validation failed:")
        for error in errors:
            logger.error(f"  - {error}")
        return 1

    logger.info("✓ Validation passed")

    if dry_run:
        logger.info("Dry run - skipping execution")
        return 0

    # Set up output directory BEFORE execution so sinks can use it
    if output_dir:
        output_dir = Path(output_dir)
    elif isinstance(engine, PersistentEngine):
        # For persistent engine, use runs/<run_id> for consistency
        output_dir = Path("runs") / engine.run_id
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = Path("results") / f"{plan_name}_{timestamp}"

    output_dir.mkdir(parents=True, exist_ok=True)

    # For resume mode, check if we're actually resuming
    if resume and isinstance(engine, PersistentEngine):
        state_file = output_dir / "state.jsonl"
        if state_file.exists():
            logger.info(f"Resuming from existing state in {output_dir}")

    # Execute with output directory and mode
    logger.info("Executing plan...")
    result = await engine.execute(output_dir=output_dir, output_mode=output_mode)

    # Report results
    print()
    print("=" * 60)
    print(f"EXECUTION {'COMPLETE' if result.success else 'FAILED'}")
    print("=" * 60)
    print(f"Duration: {result.duration_seconds:.2f}s")
    print(f"Components executed: {result.stats.get('components_executed', 0)}")
    print(f"Steps executed: {result.stats.get('steps_executed', 0)}")

    if result.errors:
        print(f"\nErrors: {len(result.errors)}")
        for err in result.errors:
            status = "✓ recovered" if err.recovered else "✗ fatal"
            print(f"  [{status}] {err.message}")

    # Show outputs summary
    if result.outputs:
        print("\nOutputs:")
        for sink_id, outputs in result.outputs.items():
            if "items" in outputs:
                print(f"  {sink_id}: {len(outputs['items'])} items collected")
            elif "count" in outputs:
                print(f"  {sink_id}: {outputs['count']} items")
            else:
                print(f"  {sink_id}: {list(outputs.keys())}")

    # Save full results (output_dir already created above)
    results_file = output_dir / "results.json"
    with open(results_file, "w") as f:
        json.dump({
            "plan_name": plan_name,
            "success": result.success,
            "duration_seconds": result.duration_seconds,
            "stats": result.stats,
            "outputs": result.outputs,
            "errors": [
                {
                    "type": e.error_type,
                    "message": e.message,
                    "recovered": e.recovered,
                    "recovery_action": e.recovery_action,
                }
                for e in result.errors
            ],
        }, f, indent=2, default=str)

    print(f"\nResults saved to: {output_dir}")

    # Create/update 'latest' symlink for easy access
    latest_link = output_dir.parent / "latest"
    try:
        if latest_link.is_symlink():
            latest_link.unlink()
        latest_link.symlink_to(output_dir.name)
    except OSError:
        pass  # Symlinks may not work on all systems

    return 0 if result.success else 1


def main():
    parser = argparse.ArgumentParser(
        description="Run dataflow evaluation plans",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("plan", type=Path, nargs="?", help="Path to plan JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Validate only")
    parser.add_argument("--output", "-o", type=Path, help="Output directory")

    # Persistence options
    parser.add_argument(
        "--run-id", "-r",
        type=str,
        help="Run ID for persistence (enables checkpoint/resume)"
    )
    parser.add_argument(
        "--resume",
        nargs="?",
        const="__latest__",
        default=None,
        metavar="RUN_NAME",
        help="Resume a previous run. No arg = latest run, or specify run name"
    )
    parser.add_argument(
        "--db",
        action="store_true",
        help="Log run to systems_history database"
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List available runs that can be resumed"
    )
    parser.add_argument(
        "--list-plans",
        action="store_true",
        help="List available plans"
    )
    parser.add_argument(
        "--input", "-i",
        action="append",
        metavar="KEY=VALUE",
        dest="inputs",
        help="Provide plan input (can be repeated: -i file=data.txt -i count=10)"
    )

    # Remaining args passed to the plan
    parser.add_argument("args", nargs="*", help="Arguments passed to the plan")

    args = parser.parse_args()

    # Handle --list-plans
    if args.list_plans:
        plans = get_available_plans()
        if not plans:
            print("No plans found in plans/ directory.")
            sys.exit(0)

        print(f"{'Plan Name':<28} {'Description'}")
        print("-" * 80)
        for plan in plans:
            desc = plan["description"][:48] + "..." if len(plan["description"]) > 48 else plan["description"]
            print(f"{plan['name']:<28} {desc}")
        sys.exit(0)

    # Handle --list-runs before plan validation
    if args.list_runs:
        runs_dir = Path("runs")
        if not runs_dir.exists():
            print("No runs/ directory found.")
            sys.exit(0)

        run_folders = [
            d for d in runs_dir.iterdir()
            if d.is_dir() and not d.is_symlink() and (d / "state.jsonl").exists()
        ]
        if not run_folders:
            print("No resumable runs found.")
            sys.exit(0)

        # Sort by modification time (most recent first)
        run_folders.sort(key=lambda d: d.stat().st_mtime, reverse=True)

        print(f"{'Run Name':<30} {'Last Modified':<20} {'State File Size'}")
        print("-" * 70)
        for run in run_folders:
            mtime = datetime.fromtimestamp(run.stat().st_mtime)
            state_file = run / "state.jsonl"
            size = state_file.stat().st_size
            size_str = f"{size:,} bytes" if size < 1024 else f"{size/1024:.1f} KB"
            print(f"{run.name:<30} {mtime.strftime('%Y-%m-%d %H:%M'):<20} {size_str}")
        sys.exit(0)

    # Handle --resume without a plan (auto-detect plan from run)
    if args.resume is not None and args.plan is None:
        run_name = None if args.resume == "__latest__" else args.resume
        sys.exit(resume_run(run_name))

    # Plan is required for all other operations
    # If no plan and interactive terminal, launch interactive mode
    if args.plan is None:
        if sys.stdin.isatty():
            sys.exit(interactive_mode())
        else:
            print("Error: Plan file is required (non-interactive mode)", file=sys.stderr)
            parser.print_usage()
            sys.exit(1)

    if not args.plan.exists():
        print(f"Error: Plan file not found: {args.plan}", file=sys.stderr)
        sys.exit(1)

    # Load plan to read settings
    with open(args.plan, "r") as f:
        plan = json.load(f)

    # Get output mode from plan settings (default: normal)
    settings = plan.get("settings", {})
    output_mode_str = settings.get("output_mode", "normal").lower()
    if output_mode_str == "quiet":
        output_mode = OutputMode.QUIET
    elif output_mode_str == "debug":
        output_mode = OutputMode.DEBUG
    else:
        output_mode = OutputMode.NORMAL

    setup_logging(output_mode)

    # Handle resume with explicit plan
    if args.resume is not None:
        run_name = None if args.resume == "__latest__" else args.resume

        # Validate run exists and set up for run_plan
        if run_name is None:
            latest = get_latest_resumable_run()
            if not latest:
                print("Error: No resumable runs found", file=sys.stderr)
                sys.exit(1)
            args.run_id = latest[0]
            print(f"Resuming latest run: {args.run_id}")
        else:
            args.run_id = run_name
            if not (Path("runs") / run_name).exists():
                print(f"Error: Run '{run_name}' not found in runs/", file=sys.stderr)
                sys.exit(1)
            print(f"Resuming run: {args.run_id}")

        args.resume = True
    else:
        args.resume = False

    # Parse plan inputs
    plan_inputs = parse_input_args(args.inputs)

    exit_code = asyncio.run(run_plan(
        args.plan,
        dry_run=args.dry_run,
        output_mode=output_mode,
        output_dir=args.output,
        plan_args=args.args,
        run_id=args.run_id,
        resume=args.resume,
        db_hook=args.db,
        plan_inputs=plan_inputs,
    ))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
