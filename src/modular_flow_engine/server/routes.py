"""API route handlers for Flow Engine service."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from .models import (
    FlowInfo,
    FlowSchema,
    FlowInputSpec,
    FlowValidationResult,
    FlowExecuteRequest,
    FlowExecuteResponse,
    AcceptedResponse,
    ComponentSchema,
    ComponentListResponse,
    HealthResponse,
)


router = APIRouter()


def get_flows_dir() -> Path:
    """Get the flows directory path."""
    return Path(__file__).parent.parent / "flows"


def load_flow_file(name: str) -> dict[str, Any]:
    """Load a flow JSON file by name."""
    flows_dir = get_flows_dir()

    # Try exact name first
    flow_path = flows_dir / f"{name}.json"
    if not flow_path.exists():
        # Try in examples subdirectory
        flow_path = flows_dir / "examples" / f"{name}.json"

    if not flow_path.exists():
        raise HTTPException(status_code=404, detail=f"Flow '{name}' not found")

    try:
        return json.loads(flow_path.read_text())
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid flow JSON: {e}")


def get_available_flows() -> list[dict[str, Any]]:
    """Get all available flows with metadata."""
    flows_dir = get_flows_dir()
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

    # Also check examples subdirectory
    examples_dir = flows_dir / "examples"
    if examples_dir.exists():
        for f in sorted(examples_dir.glob("*.json")):
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


# === Health ===

@router.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """Check service health."""
    from .app import get_uptime

    flows = get_available_flows()

    return HealthResponse(
        status="healthy",
        version="1.0.0",
        flows_available=len(flows),
        uptime_seconds=get_uptime(),
    )


# === Flows ===

@router.get("/flows", response_model=dict, tags=["Flows"])
async def list_flows() -> dict:
    """List all available flows."""
    flows = get_available_flows()

    return {
        "flows": [
            FlowInfo(
                name=f["name"],
                description=f["description"],
                inputs=list(f["data"].get("inputs", {}).keys()),
                has_returns=flow_has_return_destination(f["data"]),
            ).model_dump()
            for f in flows
        ]
    }


@router.get("/flows/{name}", response_model=FlowSchema, tags=["Flows"])
async def get_flow(name: str) -> FlowSchema:
    """Get full flow schema including inputs, returns, components."""
    data = load_flow_file(name)

    # Parse inputs
    inputs = {}
    for inp_name, inp_spec in data.get("inputs", {}).items():
        if isinstance(inp_spec, dict):
            inputs[inp_name] = FlowInputSpec(
                type=inp_spec.get("type", "string"),
                required=inp_spec.get("required", True),
                default=inp_spec.get("default"),
                description=inp_spec.get("description", ""),
            )
        else:
            inputs[inp_name] = FlowInputSpec(type=inp_spec)

    # Count flow steps
    def count_steps(flow: list) -> int:
        count = 0
        for step in flow:
            count += 1
            if "loop" in step:
                count += count_steps(step["loop"].get("steps", []))
            if "conditional" in step:
                for branch in ["then", "else"]:
                    if branch in step["conditional"]:
                        count += count_steps(step["conditional"][branch])
        return count

    return FlowSchema(
        name=data.get("name", name),
        description=data.get("description", ""),
        inputs=inputs,
        returns=data.get("returns", {}),
        components={
            comp_id: {"type": comp.get("type")}
            for comp_id, comp in data.get("components", {}).items()
        },
        flow_steps=count_steps(data.get("flow", [])),
    )


@router.post("/flows/{name}/validate", response_model=FlowValidationResult, tags=["Flows"])
async def validate_flow(name: str, request: FlowExecuteRequest) -> FlowValidationResult:
    """Validate a flow with the given inputs (dry-run)."""
    data = load_flow_file(name)

    # Check for missing required inputs
    missing_inputs = []
    for inp_name, inp_spec in data.get("inputs", {}).items():
        if isinstance(inp_spec, dict):
            required = inp_spec.get("required", True)
            default = inp_spec.get("default")
        else:
            required = True
            default = None

        if required and default is None and inp_name not in request.inputs:
            missing_inputs.append(inp_name)

    # Count steps and components
    def count_steps(flow: list) -> int:
        count = 0
        for step in flow:
            count += 1
            if "loop" in step:
                count += count_steps(step["loop"].get("steps", []))
            if "conditional" in step:
                for branch in ["then", "else"]:
                    if branch in step["conditional"]:
                        count += count_steps(step["conditional"][branch])
        return count

    return FlowValidationResult(
        valid=len(missing_inputs) == 0,
        missing_inputs=missing_inputs,
        warnings=[],
        component_count=len(data.get("components", {})),
        step_count=count_steps(data.get("flow", [])),
    )


def flow_has_return_destination(data: dict) -> bool:
    """Check if any sink has 'return' in its destinations config."""
    for comp_id, comp_def in data.get("components", {}).items():
        comp_type = comp_def.get("type", "")

        # Only check sink components
        if not comp_type.startswith("sink/"):
            continue

        config = comp_def.get("config", {})
        destinations = config.get("destinations", [])

        # collector defaults to ["return"] if not specified
        if comp_type == "sink/collector" and not destinations:
            return True

        if "return" in destinations:
            return True

    return False


@router.post("/flows/{name}/execute", tags=["Flows"])
async def execute_flow(
    name: str,
    request: FlowExecuteRequest,
    background_tasks: BackgroundTasks,
    wait: bool | None = Query(default=None, description="Wait for result. Default: true if any sink has 'return' destination."),
) -> FlowExecuteResponse | AcceptedResponse:
    """
    Execute a flow.

    Default behavior depends on whether any sink writes to the 'return' destination:
    - Sink has destinations: ["return", ...] → wait for result
    - No sinks write to return → fire-and-forget

    Use `wait=true` or `wait=false` to override.
    """
    data = load_flow_file(name)

    # Determine wait behavior based on sink destinations
    should_wait = wait if wait is not None else flow_has_return_destination(data)

    if should_wait:
        # Execute and wait for result
        return await _execute_flow(name, data, request.inputs)
    else:
        # Fire-and-forget: schedule in background
        background_tasks.add_task(_execute_flow_background, name, data, request.inputs)
        return AcceptedResponse(flow=name)


async def _execute_flow(
    name: str,
    data: dict[str, Any],
    inputs: dict[str, Any],
) -> FlowExecuteResponse:
    """Execute a flow and return results."""
    from ..core import DataflowEngine, TraceLevel, OutputMode

    engine = DataflowEngine(trace_level=TraceLevel.ERRORS)
    engine.load_flow(data)
    engine.set_inputs(inputs)

    # Check for missing required inputs
    missing = engine.get_missing_inputs()
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required inputs: {[m[0] for m in missing]}",
        )

    # Execute
    result = await engine.execute(output_mode=OutputMode.QUIET)

    return FlowExecuteResponse(
        success=result.success,
        returns=result.returns,
        outputs=result.outputs,
        duration_seconds=result.duration_seconds,
        errors=[
            {
                "type": e.error_type,
                "message": e.message,
                "recovered": e.recovered,
            }
            for e in result.errors
        ],
    )


async def _execute_flow_background(
    name: str,
    data: dict[str, Any],
    inputs: dict[str, Any],
) -> None:
    """Execute a flow in the background (fire-and-forget)."""
    try:
        await _execute_flow(name, data, inputs)
    except Exception as e:
        # Log errors for background tasks
        import logging
        logging.error(f"Background flow '{name}' failed: {e}")


# === Components ===

@router.get("/components", response_model=ComponentListResponse, tags=["Components"])
async def list_components() -> ComponentListResponse:
    """List all available component types by category."""
    from ..core import ComponentRegistry

    registry = ComponentRegistry.get_instance()
    all_types = registry.list_types()

    # Group by category
    by_category: dict[str, list[str]] = {"source": [], "transform": [], "sink": []}
    for comp_type in all_types:
        if comp_type.startswith("source/"):
            by_category["source"].append(comp_type)
        elif comp_type.startswith("transform/"):
            by_category["transform"].append(comp_type)
        elif comp_type.startswith("sink/"):
            by_category["sink"].append(comp_type)

    return ComponentListResponse(
        components=by_category,
        total=len(all_types),
    )


@router.get("/components/{category}", tags=["Components"])
async def list_components_by_category(category: str) -> dict:
    """List components in a specific category."""
    from ..core import ComponentRegistry

    registry = ComponentRegistry.get_instance()
    all_types = registry.list_types()

    prefix = f"{category}/"
    matches = [t for t in all_types if t.startswith(prefix)]

    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"No components found in category '{category}'",
        )

    return {"category": category, "components": matches}


@router.get("/components/{category}/{name}/schema", response_model=ComponentSchema, tags=["Components"])
async def get_component_schema(category: str, name: str) -> ComponentSchema:
    """Get full component manifest/schema."""
    from ..core import ComponentRegistry

    comp_type = f"{category}/{name}"
    registry = ComponentRegistry.get_instance()
    comp_class = registry.get(comp_type)

    if comp_class is None:
        raise HTTPException(status_code=404, detail=f"Component '{comp_type}' not found")

    manifest = comp_class.describe()

    return ComponentSchema(
        type=manifest.type,
        description=manifest.description,
        category=manifest.category,
        config={
            name: {
                "type": spec.type,
                "required": spec.required,
                "default": spec.default,
                "description": spec.description,
            }
            for name, spec in manifest.config.items()
        },
        inputs={
            name: {
                "type": spec.type,
                "required": spec.required,
                "description": spec.description,
            }
            for name, spec in manifest.inputs.items()
        },
        outputs={
            name: {
                "type": spec.type,
                "description": spec.description,
            }
            for name, spec in manifest.outputs.items()
        },
    )


# === Docs ===

@router.get("/docs/components", tags=["System"])
async def get_component_docs() -> dict:
    """Get generated component documentation in markdown."""
    from ..core import ComponentRegistry

    registry = ComponentRegistry.get_instance()
    docs = registry.generate_docs()

    return {"format": "markdown", "content": docs}
