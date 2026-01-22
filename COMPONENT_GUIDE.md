# Component Creation Guide

This guide explains how to create components for the dataflow evaluation system. It's designed to be used by both humans and AI agents.

## Table of Contents
1. [Component Architecture](#component-architecture)
2. [Creating a Component](#creating-a-component)
3. [Best Practices](#best-practices)
4. [Component Templates](#component-templates)
5. [Testing Components](#testing-components)
6. [Common Patterns](#common-patterns)

---

## Component Architecture

### What is a Component?

A component is a self-contained unit that:
- **Declares** what inputs it needs and outputs it produces
- **Validates** its inputs before execution
- **Executes** a single, focused operation
- **Returns** its outputs

### Component Categories

| Category | Purpose | Input/Output Pattern |
|----------|---------|---------------------|
| **Source** | Produce data from external sources | No inputs → Data outputs |
| **Transform** | Process/modify data | Data inputs → Data outputs |
| **Control** | Control execution flow | Handled by engine |
| **Sink** | Collect or output data | Data inputs → Summary outputs |

### The Component Interface

```python
class Component(ABC):
    @classmethod
    @abstractmethod
    def describe(cls) -> ComponentManifest:
        """Declare inputs, outputs, and config."""
        pass

    def validate(self, inputs: dict) -> ValidationResult:
        """Validate inputs (default checks required fields)."""
        pass

    @abstractmethod
    async def execute(self, inputs: dict, context: ExecutionContext) -> dict:
        """Execute and return outputs."""
        pass
```

---

## Creating a Component

### Step 1: Define the Interface

Before writing code, answer these questions:
1. What **category** is this? (source/transform/sink)
2. What **inputs** does it need? (name, type, required?)
3. What **outputs** does it produce? (name, type)
4. What **config** options should be available? (static settings)

### Step 2: Create the Component Class

```python
from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.context import ExecutionContext
from core.registry import register_component

@register_component("category/name")
class MyComponent(Component):
    """
    One-line description.

    Detailed description of what this component does,
    when to use it, and any important notes.
    """

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="category/name",
            description="One-line description",
            category="transform",  # or "source", "sink"
            config={
                "option_name": ConfigSpec(
                    type="string",  # string, integer, boolean, float, list, dict
                    required=False,
                    default="default_value",
                    description="What this option does",
                ),
            },
            inputs={
                "input_name": InputSpec(
                    type="string",
                    required=True,
                    description="What this input is for",
                ),
            },
            outputs={
                "output_name": OutputSpec(
                    type="string",
                    description="What this output contains",
                ),
            },
        )

    async def execute(
        self,
        inputs: dict[str, Any],
        context: ExecutionContext
    ) -> dict[str, Any]:
        # Get config values
        option = self.get_config("option_name", "default")

        # Get input values
        input_value = inputs.get("input_name", "")

        # Do the work
        result = process(input_value, option)

        # Return outputs (must match declared outputs)
        return {
            "output_name": result,
        }
```

### Step 3: Register the Component

Add to the category's `__init__.py`:

```python
from .my_component import MyComponent

__all__ = [..., "MyComponent"]
```

---

## Best Practices

### 1. Make Components Generic

**Bad:** Hardcoded assumptions
```python
# DON'T: Hardcoded for specific use case
class AnimeCharacterClassifier(Component):
    async def execute(self, inputs, context):
        return {"is_anime": "anime" in inputs["name"].lower()}
```

**Good:** Configurable and reusable
```python
# DO: Generic pattern matching
class ContainsPattern(Component):
    @classmethod
    def describe(cls):
        return ComponentManifest(
            config={"pattern": ConfigSpec(type="string", required=True)},
            inputs={"text": InputSpec(type="string", required=True)},
            outputs={"matches": OutputSpec(type="boolean")},
        )
```

### 2. Clear Input/Output Types

Declare types accurately:
- `"string"` - Text values
- `"integer"` - Whole numbers
- `"float"` - Decimal numbers
- `"boolean"` - True/False
- `"list"` - Arrays (add element type: `"list[string]"`)
- `"dict"` - Objects/maps
- `"any"` - When type varies (use sparingly)

### 3. Meaningful Error Messages

```python
async def execute(self, inputs, context):
    path = self.get_config("path")
    if not Path(path).exists():
        raise FileNotFoundError(
            f"Config 'path' points to non-existent file: {path}\n"
            f"Working directory: {Path.cwd()}"
        )
```

### 4. Config vs Inputs

| Use Config For | Use Inputs For |
|----------------|----------------|
| Static settings that don't change per-call | Dynamic data that varies |
| File paths, API keys, model names | Data being processed |
| Behavior flags | Values from other components |

### 5. Single Responsibility

Each component should do ONE thing well:
- **Good:** `YesNoParser` - parses yes/no from text
- **Bad:** `YesNoParserAndValidator` - parses AND validates against truth

### 6. Stateless When Possible

Components should not rely on state between calls, EXCEPT for:
- Sinks that accumulate results (like `Collector`)
- Caches for performance

---

## Component Templates

### Source Template

```python
@register_component("source/my_source")
class MySource(Component):
    """Load data from [source type]."""

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="source/my_source",
            description="Load data from [source type]",
            category="source",
            config={
                "path": ConfigSpec(type="string", required=True),
            },
            inputs={},  # Sources have no inputs
            outputs={
                "items": OutputSpec(type="list", description="Loaded items"),
                "count": OutputSpec(type="integer", description="Number of items"),
            },
        )

    async def execute(self, inputs, context):
        path = Path(self.get_config("path"))
        # Load data...
        items = load_from_path(path)
        return {"items": items, "count": len(items)}
```

### Transform Template

```python
@register_component("transform/my_transform")
class MyTransform(Component):
    """Transform [input type] to [output type]."""

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/my_transform",
            description="Transform [input] to [output]",
            category="transform",
            config={},
            inputs={
                "input_data": InputSpec(type="string", required=True),
            },
            outputs={
                "result": OutputSpec(type="string"),
            },
        )

    async def execute(self, inputs, context):
        data = inputs.get("input_data", "")
        result = transform(data)
        return {"result": result}
```

### Sink Template

```python
@register_component("sink/my_sink")
class MySink(Component):
    """Collect/output data to [destination]."""

    def __init__(self, instance_id, config):
        super().__init__(instance_id, config)
        self._collected = []

    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="sink/my_sink",
            description="Collect data",
            category="sink",
            config={},
            inputs={},  # Accept any inputs
            outputs={
                "items": OutputSpec(type="list"),
                "count": OutputSpec(type="integer"),
            },
        )

    def validate(self, inputs):
        return ValidationResult(valid=True)  # Accept any

    async def execute(self, inputs, context):
        if inputs:
            self._collected.append(dict(inputs))
        return {"items": self._collected, "count": len(self._collected)}
```

---

## Testing Components

### Manual Testing

```python
import asyncio
from core.context import ExecutionContext

# Create component
comp = MyComponent("test_instance", {"config_key": "value"})

# Test execution
async def test():
    ctx = ExecutionContext()
    result = await comp.execute({"input_key": "test_value"}, ctx)
    print(result)

asyncio.run(test())
```

### Validation Testing

```python
# Test that validation catches missing required inputs
result = comp.validate({})
assert not result.valid
assert "input_key" in str(result.errors)

# Test that validation passes with valid inputs
result = comp.validate({"input_key": "value"})
assert result.valid
```

---

## Common Patterns

### Pattern: API Call with Retry

```python
from core.errors import ErrorProtocol

class APIComponent(Component):
    # Override default error handling
    error_protocol = ErrorProtocol(on_error="retry", max_retries=3)

    async def execute(self, inputs, context):
        # Retries are handled by engine based on error_protocol
        response = await call_api(inputs["query"])
        return {"response": response}
```

### Pattern: Optional Inputs with Defaults

```python
inputs={
    "required_field": InputSpec(type="string", required=True),
    "optional_field": InputSpec(
        type="string",
        required=False,
        default="default_value",
        description="Optional, defaults to 'default_value'"
    ),
}

async def execute(self, inputs, context):
    value = inputs.get("optional_field", "default_value")
```

### Pattern: Multiple Output Formats

```python
outputs={
    "raw": OutputSpec(type="string", description="Raw response"),
    "parsed": OutputSpec(type="dict", description="Parsed response"),
    "success": OutputSpec(type="boolean", description="Whether parsing succeeded"),
}

async def execute(self, inputs, context):
    raw = get_data()
    try:
        parsed = parse(raw)
        return {"raw": raw, "parsed": parsed, "success": True}
    except:
        return {"raw": raw, "parsed": {}, "success": False}
```

---

## Checklist for New Components

Before submitting a component, verify:

- [ ] `describe()` accurately declares all inputs, outputs, and config
- [ ] All required inputs have `required=True`
- [ ] All outputs declared are actually returned
- [ ] Error messages include context (what failed, why, suggestions)
- [ ] Component is registered with `@register_component`
- [ ] Docstring explains what the component does
- [ ] Config vs inputs distinction is appropriate
- [ ] Component does ONE thing well

---

## Component Reference

Component documentation is auto-generated from the component manifests. To view all available components with their config, inputs, and outputs:

```bash
python3 -c "
import components
from core.registry import ComponentRegistry
print(ComponentRegistry.get_instance().generate_docs())
"
```

Or list just component types:

```bash
python3 -c "
import components
from core.registry import ComponentRegistry
for t in ComponentRegistry.get_instance().list_types():
    print(t)
"
```
