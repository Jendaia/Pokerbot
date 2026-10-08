"""Terminal chip utility, separate from the algorithm used to estimate it."""

LABELS = {"profit": "Chip EV", "balanced": "Balanced", "conservative": "Preserve stack"}


def utility(chips: float, stack: float, objective: str) -> float:
    # A downside penalty scaled by current table wealth, not a fixed currency
    # threshold. Both utilities are increasing in winnings; profit is linear.
    if objective == "conservative":
        return chips - min(0., chips) ** 2 / (2 * max(1., stack))
    return chips


def score(mean: float, standard_error: float, objective: str) -> float:
    # The profit objective explicitly optimizes estimated expected chips.
    # Other profiles also discount simulation uncertainty (not model error).
    margin = {"profit": 0., "balanced": 1., "conservative": 2.}[objective]
    return mean - margin * standard_error
