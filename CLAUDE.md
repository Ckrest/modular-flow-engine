# Modular Flow Engine - Agent Guidance

Declarative dataflow engine for AI pipelines. Flows are JSON, executed by the engine. Includes HTTP API for programmatic access.

## Key Files

| File | Purpose |
|------|---------|
| `runner.py` | CLI entry point |
| `server.py` | HTTP API entry point |
| `core/engine.py` | DataflowEngine - executes flows |
| `core/context.py` | ExecutionContext - variables, scoping, destination writers |
| `core/validation.py` | Flow validation |
| `core/registry.py` | Component auto-discovery |
| `server/` | HTTP API (FastAPI) |
| `components/*/` | Built-in components |
| `flows/` | Workflow definitions |

## Running Flows

```bash
python runner.py flows/my_flow.json               # Run a flow
python runner.py flows/my_flow.json --input x=val # With inputs
python runner.py                                  # Interactive mode
python runner.py --list-flows                     # List flows
python runner.py flows/my_flow.json --dry-run     # Validate only

python server.py                                  # Start HTTP API
```

## Output Destinations

Sinks write to configurable destinations using `context.write()`:

| Destination | Description |
|-------------|-------------|
| `return` | Include in API response (`ExecutionResult.returns`) |
| `file` | Write to JSON file (requires `path` config) |
| `console` | Print to stdout |

### Sink Configuration

```json
{
  "type": "sink/collector",
  "config": {
    "destinations": ["return", "file"],
    "path": "results.json"
  }
}
```

- `sink/collector` defaults to `["return"]` if not specified
- `sink/json_writer` defaults to `["file"]` if not specified

### HTTP API Wait Behavior

The `/flows/{name}/execute` endpoint automatically determines whether to wait for results:
- If any sink has `"return"` in destinations → wait for result
- Otherwise → fire-and-forget (202 Accepted)

Override with `?wait=true` or `?wait=false`.

## Flow Inputs

Flows declare inputs in the `inputs` section:

```json
{
  "inputs": {
    "data_file": {"type": "path", "required": true},
    "limit": {"type": "integer", "default": 10}
  }
}
```

**Reference syntax:**
- `{$inputs.name}` - In component config (resolved at flow load)
- `{name}` - In flow steps (resolved at runtime)

## Variable Resolution

```json
"{variable}"           // Simple variable or plan input
"{source.items}"       // Output field from source component
"{source.value}"       // For literal sources
"{loop_var.field}"     // Field from loop variable
```

**Common component outputs:**
- `source/literal` → `.value`
- `source/text_list` → `.items`, `.count`
- `sink/collector` → `.items`, `.count`

## Two-Phase Collection

Collectors must be finalized before using their contents:

```json
{"loop": {"steps": [{"call": "collector", ...}]}},
{"sink": "collector"},
{"call": "process", "inputs": {"data": "{collector.items}"}}
```

## Adding Components

1. Create file in `components/sources/`, `components/transforms/`, or `components/sinks/`
2. Use `@register_component` decorator:

```python
from core.component import Component, ComponentManifest, ConfigSpec, InputSpec, OutputSpec
from core.registry import register_component

@register_component("transform/my_transform")
class MyTransform(Component):
    @classmethod
    def describe(cls) -> ComponentManifest:
        return ComponentManifest(
            type="transform/my_transform",
            description="What this does",
            category="transform",
            config={...},
            inputs={...},
            outputs={...},
        )

    async def execute(self, inputs, context):
        return {...}
```

3. Component is auto-discovered on import.

## Config vs Inputs

| Config | Inputs |
|--------|--------|
| Set at component definition | Passed per-call |
| Static throughout execution | Dynamic, from other components |
| File paths, API settings | Data being processed |

## Generate Component Docs

```bash
python3 -c "
import components
from core.registry import ComponentRegistry
print(ComponentRegistry.get_instance().generate_docs())
"
```

## Common Patterns

See [PATTERNS.md](PATTERNS.md) for:
- Multi-model debate (consensus voting)
- Two-phase collection
- Batch processing with progress
