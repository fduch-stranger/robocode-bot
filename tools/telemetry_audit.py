#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bots"))

from bot_core.telemetry.schema import EXPECTED_EVASION_LABELS, event_spec, missing_required_fields, normalize_fields


def main() -> int:
    args = _parse_args()
    telemetry_dir = Path(args.telemetry_dir)
    events = list(_read_events(telemetry_dir))
    issues = _audit(events, args.require_bots)
    summary = _summary(events, issues)
    if args.json_output:
        Path(args.json_output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _print_summary(summary)
    return 1 if issues else 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Robocode bot telemetry JSONL files.")
    parser.add_argument("telemetry_dir", help="Directory containing telemetry JSONL files.")
    parser.add_argument(
        "--require-bot",
        action="append",
        default=[],
        dest="require_bots",
        help="Bot name that must have at least one telemetry event. Can be repeated.",
    )
    parser.add_argument("--json-output", help="Write structured audit JSON to this path.")
    return parser.parse_args()


def _read_events(telemetry_dir: Path) -> list[dict[str, Any]]:
    for path in sorted(telemetry_dir.glob("*.jsonl")):
        with path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as error:
                    yield {
                        "bot": path.stem,
                        "event": "telemetry.decode_error",
                        "fields": {"error": str(error)},
                        "file": path.name,
                        "line": line_number,
                    }
                    continue
                event["file"] = path.name
                event["line"] = line_number
                yield event


def _audit(events: list[dict[str, Any]], required_bots: list[str]) -> list[str]:
    issues: list[str] = []
    bots = {str(event.get("bot")) for event in events if event.get("bot")}
    shots_by_bot: dict[str, dict[str, str]] = defaultdict(dict)
    pending_hits_by_bot: dict[str, dict[str, list[tuple[str, str]]]] = defaultdict(lambda: defaultdict(list))
    pending_unattributed_by_bot: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    for bot_name in required_bots:
        if bot_name not in bots:
            issues.append(f"missing bot telemetry: {bot_name}")

    for event in events:
        name = str(event.get("event") or "")
        raw_fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        fields = normalize_fields(name, raw_fields)
        bot = str(event.get("bot") or "?")
        location = f"{event.get('file')}:{event.get('line')}"

        if name == "telemetry.decode_error":
            issues.append(f"{location} invalid json: {fields.get('error')}")
            continue

        for field in missing_required_fields(name, raw_fields):
            issues.append(f"{location} {bot} {name} missing {field}")

        if name and event_spec(name) is None:
            continue

        if name == "round.reset":
            _flush_unattributed_hits(issues, bot, pending_unattributed_by_bot[bot])
            shots_by_bot[bot].clear()
            pending_hits_by_bot[bot].clear()
            pending_unattributed_by_bot[bot].clear()
            continue

        if name == "bullet.fired" and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            aim_mode = fields.get("aim_mode")
            if aim_mode not in (None, ""):
                fired_mode = str(aim_mode)
                shots_by_bot[bot][bullet_id] = fired_mode
                pending_unattributed_by_bot[bot].pop(bullet_id, None)
                for hit_location, hit_mode in pending_hits_by_bot[bot].pop(bullet_id, []):
                    if hit_mode != fired_mode:
                        issues.append(
                            f"{hit_location} {bot} bullet.hit_bot aim_mode={hit_mode} "
                            f"does not match fired aim_mode={fired_mode}"
                        )
            continue

        if name == "bullet.hit_bot" and fields.get("bullet_id") is not None:
            bullet_id = str(fields["bullet_id"])
            hit_mode = fields.get("aim_mode")
            fired_mode = shots_by_bot[bot].get(bullet_id)
            if hit_mode in (None, "") and fired_mode in (None, ""):
                pending_unattributed_by_bot[bot][bullet_id].append(location)
            elif hit_mode not in (None, "") and fired_mode not in (None, "") and str(hit_mode) != fired_mode:
                issues.append(
                    f"{location} {bot} bullet.hit_bot aim_mode={hit_mode} does not match fired aim_mode={fired_mode}"
                )
            elif hit_mode not in (None, "") and fired_mode in (None, ""):
                pending_hits_by_bot[bot][bullet_id].append((location, str(hit_mode)))

        if name == "enemy.fire_detected":
            evasion = fields.get("evasion")
            if evasion not in EXPECTED_EVASION_LABELS:
                issues.append(f"{location} {bot} enemy.fire_detected has unexpected evasion={evasion!r}")

    for bot, pending_hits in pending_unattributed_by_bot.items():
        _flush_unattributed_hits(issues, bot, pending_hits)

    return issues


def _flush_unattributed_hits(issues: list[str], bot: str, pending_hits: dict[str, list[str]]) -> None:
    for locations in pending_hits.values():
        for location in locations:
            issues.append(f"{location} {bot} bullet.hit_bot cannot be attributed to a gun mode")


def _summary(events: list[dict[str, Any]], issues: list[str]) -> dict[str, object]:
    by_bot = Counter(str(event.get("bot") or "?") for event in events)
    by_event = Counter(str(event.get("event") or "?") for event in events)
    return {
        "events": len(events),
        "bots": dict(sorted(by_bot.items())),
        "eventCounts": dict(sorted(by_event.items())),
        "issues": issues,
    }


def _print_summary(summary: dict[str, object]) -> None:
    print(f"events: {summary['events']}")
    for bot, count in summary["bots"].items():  # type: ignore[union-attr]
        print(f"bot {bot}: {count}")
    for event, count in summary["eventCounts"].items():  # type: ignore[union-attr]
        print(f"event {event}: {count}")
    issues = summary["issues"]
    if issues:
        print("issues:")
        for issue in issues:  # type: ignore[union-attr]
            print(f"- {issue}")
    else:
        print("issues: none")


if __name__ == "__main__":
    raise SystemExit(main())
