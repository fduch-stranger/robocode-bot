#!/usr/bin/env python3
"""Summarize advisor telemetry: latency, errors, style accuracy, and the surf information test.

Style: with ``--truth <style>`` (the opponent's known style), compares the accuracy of Jev's answers
with the rule-based classifier's label logged on the same request.

Surf: for each answered wave, compares the hit rate when Jev's choice matched where we actually went
with the hit rate when it did not. If Jev's choice carries information about the enemy's aim,
waves where it disagreed with our movement should be hit more often (a one-sided two-proportion
z-test; the Phase 2 gate needs z >= 1.96 over at least 1,000 answered waves).
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SURF_GATE_MIN_WAVES = 1000
SURF_GATE_MIN_Z = 1.96


@dataclass
class AdvisorSummary:
    bot: str
    requests: dict[str, dict[str, int]] = field(default_factory=dict)
    answers: dict[str, int] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    models: list[str] = field(default_factory=list)
    latency_ms: dict[str, float | None] = field(default_factory=dict)
    latency_turns: dict[str, float | None] = field(default_factory=dict)
    mean_input_tokens: float | None = None
    style: dict[str, Any] = field(default_factory=dict)
    surf: dict[str, Any] = field(default_factory=dict)


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))], 1)


def _files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        files.extend([path] if path.is_file() else sorted(path.rglob("*.jsonl")))
    return files


def _events(paths: list[Path], bot: str):
    for path in _files(paths):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("bot") == bot and str(event.get("event", "")).startswith("advisor."):
                    fields = event.get("fields")
                    yield str(event["event"]), fields if isinstance(fields, dict) else {}


def _rate(hits: int, total: int) -> float | None:
    return round(hits / total, 4) if total else None


def surf_information_test(outcomes: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [outcome for outcome in outcomes if outcome.get("answer")]
    agree = [outcome for outcome in answered if outcome["answer"] == outcome.get("realized")]
    disagree = [outcome for outcome in answered if outcome["answer"] != outcome.get("realized")]
    agree_hits = sum(bool(outcome.get("hit")) for outcome in agree)
    disagree_hits = sum(bool(outcome.get("hit")) for outcome in disagree)
    z = None
    if agree and disagree:
        pooled = (agree_hits + disagree_hits) / len(answered)
        spread = math.sqrt(pooled * (1.0 - pooled) * (1.0 / len(agree) + 1.0 / len(disagree)))
        if spread > 0:
            z = round((disagree_hits / len(disagree) - agree_hits / len(agree)) / spread, 3)
    hit_waves = [outcome for outcome in answered if outcome.get("hit")]
    return {
        "answered_waves": len(answered),
        "answered_before_visit": _rate(sum(bool(outcome.get("answered_before_visit")) for outcome in answered), len(answered)),
        "hit_rate": _rate(sum(bool(outcome.get("hit")) for outcome in answered), len(answered)),
        "agreement": _rate(len(agree), len(answered)),
        "hit_rate_when_agree": _rate(agree_hits, len(agree)),
        "hit_rate_when_disagree": _rate(disagree_hits, len(disagree)),
        "z": z,
        "jev_choices": dict(Counter(outcome["answer"] for outcome in answered)),
        "realized": dict(Counter(outcome.get("realized") for outcome in answered)),
        "hit_waves_jev_elsewhere": _rate(sum(outcome["answer"] != outcome.get("realized") for outcome in hit_waves), len(hit_waves)),
        "gate_passed": bool(len(answered) >= SURF_GATE_MIN_WAVES and z is not None and z >= SURF_GATE_MIN_Z),
    }


def summarize(paths: list[Path], bot: str, truth: str | None = None) -> AdvisorSummary:
    summary = AdvisorSummary(bot=bot)
    requests: dict[str, Counter[str]] = {}
    answers: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    models: set[str] = set()
    latency_ms: list[float] = []
    latency_turns: list[float] = []
    tokens: list[int] = []
    style_answers: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for name, fields in _events(paths, bot):
        kind = str(fields.get("kind", "?"))
        if name == "advisor.request":
            requests.setdefault(kind, Counter())[str(fields.get("submit", "?"))] += 1
        elif name == "advisor.answer":
            answers[kind] += 1
            if isinstance(fields.get("model"), str):
                models.add(fields["model"])
            if isinstance(fields.get("latency_ms"), (int, float)):
                latency_ms.append(float(fields["latency_ms"]))
            if isinstance(fields.get("latency_turns"), (int, float)):
                latency_turns.append(float(fields["latency_turns"]))
            if isinstance(fields.get("input_tokens"), int) and fields["input_tokens"] > 0:
                tokens.append(fields["input_tokens"])
            if kind == "style":
                style_answers.append(fields)
        elif name == "advisor.error":
            errors[f"{kind}:{fields.get('error')}"] += 1
        elif name == "advisor.outcome":
            outcomes.append(fields)
    summary.requests = {kind: dict(counter) for kind, counter in sorted(requests.items())}
    summary.answers = dict(answers)
    summary.errors = dict(errors)
    summary.models = sorted(models)
    summary.latency_ms = {"p50": _percentile(latency_ms, 0.5), "p90": _percentile(latency_ms, 0.9), "max": max(latency_ms, default=None)}
    summary.latency_turns = {"p50": _percentile(latency_turns, 0.5), "p90": _percentile(latency_turns, 0.9), "max": max(latency_turns, default=None)}
    summary.mean_input_tokens = round(sum(tokens) / len(tokens), 1) if tokens else None
    summary.style = {
        "answers": len(style_answers),
        "jev_choices": dict(Counter(answer.get("choice") for answer in style_answers)),
        "rule_labels": dict(Counter(answer.get("rule") for answer in style_answers)),
        "jev_rule_agreement": _rate(sum(answer.get("choice") == answer.get("rule") for answer in style_answers), len(style_answers)),
    }
    if truth:
        summary.style["truth"] = truth
        summary.style["jev_accuracy"] = _rate(sum(answer.get("choice") == truth for answer in style_answers), len(style_answers))
        summary.style["rule_accuracy"] = _rate(sum(answer.get("rule") == truth for answer in style_answers), len(style_answers))
    summary.surf = surf_information_test(outcomes)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", type=Path, help="Telemetry JSONL files or directories (searched recursively).")
    parser.add_argument("--bot", default="adaptive-jev", help="Bot name as recorded in telemetry.")
    parser.add_argument("--truth", help="Known style of the opponent in these battles, e.g. wave_surfer.")
    parser.add_argument("--json-output", type=Path, help="Write the summary as JSON to this path.")
    args = parser.parse_args()

    summary = summarize(args.paths, args.bot, args.truth)
    text = json.dumps(asdict(summary), indent=2)
    print(text)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(text + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
