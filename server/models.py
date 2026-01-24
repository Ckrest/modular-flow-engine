"""Pydantic models for Flow Engine API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# === Flow Models ===

class FlowInputSpec(BaseModel):
    """Specification for a flow input."""
    type: str = "string"
    required: bool = True
    default: Any = None
    description: str = ""


class FlowInfo(BaseModel):
    """Summary info about a flow (for listing)."""
    name: str
    description: str
    inputs: list[str] = Field(default_factory=list)
    has_returns: bool = False


class FlowSchema(BaseModel):
    """Full flow schema with inputs, returns, components."""
    name: str
    description: str
    inputs: dict[str, FlowInputSpec] = Field(default_factory=dict)
    returns: dict[str, str] = Field(default_factory=dict)
    components: dict[str, dict[str, Any]] = Field(default_factory=dict)
    flow_steps: int = 0


class FlowValidationResult(BaseModel):
    """Result of validating a flow with inputs."""
    valid: bool
    missing_inputs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    component_count: int = 0
    step_count: int = 0


# === Execution Models ===

class FlowExecuteRequest(BaseModel):
    """Request to execute a flow."""
    inputs: dict[str, Any] = Field(default_factory=dict)


class FlowExecuteResponse(BaseModel):
    """Response from flow execution."""
    success: bool
    returns: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    errors: list[dict[str, Any]] = Field(default_factory=list)


class AcceptedResponse(BaseModel):
    """Response when flow is accepted for fire-and-forget execution."""
    accepted: bool = True
    flow: str


# === Component Models ===

class ComponentInfo(BaseModel):
    """Summary info about a component type."""
    type: str
    description: str
    category: str


class ComponentSchema(BaseModel):
    """Full component manifest."""
    type: str
    description: str
    category: str
    config: dict[str, dict[str, Any]] = Field(default_factory=dict)
    inputs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    outputs: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ComponentListResponse(BaseModel):
    """Response listing components by category."""
    components: dict[str, list[str]]
    total: int


# === Health Check ===

class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    version: str = "1.0.0"
    flows_available: int = 0
    uptime_seconds: float = 0.0
