#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BOTS_DIR = ROOT / "bots"
if str(BOTS_DIR) not in sys.path:
    sys.path.insert(0, str(BOTS_DIR))

from bot_core.telemetry.schema import CANONICAL_FIELDS, EVENT_SPECS  # noqa: E402


def build_markdown() -> str:
    lines = [
        "# Telemetry Event Schema",
        "",
        "This file is generated from `bots/bot_core/telemetry/schema.py`.",
        "Run `tools/telemetry_schema_docs.py --output docs/telemetry-schema.md` after changing the schema.",
        "",
        "The browser viewer and telemetry audit normalize bot-specific fields into a common dashboard contract.",
        "",
        "## Canonical Dashboard Fields",
        "",
    ]
    for field in sorted(CANONICAL_FIELDS):
        lines.append(f"- `{field}`")
    lines.extend(["", "## Events", ""])

    by_category: dict[str, list[str]] = {}
    for event_name, spec in EVENT_SPECS.items():
        by_category.setdefault(spec.category, []).append(event_name)

    for category in sorted(by_category):
        lines.extend([f"### {category.title()}", ""])
        lines.extend(["| Event | Required Fields | Optional Fields | Aliases |", "| --- | --- | --- | --- |"])
        for event_name in sorted(by_category[category]):
            spec = EVENT_SPECS[event_name]
            required = fields_cell(spec.required_fields)
            optional = fields_cell(spec.optional_fields)
            aliases = aliases_cell(spec.aliases or {})
            lines.append(f"| `{event_name}` | {required} | {optional} | {aliases} |")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def fields_cell(fields: tuple[str, ...]) -> str:
    if not fields:
        return "-"
    return ", ".join(f"`{field}`" for field in fields)


def aliases_cell(aliases: dict[str, tuple[str, ...]]) -> str:
    if not aliases:
        return "-"
    parts = []
    for canonical in sorted(aliases):
        alias_list = ", ".join(f"`{alias}`" for alias in aliases[canonical])
        parts.append(f"`{canonical}` from {alias_list}")
    return "<br>".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate telemetry schema documentation.")
    parser.add_argument("--output", type=Path, help="Write markdown to this path instead of stdout.")
    args = parser.parse_args()

    markdown = build_markdown()
    if args.output:
        output_path = args.output if args.output.is_absolute() else ROOT / args.output
        output_path.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
