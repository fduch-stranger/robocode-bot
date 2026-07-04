import math


GUN_FEATURE_COUNT = 7
GUN_FEATURE_WEIGHTS = (2.0, 1.2, 1.8, 1.3, 0.8, 0.7, 0.9)


def require_gun_feature_count(features: tuple[float, ...], name: str) -> None:
    assert len(features) == GUN_FEATURE_COUNT, (
        f"{name} must contain {GUN_FEATURE_COUNT} values, got {len(features)}"
    )


def feature_distance(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    assert len(GUN_FEATURE_WEIGHTS) == GUN_FEATURE_COUNT
    require_gun_feature_count(left, "left")
    require_gun_feature_count(right, "right")
    return math.sqrt(sum(weight * (a - b) ** 2 for weight, a, b in zip(GUN_FEATURE_WEIGHTS, left, right)))


def segment_features(features: tuple[float, ...]) -> tuple[int, ...]:
    require_gun_feature_count(features, "features")
    distance, firepower, lateral_speed, advancing_speed, acceleration, velocity_change_age, wall_margin = features
    return (
        bucket(distance, 0.30, 0.55),
        bucket(firepower, 0.42, 0.62),
        bucket(lateral_speed, 0.25, 0.70),
        signed_bucket(advancing_speed, -0.25, 0.25),
        0 if abs(acceleration) >= 0.18 or velocity_change_age <= 0.15 else 1,
        bucket(wall_margin, 0.12, 0.25),
    )


def bucket(value: float, low: float, high: float) -> int:
    if value < low:
        return 0
    if value < high:
        return 1
    return 2


def signed_bucket(value: float, low: float, high: float) -> int:
    if value < low:
        return 0
    if value > high:
        return 2
    return 1


__all__ = [
    "GUN_FEATURE_COUNT",
    "GUN_FEATURE_WEIGHTS",
    "bucket",
    "feature_distance",
    "require_gun_feature_count",
    "segment_features",
    "signed_bucket",
]
