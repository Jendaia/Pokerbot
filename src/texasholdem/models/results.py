from __future__ import annotations

from dataclasses import dataclass, field
from math import log, sqrt

from ..core.hand_evaluator import HAND_NAMES


@dataclass(slots=True)
class EquityResult:
    mode: str
    total_possible: int
    trials: int = 0
    wins: int = 0
    ties: int = 0
    losses: int = 0
    equity_share: float = 0.0
    equity_squared_share: float = 0.0
    hand_categories: dict[str, int] = field(default_factory=dict)

    @property
    def win_percentage(self) -> float:
        return self._percentage(self.wins)

    @property
    def tie_percentage(self) -> float:
        return self._percentage(self.ties)

    @property
    def loss_percentage(self) -> float:
        return self._percentage(self.losses)

    @property
    def equity_percentage(self) -> float:
        return 100.0 * self.equity_share / self.trials if self.trials else 0.0

    @property
    def equity_standard_error_percentage(self) -> float | None:
        if self.mode == "exact":
            return 0.0
        if self.trials < 2:
            return None
        variance = max(0.0, (
            self.equity_squared_share - self.equity_share ** 2 / self.trials
        ) / (self.trials - 1))
        return 100.0 * sqrt(variance / self.trials)

    def _interval(self, percentage: float) -> tuple[float, float]:
        if self.mode == "exact":
            return percentage, percentage
        if not self.trials:
            return 0.0, 100.0
        # Hoeffding's inequality for independent bounded [0, 1] pot shares.
        # Unlike a normal interval, this stays meaningful after zero observed losses.
        margin = 100.0 * sqrt(log(2.0 / 0.05) / (2.0 * self.trials))
        return max(0.0, percentage - margin), min(100.0, percentage + margin)

    @property
    def equity_95_interval(self) -> tuple[float, float]:
        return self._interval(self.equity_percentage)

    @property
    def win_95_interval(self) -> tuple[float, float]:
        return self._interval(self.win_percentage)

    def category_percentages(self) -> dict[str, float]:
        return {name: self._percentage(self.hand_categories.get(name, 0)) for name in HAND_NAMES}

    def _percentage(self, count: int) -> float:
        return 100.0 * count / self.trials if self.trials else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "is_exact": self.mode == "exact",
            "total_possible": self.total_possible,
            "trials": self.trials,
            "wins": self.wins,
            "ties": self.ties,
            "losses": self.losses,
            "win_percentage": self.win_percentage,
            "tie_percentage": self.tie_percentage,
            "loss_percentage": self.loss_percentage,
            "equity_percentage": self.equity_percentage,
            "equity_standard_error_percentage": self.equity_standard_error_percentage,
            "equity_95_interval": self.equity_95_interval,
            "win_95_interval": self.win_95_interval,
            "confidence_method": "exact" if self.mode == "exact" else "hoeffding",
            "hand_categories": self.category_percentages(),
            "hand_category_counts": {name: self.hand_categories.get(name, 0) for name in HAND_NAMES},
            "opponent_model": "uniform legal completions of each opponent holding",
        }


@dataclass(slots=True)
class HandDistributionResult:
    """Hero's final hand categories over possible board runouts, independent of deal count."""

    mode: str
    total_possible: int
    trials: int
    hand_categories: dict[str, int]

    def category_percentages(self) -> dict[str, float]:
        return {
            name: 100.0 * self.hand_categories.get(name, 0) / self.trials
            for name in HAND_NAMES
        }

    def as_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "is_exact": self.mode == "exact",
            "total_possible_board_runouts": self.total_possible,
            "trials": self.trials,
            "hand_categories": self.category_percentages(),
            "hand_category_counts": {name: self.hand_categories.get(name, 0) for name in HAND_NAMES},
        }
