#!/usr/bin/env python3
"""Probe the Jev API with advisor-shaped requests: latency percentiles, errors, and the model ID.

The key is read from TYPESAFE_API_KEY, falling back to the repo .env (or ROBOCODE_ENV_FILE). It is
never printed or written anywhere. Style requests use idealized feature profiles, so the report also
shows whether Jev names the intended style when the evidence is clear.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bots"))

from bot_core.advisors.jev_transport import API_KEY_ENV, AdvisorError, JevTransport  # noqa: E402
from bot_core.advisors.schemas import (  # noqa: E402
    STYLE_OPTIONS,
    STYLE_QUESTION_ID,
    SURF_OPTIONS,
    SURF_QUESTION_ID,
    parse_choice,
    style_questions,
    surf_questions,
)
from bot_core.advisors.state_summary import (  # noqa: E402
    StyleFeatures,
    SurfFeatures,
    rule_based_style,
    style_state,
    surf_state,
)

ENV_PREFIXES = ("TYPESAFE_", "ROBOCODE_JEV_")

STYLE_PROFILES: dict[str, StyleFeatures] = {
    "wave_surfer": StyleFeatures(900, 7.2, 6.4, 6.0, 2.6, 420.0, 45.0, 0.0, 2.0, 0.0, 0.15, 0.04),
    "orbiter": StyleFeatures(900, 8.0, 7.4, 1.0, 1.0, 380.0, 30.0, 0.0, 1.6, 0.0, 0.1, 0.25),
    "chaser": StyleFeatures(900, 7.5, 3.0, 2.5, 1.1, 180.0, 60.0, -40.0, 2.5, 2.0, 0.1, 0.18),
    "sweeper": StyleFeatures(900, 7.8, 4.0, 3.0, 1.0, 380.0, 150.0, 0.0, 4.0, 0.2, 0.2, 0.1),
    "oscillator": StyleFeatures(900, 5.0, 4.5, 14.0, 1.0, 400.0, 25.0, 0.0, 0.3, 0.0, 0.1, 0.06),
    "linear_mover": StyleFeatures(900, 8.0, 5.0, 0.8, 1.0, 400.0, 120.0, 0.0, 0.2, 0.0, 0.4, 0.3),
    "random_mover": StyleFeatures(900, 5.5, 3.5, 8.0, 1.0, 380.0, 80.0, 0.0, 6.5, 0.1, 0.2, 0.08),
    "stationary": StyleFeatures(900, 0.1, 0.05, 0.0, None, 400.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.9),
}

SURF_PROFILES: list[SurfFeatures] = [
    SurfFeatures(420.0, 1.9, 30.0, 8.0, 0.95, 1.0, 1.0, (0.6, 0.7, 0.55, 0.8, 0.65)),
    SurfFeatures(420.0, 1.9, 30.0, 8.0, 0.95, 0.3, 1.0, (-0.6, -0.7, -0.5, -0.8)),
    SurfFeatures(250.0, 2.8, 22.0, 6.0, 0.9, 1.0, 0.5, (0.0, 0.05, -0.1, 0.1, 0.0, -0.05)),
    SurfFeatures(520.0, 1.2, 50.0, 0.5, 0.0, 1.0, 1.0, ()),
]


@dataclass
class ProbeResult:
    kind: str
    expected: str | None
    latency_ms: float
    ok: bool
    error: str | None = None
    status: int | None = None
    model: str | None = None
    input_tokens: int | None = None
    choice: str | None = None
    confidence: float | None = None


def load_env_file(path: Path) -> None:
    """Export TYPESAFE_* and ROBOCODE_JEV_* values from ``path`` unless the environment has them."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", line)
        if match is None:
            continue
        name, value = match.group(1), match.group(2).strip()
        if not name.startswith(ENV_PREFIXES) or name in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[name] = value


def build_requests(count: int) -> list[tuple[str, str | None, object, dict[str, Any]]]:
    styles = list(STYLE_PROFILES.items())
    requests: list[tuple[str, str | None, object, dict[str, Any]]] = []
    for index in range(count):
        if index % 2 == 0:
            label, features = styles[(index // 2) % len(styles)]
            requests.append(("style", label, style_state(features), style_questions()))
        else:
            features = SURF_PROFILES[(index // 2) % len(SURF_PROFILES)]
            requests.append(("surf", None, surf_state(features), surf_questions()))
    return requests


def run_one(transport: JevTransport, request: tuple[str, str | None, object, dict[str, Any]]) -> ProbeResult:
    kind, expected, state, questions = request
    started = time.perf_counter()
    try:
        response = transport.evaluate(state, questions)
    except AdvisorError as error:
        return ProbeResult(kind, expected, (time.perf_counter() - started) * 1000.0, False, error.kind, error.status)
    latency_ms = (time.perf_counter() - started) * 1000.0
    question_id, options = (STYLE_QUESTION_ID, STYLE_OPTIONS) if kind == "style" else (SURF_QUESTION_ID, SURF_OPTIONS)
    answer = parse_choice(response.answers.get(question_id), options)
    return ProbeResult(
        kind,
        expected,
        latency_ms,
        answer is not None,
        None if answer is not None else "parse",
        None,
        response.model,
        response.input_tokens,
        answer.choice if answer is not None else None,
        round(answer.confidence, 3) if answer is not None else None,
    )


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered) - 1, int(fraction * len(ordered)))], 1)


def summarize(results: list[ProbeResult]) -> dict[str, Any]:
    ok = [result for result in results if result.ok]
    errors: dict[str, int] = {}
    for result in results:
        if not result.ok:
            key = result.error if result.status is None else f"{result.error}:{result.status}"
            errors[key] = errors.get(key, 0) + 1
    latencies = [result.latency_ms for result in ok]
    warm = [result.latency_ms for result in ok[1:]]
    style = [result for result in ok if result.kind == "style"]
    surf = [result for result in ok if result.kind == "surf"]
    tokens = [result.input_tokens for result in ok if result.input_tokens is not None]
    return {
        "requests": len(results),
        "ok": len(ok),
        "errors": errors,
        "models": sorted({result.model for result in ok if result.model}),
        "latency_ms": {
            "first": round(results[0].latency_ms, 1) if results else None,
            "p50": percentile(latencies, 0.5),
            "p90": percentile(latencies, 0.9),
            "max": round(max(latencies), 1) if latencies else None,
            "warm_p50": percentile(warm, 0.5),
            "warm_p90": percentile(warm, 0.9),
        },
        "mean_input_tokens": round(sum(tokens) / len(tokens), 1) if tokens else None,
        "style_idealized_correct": f"{sum(result.choice == result.expected for result in style)}/{len(style)}",
        "rule_idealized_correct": (
            f"{sum(rule_based_style(features) == label for label, features in STYLE_PROFILES.items())}/{len(STYLE_PROFILES)}"
        ),
        "style_confusions": sorted({f"{result.expected}->{result.choice}" for result in style if result.choice != result.expected}),
        "surf_choices": {option: sum(result.choice == option for result in surf) for option in SURF_OPTIONS},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requests", type=int, default=30, help="Number of requests (alternating style and surf).")
    parser.add_argument("--concurrency", type=int, default=1, help="Parallel requests, one connection per thread.")
    parser.add_argument("--json-output", type=Path, help="Write per-request results and the summary as JSON.")
    args = parser.parse_args()

    load_env_file(Path(os.environ.get("ROBOCODE_ENV_FILE") or ROOT / ".env"))
    transport = JevTransport.from_environment()
    if transport is None:
        print(f"{API_KEY_ENV} is not set in the environment or .env", file=sys.stderr)
        return 2
    requests = build_requests(max(1, args.requests))
    started = time.perf_counter()
    if args.concurrency <= 1:
        results = [run_one(transport, request) for request in requests]
    else:
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            results = list(pool.map(lambda request: run_one(transport, request), requests))
    elapsed_s = time.perf_counter() - started
    transport.close()

    summary = summarize(results)
    summary["elapsed_s"] = round(elapsed_s, 2)
    summary["concurrency"] = args.concurrency
    print(json.dumps(summary, indent=2))
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        payload = {"summary": summary, "results": [result.__dict__ for result in results]}
        args.json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return 0 if summary["ok"] >= 0.9 * len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
