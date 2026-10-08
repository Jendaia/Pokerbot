import unittest

from texasholdem import Card, GameState, full_deck, parse_cards, showdown


class CardsAndStateTests(unittest.TestCase):
    def test_deck_and_card_notations(self):
        self.assertEqual(len(set(full_deck())), 52)
        self.assertEqual(parse_cards("as,KH 10d"), parse_cards("As Kh Td"))
        self.assertEqual(Card.parse("As").name, "Ace of spades")

    def test_invalid_cards(self):
        for text in ("1s", "AX", "A", "11s", "10", ""):
            with self.subTest(text=text), self.assertRaises(ValueError):
                Card.parse(text)
        for rank, suit in ((2.0, "s"), (True, "s"), (14, ""), (14, "cd"), (14, None)):
            with self.subTest(rank=rank, suit=suit), self.assertRaises(ValueError):
                Card(rank, suit)

    def test_valid_streets(self):
        for board, street in (("", "pre-flop"), ("2c 3d 4h", "flop"),
                              ("2c 3d 4h 5s", "turn"), ("2c 3d 4h 5s 6c", "river")):
            state = GameState(parse_cards("As Kh"), parse_cards(board))
            self.assertEqual(state.street, street)

    def test_invalid_state_shapes(self):
        for hero in ("", "As", "As Kh Qd"):
            with self.assertRaises(ValueError):
                GameState(parse_cards(hero))
        for board in ("2c", "2c 3d", "2c 3d 4h 5s 6c 7h"):
            with self.assertRaises(ValueError):
                GameState(parse_cards("As Kh"), parse_cards(board))
        for opponents in (0, 10, 1.5, True):
            with self.assertRaises(ValueError):
                GameState(parse_cards("As Kh"), opponents=opponents)
        with self.assertRaises(ValueError):
            GameState(parse_cards("As Kh"), opponent_hands=(parse_cards("2c 3d 4h"),))
        with self.assertRaises(ValueError):
            GameState(parse_cards("As Kh"), opponent_hands=((), ()))

    def test_duplicates_across_every_card_source(self):
        for options in (
            {"hero": parse_cards("As As")},
            {"board": parse_cards("As 2c 3d")},
            {"opponent_hands": (parse_cards("As 4h"),)},
            {"dead_cards": parse_cards("As")},
            {"opponents": 2, "opponent_hands": (parse_cards("2c"), parse_cards("2c"))},
            {"board": parse_cards("2c 3d 4h"), "dead_cards": parse_cards("4h")},
        ):
            kwargs = {"hero": parse_cards("As Kh"), **options}
            with self.subTest(options=options), self.assertRaises(ValueError):
                GameState(**kwargs)

    def test_state_copies_mutable_inputs_and_pads_unknown_seats(self):
        cards = list(parse_cards("As Kh"))
        hand = list(parse_cards("Qd"))
        state = GameState(cards, opponents=2, opponent_hands=[hand])
        cards.clear()
        hand.clear()
        self.assertEqual(state.hero, parse_cards("As Kh"))
        self.assertEqual(state.unknown_cards_per_opponent, (1, 2))
        self.assertEqual(state.opponent_hands, (parse_cards("Qd"), ()))

    def test_not_enough_unseen_cards_rejected(self):
        hero = parse_cards("As Kh")
        dead = tuple(card for card in full_deck() if card not in hero)
        with self.assertRaisesRegex(ValueError, "Not enough"):
            GameState(hero, dead_cards=dead)

    def test_showdown_ties_and_validation(self):
        board = parse_cards("As Ks Qs Js Ts")
        self.assertEqual(showdown((parse_cards("2c 3d"), parse_cards("4h 5d")), board), (0, 1))
        with self.assertRaises(ValueError):
            showdown((parse_cards("As 2d"),), board)
        with self.assertRaises(ValueError):
            showdown((parse_cards("2c 3d"),), board[:4])
