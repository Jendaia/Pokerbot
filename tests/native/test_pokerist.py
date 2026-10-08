"""Extraction tests use a synthetic, mutable IL2CPP heap with relocated fields."""

from types import SimpleNamespace
import unittest

from texasholdem.analyzers.native.memory import MemoryReader
from texasholdem.analyzers.native.pokerist import MANUAL_PLAYER, PLAYER, POKER, VIEWS, PokeristReader
from texasholdem.analyzers.native.runtime import RuntimeClass, RuntimeField
from native.test_memory import ByteMemory


class Heap(ByteMemory):
    managed_string = MemoryReader.managed_string

    def __init__(self):
        self.data = bytearray(0x20000)
        self.next = 0x8000

    def allocate(self, size=512):
        address = self.next
        self.next += size
        return address

    def refresh_maps(self):
        pass

    def find_pointers(self, values):
        result = {value: [] for value in values}
        for address in range(0, len(self.data), 8):
            value = self.pointer(address)
            if value in result:
                result[value].append(address)
        return result


FORMATS = {"Q": 0x12, "?": 2, "i": 8, "q": 0xA, "d": 0xD}


class FakeTable:
    def __init__(self):
        self.reader = r = PokeristReader.__new__(PokeristReader)
        self.heap = r.memory = Heap()
        r.classes = {}
        r.process = SimpleNamespace(pid=1)
        r.table_filter = None
        r.poker_types = {0: "Texas"}
        r.suits = {1: "CLUBS", 2: "SPADES", 3: "HEARTS", 4: "DIAMONDS", 999: "UNKNOWN"}
        r.ranks = {2: "TWO", 10: "TEN", 11: "JACK", 14: "ACE", 999: "UNKNOWN"}
        self.class_(VIEWS[0], [])
        self.class_(POKER, [("<State>k__BackingField", "Q"), ("m_Replay", "?")], start=320)
        self.class_("SceneTable", [("<Closing>k__BackingField", "?")], start=304)
        self.class_("Table", [("<WasDestroyed>k__BackingField", "?"), ("m_IsInited", "?"),
                             ("m_Session", "Q"), ("m_Players", "Q")], start=256)
        self.class_("PokerTableState", [("Players", "Q"), ("DealerPlace", "i"), ("Cards", "Q"),
                     ("TableMoney", "q"), ("Current", "i"), ("SeatPlaces", "Q"), ("DeskID", "Q"),
                     ("GameInProgress", "?"), ("PrivateCards", "Q"), ("Spectators", "i"),
                     ("SmallBlindAmount", "q"), ("<ResultInProgress>k__BackingField", "?")])
        self.class_("Session", [("<Table>k__BackingField", "Q"), ("<Spectate>k__BackingField", "?")])
        self.class_("TableInfo", [("ID", "Q"), ("Places", "i"), ("GameUID", "Q")])
        self.class_("PokerTableInfo", [("PokerType", "i")], start=192)
        self.class_("PlayerInfo", [("m_ID", "Q"), ("m_Nick", "Q"), ("Place", "i"), ("DAmount", "d")])
        self.class_("PokerPlayerInfo", [("TableAmount", "d"), ("Folded", "?"), ("IsSitout", "?"),
                                     ("IsPlaying", "?"), ("CardsCount", "i")], start=192)
        self.class_("CardInfo", [("ID", "i"), ("Suite", "i"), ("Value", "i")])
        self.class_(PLAYER, [("m_Info", "Q"), ("<HasTimer>k__BackingField", "?")])
        self.class_(MANUAL_PLAYER, [], parent=PLAYER)
        self.class_("PlayerHostPoker", [], parent=PLAYER)
        r.runtime = SimpleNamespace(class_name=lambda address: r.classes[VIEWS[0]].metadata_type.full_name)

        self.owner = r.owner = self.object(VIEWS[0])
        self.heap.write("<Q", self.owner + 16, 123456)
        self.state = self.object("PokerTableState")
        self.session = self.object("Session")
        self.info = self.object("PokerTableInfo")
        self.set(self.owner, POKER, "<State>k__BackingField", "Q", self.state)
        self.set(self.owner, "Table", "m_IsInited", "?", True)
        self.set(self.owner, "Table", "m_Session", "Q", self.session)
        self.set(self.session, "Session", "<Table>k__BackingField", "Q", self.info)
        self.set(self.info, "TableInfo", "ID", "Q", 42)
        self.set(self.info, "TableInfo", "GameUID", "Q", 123)
        self.set(self.info, "TableInfo", "Places", "i", 5)
        self.set(self.state, "PokerTableState", "DeskID", "Q", 42)
        self.set(self.state, "PokerTableState", "SeatPlaces", "Q", self.array("i", (1, 3, 5, 7, 9)))
        self.set(self.state, "PokerTableState", "DealerPlace", "i", 7)
        self.set(self.state, "PokerTableState", "Current", "i", 3)
        self.set(self.state, "PokerTableState", "GameInProgress", "?", True)
        self.set(self.state, "PokerTableState", "TableMoney", "q", 100)
        self.set(self.state, "PokerTableState", "SmallBlindAmount", "q", 25)
        self.hero = self.player(101, 1, 500, 25)
        self.opponent = self.player(102, 3, 900, 50)
        self.set(self.state, "PokerTableState", "Players", "Q", self.list((self.hero, self.opponent)))
        manual = self.object(MANUAL_PLAYER)
        host = self.object("PlayerHostPoker")
        self.set(manual, PLAYER, "m_Info", "Q", self.hero)
        self.set(host, PLAYER, "m_Info", "Q", self.opponent)
        self.set(host, PLAYER, "<HasTimer>k__BackingField", "?", True)
        self.set(self.owner, "Table", "m_Players", "Q", self.list((manual, host)))
        self.private_cards = self.array("Q", (self.card(14, 2), self.card(11, 1)))
        self.set(self.state, "PokerTableState", "PrivateCards", "Q", self.private_cards)
        self.set(self.state, "PokerTableState", "Cards", "Q", self.array("Q", (
            self.card(2, 4), self.card(10, 3), self.card(2, 3))))

    def class_(self, name, fields, start=32, parent=None):
        address = 0x1000 + len(self.reader.classes) * 256
        self.reader.classes[name] = RuntimeClass(address, SimpleNamespace(full_name=name),
            tuple(RuntimeField(field, start + index * 8, 0, 0, FORMATS[fmt])
                  for index, (field, fmt) in enumerate(fields)), 0, 0)
        if parent:
            self.heap.write("<Q", address + 0x58, self.reader.classes[parent].address)

    def object(self, class_name):
        address = self.heap.allocate()
        self.heap.write("<Q", address, self.reader.classes[class_name].address)
        return address

    def set(self, obj, cls, name, fmt, value):
        self.heap.write("<" + fmt, obj + self.reader.offset(cls, name), value)

    def array(self, fmt, items):
        address = self.heap.allocate()
        self.heap.write("<Q", address + 24, len(items))
        self.heap.write("<" + fmt * len(items), address + 32, *items)
        return address

    def list(self, items):
        address = self.heap.allocate()
        self.heap.write("<Qii", address + 16, self.array("Q", items), len(items), 1)
        return address

    def player(self, id_, seat, stack, bet):
        address = self.object("PokerPlayerInfo")
        for cls, name, fmt, value in (
            ("PlayerInfo", "m_ID", "Q", id_), ("PlayerInfo", "Place", "i", seat),
            ("PlayerInfo", "DAmount", "d", stack), ("PokerPlayerInfo", "TableAmount", "d", bet),
            ("PokerPlayerInfo", "IsPlaying", "?", True), ("PokerPlayerInfo", "CardsCount", "i", 2),
        ):
            self.set(address, cls, name, fmt, value)
        return address

    def card(self, rank, suit):
        address = self.object("CardInfo")
        for name, value in (("ID", 555), ("Suite", suit), ("Value", rank)):
            self.set(address, "CardInfo", name, "i", value)
        return address


class PokeristExtractionTests(unittest.TestCase):
    def setUp(self):
        self.table = FakeTable()
        self.reader = self.table.reader

    def test_extracts_private_cards_and_global_acting_seat_using_relocated_fields(self):
        result = self.reader.read()
        self.assertEqual(result.acting_player_id, 102)
        self.assertEqual(result.dealer_seat, 7)
        self.assertEqual(result.hero_id, 101)
        self.assertEqual([card.code for card in result.hero_cards], ["As", "Jc"])
        self.assertEqual([card.code for card in result.board], ["2d", "Th", "2h"])
        self.assertEqual(result.pot_total, 175)
        self.assertEqual(result.to_game_state().opponents, 1)

    def test_spectator_suppresses_lingering_local_cards(self):
        self.table.set(self.table.session, "Session", "<Spectate>k__BackingField", "?", True)
        result = self.reader.read()
        self.assertIsNone(result.hero_id)
        self.assertEqual(result.hero_cards, ())

    def test_hidden_cards_remain_unknown_and_do_not_make_calculator_state(self):
        card = self.table.card(999, 999)
        self.table.set(self.table.state, "PokerTableState", "PrivateCards", "Q", self.table.array("Q", (card, card)))
        result = self.reader.read()
        self.assertIsNone(result.hero_cards[0].code)
        with self.assertRaises(ValueError):
            result.to_game_state()

    def test_ignores_unowned_stale_state_during_discovery(self):
        stale = self.table.object("PokerTableState")
        self.table.set(stale, "PokerTableState", "DeskID", "Q", 99)
        self.reader.discover_table()
        self.assertEqual(self.reader.owner, self.table.owner)

    def test_changed_player_rows_fail_consistency_check(self):
        original = self.reader._player_data
        reads = 0

        def changing_data(address):
            nonlocal reads
            reads += 1
            data = original(address)
            if reads == 2:
                self.table.set(self.table.hero, "PlayerInfo", "DAmount", "d", 499)
            return data

        self.reader._player_data = changing_data
        with self.assertRaisesRegex(ValueError, "changed"):
            self.reader._capture()

    def test_mismatched_table_id_and_destroyed_owner_rejected(self):
        self.table.set(self.table.info, "TableInfo", "ID", "Q", 99)
        with self.assertRaisesRegex(ValueError, "IDs disagree"):
            self.reader.root(self.table.owner)
        self.table.set(self.table.info, "TableInfo", "ID", "Q", 42)
        self.table.heap.write("<Q", self.table.owner + 16, 0)
        with self.assertRaisesRegex(ValueError, "destroyed"):
            self.reader.root(self.table.owner)
