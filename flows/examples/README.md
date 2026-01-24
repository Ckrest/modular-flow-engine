# Example Plans

These examples demonstrate core patterns. Each is self-contained and uses generic data.

## Running Examples

```bash
# Basic loop - no inputs needed
python runner.py flows/examples/01_basic_loop.json

# With inputs - provide your own data
python runner.py flows/examples/02_with_inputs.json \
  --input data_file=flows/examples/sample_items.txt \
  --input prefix="[" --input suffix="]"

# Transform chain - lookup metadata
python runner.py flows/examples/03_transform_chain.json \
  --input items_file=flows/examples/sample_items.txt \
  --input metadata_file=flows/examples/sample_metadata.txt

# Nested loops - cross-product
python runner.py flows/examples/04_nested_loops.json \
  --input items_file=flows/examples/sample_items.txt \
  --input 'options=["x","y","z"]'

# Two-phase collection
python runner.py flows/examples/05_two_phase.json \
  --input data_file=flows/examples/sample_items.txt
```

## Examples Overview

| Example | Pattern | Key Concepts |
|---------|---------|--------------|
| `01_basic_loop` | Load → Loop → Collect | `source/text_list`, `sink/collector`, loop basics |
| `02_with_inputs` | Reusable plan | Plan inputs, `{$inputs.x}` in config, `{x}` in flow |
| `03_transform_chain` | Multiple transforms | `source/key_value`, `transform/lookup`, chaining |
| `04_nested_loops` | Cross-product | `source/literal`, nested loops, combinations |
| `05_two_phase` | Collect then process | `{"sink": ...}` finalization, accessing `.items` |
| `06_council` | Multi-model voting | `composite/council`, consensus checking, AI debate |

## Sample Data

- `sample_items.txt` - Simple list: alpha, beta, gamma, delta, epsilon
- `sample_metadata.txt` - Key|value pairs for lookup

## Components Used

**Sources:**
- `source/text_list` - Load lines from a file
- `source/key_value` - Load key|value pairs
- `source/literal` - Inline data (from inputs)

**Transforms:**
- `transform/template` - String formatting with `{var}` substitution
- `transform/lookup` - Dictionary lookup with default

**Sinks:**
- `sink/collector` - Accumulate items, access via `.items` after finalization
