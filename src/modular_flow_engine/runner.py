#!/usr/bin/env python3
"""
Modular Flow Engine Runner

Usage:
    python runner.py                     # Interactive mode
    python runner.py <flow.json>         # Run a flow
    python runner.py --list-flows        # List available flows

Options:
    --dry-run       Validate flow without executing
    --output DIR    Output directory (default: results/)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any



def get_available_flows() -> list[dict]:
    """Get all available flows with metadata."""
    flows_dir = Path("flows")
    if not flows_dir.exists():
        return []

    flows = []
    for f in sorted(flows_dir.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            flows.append({
                "path": f,
                "name": data.get("name", f.stem),
                "description": data.get("description", "No description"),
                "data": data,
            })
        except (json.JSONDecodeError, IOError):
            continue
    return flows


def analyze_flow(flow_data: dict) -> dict:
    """Analyze a flow and return useful metadata."""
    components = flow_data.get("components", {})

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

    check_flow(flow_data.get("flow", []))

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


def get_flow_inputs_schema(flow_data: dict) -> dict[str, dict]:
    """Get the input schema from a flow dict."""
    schema = {}
    for name, spec in flow_data.get("inputs", {}).items():
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
    """Interactively prompt for flow inputs."""
    inputs = {}

    required_inputs = [(k, v) for k, v in schema.items() if v["required"] and v["default"] is None]
    optional_inputs = [(k, v) for k, v in schema.items() if not v["required"] or v["default"] is not None]

    if required_inputs:
        print("This flow requires the following inputs:\n")

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


def interactive_mode() -> int:
    """Run interactive flow selection and execution."""
    print("\n=== Modular Flow Engine ===\n")

    # Get available flows
    flows = get_available_flows()
    if not flows:
        print("No flows found in flows/ directory.")
        return 1

    # Show flows
    print("Available flows:")
    for i, flow in enumerate(flows, 1):
        desc = flow["description"][:50] + "..." if len(flow["description"]) > 50 else flow["description"]
        print(f"  {i:2}. {flow['name']:<25} {desc}")

    print()

    # Select flow
    try:
        prompt = f"Select flow [1-{len(flows)} or name]: "
        selection = input(prompt).strip()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 0

    # Parse selection
    selected_flow = None
    if selection.isdigit():
        idx = int(selection) - 1
        if 0 <= idx < len(flows):
            selected_flow = flows[idx]
    else:
        # Search by name
        for flow in flows:
            if flow["name"] == selection or flow["path"].stem == selection:
                selected_flow = flow
                break

    if not selected_flow:
        print(f"Invalid selection: {selection}")
        return 1

    # Analyze flow
    analysis = analyze_flow(selected_flow["data"])

    print()
    print(f"─── {selected_flow['name']} ───")
    print(selected_flow["description"])
    print()

    # Check API requirements - only show if there's a problem
    if analysis["uses_api"] and analysis["api_key_name"]:
        if not check_api_key(analysis["api_key_name"]):
            print(f"⚠ API key '{analysis['api_key_name']}' not found")
            print(f"  Add it to config/api_keys.json before running")
            print()

    # Check for required inputs
    input_schema = get_flow_inputs_schema(selected_flow["data"])
    flow_inputs = {}
    if input_schema:
        flow_inputs = prompt_for_inputs(input_schema)
        if flow_inputs is None:
            return 0  # User cancelled

    # Build the command for display at the end
    cmd_parts = ["python runner.py", str(selected_flow["path"])]
    for key, value in flow_inputs.items():
        if isinstance(value, str) and " " in value:
            cmd_parts.append(f'--input {key}="{value}"')
        else:
            cmd_parts.append(f"--input {key}={value}")

    # Determine output mode from flow
    settings = selected_flow["data"].get("settings", {})
    output_mode_str = settings.get("output_mode", "normal").lower()
    if output_mode_str == "quiet":
        output_mode = OutputMode.QUIET
    elif output_mode_str == "debug":
        output_mode = OutputMode.DEBUG
    else:
        output_mode = OutputMode.NORMAL

    setup_logging(output_mode)

    # Run the flow
    print("=" * 50)
    print(f"Running {selected_flow['name']}...")
    print("=" * 50)
    print()

    exit_code = asyncio.run(run_flow(
        selected_flow["path"],
        dry_run=False,
        output_mode=output_mode,
        output_dir=None,
        flow_inputs=flow_inputs,
    ))

    # Show the command to run again
    print()
    print("═" * 50)
    print("To run again:")
    print(f"  {' '.join(cmd_parts)}")
    print("═" * 50)

    return exit_code


from .core import (
    DataflowEngine,
    ValidationError,
    ExecutionError,
    load_composites_from_directory,
    TraceLevel,
    validate_flow,
    OutputMode,
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


async def run_flow(
    flow_path: Path,
    dry_run: bool = False,
    output_mode: OutputMode = OutputMode.NORMAL,
    output_dir: Path | None = None,
    flow_inputs: dict[str, Any] | None = None,
) -> int:
    """Run a flow and return exit code."""
    import logging
    logger = logging.getLogger(__name__)

    # Load flow
    logger.info(f"Loading flow: {flow_path}")
    with open(flow_path, "r") as f:
        flow = json.load(f)

    flow_name = flow.get("name", flow_path.stem)
    logger.info(f"Flow: {flow_name}")
    logger.info(f"Description: {flow.get('description', 'No description')}")

    # Import components to register them
    from . import components  # noqa: F401

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

    # Create engine
    engine = DataflowEngine(trace_level=trace_level)
    engine.load_flow(flow)

    # Set flow inputs if provided
    if flow_inputs:
        engine.set_inputs(flow_inputs)

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
    logger.info("Validating flow...")
    validation_report = validate_flow(flow)

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

    # Set up output directory
    if output_dir:
        output_dir = Path(output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output_dir = Path("results") / f"{flow_name}_{timestamp}"

    output_dir.mkdir(parents=True, exist_ok=True)

    # Execute
    logger.info("Executing flow...")
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

    # Show returns (from sinks via context.write())
    if result.returns:
        print("\nReturns:")
        for key, value in result.returns.items():
            if isinstance(value, dict) and "items" in value:
                print(f"  {key}: {len(value['items'])} items")
            elif isinstance(value, list):
                print(f"  {key}: {len(value)} items")
            elif isinstance(value, dict):
                print(f"  {key}: {list(value.keys())}")
            else:
                val_str = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                print(f"  {key}: {val_str}")

    # Save full results
    results_file = output_dir / "results.json"
    with open(results_file, "w") as f:
        json.dump({
            "flow_name": flow_name,
            "success": result.success,
            "duration_seconds": result.duration_seconds,
            "stats": result.stats,
            "returns": result.returns,
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
        description="Run modular flow engine workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("flow", type=Path, nargs="?", help="Path to flow JSON file")
    parser.add_argument("--dry-run", action="store_true", help="Validate only")
    parser.add_argument("--output", "-o", type=Path, help="Output directory")
    parser.add_argument(
        "--list-flows",
        action="store_true",
        help="List available flows"
    )
    parser.add_argument(
        "--input", "-i",
        action="append",
        metavar="KEY=VALUE",
        dest="inputs",
        help="Provide flow input (can be repeated: -i file=data.txt -i count=10)"
    )

    # Remaining args passed to the flow
    parser.add_argument("args", nargs="*", help="Arguments passed to the flow")

    args = parser.parse_args()

    # Handle --list-flows
    if args.list_flows:
        flows = get_available_flows()
        if not flows:
            print("No flows found in flows/ directory.")
            sys.exit(0)

        print(f"{'Flow Name':<28} {'Description'}")
        print("-" * 80)
        for flow in flows:
            desc = flow["description"][:48] + "..." if len(flow["description"]) > 48 else flow["description"]
            print(f"{flow['name']:<28} {desc}")
        sys.exit(0)

    # Flow is required for all other operations
    # If no flow and interactive terminal, launch interactive mode
    if args.flow is None:
        if sys.stdin.isatty():
            sys.exit(interactive_mode())
        else:
            print("Error: Flow file is required (non-interactive mode)", file=sys.stderr)
            parser.print_usage()
            sys.exit(1)

    if not args.flow.exists():
        print(f"Error: Flow file not found: {args.flow}", file=sys.stderr)
        sys.exit(1)

    # Load flow to read settings
    with open(args.flow, "r") as f:
        flow = json.load(f)

    # Get output mode from flow settings (default: normal)
    settings = flow.get("settings", {})
    output_mode_str = settings.get("output_mode", "normal").lower()
    if output_mode_str == "quiet":
        output_mode = OutputMode.QUIET
    elif output_mode_str == "debug":
        output_mode = OutputMode.DEBUG
    else:
        output_mode = OutputMode.NORMAL

    setup_logging(output_mode)

    # Parse flow inputs
    flow_inputs = parse_input_args(args.inputs)

    exit_code = asyncio.run(run_flow(
        args.flow,
        dry_run=args.dry_run,
        output_mode=output_mode,
        output_dir=args.output,
        flow_inputs=flow_inputs,
    ))

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
