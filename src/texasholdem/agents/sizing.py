"""Stack/pot-aware candidates snapped to the client's exact selectable bets."""
from .models import Action


def native_actions(frame, tracker, settings):
    o = frame.observation
    hero = next(p for p in o.players if p.id == o.hero_id)
    highest = max(p.bet for p in o.players)
    call = min(hero.stack, max(0, highest - hero.bet))
    result = [Action("check" if "check" in frame.legal else "fold")]
    if not tracker.ledger_complete:
        return tuple(result)
    if "call" in frame.legal and 0 < call <= settings.action_cap:
        result.append(Action("call"))
    if "raise" not in frame.legal or not frame.raise_min or not frame.raise_max:
        return tuple(result)
    limit = min(frame.raise_max, hero.stack, settings.action_cap)
    available = sorted(v for v in {frame.raise_min, frame.raise_max, *frame.raise_steps}
                       if frame.raise_min <= v <= limit and v > call)
    if not available:
        return tuple(result)
    fractions = {"profit": (.33, .66, 1., 1.5), "balanced": (.33, .66, 1.),
                 "conservative": (.33, .5, .75)}[settings.objective]
    targets = [call + fraction * (o.pot_total + call) for fraction in fractions]
    if settings.objective != "balanced":
        opponents = [p for p in o.players if p.id != hero.id and p.playing and not p.folded and p.cards_count]
        effective = min(hero.stack, max((p.stack + p.bet - hero.bet for p in opponents), default=0))
        # A commitment-sized bet and an effective all-in matter at low SPR;
        # both are still evaluated, never forced based on stack alone.
        targets.extend((effective / 3, effective))
        if not o.board:
            bb = 2 * o.small_blind
            limpers = max(0, sum(p.bet == bb for p in opponents) - 1)
            targets.append((2.5 + limpers) * bb - hero.bet if highest <= bb else 3 * highest - hero.bet)
    sizes = {available[0], available[-1]}
    sizes.update(min(available, key=lambda v: (abs(v - target), v)) for target in targets)
    result.extend(Action("raise", value) for value in sorted(sizes))
    return tuple(result)
