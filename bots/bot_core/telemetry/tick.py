def rounded(value: float | None, digits: int) -> float | None:
    if value is None:
        return None
    return round(value, digits)
