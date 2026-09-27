#!/usr/bin/env python3
"""Summarize bot turn timing: decision-time percentiles, skipped turns, and slow-turn causes.

Slow turns (bot.turn_timing with severity != "ok") carry phase_us and, for bots that opt in,
gc_pause_us, so each one can be attributed to a code path or to garbage collection.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TimingSummary:
    bot: str
    timing_samples: int = 0
    slow_turns: int = 0
    skipped_turns: int = 0
    decision_us: dict[str, int | None] = field(default_factory=dict)
    slow_turn_top_phase: dict[str, int] = field(default_factory=dict)
    slow_turns_gc_dominated: int = 0
    slow_turn_gc_generations: dict[str, int] = field(default_factory=dict)
    mean_phase_us_ok_turns: dict[str, float] = field(default_factory=dict)
    slowest: list[dict[str, Any]] = field(default_factory=list)


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _telemetry_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        if path.is_file():
            files.append(path)
        else:
            files.extend(sorted(path.rglob("*.jsonl")))
    return files


def summarize(paths: list[Path], bot: str, slowest: int = 10) -> TimingSummary:
    summary = TimingSummary(bot=bot)
    elapsed: list[int] = []
    top_phase: Counter[str] = Counter()
    gc_generations: Counter[str] = Counter()
    ok_phase_totals: Counter[str] = Counter()
    ok_phase_turns = 0
    slow_records: list[dict[str, Any]] = []
    for path in _telemetry_files(paths):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict) or event.get("bot") != bot:
                    continue
                fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
                name = event.get("event")
                if name == "bot.skipped_turn":
                    summary.skipped_turns += 1
                    continue
                if name != "bot.turn_timing" or not isinstance(fields.get("decision_elapsed_us"), int):
                    continue
                summary.timing_samples += 1
                decision_us = fields["decision_elapsed_us"]
                elapsed.append(decision_us)
                phases = fields.get("phase_us") if isinstance(fields.get("phase_us"), dict) else {}
                if fields.get("severity") == "ok":
                    if phases:
                        ok_phase_turns += 1
                        ok_phase_totals.update({str(k): int(v) for k, v in phases.items()})
                    continue
                summary.slow_turns += 1
                gc_pause_us = fields.get("gc_pause_us")
                if isinstance(gc_pause_us, int) and gc_pause_us * 2 >= decision_us:
                    summary.slow_turns_gc_dominated += 1
                    top_phase["gc"] += 1
                elif phases:
                    top_phase[max(phases, key=lambda key: phases[key])] += 1
                if isinstance(fields.get("gc_max_generation"), int) and fields["gc_max_generation"] >= 0:
                    gc_generations[str(fields["gc_max_generation"])] += 1
                slow_records.append(
                    {
                        "file": path.name,
                        "turn": event.get("turn"),
                        "decision_us": decision_us,
                        "gc_pause_us": gc_pause_us,
                        "gc_max_generation": fields.get("gc_max_generation"),
                        "phase_us": phases,
                        "gun_samples": fields.get("gun_samples"),
                        "movement_waves": fields.get("movement_waves"),
                        "shadow_bullets": fields.get("shadow_bullets"),
                    }
                )
    summary.decision_us = {
        "p50": _percentile(elapsed, 0.50),
        "p95": _percentile(elapsed, 0.95),
        "p99": _percentile(elapsed, 0.99),
        "max": max(elapsed) if elapsed else None,
    }
    summary.slow_turn_top_phase = dict(top_phase.most_common())
    summary.slow_turn_gc_generations = dict(sorted(gc_generations.items()))
    if ok_phase_turns:
        summary.mean_phase_us_ok_turns = {
            phase: round(total / ok_phase_turns, 1) for phase, total in ok_phase_totals.most_common()
        }
    summary.slowest = sorted(slow_records, key=lambda record: -record["decision_us"])[:slowest]
    return summary


def _format(summary: TimingSummary) -> str:
    decision = summary.decision_us
    lines = [
        f"bot: {summary.bot}",
        f"timing samples: {summary.timing_samples}, slow turns: {summary.slow_turns}, skipped turns: {summary.skipped_turns}",
        f"decision us: p50={decision.get('p50')} p95={decision.get('p95')} p99={decision.get('p99')} max={decision.get('max')}",
        f"slow turns dominated by GC: {summary.slow_turns_gc_dominated}; GC generations in slow turns: {summary.slow_turn_gc_generations}",
        f"slow-turn top phase: {summary.slow_turn_top_phase}",
        f"mean phase us on ok turns: {summary.mean_phase_us_ok_turns}",
        "slowest turns:",
    ]
    for record in summary.slowest:
        lines.append(
            "  turn={turn} decision_us={decision_us} gc_pause_us={gc_pause_us} gen={gc_max_generation} "
            "gun_samples={gun_samples} movement_waves={movement_waves} shadows={shadow_bullets} phases={phase_us}".format(**record)
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Telemetry JSONL files or directories (searched recursively).")
    parser.add_argument("--bot", required=True, help="Bot name as recorded in telemetry, e.g. adaptive-prime.")
    parser.add_argument("--slowest", type=int, default=10, help="How many of the slowest turns to list.")
    parser.add_argument("--json-output", type=Path, help="Write the summary as JSON to this path.")
    args = parser.parse_args()

    summary = summarize(args.paths, args.bot, args.slowest)
    print(_format(summary))
    if args.json_output:
        args.json_output.write_text(json.dumps(asdict(summary), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
