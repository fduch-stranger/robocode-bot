from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

from bot_core.geometry.numeric import clamp


@dataclass(frozen=True)
class CombatProfileConfig:
    recent_turns: int = 240
    damage_deficit_margin: float = 10.0
    high_enemy_damage: float = 25.0
    min_conversion_resolutions: int = 12
    low_conversion_rate: float = 0.12
    min_enemy_fire_samples: int = 5
    weak_enemy_fire_confidence: float = 0.75


@dataclass(frozen=True)
class CombatTotals:
    own_accepted_shots: int = 0
    own_resolved_shots: int = 0
    own_hits: int = 0
    own_misses: int = 0
    own_fired_energy: float = 0.0
    own_hit_damage: float = 0.0
    enemy_inferred_shots: int = 0
    enemy_fire_confidence_sum: float = 0.0
    enemy_weighted_shots: float = 0.0
    enemy_inferred_fired_energy: float = 0.0
    enemy_weighted_fired_energy: float = 0.0
    enemy_hits: int = 0
    enemy_hit_damage: float = 0.0
    enemy_hits_matched: int = 0

    @property
    def own_hit_rate(self) -> float:
        return self.own_hits / self.own_resolved_shots if self.own_resolved_shots else 0.0

    @property
    def own_damage_per_accepted_shot(self) -> float:
        return self.own_hit_damage / self.own_accepted_shots if self.own_accepted_shots else 0.0

    @property
    def own_damage_per_fired_energy(self) -> float:
        return self.own_hit_damage / self.own_fired_energy if self.own_fired_energy else 0.0

    @property
    def own_resolution_coverage(self) -> float:
        if not self.own_accepted_shots:
            return 0.0
        return min(1.0, self.own_resolved_shots / self.own_accepted_shots)

    @property
    def enemy_average_fire_confidence(self) -> float:
        return self.enemy_fire_confidence_sum / self.enemy_inferred_shots if self.enemy_inferred_shots else 0.0

    @property
    def enemy_hit_match_coverage(self) -> float:
        return self.enemy_hits_matched / self.enemy_hits if self.enemy_hits else 0.0

    @property
    def damage_delta(self) -> float:
        return self.own_hit_damage - self.enemy_hit_damage


@dataclass(frozen=True)
class CombatProfileSnapshot:
    target_id: int | None
    turn: int
    recent_window_start: int
    recent: CombatTotals
    lifetime: CombatTotals
    tags: tuple[str, ...]


@dataclass(frozen=True)
class OwnBulletResolution:
    bullet_id: str
    target_id: int | None
    fired_turn: int
    resolved_turn: int
    power: float
    gun_mode: str | None
    source: str | None
    outcome: str
    damage: float
    previous_outcome: str | None = None


@dataclass(frozen=True)
class _OwnBullet:
    bullet_id: str
    target_id: int | None
    fired_turn: int
    power: float
    gun_mode: str | None
    source: str | None


@dataclass(frozen=True)
class _CombatEvent:
    turn: int
    kind: str
    power: float = 0.0
    damage: float = 0.0
    confidence: float = 0.0
    matched: bool = False


class _TotalsAccumulator:
    def __init__(self) -> None:
        self.own_accepted_shots = 0
        self.own_resolved_shots = 0
        self.own_hits = 0
        self.own_misses = 0
        self.own_fired_energy = 0.0
        self.own_hit_damage = 0.0
        self.enemy_inferred_shots = 0
        self.enemy_fire_confidence_sum = 0.0
        self.enemy_weighted_shots = 0.0
        self.enemy_inferred_fired_energy = 0.0
        self.enemy_weighted_fired_energy = 0.0
        self.enemy_hits = 0
        self.enemy_hit_damage = 0.0
        self.enemy_hits_matched = 0

    def add(self, event: _CombatEvent) -> None:
        if event.kind == "own_fire":
            self.own_accepted_shots += 1
            self.own_fired_energy += event.power
        elif event.kind == "own_hit":
            self.own_resolved_shots += 1
            self.own_hits += 1
            self.own_hit_damage += event.damage
        elif event.kind == "own_miss":
            self.own_resolved_shots += 1
            self.own_misses += 1
        elif event.kind == "own_miss_retract":
            self.own_resolved_shots -= 1
            self.own_misses -= 1
        elif event.kind == "enemy_fire":
            self.enemy_inferred_shots += 1
            self.enemy_fire_confidence_sum += event.confidence
            self.enemy_weighted_shots += event.confidence
            self.enemy_inferred_fired_energy += event.power
            self.enemy_weighted_fired_energy += event.power * event.confidence
        elif event.kind == "enemy_hit":
            self.enemy_hits += 1
            self.enemy_hit_damage += event.damage
            if event.matched:
                self.enemy_hits_matched += 1

    def snapshot(self) -> CombatTotals:
        return CombatTotals(
            own_accepted_shots=self.own_accepted_shots,
            own_resolved_shots=self.own_resolved_shots,
            own_hits=self.own_hits,
            own_misses=self.own_misses,
            own_fired_energy=self.own_fired_energy,
            own_hit_damage=self.own_hit_damage,
            enemy_inferred_shots=self.enemy_inferred_shots,
            enemy_fire_confidence_sum=self.enemy_fire_confidence_sum,
            enemy_weighted_shots=self.enemy_weighted_shots,
            enemy_inferred_fired_energy=self.enemy_inferred_fired_energy,
            enemy_weighted_fired_energy=self.enemy_weighted_fired_energy,
            enemy_hits=self.enemy_hits,
            enemy_hit_damage=self.enemy_hit_damage,
            enemy_hits_matched=self.enemy_hits_matched,
        )


class CombatProfileStore:
    def __init__(self, config: CombatProfileConfig | None = None) -> None:
        self.config = config or CombatProfileConfig()
        self._lifetime: dict[int | None, _TotalsAccumulator] = defaultdict(_TotalsAccumulator)
        self._recent_events: dict[int | None, deque[_CombatEvent]] = defaultdict(deque)
        self._own_bullets: dict[str, _OwnBullet] = {}
        self._resolved_own_bullets: dict[str, OwnBulletResolution] = {}
        self._closed_round_turn: int | None = None

    def record_own_fire(
        self,
        turn: int,
        target_id: int | None,
        bullet_id: object,
        power: float,
        *,
        gun_mode: str | None = None,
        source: str | None = None,
    ) -> bool:
        key = _bullet_key(bullet_id)
        if key is None or key in self._own_bullets or key in self._resolved_own_bullets:
            return False
        bullet = _OwnBullet(key, target_id, turn, power, gun_mode, source)
        self._own_bullets[key] = bullet
        self._record(target_id, _CombatEvent(turn, "own_fire", power=power))
        return True

    def resolve_own_bullet(
        self,
        turn: int,
        bullet_id: object,
        outcome: str,
        *,
        damage: float = 0.0,
    ) -> OwnBulletResolution | None:
        key = _bullet_key(bullet_id)
        bullet = self._own_bullets.pop(key, None) if key is not None else None
        if bullet is None:
            previous = self._resolved_own_bullets.get(key) if key is not None else None
            if (
                previous is None
                or outcome != "hit_bot"
                or previous.outcome != "round_end"
            ):
                return None
            self._record(previous.target_id, _CombatEvent(turn, "own_miss_retract", power=previous.power))
            self._record(previous.target_id, _CombatEvent(turn, "own_hit", power=previous.power, damage=damage))
            corrected = OwnBulletResolution(
                bullet_id=previous.bullet_id,
                target_id=previous.target_id,
                fired_turn=previous.fired_turn,
                resolved_turn=turn,
                power=previous.power,
                gun_mode=previous.gun_mode,
                source=previous.source,
                outcome=outcome,
                damage=damage,
                previous_outcome=previous.outcome,
            )
            self._resolved_own_bullets[corrected.bullet_id] = corrected
            return corrected
        hit = outcome == "hit_bot"
        event = _CombatEvent(turn, "own_hit" if hit else "own_miss", power=bullet.power, damage=damage)
        self._record(bullet.target_id, event)
        resolution = OwnBulletResolution(
            bullet_id=bullet.bullet_id,
            target_id=bullet.target_id,
            fired_turn=bullet.fired_turn,
            resolved_turn=turn,
            power=bullet.power,
            gun_mode=bullet.gun_mode,
            source=bullet.source,
            outcome=outcome,
            damage=damage,
        )
        self._resolved_own_bullets[resolution.bullet_id] = resolution
        return resolution

    def record_enemy_fire(
        self,
        turn: int,
        target_id: int,
        power: float,
        confidence: float,
    ) -> None:
        self._record(
            target_id,
            _CombatEvent(
                turn,
                "enemy_fire",
                power=power,
                confidence=clamp(confidence, 0.0, 1.0),
            ),
        )

    def record_enemy_hit(
        self,
        turn: int,
        target_id: int,
        power: float,
        damage: float,
        *,
        matched_wave: bool,
    ) -> None:
        self._record(
            target_id,
            _CombatEvent(turn, "enemy_hit", power=power, damage=damage, matched=matched_wave),
        )

    def snapshot(self, target_id: int | None, turn: int) -> CombatProfileSnapshot:
        window_start = max(0, turn - max(1, self.config.recent_turns) + 1)
        recent = _TotalsAccumulator()
        events = self._recent_events.get(target_id)
        if events is not None:
            while events and events[0].turn < window_start:
                events.popleft()
            for event in events:
                if event.turn <= turn:
                    recent.add(event)
        lifetime = self._lifetime.get(target_id)
        recent_totals = recent.snapshot()
        lifetime_totals = lifetime.snapshot() if lifetime is not None else CombatTotals()
        return CombatProfileSnapshot(
            target_id=target_id,
            turn=turn,
            recent_window_start=window_start,
            recent=recent_totals,
            lifetime=lifetime_totals,
            tags=self._tags(recent_totals),
        )

    def close_round(self, turn: int) -> tuple[OwnBulletResolution, ...]:
        self._closed_round_turn = turn
        resolutions: list[OwnBulletResolution] = []
        for bullet_id in tuple(self._own_bullets):
            resolution = self.resolve_own_bullet(turn, bullet_id, "round_end")
            if resolution is not None:
                resolutions.append(resolution)
        return tuple(resolutions)

    def clear_round_state(self) -> None:
        self._own_bullets.clear()
        self._resolved_own_bullets.clear()
        self._recent_events.clear()
        self._closed_round_turn = None

    def clear_battle_state(self) -> None:
        self._lifetime.clear()
        self.clear_round_state()

    @property
    def pending_own_bullets(self) -> int:
        return len(self._own_bullets)

    @property
    def round_closed_turn(self) -> int | None:
        return self._closed_round_turn

    @property
    def target_ids(self) -> tuple[int | None, ...]:
        attributed = tuple(sorted(target_id for target_id in self._lifetime if target_id is not None))
        return attributed + ((None,) if None in self._lifetime else ())

    def _record(self, target_id: int | None, event: _CombatEvent) -> None:
        self._lifetime[target_id].add(event)
        self._recent_events[target_id].append(event)

    def _tags(self, recent: CombatTotals) -> tuple[str, ...]:
        tags: list[str] = []
        if recent.enemy_hit_damage > recent.own_hit_damage + self.config.damage_deficit_margin:
            tags.append("damage_deficit")
        if (
            recent.own_resolved_shots >= self.config.min_conversion_resolutions
            and recent.own_hit_rate < self.config.low_conversion_rate
        ):
            tags.append("low_our_conversion")
        if recent.enemy_hit_damage >= self.config.high_enemy_damage:
            tags.append("high_enemy_damage")
        if (
            recent.enemy_inferred_shots >= self.config.min_enemy_fire_samples
            and recent.enemy_average_fire_confidence < self.config.weak_enemy_fire_confidence
        ):
            tags.append("enemy_fire_detection_weak")
        return tuple(tags)


def inferred_fire_confidence(scan_gap: int) -> float:
    """Confidence in a classified energy-drop shot, based on observation age."""
    return clamp(1.0 - 0.15 * max(0, scan_gap - 1), 0.55, 1.0)


def _bullet_key(bullet_id: object) -> str | None:
    if bullet_id is None:
        return None
    if isinstance(bullet_id, (int, str)):
        return str(bullet_id)
    return None
