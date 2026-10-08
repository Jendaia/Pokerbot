"""Produce serializable observations for a future agent; no betting policy is imposed."""
import json

from texasholdem import EquityCalculator, GameState, combination_counts, parse_cards


def make_observation(state: GameState, simulations: int = 20_000, seed: int | None = None):
    result = EquityCalculator().calculate(state, simulations=simulations, seed=seed)
    return {
        "state": state.as_dict(),
        "combinations": combination_counts(state),
        "showdown": result.as_dict(),
    }


if __name__ == "__main__":
    state = GameState(parse_cards("As Kh"), parse_cards("Qs Jh 2c"), opponents=2)
    print(json.dumps(make_observation(state, seed=42), indent=2))
