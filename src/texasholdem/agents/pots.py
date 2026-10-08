from __future__ import annotations


def pot_payout(contributions: dict[int, float], ranks: dict[int, tuple], hero: int) -> float:
    """Distribute main/side pots; folded players contribute but cannot win.

    Singleton layers return uncalled chips. Rake is not included.
    """
    previous, result = 0., 0.
    for level in sorted({amount for amount in contributions.values() if amount > 0}):
        contributors = [id_ for id_, amount in contributions.items() if amount >= level]
        amount = (level - previous) * len(contributors)
        eligible = [id_ for id_ in contributors if id_ in ranks]
        if eligible:
            best = max(ranks[id_] for id_ in eligible)
            winners = [id_ for id_ in eligible if ranks[id_] == best]
            if hero in winners:
                result += amount / len(winners)
        previous = level
    return result
