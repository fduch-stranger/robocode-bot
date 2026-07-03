#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def main() -> int:
    args = _parse_args()
    events = list(_read_events(Path(args.telemetry_dir), args.bot))
    summary = summarize_events(events, post_switch_shots=args.post_switch_shots)
    _print_summary(summary)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize gun-mode telemetry from a Robocode telemetry directory.")
    parser.add_argument("telemetry_dir", help="Directory containing telemetry JSONL files.")
    parser.add_argument("--bot", default="adaptive-prime", help="Bot telemetry name to summarize.")
    parser.add_argument("--post-switch-shots", type=int, default=6, help="Real shots to track after each gun switch.")
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


@dataclass
class SwitchWindow:
    target: str
    mode: str
    turn: int | None
    score: float | None
    raw_score: float | None
    current_score: float | None
    raw_current_score: float | None
    confidence_penalty: float | None
    source_penalty: float | None
    traditional_gf_source: str | None
    visits: int | None
    shots: list[str] = field(default_factory=list)
    hits: int = 0
    accepting: bool = True


def summarize_events(events: list[dict[str, Any]], *, post_switch_shots: int = 6) -> dict[str, object]:
    fired: Counter[str] = Counter()
    hits: Counter[str] = Counter()
    shots_by_id: dict[str, str] = {}
    pending_hits_by_id: Counter[str] = Counter()
    traditional_gf_source_by_id: dict[str, str] = {}
    pending_traditional_gf_source_hits_by_id: Counter[str] = Counter()
    traditional_gf_source_fired: Counter[str] = Counter()
    traditional_gf_source_hits: Counter[str] = Counter()
    wave_selected: Counter[str] = Counter()
    eval_selected: Counter[str] = Counter()
    wave_scores: dict[str, list[float]] = defaultdict(list)
    eval_scores: dict[str, list[float]] = defaultdict(list)
    wave_selected_scores: dict[str, list[float]] = defaultdict(list)
    wave_non_selected_scores: dict[str, list[float]] = defaultdict(list)
    eval_selected_scores: dict[str, list[float]] = defaultdict(list)
    eval_non_selected_scores: dict[str, list[float]] = defaultdict(list)
    wave_scores_by_target: dict[tuple[str, str], list[float]] = defaultdict(list)
    eval_scores_by_target: dict[tuple[str, str], list[float]] = defaultdict(list)
    traditional_gf_sources: Counter[str] = Counter()
    traditional_gf_values: dict[str, list[float]] = defaultdict(list)
    traditional_gf_values_by_source: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    traditional_gf_error_values: dict[str, dict[str, list[float]]] = {
        "production": defaultdict(list),
        "production_selected": defaultdict(list),
        "eval": defaultdict(list),
        "eval_selected": defaultdict(list),
    }
    traditional_gf_error_values_by_source: dict[str, dict[str, dict[str, list[float]]]] = {
        "production": defaultdict(lambda: defaultdict(list)),
        "production_selected": defaultdict(lambda: defaultdict(list)),
        "eval": defaultdict(lambda: defaultdict(list)),
        "eval_selected": defaultdict(lambda: defaultdict(list)),
    }
    switch_windows: list[SwitchWindow] = []
    active_switch_window: int | None = None
    shot_to_switch_window: dict[str, int] = {}

    for event_index, event in enumerate(events):
        name = event.get("event")
        fields = event.get("fields") if isinstance(event.get("fields"), dict) else {}
        if name == "round.reset":
            shots_by_id.clear()
            pending_hits_by_id.clear()
            traditional_gf_source_by_id.clear()
            pending_traditional_gf_source_hits_by_id.clear()
            shot_to_switch_window.clear()
            if active_switch_window is not None:
                switch_windows[active_switch_window].accepting = False
            active_switch_window = None
        elif name == "bullet.fired" and fields.get("aim_mode"):
            mode = str(fields["aim_mode"])
            fired[mode] += 1
            bullet_id = _bullet_id(fields) or f"event:{event_index}"
            if (
                active_switch_window is not None
                and switch_windows[active_switch_window].accepting
                and switch_windows[active_switch_window].mode == mode
                and len(switch_windows[active_switch_window].shots) < post_switch_shots
            ):
                switch_windows[active_switch_window].shots.append(bullet_id)
                shot_to_switch_window[bullet_id] = active_switch_window
                if len(switch_windows[active_switch_window].shots) >= post_switch_shots:
                    switch_windows[active_switch_window].accepting = False
            shots_by_id[bullet_id] = mode
            traditional_gf_source = str(fields["traditional_gf_source"]) if fields.get("traditional_gf_source") else None
            pending_source_hits = pending_traditional_gf_source_hits_by_id.pop(bullet_id, 0)
            if mode == "traditional_gf" and traditional_gf_source is not None:
                traditional_gf_source_fired[traditional_gf_source] += 1
                traditional_gf_source_by_id[bullet_id] = traditional_gf_source
                if pending_source_hits:
                    traditional_gf_source_hits[traditional_gf_source] += pending_source_hits
            pending_hits = pending_hits_by_id.pop(bullet_id, 0)
            if pending_hits:
                hits[mode] += pending_hits
                if bullet_id in shot_to_switch_window:
                    switch_windows[shot_to_switch_window[bullet_id]].hits += pending_hits
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
            bullet_id = _bullet_id(fields)
            if bullet_id is not None and bullet_id in shot_to_switch_window:
                switch_windows[shot_to_switch_window[bullet_id]].hits += 1
            source = str(fields["traditional_gf_source"]) if fields.get("traditional_gf_source") else None
            if source is None and bullet_id is not None:
                source = traditional_gf_source_by_id.get(bullet_id)
            if mode == "traditional_gf" and source is not None:
                traditional_gf_source_hits[source] += 1
            elif bullet_id is not None and (mode is None or mode == "traditional_gf"):
                pending_traditional_gf_source_hits_by_id[bullet_id] += 1
        elif name == "gun.wave_visit":
            _record_wave(
                fields,
                wave_selected,
                wave_scores,
                wave_scores_by_target,
                wave_selected_scores,
                wave_non_selected_scores,
            )
            _record_traditional_gf_error(fields, traditional_gf_error_values["production"])
            _record_traditional_gf_source_error(fields, traditional_gf_error_values_by_source["production"])
            if fields.get("selected_gun") == "traditional_gf":
                _record_traditional_gf_error(fields, traditional_gf_error_values["production_selected"])
                _record_traditional_gf_source_error(fields, traditional_gf_error_values_by_source["production_selected"])
        elif name == "gun.eval_wave_visit":
            _record_wave(
                fields,
                eval_selected,
                eval_scores,
                eval_scores_by_target,
                eval_selected_scores,
                eval_non_selected_scores,
            )
            _record_traditional_gf_error(fields, traditional_gf_error_values["eval"])
            _record_traditional_gf_source_error(fields, traditional_gf_error_values_by_source["eval"])
            if fields.get("selected_gun") == "traditional_gf":
                _record_traditional_gf_error(fields, traditional_gf_error_values["eval_selected"])
                _record_traditional_gf_source_error(fields, traditional_gf_error_values_by_source["eval_selected"])
        elif name == "track" and fields.get("traditional_gf_source"):
            _record_traditional_gf_diagnostics(fields, traditional_gf_sources, traditional_gf_values)
            _record_traditional_gf_source_diagnostics(fields, traditional_gf_values_by_source)
        elif name == "gun.traditional_gf_profile" and fields.get("source"):
            _record_traditional_gf_diagnostics(fields, traditional_gf_sources, traditional_gf_values)
            _record_traditional_gf_source_diagnostics(fields, traditional_gf_values_by_source)
        elif name == "gun.switch_decision" and fields.get("changed"):
            if active_switch_window is not None:
                switch_windows[active_switch_window].accepting = False
            window = _switch_window_from_decision(event, fields)
            if window is not None:
                switch_windows.append(window)
                active_switch_window = len(switch_windows) - 1

    return {
        "fired": dict(fired),
        "hits": dict(hits),
        "hit_rate": _rates(hits, fired),
        "wave_selected": dict(wave_selected),
        "eval_selected": dict(eval_selected),
        "wave_avg": _averages(wave_scores),
        "eval_avg": _averages(eval_scores),
        "wave_selected_avg": _averages(wave_selected_scores),
        "wave_non_selected_avg": _averages(wave_non_selected_scores),
        "eval_selected_avg": _averages(eval_selected_scores),
        "eval_non_selected_avg": _averages(eval_non_selected_scores),
        "wave_count": {mode: len(scores) for mode, scores in sorted(wave_scores.items())},
        "eval_count": {mode: len(scores) for mode, scores in sorted(eval_scores.items())},
        "traditional_gf_diagnostics": _traditional_gf_diagnostics_summary(
            traditional_gf_sources,
            traditional_gf_values,
        ),
        "traditional_gf_diagnostics_by_source": _traditional_gf_source_diagnostics_summary(
            traditional_gf_sources,
            traditional_gf_values_by_source,
        ),
        "traditional_gf_source_real": {
            "fired": dict(traditional_gf_source_fired),
            "hits": dict(traditional_gf_source_hits),
            "hit_rate": _rates(traditional_gf_source_hits, traditional_gf_source_fired),
        },
        "traditional_gf_error": _traditional_gf_error_summary(traditional_gf_error_values),
        "traditional_gf_error_by_source": _traditional_gf_error_by_source_summary(
            traditional_gf_error_values_by_source,
        ),
        "calibration": _calibration_summary(switch_windows, wave_scores_by_target, eval_scores_by_target),
    }


def _bullet_id(fields: dict[str, Any]) -> str | None:
    bullet_id = fields.get("bullet_id")
    if bullet_id is None:
        return None
    return str(bullet_id)


def _record_wave(
    fields: dict[str, Any],
    selected: Counter[str],
    scores_by_mode: dict[str, list[float]],
    scores_by_target: dict[tuple[str, str], list[float]],
    selected_scores_by_mode: dict[str, list[float]],
    non_selected_scores_by_mode: dict[str, list[float]],
) -> None:
    selected_mode = str(fields["selected_gun"]) if fields.get("selected_gun") else None
    if selected_mode is not None:
        selected[selected_mode] += 1
    scores = fields.get("virtual_scores") if isinstance(fields.get("virtual_scores"), dict) else {}
    target = str(fields.get("target"))
    for mode, score in scores.items():
        mode_name = str(mode)
        score_value = float(score)
        scores_by_mode[mode_name].append(score_value)
        scores_by_target[(target, mode_name)].append(score_value)
        if mode_name == selected_mode:
            selected_scores_by_mode[mode_name].append(score_value)
        else:
            non_selected_scores_by_mode[mode_name].append(score_value)


def _record_traditional_gf_diagnostics(
    fields: dict[str, Any],
    sources: Counter[str],
    values: dict[str, list[float]],
) -> None:
    sources[str(fields.get("source", fields.get("traditional_gf_source")))] += 1
    for output_field, field_names in {
        "global_guess_factor": ("global_guess_factor", "traditional_gf_global"),
        "global_weight": ("global_weight", "traditional_gf_global_weight"),
        "segment_guess_factor": ("segment_guess_factor", "traditional_gf_segment"),
        "segment_weight": ("segment_weight", "traditional_gf_segment_weight"),
        "blend": ("blend", "traditional_gf_blend"),
        "raw_guess_factor": ("raw_guess_factor", "traditional_gf_raw"),
        "selected_guess_factor": ("selected_guess_factor", "traditional_gf_selected"),
        "source_bias_correction": ("source_bias_correction", "traditional_gf_source_bias"),
        "source_bias_samples": ("source_bias_samples", "traditional_gf_source_bias_samples"),
    }.items():
        value = next((_float_or_none(fields.get(field)) for field in field_names if field in fields), None)
        if value is not None:
            values[output_field].append(value)


def _record_traditional_gf_source_diagnostics(
    fields: dict[str, Any],
    values_by_source: dict[str, dict[str, list[float]]],
) -> None:
    source = fields.get("source", fields.get("traditional_gf_source"))
    if source is None:
        return
    _record_traditional_gf_diagnostics(fields, Counter(), values_by_source[str(source)])


def _record_traditional_gf_error(fields: dict[str, Any], values: dict[str, list[float]]) -> None:
    if "traditional_gf_error" not in fields:
        return
    for output_field in (
        "guess_factor",
        "traditional_gf_guess_factor",
        "traditional_gf_error",
        "traditional_gf_abs_error",
    ):
        value = _float_or_none(fields.get(output_field))
        if value is not None:
            values[output_field].append(value)


def _record_traditional_gf_source_error(
    fields: dict[str, Any],
    values_by_source: dict[str, dict[str, list[float]]],
) -> None:
    source = fields.get("traditional_gf_source")
    if source is None:
        return
    _record_traditional_gf_error(fields, values_by_source[str(source)])


def _traditional_gf_error_summary(
    grouped_values: dict[str, dict[str, list[float]]],
) -> dict[str, dict[str, float | int | None]]:
    summary: dict[str, dict[str, float | int | None]] = {}
    for group, values in grouped_values.items():
        count = len(values.get("traditional_gf_error", []))
        summary[group] = {
            "count": count,
            "avg_actual_guess_factor": _average_values(values.get("guess_factor", [])),
            "avg_aim_guess_factor": _average_values(values.get("traditional_gf_guess_factor", [])),
            "avg_error": _average_values(values.get("traditional_gf_error", [])),
            "avg_abs_error": _average_values(values.get("traditional_gf_abs_error", [])),
        }
    return summary


def _traditional_gf_error_by_source_summary(
    grouped_values: dict[str, dict[str, dict[str, list[float]]]],
) -> dict[str, dict[str, dict[str, float | int | None]]]:
    return {
        group: _traditional_gf_error_summary(dict(sorted(values_by_source.items())))
        for group, values_by_source in grouped_values.items()
    }


def _traditional_gf_diagnostics_summary(
    sources: Counter[str],
    values: dict[str, list[float]],
) -> dict[str, object]:
    return {
        "source_counts": dict(sorted(sources.items())),
        "averages": _averages(values),
        "count": sum(sources.values()),
    }


def _traditional_gf_source_diagnostics_summary(
    sources: Counter[str],
    values_by_source: dict[str, dict[str, list[float]]],
) -> dict[str, dict[str, object]]:
    return {
        source: {
            "count": sources[source],
            "averages": _averages(values_by_source[source]),
        }
        for source in sorted(sources)
    }


def _switch_window_from_decision(event: dict[str, Any], fields: dict[str, Any]) -> SwitchWindow | None:
    selected = fields.get("selected")
    if not selected:
        return None
    selected_candidate = _selected_candidate(fields, str(selected))
    score = _float_or_none(selected_candidate.get("score") if selected_candidate is not None else None)
    current_score = _float_or_none(selected_candidate.get("current_score") if selected_candidate is not None else None)
    raw_score = _float_or_none(selected_candidate.get("raw_score") if selected_candidate is not None else None)
    raw_current_score = _float_or_none(
        selected_candidate.get("raw_current_score") if selected_candidate is not None else None
    )
    confidence_penalty = _float_or_none(
        selected_candidate.get("confidence_penalty") if selected_candidate is not None else None
    )
    source_penalty = _float_or_none(
        selected_candidate.get("source_penalty") if selected_candidate is not None else None
    )
    traditional_gf_source = (
        str(selected_candidate["traditional_gf_source"])
        if selected_candidate is not None and selected_candidate.get("traditional_gf_source")
        else None
    )
    return SwitchWindow(
        target=str(fields.get("target")),
        mode=str(selected),
        turn=_int_or_none(event.get("turn")),
        score=score,
        raw_score=score if raw_score is None else raw_score,
        current_score=current_score,
        raw_current_score=current_score if raw_current_score is None else raw_current_score,
        confidence_penalty=0.0 if confidence_penalty is None else confidence_penalty,
        source_penalty=0.0 if source_penalty is None else source_penalty,
        traditional_gf_source=traditional_gf_source,
        visits=_int_or_none(selected_candidate.get("visits") if selected_candidate is not None else None),
    )


def _selected_candidate(fields: dict[str, Any], selected: str) -> dict[str, Any] | None:
    candidates = fields.get("candidates") if isinstance(fields.get("candidates"), list) else []
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate.get("mode") == selected:
            return candidate
    return None


def _calibration_summary(
    windows: list[SwitchWindow],
    wave_scores_by_target: dict[tuple[str, str], list[float]],
    eval_scores_by_target: dict[tuple[str, str], list[float]],
) -> dict[str, dict[str, dict[str, float | int | None]]]:
    grouped: dict[tuple[str, str], list[SwitchWindow]] = defaultdict(list)
    for window in windows:
        grouped[(window.target, window.mode)].append(window)

    summary: dict[str, dict[str, dict[str, float | int | None]]] = defaultdict(dict)
    for (target, mode), mode_windows in sorted(grouped.items()):
        shots = sum(len(window.shots) for window in mode_windows)
        hits = sum(window.hits for window in mode_windows)
        switch_scores = [window.score for window in mode_windows if window.score is not None]
        raw_switch_scores = [window.raw_score for window in mode_windows if window.raw_score is not None]
        confidence_penalties = [
            window.confidence_penalty for window in mode_windows if window.confidence_penalty is not None
        ]
        source_penalties = [window.source_penalty for window in mode_windows if window.source_penalty is not None]
        switch_visits = [window.visits for window in mode_windows if window.visits is not None]
        sources = Counter(
            window.traditional_gf_source for window in mode_windows if window.traditional_gf_source is not None
        )
        hit_rate = round(hits / shots, 4) if shots else 0.0
        avg_score = _average_values(switch_scores)
        avg_raw_score = _average_values(raw_switch_scores)
        production_avg = _average_values(wave_scores_by_target.get((target, mode), []))
        eval_avg = _average_values(eval_scores_by_target.get((target, mode), []))
        summary[target][mode] = {
            "switches": len(mode_windows),
            "avg_score_at_switch": avg_score,
            "avg_raw_score_at_switch": avg_raw_score,
            "avg_confidence_penalty": _average_values(confidence_penalties),
            "avg_source_penalty": _average_values(source_penalties),
            "source_counts": dict(sources),
            "avg_visits_at_switch": _average_values(switch_visits),
            "post_switch_shots": shots,
            "post_switch_hits": hits,
            "post_switch_hit_rate": hit_rate,
            "score_hit_gap": round(avg_score - hit_rate, 4) if avg_score is not None else None,
            "raw_score_hit_gap": round(avg_raw_score - hit_rate, 4) if avg_raw_score is not None else None,
            "production_wave_avg": production_avg,
            "production_wave_count": len(wave_scores_by_target.get((target, mode), [])),
            "production_hit_gap": round(production_avg - hit_rate, 4) if production_avg is not None else None,
            "eval_avg": eval_avg,
            "eval_count": len(eval_scores_by_target.get((target, mode), [])),
            "eval_hit_gap": round(eval_avg - hit_rate, 4) if eval_avg is not None else None,
        }
    return {target: dict(modes) for target, modes in sorted(summary.items())}


def _rates(hits: Counter[str], fired: Counter[str]) -> dict[str, float]:
    return {mode: round(hits[mode] / shots, 4) for mode, shots in sorted(fired.items()) if shots}


def _averages(scores_by_mode: dict[str, list[float]]) -> dict[str, float]:
    return {mode: round(sum(scores) / len(scores), 4) for mode, scores in sorted(scores_by_mode.items()) if scores}


def _average_values(values: list[float] | list[int]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _print_summary(summary: dict[str, object]) -> None:
    for key in (
        "fired",
        "hits",
        "hit_rate",
        "wave_selected",
        "eval_selected",
        "wave_avg",
        "eval_avg",
        "wave_selected_avg",
        "wave_non_selected_avg",
        "eval_selected_avg",
        "eval_non_selected_avg",
        "wave_count",
        "eval_count",
        "traditional_gf_diagnostics",
        "traditional_gf_diagnostics_by_source",
        "traditional_gf_source_real",
        "traditional_gf_error",
        "traditional_gf_error_by_source",
        "calibration",
    ):
        print(f"{key}: {summary[key]}")


if __name__ == "__main__":
    raise SystemExit(main())
