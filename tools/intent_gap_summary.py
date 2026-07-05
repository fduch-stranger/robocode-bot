#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class IntentRecord:
    path: str
    line: int
    botName: str
    round: int
    turn: int


@dataclass(frozen=True)
class IntentRoundSummary:
    path: str
    botName: str
    round: int
    intents: int
    uniqueTurns: int
    firstTurn: int | None
    lastTurn: int | None
    missingTurns: int
    missingRanges: tuple[str, ...]
    duplicateTurns: tuple[int, ...]
    longestMissingRun: int


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    summaries, warnings = summarize_paths([Path(path) for path in args.paths])
    payload = {
        "status": "gap" if has_gaps(summaries) else "ok",
        "warnings": warnings,
        "rounds": [asdict(summary) for summary in summaries],
    }
    if args.json_output:
        args.json_output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print_summary(summaries, warnings)
    if payload["status"] == "gap" and not args.warn_only:
        return 1
    if warnings and not args.warn_only:
        return 2
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize missing or duplicate bot intent turns from runner intents.jsonl diagnostics.",
    )
    parser.add_argument("paths", nargs="+", help="Path to intents.jsonl, a run directory, or a directory of runs.")
    parser.add_argument("--json-output", type=Path, help="Write structured summary JSON.")
    parser.add_argument("--warn-only", action="store_true", help="Always exit 0 after reporting gaps or warnings.")
    return parser.parse_args(argv)


def summarize_paths(paths: list[Path]) -> tuple[list[IntentRoundSummary], list[str]]:
    intent_files = discover_intent_files(paths)
    warnings: list[str] = []
    records: list[IntentRecord] = []
    for path in intent_files:
        file_records, file_warnings = read_intents(path)
        records.extend(file_records)
        warnings.extend(file_warnings)
    if not intent_files:
        warnings.append("no intents.jsonl files discovered")
    return summarize_records(records), warnings


def discover_intent_files(paths: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for path in paths:
        if path.is_file():
            files.add(path)
            continue
        direct = path / "intents.jsonl"
        if direct.is_file():
            files.add(direct)
        files.update(candidate for candidate in path.glob("**/intents.jsonl") if candidate.is_file())
    return sorted(files)


def read_intents(path: Path) -> tuple[list[IntentRecord], list[str]]:
    records: list[IntentRecord] = []
    warnings: list[str] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line_number, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                    records.append(
                        IntentRecord(
                            path=str(path),
                            line=line_number,
                            botName=str(payload["botName"]),
                            round=int(payload["round"]),
                            turn=int(payload["turn"]),
                        )
                    )
                except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exception:
                    warnings.append(f"{path}:{line_number}: invalid intent record: {exception}")
    except OSError as exception:
        warnings.append(f"{path}: failed to read intents: {exception}")
    return records, warnings


def summarize_records(records: list[IntentRecord]) -> list[IntentRoundSummary]:
    grouped: dict[tuple[str, str, int], list[IntentRecord]] = {}
    for record in records:
        grouped.setdefault((record.path, record.botName, record.round), []).append(record)

    summaries: list[IntentRoundSummary] = []
    for (path, bot_name, round_number), group in sorted(grouped.items()):
        turns = sorted(record.turn for record in group)
        unique_turns = sorted(set(turns))
        duplicates = tuple(turn for turn in unique_turns if turns.count(turn) > 1)
        missing = _missing_ranges(unique_turns)
        summaries.append(
            IntentRoundSummary(
                path=path,
                botName=bot_name,
                round=round_number,
                intents=len(turns),
                uniqueTurns=len(unique_turns),
                firstTurn=unique_turns[0] if unique_turns else None,
                lastTurn=unique_turns[-1] if unique_turns else None,
                missingTurns=sum(end - start + 1 for start, end in missing),
                missingRanges=tuple(_format_range(start, end) for start, end in missing),
                duplicateTurns=duplicates,
                longestMissingRun=max((end - start + 1 for start, end in missing), default=0),
            )
        )
    return summaries


def has_gaps(summaries: list[IntentRoundSummary]) -> bool:
    return any(summary.missingTurns or summary.duplicateTurns for summary in summaries)


def print_summary(summaries: list[IntentRoundSummary], warnings: list[str]) -> None:
    for summary in summaries:
        status = "gap" if summary.missingTurns or summary.duplicateTurns else "ok"
        details = [
            f"file={summary.path}",
            f"bot={summary.botName}",
            f"round={summary.round}",
            f"status={status}",
            f"intents={summary.intents}",
            f"turns={summary.firstTurn}-{summary.lastTurn}",
        ]
        if summary.missingRanges:
            details.append(f"missing={','.join(summary.missingRanges)}")
        if summary.duplicateTurns:
            details.append(f"duplicates={','.join(str(turn) for turn in summary.duplicateTurns)}")
        print(" ".join(details))
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def _missing_ranges(turns: list[int]) -> list[tuple[int, int]]:
    if len(turns) < 2:
        return []
    ranges: list[tuple[int, int]] = []
    previous = turns[0]
    for current in turns[1:]:
        if current > previous + 1:
            ranges.append((previous + 1, current - 1))
        previous = current
    return ranges


def _format_range(start: int, end: int) -> str:
    return str(start) if start == end else f"{start}-{end}"


if __name__ == "__main__":
    raise SystemExit(main())
