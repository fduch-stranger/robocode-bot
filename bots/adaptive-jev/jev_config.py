"""Flags and tuning for the Jev advisor layer. See docs/plans/jev-advisor-bot.md."""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import asdict, dataclass

PHASES = ("style", "surf")
MODES = ("shadow", "active")
TRANSPORTS = ("jev", "stub")


def _flag(values: Mapping[str, str], name: str, default: bool) -> bool:
    raw = values.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _choice(values: Mapping[str, str], name: str, options: tuple[str, ...], default: str) -> str:
    raw = (values.get(name) or "").strip().lower()
    return raw if raw in options else default


def _number(values: Mapping[str, str], name: str, default: float, minimum: float) -> float:
    try:
        return max(minimum, float((values.get(name) or "").strip()))
    except ValueError:
        return default


@dataclass(frozen=True)
class JevConfig:
    enabled: bool = False
    mode: str = "shadow"
    phases: tuple[str, ...] = ("style",)
    transport: str = "jev"
    stub_mode: str = "random"
    stub_latency_ms: float = 250.0
    max_queue: int = 2
    workers: int = 2
    max_rps: float = 10.0
    # Phase 1: first style question once this many scans are in, then every interval.
    style_first_samples: int = 120
    style_interval_samples: int = 200
    # Phase 2 (active mode only): answers below this confidence, or older than the age limit, are ignored.
    surf_min_confidence: float = 0.5
    surf_max_age_turns: int = 20
    surf_danger_factor: float = 1.15

    @property
    def active(self) -> bool:
        return self.mode == "active"

    def phase_enabled(self, phase: str) -> bool:
        return phase in self.phases

    def status_fields(self) -> dict[str, object]:
        fields = asdict(self)
        fields["phases"] = ",".join(self.phases)
        return {f"jev_{name}": value for name, value in fields.items()}


def load_jev_config(env: Mapping[str, str] | None = None) -> JevConfig:
    values = os.environ if env is None else env
    raw_phases = (values.get("ROBOCODE_JEV_PHASES") or "style").lower().replace(" ", "")
    phases = tuple(phase for phase in PHASES if phase in raw_phases.split(","))
    return JevConfig(
        enabled=_flag(values, "ROBOCODE_JEV_ENABLED", False),
        mode=_choice(values, "ROBOCODE_JEV_MODE", MODES, "shadow"),
        phases=phases or ("style",),
        transport=_choice(values, "ROBOCODE_JEV_TRANSPORT", TRANSPORTS, "jev"),
        stub_mode=_choice(values, "ROBOCODE_JEV_STUB_MODE", ("fixed", "random"), "random"),
        stub_latency_ms=_number(values, "ROBOCODE_JEV_STUB_LATENCY_MS", 250.0, 0.0),
        max_queue=int(_number(values, "ROBOCODE_JEV_MAX_INFLIGHT", 2, 1)),
        workers=int(_number(values, "ROBOCODE_JEV_WORKERS", 2, 1)),
        max_rps=_number(values, "ROBOCODE_JEV_MAX_RPS", 10.0, 0.1),
    )
