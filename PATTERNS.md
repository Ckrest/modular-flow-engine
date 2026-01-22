# Dataflow Patterns

Common patterns for building dataflow evaluation plans.

---

## Multi-Model Debate Pattern

When a classification decision is high-stakes or subjective, use multiple AI models to vote and identify where they disagree.

### Use Case
- Content classification/moderation
- Subjective quality assessment
- Any task where model bias could affect results

### Structure

```
┌─────────────────────────────────────────────────────────────────┐
│                     Multi-Model Debate                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Phase 1: Voting (nested loops)                          │  │
│   │                                                          │  │
│   │   for each ITEM:                                        │  │
│   │       for each MODEL:                                   │  │
│   │           1. Build prompt                                │  │
│   │           2. Ask model                                   │  │
│   │           3. Parse response                              │  │
│   │           4. Collect vote                                │  │
│   │                                                          │  │
│   └──────────────────────────────────────────────────────────┘  │
│                              ▼                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Phase 2: Consensus Check                                │  │
│   │                                                          │  │
│   │   category_consensus analyzes all votes and outputs:     │  │
│   │   - agreed: items with majority agreement               │  │
│   │   - disputed: items needing arbitration                 │  │
│   │                                                          │  │
│   └──────────────────────────────────────────────────────────┘  │
│                              ▼                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Phase 3a: Collect Agreed Items                          │  │
│   │                                                          │  │
│   │   Loop over agreed items, collect to final results       │  │
│   │                                                          │  │
│   └──────────────────────────────────────────────────────────┘  │
│                              ▼                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Phase 3b: Arbitrate Disputed Items                      │  │
│   │                                                          │  │
│   │   for each DISPUTED item:                               │  │
│   │       1. Build debate prompt with all model votes        │  │
│   │       2. Ask arbitrator model                            │  │
│   │       3. Parse final category                            │  │
│   │       4. Collect to final results                        │  │
│   │                                                          │  │
│   └──────────────────────────────────────────────────────────┘  │
│                              ▼                                  │
│   ┌──────────────────────────────────────────────────────────┐  │
│   │  Phase 4: Output                                         │  │
│   │                                                          │  │
│   │   Write final_collector items to JSON                    │  │
│   │                                                          │  │
│   └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Key Components

1. **`transform/openrouter`** - Call multiple AI models
2. **`transform/category_parser`** - Extract category from response
3. **`sink/collector`** - Collect votes in memory
4. **`transform/category_consensus`** - Analyze votes for agreement
5. **Arbitrator** - Another `transform/openrouter` with a powerful model (e.g., GPT-4.1)

### Consensus Types

| Type | Definition | Action |
|------|------------|--------|
| `unanimous` | All models agree (100%) | Accept directly |
| `majority` | Most agree (> threshold, default 50%) | Accept with majority vote |
| `disputed` | No clear winner | Send to arbitrator |

### Example Plan Structure

```json
{
  "components": {
    "models": {
      "type": "source/literal",
      "config": {
        "value": [
          "openai/gpt-4.1-mini",
          "anthropic/claude-sonnet-4",
          "google/gemini-2.5-flash-preview-09-2025"
        ]
      }
    },
    "categories": {
      "type": "source/literal",
      "config": {
        "value": ["category_a", "category_b", "category_c", "pass"]
      }
    },
    "ask_model": {
      "type": "transform/openrouter",
      "config": {"temperature": 0.0, "max_tokens": 20}
    },
    "parse_category": {
      "type": "transform/category_parser",
      "config": {"default_category": "unknown"}
    },
    "votes_collector": {
      "type": "sink/collector",
      "config": {"fields": ["item", "model", "category"]}
    },
    "check_consensus": {
      "type": "transform/category_consensus",
      "config": {"majority_threshold": 0.5}
    },
    "arbitrator": {
      "type": "transform/openrouter",
      "config": {"model": "openai/gpt-4.1", "temperature": 0.0}
    }
  },

  "flow": [
    {"source": "categories"},
    {"source": "models"},

    {
      "loop": {
        "over": "items.value",
        "as": "item",
        "steps": [
          {
            "loop": {
              "over": "models.value",
              "as": "model_name",
              "steps": [
                {"call": "ask_model", "inputs": {...}, "outputs": {"response": "model_response"}},
                {"call": "parse_category", "inputs": {...}, "outputs": {"category": "voted_category"}},
                {"call": "votes_collector", "inputs": {"item": "{item}", "model": "{model_name}", "category": "{voted_category}"}}
              ]
            }
          }
        ]
      }
    },

    {"sink": "votes_collector"},

    {
      "call": "check_consensus",
      "inputs": {"votes": "{votes_collector.items}"},
      "outputs": {"agreed": "agreed_items", "disputed": "disputed_items"}
    },

    {
      "loop": {
        "over": "disputed_items",
        "as": "dispute",
        "steps": [
          {"call": "arbitrator", "inputs": {...}},
          {"call": "final_collector", "inputs": {...}}
        ]
      }
    }
  ]
}
```

### Benefits

1. **Reliability**: Multiple perspectives reduce single-model bias
2. **Transparency**: Vote breakdown shows where models agree/disagree
3. **Human Review**: Disputed items can be flagged for manual review
4. **Cost Optimization**: Arbitrator only called for disputes

---

## Two-Phase Collection Pattern

Collect data in one phase, process collected data in another.

### Structure

```json
{
  "flow": [
    {
      "loop": {
        "over": "items",
        "as": "item",
        "steps": [
          {"call": "processor", "inputs": {...}},
          {"call": "collector", "inputs": {...}}
        ]
      }
    },

    {"sink": "collector"},

    {
      "call": "aggregator",
      "inputs": {"items": "{collector.items}"}
    }
  ]
}
```

### Key Insight

The `{"sink": "collector"}` step "finalizes" the collector and makes its `.items` available to subsequent steps. Without this, looping over `collector.items` would happen before collection is complete.

---

## Batch Processing with Progress

For long-running jobs, add progress printing:

```json
{
  "loop": {
    "over": "items",
    "as": "item",
    "index": "i",
    "steps": [
      {"call": "process_item", "inputs": {...}},
      {
        "call": "progress_print",
        "inputs": {
          "message": "Processed {i}/1000: {item}"
        }
      }
    ]
  }
}
```

Use `transform/print` with a prefix for visual feedback:

```json
"progress_print": {
  "type": "transform/print",
  "config": {"prefix": "  📊 "}
}
```

---

## Checkpoint Resume Pattern

For jobs that may crash or be interrupted:

1. **Use run-id**: `--run-id my_job`
2. **State persists**: `runs/my_job/state.jsonl` logs every call
3. **Resume**: `--resume` skips completed work

### How It Works

The `PersistentEngine` computes a hash for each component call based on:
- Component ID
- Resolved inputs

On resume, if the hash matches a completed call in the log, the cached outputs are used without re-executing.

### Best Practices

- Use meaningful run IDs for long jobs
- Check `state.jsonl` to see progress
- Completed iterations show in resume log

---

## Error Handling Patterns

### Retry on Failure

```json
{
  "error_handling": {
    "default": "retry",
    "max_retries": 3
  }
}
```

### Skip and Continue

For non-critical steps:

```json
{
  "error_handling": {
    "default": "skip"
  }
}
```

### Fail Fast

```json
{
  "error_handling": {
    "default": "fail"
  }
}
```

---

## Model Selection Pattern

Let the plan specify models flexibly:

```json
{
  "ask_model": {
    "type": "transform/openrouter",
    "config": {
      "temperature": 0.0,
      "max_tokens": 100
    }
  }
}
```

Then pass model per-call:

```json
{
  "call": "ask_model",
  "inputs": {
    "model": "{model_name}",
    "prompt": "..."
  }
}
```

This allows:
- Looping over different models
- Using different models for different tasks
- Easy model comparison experiments

---

## Template Patterns

### Simple Interpolation

```json
{
  "call": "template",
  "inputs": {
    "template": "Classify this item: {item}",
    "item": "{current_item}"
  }
}
```

### Multi-variable Templates

```json
{
  "call": "template",
  "inputs": {
    "template": "Tag: {tag}\n\nModel votes:\n{votes}\n\nCategories: {categories}\n\nCorrect category:",
    "tag": "{dispute.item}",
    "votes": "{dispute.model_votes}",
    "categories": "a, b, c, pass"
  }
}
```

---

## Category Parsing Pattern

When expecting a single-word category response from an AI model:

```json
{
  "parse_category": {
    "type": "transform/category_parser",
    "config": {
      "default_category": "unknown"
    }
  }
}
```

Usage:

```json
{
  "call": "parse_category",
  "inputs": {
    "text": "{model_response}",
    "categories": "{categories.value}"
  },
  "outputs": {
    "category": "parsed_category",
    "matched": "did_match",
    "confidence": "match_confidence"
  }
}
```

### Confidence Levels

- `exact`: Category found as standalone word
- `partial`: Category found as substring
- `none`: No match, using default
