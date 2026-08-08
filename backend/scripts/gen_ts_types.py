#!/usr/bin/env python3
"""Generate frontend/src/types/api.generated.ts from Pydantic contracts.

Usage:
    cd backend && python scripts/gen_ts_types.py

The generated file is committed to git. CI verifies freshness with:
    python scripts/gen_ts_types.py --check
which exits non-zero if the file would change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# JSON Schema → TypeScript converter
# ---------------------------------------------------------------------------

def _ref_name(ref: str) -> str:
    """Extract model name from a $ref like '#/$defs/StockVoiceOut'."""
    return ref.rsplit("/", 1)[-1]


def _schema_to_ts(schema: dict[str, Any], defs: dict[str, Any], indent: int = 0) -> str:
    """Recursively convert a JSON Schema node to a TypeScript type expression."""
    if "$ref" in schema:
        return _ref_name(schema["$ref"])

    if "allOf" in schema:
        parts = [s for s in schema["allOf"] if "$ref" in s or "type" in s]
        if len(parts) == 1:
            return _schema_to_ts(parts[0], defs, indent)
        return " & ".join(_schema_to_ts(p, defs, indent) for p in parts)

    if "anyOf" in schema:
        inner = [s for s in schema["anyOf"] if s != {"type": "null"}]
        null_present = any(s == {"type": "null"} for s in schema["anyOf"])
        if not inner:
            return "null"
        ts = " | ".join(_schema_to_ts(s, defs, indent) for s in inner)
        if null_present:
            ts += " | null"
        return ts

    t = schema.get("type")

    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"

    if t == "array":
        items = schema.get("items", {})
        return f"{_schema_to_ts(items, defs, indent)}[]"

    if t == "object":
        props = schema.get("properties", {})
        required_set = set(schema.get("required", []))
        if not props:
            return "Record<string, unknown>"
        pad = "  " * (indent + 1)
        lines = ["{"]
        for name, prop_schema in props.items():
            opt = "" if name in required_set else "?"
            lines.append(f"{pad}{name}{opt}: {_schema_to_ts(prop_schema, defs, indent + 1)};")
        lines.append("  " * indent + "}")
        return "\n".join(lines)

    return "unknown"


def _model_to_ts_interface(name: str, schema: dict[str, Any], defs: dict[str, Any]) -> str:
    """Convert a Pydantic model's JSON Schema to a TypeScript interface string."""
    props = schema.get("properties", {})
    required_set = set(schema.get("required", []))
    description = schema.get("description", "")

    lines: list[str] = []
    if description:
        lines.append(f"/** {description} */")
    lines.append(f"export interface {name} {{")
    for field_name, field_schema in props.items():
        opt = "" if field_name in required_set else "?"
        ts_type = _schema_to_ts(field_schema, defs)
        lines.append(f"  {field_name}{opt}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Model registry
# ---------------------------------------------------------------------------

def _collect_models() -> list[tuple[str, dict[str, Any]]]:
    """Return (name, json_schema) pairs for every contract model."""
    # Ensure backend/ is on sys.path regardless of cwd.
    _backend = str(Path(__file__).parent.parent)
    if _backend not in sys.path:
        sys.path.insert(0, _backend)

    from api.contracts import (
        AddLexiconIn,
        AddLexiconOut,
        CharacterVoiceOut,
        CreateCloneOut,
        DeleteOut,
        ErrorOut,
        LexiconEntryOut,
        ListClonesOut,
        ListVoicesOut,
        PipelineStartOut,
        PipelineStatusOut,
        PipelineTraceDetailOut,
        PipelineTraceOut,
        PreviewOut,
        RerenderOut,
        SetCharacterIn,
        SetCharacterOut,
        StockVoiceOut,
        VoiceCloneOut,
        VoiceDetailOut,
        WaveformOut,
    )

    models = [
        ErrorOut,
        CharacterVoiceOut,
        SetCharacterIn,
        SetCharacterOut,
        LexiconEntryOut,
        AddLexiconIn,
        AddLexiconOut,
        DeleteOut,
        PipelineTraceOut,
        PipelineStatusOut,
        PipelineTraceDetailOut,
        PipelineStartOut,
        StockVoiceOut,
        ListVoicesOut,
        VoiceDetailOut,
        VoiceCloneOut,
        ListClonesOut,
        CreateCloneOut,
        PreviewOut,
        RerenderOut,
        WaveformOut,
    ]

    result: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for m in models:
        schema = m.model_json_schema()
        name = schema.get("title", m.__name__)
        if name not in seen:
            seen.add(name)
            result.append((name, schema))
        # Also emit $defs (nested models)
        for def_name, def_schema in schema.get("$defs", {}).items():
            if def_name not in seen:
                seen.add(def_name)
                result.append((def_name, def_schema))
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

HEADER = """\
// AUTO-GENERATED — do not edit by hand.
// Source: backend/api/contracts/  |  Generator: backend/scripts/gen_ts_types.py
// Regenerate: cd backend && python scripts/gen_ts_types.py

"""


def generate() -> str:
    models = _collect_models()
    # Collect all $defs across every top-level schema so cross-refs resolve.
    all_defs: dict[str, Any] = {}
    for _, schema in models:
        all_defs.update(schema.get("$defs", {}))

    chunks: list[str] = [HEADER]
    for name, schema in models:
        t = schema.get("type")
        if t == "object" or "properties" in schema:
            chunks.append(_model_to_ts_interface(name, schema, all_defs))
            chunks.append("")
    return "\n".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the generated file would change (for CI).",
    )
    args = parser.parse_args()

    # Locate output path relative to this script's repo root.
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent.parent
    out_path = repo_root / "frontend" / "src" / "types" / "api.generated.ts"

    content = generate()

    if args.check:
        if out_path.exists() and out_path.read_text() == content:
            print("api.generated.ts is up to date.")
            sys.exit(0)
        print(
            "ERROR: api.generated.ts is stale. Run:\n"
            "  cd backend && python scripts/gen_ts_types.py",
            file=sys.stderr,
        )
        sys.exit(1)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content)
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
