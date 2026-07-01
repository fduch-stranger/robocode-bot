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
    _print_summary(events, issues)
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

        if name == "bullet.fired" and fields.get("bullet_id") is not None:
            aim_mode = fields.get("aim_mode")
            if aim_mode not in (None, ""):
                shots_by_bot[bot][str(fields["bullet_id"])] = str(aim_mode)

        if name == "bullet.hit_bot" and fields.get("bullet_id") is not None:
            hit_mode = fields.get("aim_mode")
            fired_mode = shots_by_bot[bot].get(str(fields["bullet_id"]))
            if hit_mode in (None, "") and fired_mode in (None, ""):
                issues.append(f"{location} {bot} bullet.hit_bot cannot be attributed to a gun mode")
            elif hit_mode not in (None, "") and fired_mode not in (None, "") and str(hit_mode) != fired_mode:
                issues.append(
                    f"{location} {bot} bullet.hit_bot aim_mode={hit_mode} does not match fired aim_mode={fired_mode}"
                )

        if name == "enemy.fire_detected":
            evasion = fields.get("evasion")
            if evasion not in EXPECTED_EVASION_LABELS:
                issues.append(f"{location} {bot} enemy.fire_detected has unexpected evasion={evasion!r}")

    return issues


def _print_summary(events: list[dict[str, Any]], issues: list[str]) -> None:
    by_bot = Counter(str(event.get("bot") or "?") for event in events)
    by_event = Counter(str(event.get("event") or "?") for event in events)
    print(f"events: {len(events)}")
    for bot, count in sorted(by_bot.items()):
        print(f"bot {bot}: {count}")
    for event, count in sorted(by_event.items()):
        print(f"event {event}: {count}")
    if issues:
        print("issues:")
        for issue in issues:
            print(f"- {issue}")
    else:
        print("issues: none")


if __name__ == "__main__":
    raise SystemExit(main())
