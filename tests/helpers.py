from texasholdem import GameState, full_deck, parse_cards


def small_state():
    """Six unseen cards allow an independent exhaustive multi-seat check."""
    hero = parse_cards("As Kh")
    board = parse_cards("Qs Js 2d 3c")
    known_opponent = parse_cards("Ac")
    available = parse_cards("Ts Td 9h 9s 4c 5d")
    keep = set(hero + board + known_opponent + available)
    dead = tuple(card for card in full_deck() if card not in keep)
    return GameState(hero, board, 2, (known_opponent, ()), dead)
