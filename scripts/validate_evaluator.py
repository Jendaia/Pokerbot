"""Exhaustively verify category counts across every five-card combination."""
from collections import Counter
from itertools import combinations
from math import comb
from pathlib import Path
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from texasholdem import full_deck  # noqa: E402
from texasholdem.core.hand_evaluator import HAND_NAMES, _evaluate_unchecked  # noqa: E402


def main():
    expected = {
        "High Card": (comb(13, 5) - 10) * (4 ** 5 - 4),
        "One Pair": 13 * comb(4, 2) * comb(12, 3) * 4 ** 3,
        "Two Pair": comb(13, 2) * comb(4, 2) ** 2 * 11 * 4,
        "Three of a Kind": 13 * comb(4, 3) * comb(12, 2) * 4 ** 2,
        "Straight": 10 * (4 ** 5 - 4),
        "Flush": 4 * (comb(13, 5) - 10),
        "Full House": 13 * comb(4, 3) * 12 * comb(4, 2),
        "Four of a Kind": 13 * 12 * 4,
        "Straight Flush": 10 * 4,
    }
    start = perf_counter()
    actual = Counter(HAND_NAMES[_evaluate_unchecked(hand)[0]] for hand in combinations(full_deck(), 5))
    if dict(actual) != expected:
        raise AssertionError(f"Category mismatch: actual={dict(actual)}, expected={expected}")
    total = sum(actual.values())
    if total != comb(52, 5):
        raise AssertionError(f"Incorrect total: {total}")
    for name in HAND_NAMES:
        print(f"{name:<18} {actual[name]:>10,}")
    print(f"Verified all {total:,} five-card hands in {perf_counter() - start:.2f}s.")


if __name__ == "__main__":
    main()
