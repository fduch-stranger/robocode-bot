from bot_core.gun.config import GunDecisionContext
from bot_core.gun.context import AimContext, GunBearing, GunVisit, guess_factor_aim_bearing
from bot_core.gun.guess_factors import bin_to_guess_factor
from bot_core.gun.guns.anti_surfer.config import AntiSurferGunConfig
from bot_core.gun.guns.anti_surfer.profile import GuessFactorProfile


class AntiSurferGun:
    mode = "anti_surfer"

    def __init__(self, config: AntiSurferGunConfig) -> None:
        self.config = config
        self.profiles: dict[int, GuessFactorProfile] = {}
        self.mode_policy = config.mode_policy()

    def aim(self, context: AimContext) -> GunBearing | None:
        guess_factor = self.guess_factor(context.target.bot_id)
        if guess_factor is None:
            return None
        return GunBearing(
            self.mode,
            guess_factor_aim_bearing(context.bot, context.target, context.firepower, guess_factor),
            guess_factor=guess_factor,
            decision_context=GunDecisionContext(
                self.mode,
                {
                    "context_tags": self._context_tags(context),
                    "surfer_relevance": self._surfer_relevance(context),
                },
            ),
            metadata={
                self.mode: {
                    "context_tags": self._context_tags(context),
                    "surfer_relevance": self._surfer_relevance(context),
                    "wall_escape_balance": context.fire_context.wall_escape_balance,
                }
            },
        )

    def observe_visit(self, visit: GunVisit) -> None:
        self.record(visit.wave.target_id, visit.guess_factor)

    def visit_diagnostics(self, visit: GunVisit) -> dict[str, object]:
        context = visit.wave.fire_context
        return {
            "context_tags": context.movement_tags,
            "surfer_relevance": self._surfer_relevance_from_tags(context.movement_tags, context.wall_escape_balance),
            "wall_escape_balance": context.wall_escape_balance,
        }

    @staticmethod
    def _context_tags(context: AimContext) -> frozenset[str]:
        tags = set(context.movement_tags.intersection({"surfer", "nonlinear_mover", "adaptive_mover"}))
        if abs(context.fire_context.wall_escape_balance) >= 0.35:
            tags.add("wall_constrained")
        return frozenset(tags)

    @staticmethod
    def _surfer_relevance(context: AimContext) -> float:
        return AntiSurferGun._surfer_relevance_from_tags(context.movement_tags, context.fire_context.wall_escape_balance)

    @staticmethod
    def _surfer_relevance_from_tags(tags: frozenset[str], wall_escape_balance: float) -> float:
        score = 0.0
        if "surfer" in tags:
            score += 0.5
        if "nonlinear_mover" in tags:
            score += 0.2
        if "adaptive_mover" in tags:
            score += 0.2
        if abs(wall_escape_balance) >= 0.35:
            score += 0.1
        return min(1.0, score)

    def metrics(self, target_id: int | None = None) -> dict[str, int | float]:
        return {}

    def record(self, target_id: int, guess_factor: float) -> None:
        profile = self.profiles.setdefault(
            target_id,
            GuessFactorProfile.with_bins(self.config.guess_factor_bins),
        )
        profile.record(guess_factor, self.config.guess_factor_bins, self.config.smoothing_bins, self.config.decay)

    def guess_factor(self, target_id: int) -> float | None:
        profile = self.profiles.get(target_id)
        if profile is None or profile.effective_weight < self.config.min_samples:
            return None

        center = (self.config.guess_factor_bins - 1) / 2.0
        candidates = range(1, self.config.guess_factor_bins - 1)
        safest_index = min(
            candidates,
            key=lambda index: (
                profile.bins[index],
                abs(index - center),
            ),
        )
        return bin_to_guess_factor(safest_index, self.config.guess_factor_bins)

    def clear_round_state(self) -> None:
        return None

    def remove_target(self, target_id: int) -> None:
        return None
