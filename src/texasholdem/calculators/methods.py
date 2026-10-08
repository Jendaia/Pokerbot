from __future__ import annotations

DEFAULT_MAX_EXACT_TRIALS = 200_000


def select_method(
    mode: str,
    total: int,
    max_exact_trials: int,
    simulations: int,
    allow_large_exact: bool,
) -> str:
    if mode not in {"auto", "exact", "monte-carlo"}:
        raise ValueError("mode must be auto, exact, or monte-carlo")
    if type(simulations) is not int or simulations < 1:
        raise ValueError("simulations must be a positive integer")
    if mode == "auto":
        return "exact" if total <= max_exact_trials else "monte-carlo"
    if mode == "exact" and total > max_exact_trials and not allow_large_exact:
        raise ValueError(
            f"Exact calculation requires {total:,} trials, exceeding the "
            f"{max_exact_trials:,} trial limit. Use allow_large_exact=True "
            "(CLI: --allow-large-exact), increase max_exact_trials, or use monte-carlo."
        )
    return mode


def validate_exact_limit(value: int) -> None:
    if type(value) is not int or value < 1:
        raise ValueError("max_exact_trials must be a positive integer")
