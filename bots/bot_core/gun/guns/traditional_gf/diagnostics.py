from dataclasses import dataclass


@dataclass(frozen=True)
class TraditionalGfDiagnostics:
    global_guess_factor: float
    global_weight: float
    segment_guess_factor: float | None = None
    segment_weight: float = 0.0
    blend: float = 0.0
    raw_guess_factor: float | None = None
    selected_guess_factor: float | None = None
    source: str = "global"
    source_bias_correction: float = 0.0
    source_bias_samples: int = 0


__all__ = ["TraditionalGfDiagnostics"]
