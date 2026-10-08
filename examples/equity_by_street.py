"""Run with PYTHONPATH=src python3 examples/equity_by_street.py."""
from texasholdem import EquityCalculator, GameState, parse_cards


def main():
    hero = parse_cards("As Ah")
    board = parse_cards("Ks 7d 2c 9h 3s")
    calculator = EquityCalculator()
    print(f"{'Street':<10} {'Method':<13} {'Possible deals':>15} {'Win':>9} {'Equity':>9}")
    for size in (0, 3, 4, 5):
        state = GameState(hero, board[:size])
        result = calculator.calculate(state, simulations=20_000, seed=42)
        print(f"{state.street:<10} {result.mode:<13} {result.total_possible:>15,} "
              f"{result.win_percentage:>8.2f}% {result.equity_percentage:>8.2f}%")


if __name__ == "__main__":
    main()
