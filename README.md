# Modular Flow Engine

A declarative dataflow engine for orchestrating multi-step AI pipelines. Define workflows as JSON flows, the engine handles execution and error recovery. Includes an HTTP API for programmatic access.

## Quick Start

```bash
# Run an example flow
python runner.py flows/simple_test.json

# Run with user-provided inputs
python runner.py flows/input_test.json \
  --input data_file=/path/to/data.txt \
  --input limit=10

# Interactive mode - guided flow selection
python runner.py

# Start HTTP API service
python server.py
```

## CLI Reference

```
python runner.py                      # Interactive mode
python runner.py <flow.json>          # Run a flow
python runner.py --list-flows         # List available flows

Options:
  --input, -i KEY=VALUE   Provide flow inputs (repeatable)
  --dry-run               Validate flow without executing
  --output, -o DIR        Output directory (default: results/)
```

## HTTP API

The flow engine includes an HTTP service for programmatic access:

```bash
# Start the service
python server.py                    # Default port 9847
python server.py --port 8080        # Custom port
```

### API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /flows` | List available flows |
| `GET /flows/{name}` | Get flow schema |
| `POST /flows/{name}/execute` | Execute flow |
| `POST /flows/{name}/validate` | Validate inputs |
| `GET /jobs` | List jobs |
| `GET /jobs/{job_id}` | Get job status |
| `GET /components` | List components |
| `GET /health` | Health check |

### Example API Usage

```bash
# Execute a flow
curl -X POST http://localhost:9847/flows/with_inputs/execute \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"data_file": "/tmp/test.txt"}}'

# Async execution (returns job_id)
curl -X POST "http://localhost:9847/flows/with_inputs/execute?sync=false" \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"data_file": "/tmp/test.txt"}}'
```

Interactive API docs at: http://localhost:9847/docs

## Flow Structure

```json
{
  "name": "my_workflow",
  "description": "What this flow does",

  "inputs": {
    "data_file": {
      "type": "path",
      "required": true,
      "description": "Path to input data"
    },
    "limit": {
      "type": "integer",
      "required": false,
      "default": 10
    }
  },

  "components": {
    "data": {
      "type": "source/text_list",
      "config": { "path": "{$inputs.data_file}" }
    },
    "results": {
      "type": "sink/collector"
    }
  },

  "flow": [
    {"source": "data"},
    {
      "loop": {
        "over": "data.items",
        "as": "item",
        "steps": [
          {"call": "results", "inputs": {"value": "{item}"}}
        ]
      }
    },
    {"sink": "results"}
  ]
}
```

### Flow Inputs

Flows can declare inputs that users provide at runtime:

| Type | Example Value | Notes |
|------|---------------|-------|
| `string` | `"hello"` | Text |
| `path` | `"/path/to/file.txt"` | Validated to exist |
| `integer` | `42` | Whole number |
| `boolean` | `true` | true/false |
| `list` | `["a","b"]` | JSON array |

**Reference in flows:**
- In component config: `{$inputs.name}` (resolved when flow loads)
- In flow steps: `{name}` (resolved at runtime)

### Output Destinations

Sinks write to configurable destinations:

```json
{
  "results": {
    "type": "sink/collector",
    "config": {
      "destinations": ["return", "file"],
      "path": "results.json"
    }
  }
}
```

| Destination | Description |
|-------------|-------------|
| `return` | Include in API response |
| `file` | Write to JSON file (requires `path` config) |
| `console` | Print to stdout |

- `sink/collector` defaults to `["return"]` if not specified
- `sink/json_writer` defaults to `["file"]` if not specified

The HTTP API automatically waits for results if any sink has `"return"` in destinations.

## Components

Components are the building blocks. They're organized by category:

| Category | Purpose | Examples |
|----------|---------|----------|
| `source/*` | Load data | `text_list`, `literal`, `api_key` |
| `transform/*` | Process data | `template`, `openrouter`, `yesno_parser` |
| `sink/*` | Collect/output | `collector`, `json_writer` |

**List available components:**
```bash
python3 -c "import components; from core.registry import ComponentRegistry; print('\n'.join(ComponentRegistry.get_instance().list_types()))"
```

**Generate full documentation:**
```bash
python3 -c "import components; from core.registry import ComponentRegistry; print(ComponentRegistry.get_instance().generate_docs())"
```

## Flow Control

### Loops
```json
{
  "loop": {
    "over": "source.items",
    "as": "item",
    "index": "i",
    "steps": [...]
  }
}
```

### Nested Loops
```json
{
  "loop": {
    "over": "items",
    "as": "item",
    "steps": [
      {
        "loop": {
          "over": "models.value",
          "as": "model",
          "steps": [...]
        }
      }
    ]
  }
}
```

### Two-Phase Collection

Collectors must be finalized before accessing their contents:

```json
{"loop": {"steps": [{"call": "collector", ...}]}},
{"sink": "collector"},
{"call": "process", "inputs": {"data": "{collector.items}"}}
```

## OpenRouter Setup

1. Get an API key from [openrouter.ai](https://openrouter.ai)
2. Add to `config/api_keys.json`:
   ```json
   {"openrouter": "sk-or-..."}
   ```
3. Use in flows:
   ```json
   {
     "api_key": {"type": "source/api_key", "config": {"key_name": "openrouter"}},
     "ask_model": {"type": "transform/openrouter", "config": {"temperature": 0.0}}
   }
   ```

## Directory Structure

```
modular-flow-engine/
├── runner.py           # CLI entry point
├── server.py           # HTTP API entry point
├── core/               # Engine and base classes
│   ├── engine.py       # DataflowEngine
│   ├── context.py      # ExecutionContext with destination writers
│   ├── component.py    # Component base class
│   ├── validation.py   # Flow validation
│   └── registry.py     # Component auto-discovery
├── server/             # HTTP API package
│   ├── app.py          # FastAPI application
│   ├── routes.py       # API endpoints
│   └── models.py       # Pydantic models
├── components/         # Built-in components
│   ├── sources/        # Data sources
│   ├── transforms/     # Data processors
│   └── sinks/          # Data outputs
├── composites/         # Reusable component groups
├── flows/              # Workflow definitions
├── config/             # API keys (gitignored)
└── results/            # Output files
```

## Examples

The `flows/examples/` directory contains working examples of core patterns:

| Example | What it demonstrates |
|---------|---------------------|
| `01_basic_loop` | Simplest pattern: load → loop → collect |
| `02_with_inputs` | Reusable flows with user-provided inputs |
| `03_transform_chain` | Chaining transforms: load, lookup, format |
| `04_nested_loops` | Cross-product iteration (items × options) |
| `05_two_phase` | Collect first, then process collected data |
| `06_council` | Multi-model AI voting with consensus |

See [flows/examples/README.md](flows/examples/README.md) for run commands.

## Further Reading

- [flows/examples/](flows/examples/) - Working examples to learn from
- [CLAUDE.md](CLAUDE.md) - Agent guidance and component reference
