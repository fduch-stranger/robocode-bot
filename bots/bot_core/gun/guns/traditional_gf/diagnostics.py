from dataclasses import dataclass


@dataclass(frozen=True)
class TraditionalGfDiagnostics:
    global_guess_factor: float
    global_weight: float
    segment_guess_factor: float | None = None
    segment_weight: float = 0.0
    blend: float = 0.0
    selected_guess_factor: float | None = None
    source: str = "global"
    profile_key: tuple[int, ...] = ()


__all__ = ["TraditionalGfDiagnostics"]
