# Dataflow Evaluation System

A declarative dataflow engine for orchestrating multi-step AI evaluation pipelines. Define workflows as JSON plans, the engine handles execution, checkpointing, and error recovery.

## Quick Start

```bash
# Run an example
python runner.py plans/examples/01_basic_loop.json

# Run with user-provided inputs
python runner.py plans/examples/02_with_inputs.json \
  --input data_file=plans/examples/sample_items.txt \
  --input prefix="test_"

# Interactive mode - guided plan selection
python runner.py

# Resume after interrupt
python runner.py --resume
```

## CLI Reference

```
python runner.py                      # Interactive mode
python runner.py <plan.json>          # Run a plan
python runner.py --list-plans         # List available plans
python runner.py --list-runs          # List resumable runs
python runner.py --resume             # Resume latest run
python runner.py --resume <name>      # Resume specific run

Options:
  --input, -i KEY=VALUE   Provide plan inputs (repeatable)
  --run-id, -r ID         Enable checkpoint/resume with this ID
  --dry-run               Validate plan without executing
  --output, -o DIR        Output directory (default: results/)
  --db                    Log run to systems_history database
```

## Plan Structure

```json
{
  "name": "my_workflow",
  "description": "What this plan does",

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

### Plan Inputs

Plans can declare inputs that users provide at runtime:

| Type | Example Value | Notes |
|------|---------------|-------|
| `string` | `"hello"` | Text |
| `path` | `"/path/to/file.txt"` | Validated to exist |
| `integer` | `42` | Whole number |
| `boolean` | `true` | true/false |
| `list` | `["a","b"]` | JSON array |

**Reference in plans:**
- In component config: `{$inputs.name}` (resolved when plan loads)
- In flow steps: `{name}` (resolved at runtime)

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

## Checkpoint/Resume

For long-running jobs, use `--run-id` to enable automatic checkpointing:

```bash
# Start a job
python runner.py plans/big_job.json --run-id my_job

# If interrupted, resume where you left off
python runner.py --resume my_job

# Or just resume the latest run
python runner.py --resume
```

State is saved to `runs/<run-id>/state.jsonl`. On resume:
- Completed calls are skipped (cached)
- Completed loop iterations are skipped
- In-progress work is retried

## OpenRouter Setup

1. Get an API key from [openrouter.ai](https://openrouter.ai)
2. Add to `config/api_keys.json`:
   ```json
   {"openrouter": "sk-or-..."}
   ```
3. Use in plans:
   ```json
   {
     "api_key": {"type": "source/api_key", "config": {"key_name": "openrouter"}},
     "ask_model": {"type": "transform/openrouter", "config": {"temperature": 0.0}}
   }
   ```

## Directory Structure

```
dataflow-eval/
├── runner.py           # CLI entry point
├── core/               # Engine and base classes
│   ├── engine.py       # DataflowEngine
│   ├── persistence.py  # PersistentEngine (checkpoint/resume)
│   ├── component.py    # Component base class
│   ├── validation.py   # Plan validation
│   └── registry.py     # Component auto-discovery
├── components/         # Built-in components
│   ├── sources/        # Data sources
│   ├── transforms/     # Data processors
│   └── sinks/          # Data outputs
├── composites/         # Reusable component groups
├── plans/              # Workflow definitions
├── config/             # API keys (gitignored)
├── runs/               # Checkpoint state (per run-id)
└── results/            # Output files
```

## Examples

The `plans/examples/` directory contains working examples of core patterns:

| Example | What it demonstrates |
|---------|---------------------|
| `01_basic_loop` | Simplest pattern: load → loop → collect |
| `02_with_inputs` | Reusable plans with user-provided inputs |
| `03_transform_chain` | Chaining transforms: load, lookup, format |
| `04_nested_loops` | Cross-product iteration (items × options) |
| `05_two_phase` | Collect first, then process collected data |
| `06_council` | Multi-model AI voting with consensus |

See [plans/examples/README.md](plans/examples/README.md) for run commands.

## Further Reading

- [plans/examples/](plans/examples/) - Working examples to learn from
- [COMPONENT_GUIDE.md](COMPONENT_GUIDE.md) - Creating custom components
- [PATTERNS.md](PATTERNS.md) - Advanced workflow patterns
