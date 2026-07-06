"""Schema loader: reads YAML definitions from schemas/ and builds LLM prompts."""

from pathlib import Path

import yaml

SCHEMAS_DIR = Path(__file__).parent.parent / "schemas"


def load(name: str) -> dict:
    """Load a schema by name, e.g. load('cfpb_complaints')."""
    path = SCHEMAS_DIR / f"{name}.yaml"
    with open(path) as f:
        return yaml.safe_load(f)


def build_schema_description(schema_data: dict) -> str:
    table = schema_data["table"]
    lines = [f"Table: `{table}`", "", "Columns:"]
    for col in schema_data["columns"]:
        lines.append(f"  {col['name']:<35} {col['type']:<8} {col['description']}")
    return "\n".join(lines)


def build_rules(schema_data: dict) -> str:
    rules = schema_data.get("rules", [])
    numbered = "\n".join(f"{i+1}. {r.strip()}" for i, r in enumerate(rules))
    return f"RULES (must follow):\n{numbered}"


def build_value_hints(schema_data: dict) -> str:
    hints = schema_data.get("value_hints", {})
    lines = []
    if "product_labels" in hints:
        lines.append("Known product labels (reference when matching product names):")
        for label in hints["product_labels"]:
            lines.append(f"  - {label}")
    if "tags" in hints:
        lines.append(f"\nKnown tags values: {', '.join(hints['tags'])}")
    return "\n".join(lines)


def build_examples(schema_data: dict) -> str:
    examples = schema_data.get("examples", [])
    blocks = []
    for ex in examples:
        blocks.append(f"Q: {ex['question']}\nSQL:\n{ex['sql'].strip()}")
    return "EXAMPLES:\n\n" + "\n\n".join(blocks)


def build_prompt(question: str, schema_data: dict) -> str:
    parts = [
        build_schema_description(schema_data),
        build_rules(schema_data),
        build_value_hints(schema_data),
        build_examples(schema_data),
        f"Q: {question}\nSQL:",
    ]
    return "\n\n".join(parts)
