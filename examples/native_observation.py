"""Export one live observation and optional showdown equity for an AI consumer."""

import json

from texasholdem import EquityCalculator
from texasholdem.analyzers.native import PokeristReader


def main():
    with PokeristReader() as reader:
        observation = reader.read()
    result = observation.as_dict()
    try:
        state = observation.to_game_state()
    except ValueError as error:
        result["equity_unavailable_reason"] = str(error)
    else:
        result["equity"] = EquityCalculator().calculate(state, simulations=10_000, seed=42).as_dict()
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
