#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class NumberStats:
    count: int
    min: float | None
    max: float | None
    avg: float | None
    p50: float | None
    p95: float | None


@dataclass(frozen=True)
class RadarSummary:
    bot: str | None
    telemetryFiles: int
    events: int
    trackTurns: int
    freshTargetTurns: int
    staleTargetTurns: int
    lostTargetTurns: int
    freshTargetRate: float
    staleTargetRate: float
    lostTargetRate: float
    targetAge: NumberStats
    radarAge: NumberStats
    radarModes: dict[str, int]
    holdReasons: dict[str, int]
    staleHoldCount: int
    shots: int
    freshShots: int
    staleShots: int
    lostShots: int
    unknownAgeShots: int
    hits: int
    freshShotHits: int
    staleShotHits: int
    lostShotHits: int
    unknownAgeShotHits: int
    hitRate: float
    freshShotHitRate: float
    staleShotHitRate: float
    lostShotHitRate: float
    scanReacquiredCount: int
    scanReacquiredPreviousAge: NumberStats
    targetReacquireCount: int
    targetReacquireAge: NumberStats
    targetDropLostCount: int
    targetDropLostAge: NumberStats
    targetStaleCount: int
    enemyFireDetectedScanGap: NumberStats
    enemyEnergyDropIgnoredScanGap: NumberStats
    warnings: tuple[str, ...]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    events, warnings, file_count = read_events([Path(path) for path in args.paths], args.bot)
    summary = summarize_events(
        events,
        bot=args.bot,
        telemetry_files=file_count,
        warnings=warnings,
        fresh_age=args.fresh_age,
        stale_age=args.stale_age,
        lost_age=args.lost_age,
    )
    payload = asdict(summary)
    if args.json_output:
        args.json_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print_summary(summary)
    return 0 if not warnings else 2


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize radar freshness and tracking efficiency from telemetry JSONL.")
    parser.add_argument("paths", nargs="+", help="Telemetry JSONL file, telemetry directory, run directory, or directory of runs.")
    parser.add_argument("--bot", help="Only summarize events for this telemetry bot name.")
    parser.add_argument("--fresh-age", type=int, default=1, help="Target age treated as fresh. Default: 1.")
    parser.add_argument("--stale-age", type=int, default=2, help="Target age above this is stale. Default: 2.")
    parser.add_argument("--lost-age", type=int, default=4, help="Target age above this is lost. Default: 4.")
    parser.add_argument("--json-output", type=Path, help="Write structured summary JSON.")
    return parser.parse_args(argv)


def read_events(paths: list[Path], bot: str | None = None) -> tuple[list[dict[str, Any]], list[str], int]:
    files = discover_telemetry_files(paths)
    warnings: list[str] = []
    events: list[dict[str, Any]] = []
    if not files:
        warnings.append("no telemetry JSONL files discovered")
    for path in files:
        try:
            with path.open(encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, start=1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError as exception:
                        warnings.append(f"{path}:{line_number}: invalid JSON: {exception}")
                        continue
                    if bot is not None and event.get("bot") != bot:
                        continue
                    events.append(event)
        except OSError as exception:
            warnings.append(f"{path}: failed to read telemetry: {exception}")
    return events, warnings, len(files)


def discover_telemetry_files(paths: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file() and path.suffix == ".jsonl":
            files.add(path)
            continue
        if not path.is_dir():
            continue
        files.update(candidate for candidate in path.glob("*.jsonl") if candidate.is_file())
        telemetry_dir = path / "telemetry"
        if telemetry_dir.is_dir():
            files.update(candidate for candidate in telemetry_dir.glob("*.jsonl") if candidate.is_file())
        files.update(candidate for candidate in path.glob("**/telemetry/*.jsonl") if candidate.is_file())
    return sorted(files)


def summarize_events(
    events: list[dict[str, Any]],
    *,
    bot: str | None = None,
    telemetry_files: int = 0,
    warnings: list[str] | None = None,
    fresh_age: int = 1,
    stale_age: int = 2,
    lost_age: int = 4,
) -> RadarSummary:
    summary_warnings = list(warnings or [])
    target_ages: list[float] = []
    radar_ages: list[float] = []
    radar_modes: Counter[str] = Counter()
    hold_reasons: Counter[str] = Counter()
    shot_age_by_bullet: dict[str, float | None] = {}
    shot_ages: list[float | None] = []
    hit_ages: list[float | None] = []
    scan_reacquired_previous_ages: list[float] = []
    target_reacquire_ages: list[float] = []
    target_drop_lost_ages: list[float] = []
    enemy_fire_scan_gaps: list[float] = []
    enemy_ignored_scan_gaps: list[float] = []
    target_stale_count = 0

    for index, event in enumerate(events):
        name = str(event.get("event", ""))
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        if name == "track":
            age = _number(fields.get("age"))
            if age is not None:
                target_ages.append(age)
            radar_age = _number(fields.get("radar_age"))
            if radar_age is not None:
                radar_ages.append(radar_age)
            if fields.get("radar_mode") is not None:
                radar_modes[str(fields["radar_mode"])] += 1
            if fields.get("hold_reason") is not None:
                hold_reasons[str(fields["hold_reason"])] += 1
        elif name == "bullet.fired":
            age = _number(fields.get("target_age"))
            shot_ages.append(age)
            bullet_id = _bullet_id(fields) or f"event:{index}"
            shot_age_by_bullet[bullet_id] = age
        elif name == "bullet.hit_bot":
            bullet_id = _bullet_id(fields)
            hit_ages.append(shot_age_by_bullet.get(bullet_id) if bullet_id is not None else None)
        elif name == "scan.reacquired":
            _append_number(scan_reacquired_previous_ages, fields.get("previous_age"))
        elif name == "target.reacquire":
            _append_number(target_reacquire_ages, fields.get("age"))
        elif name == "target.drop_lost":
            _append_number(target_drop_lost_ages, fields.get("age"))
        elif name == "target.stale":
            target_stale_count += 1
        elif name == "enemy.fire_detected":
            _append_number(enemy_fire_scan_gaps, fields.get("scan_gap"))
        elif name == "enemy.energy_drop_ignored":
            _append_number(enemy_ignored_scan_gaps, fields.get("scan_gap"))

    fresh_turns = sum(1 for age in target_ages if age <= fresh_age)
    stale_turns = sum(1 for age in target_ages if age > stale_age)
    lost_turns = sum(1 for age in target_ages if age > lost_age)
    fresh_shots = _count_age(shot_ages, lambda age: age <= fresh_age)
    stale_shots = _count_age(shot_ages, lambda age: age > stale_age)
    lost_shots = _count_age(shot_ages, lambda age: age > lost_age)
    fresh_hits = _count_age(hit_ages, lambda age: age <= fresh_age)
    stale_hits = _count_age(hit_ages, lambda age: age > stale_age)
    lost_hits = _count_age(hit_ages, lambda age: age > lost_age)
    unknown_shots = sum(1 for age in shot_ages if age is None)
    unknown_hits = sum(1 for age in hit_ages if age is None)
    if events and not target_ages:
        summary_warnings.append("no track events found; target freshness rates and radar mode distribution are unavailable")

    return RadarSummary(
        bot=bot,
        telemetryFiles=telemetry_files,
        events=len(events),
        trackTurns=len(target_ages),
        freshTargetTurns=fresh_turns,
        staleTargetTurns=stale_turns,
        lostTargetTurns=lost_turns,
        freshTargetRate=_rate(fresh_turns, len(target_ages)),
        staleTargetRate=_rate(stale_turns, len(target_ages)),
        lostTargetRate=_rate(lost_turns, len(target_ages)),
        targetAge=_stats(target_ages),
        radarAge=_stats(radar_ages),
        radarModes=dict(sorted(radar_modes.items())),
        holdReasons=dict(sorted(hold_reasons.items())),
        staleHoldCount=hold_reasons.get("stale", 0),
        shots=len(shot_ages),
        freshShots=fresh_shots,
        staleShots=stale_shots,
        lostShots=lost_shots,
        unknownAgeShots=unknown_shots,
        hits=len(hit_ages),
        freshShotHits=fresh_hits,
        staleShotHits=stale_hits,
        lostShotHits=lost_hits,
        unknownAgeShotHits=unknown_hits,
        hitRate=_rate(len(hit_ages), len(shot_ages)),
        freshShotHitRate=_rate(fresh_hits, fresh_shots),
        staleShotHitRate=_rate(stale_hits, stale_shots),
        lostShotHitRate=_rate(lost_hits, lost_shots),
        scanReacquiredCount=len(scan_reacquired_previous_ages),
        scanReacquiredPreviousAge=_stats(scan_reacquired_previous_ages),
        targetReacquireCount=len(target_reacquire_ages),
        targetReacquireAge=_stats(target_reacquire_ages),
        targetDropLostCount=len(target_drop_lost_ages),
        targetDropLostAge=_stats(target_drop_lost_ages),
        targetStaleCount=target_stale_count,
        enemyFireDetectedScanGap=_stats(enemy_fire_scan_gaps),
        enemyEnergyDropIgnoredScanGap=_stats(enemy_ignored_scan_gaps),
        warnings=tuple(summary_warnings),
    )


def print_summary(summary: RadarSummary) -> None:
    bot = f" bot={summary.bot}" if summary.bot else ""
    print(
        "radar_efficiency"
        f"{bot} files={summary.telemetryFiles} events={summary.events} track_turns={summary.trackTurns}"
    )
    print(
        "freshness "
        f"fresh={summary.freshTargetTurns}/{summary.trackTurns} ({_percent(summary.freshTargetRate)}) "
        f"stale={summary.staleTargetTurns}/{summary.trackTurns} ({_percent(summary.staleTargetRate)}) "
        f"lost={summary.lostTargetTurns}/{summary.trackTurns} ({_percent(summary.lostTargetRate)}) "
        f"age_p95={_format_number(summary.targetAge.p95)} age_max={_format_number(summary.targetAge.max)}"
    )
    print(
        "fire "
        f"shots={summary.shots} hits={summary.hits} hit_rate={_percent(summary.hitRate)} "
        f"fresh_shots={summary.freshShots} fresh_hit_rate={_percent(summary.freshShotHitRate)} "
        f"stale_shots={summary.staleShots} stale_hit_rate={_percent(summary.staleShotHitRate)} "
        f"lost_shots={summary.lostShots} lost_hit_rate={_percent(summary.lostShotHitRate)}"
    )
    print(
        "reacquire "
        f"scan_reacquired={summary.scanReacquiredCount} previous_age_p95={_format_number(summary.scanReacquiredPreviousAge.p95)} "
        f"target_reacquire={summary.targetReacquireCount} drop_lost={summary.targetDropLostCount} target_stale={summary.targetStaleCount}"
    )
    print(f"radar_modes {_format_counter(summary.radarModes)}")
    print(f"hold_reasons {_format_counter(summary.holdReasons)}")
    print(
        "enemy_fire_scan_gap "
        f"detected_p95={_format_number(summary.enemyFireDetectedScanGap.p95)} "
        f"ignored_p95={_format_number(summary.enemyEnergyDropIgnoredScanGap.p95)}"
    )
    for warning in summary.warnings:
        print(f"warning: {warning}")


def _append_number(values: list[float], value: object) -> None:
    number = _number(value)
    if number is not None:
        values.append(number)


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _bullet_id(fields: dict[str, Any]) -> str | None:
    for key in ("bullet_id", "bulletId", "id"):
        value = fields.get(key)
        if value is not None:
            return str(value)
    return None


def _stats(values: list[float]) -> NumberStats:
    if not values:
        return NumberStats(0, None, None, None, None, None)
    ordered = sorted(values)
    return NumberStats(
        count=len(ordered),
        min=ordered[0],
        max=ordered[-1],
        avg=sum(ordered) / len(ordered),
        p50=_percentile(ordered, 0.50),
        p95=_percentile(ordered, 0.95),
    )


def _percentile(ordered_values: list[float], percentile: float) -> float:
    if len(ordered_values) == 1:
        return ordered_values[0]
    index = round((len(ordered_values) - 1) * percentile)
    return ordered_values[index]


def _count_age(values: list[float | None], predicate: Any) -> int:
    return sum(1 for value in values if value is not None and predicate(value))


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _percent(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_number(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value.is_integer():
        return str(int(value))
    return f"{value:.2f}"


def _format_counter(values: dict[str, int]) -> str:
    if not values:
        return "none"
    return " ".join(f"{key}={value}" for key, value in sorted(values.items()))


if __name__ == "__main__":
    raise SystemExit(main())
