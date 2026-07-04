from bot_core.geometry.numeric import clamp


def guess_factor_to_bin(guess_factor: float, bins: int) -> int:
    return round((clamp(guess_factor, -1.0, 1.0) + 1.0) * (bins - 1) / 2.0)


def bin_to_guess_factor(index: int, bins: int) -> float:
    return -1.0 + 2.0 * index / (bins - 1)


__all__ = ["bin_to_guess_factor", "guess_factor_to_bin"]
