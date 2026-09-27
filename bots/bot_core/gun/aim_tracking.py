from bot_core.geometry.angles import relative_bearing


def offset_tracking_bearing(last_aim_bearing: float, last_direct_bearing: float, direct_bearing: float) -> float:
    """Keep the last aim's angular offset from the direct bearing, applied to the current direct bearing."""
    return direct_bearing + relative_bearing(last_aim_bearing, last_direct_bearing)
