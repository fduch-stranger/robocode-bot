#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def main() -> int:
    args = _parse_args()
    events = list(_read_events(Path(args.telemetry_dir), args.bot))
    summary = summarize_events(events)
    _print_summary(summary)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize gun-mode telemetry from a Robocode telemetry directory.")
    parser.add_argument("telemetry_dir", help="Directory containing telemetry JSONL files.")
    parser.add_argument("--bot", default="adaptive-prime", help="Bot telemetry name to summarize.")
    return parser.parse_args()


def _read_events(telemetry_dir: Path, bot: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in sorted(telemetry_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                event = json.loads(line)
                if event.get("bot") == bot:
                    events.append(event)
    return events


def summarize_events(events: list[dict[str, Any]]) -> dict[str, object]:
    fired: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    shots_by_id: dict[str, str] = {}
    pending_hits_by_id: Counter[str] = Counter()
    wave_selected: Counter[str] = Counter()
    eval_selected: Counter[str] = Counter()
    wave_scores: dict[str, list[float]] = defaultdict(list)
    eval_scores: dict[str, list[float]] = defaultdict(list)

    for event in events:
        name = event.get("event")
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        if name == "round.reset":
            shots_by_id.clear()
            pending_hits_by_id.clear()
        elif name == "bullet.fired" and fields.get("aim_mode"):
            mode = str(fields["aim_mode"])
            fired[mode] += 1
            bullet_id = _bullet_id(fields)
            if bullet_id is not None:
                shots_by_id[bullet_id] = mode
                pending_hits = pending_hits_by_id.pop(bullet_id, 0)
                if pending_hits:
                    hits[mode] += pending_hits
        elif name == "bullet.hit_bot":
            mode = str(fields["aim_mode"]) if fields.get("aim_mode") else None
            if mode is None:
                bullet_id = _bullet_id(fields)
                if bullet_id is not None:
                    mode = shots_by_id.get(bullet_id)
                    if mode is None:
                        pending_hits_by_id[bullet_id] += 1
            if mode is not None:
                hits[mode] += 1
        elif name == "gun.wave_visit":
            _record_wave(fields, wave_selected, wave_scores)
        elif name == "gun.eval_wave_visit":
            _record_wave(fields, eval_selected, eval_scores)

    return {
        "fired": dict(fired),
        "hits": dict(hits),
        "hit_rate": _rates(hits, fired),
        "wave_selected": dict(wave_selected),
        "eval_selected": dict(eval_selected),
        "wave_avg": _averages(wave_scores),
        "eval_avg": _averages(eval_scores),
        "wave_count": {mode: len(scores) for mode, scores in sorted(wave_scores.items())},
        "eval_count": {mode: len(scores) for mode, scores in sorted(eval_scores.items())},
    }


def _bullet_id(fields: dict[str, Any]) -> str | None:
    bullet_id = fields.get("bullet_id")
    if bullet_id is None:
        return None
    return str(bullet_id)


def _record_wave(fields: dict[str, Any], selected: Counter[str], scores_by_mode: dict[str, list[float]]) -> None:
    if fields.get("selected_gun"):
        selected[str(fields["selected_gun"])] += 1
    scores = fields.get("virtual_scores") if isinstance(fields.get("virtual_scores"), dict) else {}
    for mode, score in scores.items():
        scores_by_mode[str(mode)].append(float(score))


def _rates(hits: Counter[str], fired: Counter[str]) -> dict[str, float]:
    return {mode: round(hits[mode] / shots, 4) for mode, shots in sorted(fired.items()) if shots}


def _averages(scores_by_mode: dict[str, list[float]]) -> dict[str, float]:
    return {mode: round(sum(scores) / len(scores), 4) for mode, scores in sorted(scores_by_mode.items()) if scores}


def _print_summary(summary: dict[str, object]) -> None:
    for key in (
        "fired",
        "hits",
        "hit_rate",
        "wave_selected",
        "eval_selected",
        "wave_avg",
        "eval_avg",
        "wave_count",
        "eval_count",
    ):
        print(f"{key}: {summary[key]}")


if __name__ == "__main__":
    raise SystemExit(main())
