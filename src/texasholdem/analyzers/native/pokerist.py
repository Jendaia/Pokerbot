from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
from math import isfinite
import time

from ...models.observation import ObservedCard, ObservedPlayer, TableObservation
from .collections import array_integers, array_pointers, list_pointers
from .memory import MemoryReader
from .metadata import Metadata
from .process import find_process
from .runtime import Runtime, RuntimeField


POKER = "Casino.Games.Poker.Poker"
PLAYER = "Casino.Games.Poker.Players.PlayerPoker"
MANUAL_PLAYER = "Casino.Games.Poker.Players.PlayerManualPoker"
VIEWS = ("Casino.Games.Poker.Poker2D.Poker2D", "Casino.Games.Poker.Poker3D.Poker3D")
REQUIRED_TYPES = {POKER, PLAYER, MANUAL_PLAYER, *VIEWS, "PokerTableState", "PokerPlayerInfo",
                  "PlayerInfo", "CardInfo", "Session", "Table", "SceneTable", "TableInfo", "PokerTableInfo"}
SUITS = {"CLUBS": "c", "SPADES": "s", "HEARTS": "h", "DIAMONDS": "d"}
RANKS = dict(zip(("TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
                  "TEN", "JACK", "QUEEN", "KING", "ACE"), "23456789TJQKA"))


class PokeristReader:
    """Read a Linux/Proton IL2CPP client without injecting or modifying it.

    Game field offsets are obtained from live FieldInfo records and checked
    against the installed metadata. Unity's runtime/collection layout is the
    64-bit layout verified with Pokerist's Unity 6000.0.75f1 build.
    """

    def __init__(self, pid: int | None = None, *, table_id: int | None = None):
        self.process = find_process(pid)
        self.metadata = Metadata(self.process.metadata)
        self.memory = MemoryReader(self.process.pid)
        self.table_filter = table_id
        self.owner: int | None = None
        try:
            self.runtime = Runtime(self.memory, self.metadata)
            self.classes = self.runtime.find_classes(tuple(item for item in self.metadata.types
                                                           if item.full_name in REQUIRED_TYPES))
            self.suits = self.metadata.enum_values("CardSuite")
            self.ranks = self.metadata.enum_values("CardValue")
            self.poker_types = self.field_enum("PokerTableInfo", "PokerType")
            self.discover_table()
        except BaseException:
            self.memory.close()
            raise

    def close(self) -> None:
        self.memory.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def field(self, class_name: str, name: str) -> RuntimeField:
        item = self.classes.get(class_name)
        if item is not None:
            for field in item.fields:
                if field.name == name and not field.is_static and field.offset >= 16:
                    return field
        raise ValueError(f"Unsupported/uninitialized client field: {class_name}.{name}")

    def offset(self, class_name: str, name: str) -> int:
        return self.field(class_name, name).offset

    def field_enum(self, class_name: str, name: str) -> dict[int, str]:
        field = self.field(class_name, name)
        definition = self.memory.pointer(field.type_pointer)
        start = self.runtime.metadata_base + self.metadata.types_offset
        index, remainder = divmod(definition - start, self.metadata.TYPE_SIZE)
        if remainder or not 0 <= index < len(self.metadata.types):
            raise ValueError(f"Unsupported enum type layout: {class_name}.{name}")
        return self.metadata.enum_values(self.metadata.types[index])

    def value(self, obj: int, cls: str, field: str, fmt: str):
        definition = self.field(cls, field)
        allowed = {"?": {2}, "i": {8, 0x11}, "q": {0xA}, "d": {0xD},
                   "Q": {0xB, 0xE, 0x12, 0x14, 0x15, 0x1C, 0x1D}}
        if definition.type_code not in allowed[fmt]:
            raise ValueError(f"Unexpected runtime field type: {cls}.{field}")
        return self.memory.unpack("<" + fmt, obj + definition.offset)[0]

    def pointer(self, obj: int, cls: str, field: str) -> int:
        return self.value(obj, cls, field, "Q")

    def has_class(self, obj: int, name: str) -> bool:
        expected = self.classes.get(name)
        return bool(obj and expected and self.memory.pointer(obj) == expected.address)

    def root(self, owner: int) -> tuple[int, int, int]:
        m = self.memory
        if m.pointer(owner) not in {self.classes[name].address for name in VIEWS if name in self.classes}:
            raise ValueError("Table owner has changed")
        if not m.pointer(owner + 16):  # UnityEngine.Object.m_CachedPtr
            raise ValueError("Table owner has been destroyed")
        for cls, field in (("Table", "<WasDestroyed>k__BackingField"),
                           ("SceneTable", "<Closing>k__BackingField"), (POKER, "m_Replay")):
            if self.value(owner, cls, field, "?"):
                raise ValueError("Table owner is inactive or a replay")
        if not self.value(owner, "Table", "m_IsInited", "?"):
            raise ValueError("Table is not initialized")
        state = self.pointer(owner, POKER, "<State>k__BackingField")
        session = self.pointer(owner, "Table", "m_Session")
        if not self.has_class(state, "PokerTableState") or not self.has_class(session, "Session"):
            raise ValueError("Table state/session types do not match")
        info = self.pointer(session, "Session", "<Table>k__BackingField")
        if not self.has_class(info, "PokerTableInfo"):
            raise ValueError("Session table info type does not match")
        desk_id = self.value(state, "PokerTableState", "DeskID", "Q")
        if not desk_id or desk_id != self.value(info, "TableInfo", "ID", "Q"):
            raise ValueError("Session/table IDs disagree")
        if self.table_filter is not None and desk_id != self.table_filter:
            raise ValueError("Table does not match requested ID")
        return state, session, info

    def discover_table(self) -> None:
        self.memory.refresh_maps()
        class_addresses = {self.classes[name].address for name in VIEWS if name in self.classes}
        matches = self.memory.find_pointers(class_addresses)
        candidates: dict[int, list[int]] = {}
        for hits in matches.values():
            for owner in hits:
                try:
                    state, _, _ = self.root(owner)
                    candidates.setdefault(state, []).append(owner)
                except (OSError, ValueError):
                    continue
        if len(candidates) != 1 or len(next(iter(candidates.values()), ())) != 1:
            raise ValueError("Cannot uniquely locate a live poker table; enter a table or use --table-id")
        self.owner = next(iter(candidates.values()))[0]

    def _header(self, state: int) -> tuple:
        fields = (("Players", "Q"), ("DealerPlace", "i"), ("Cards", "Q"), ("TableMoney", "q"),
                  ("Current", "i"), ("SeatPlaces", "Q"), ("DeskID", "Q"), ("GameInProgress", "?"),
                  ("PrivateCards", "Q"), ("Spectators", "i"), ("SmallBlindAmount", "q"),
                  ("<ResultInProgress>k__BackingField", "?"))
        return tuple(self.value(state, "PokerTableState", name, fmt) for name, fmt in fields)

    def _player_data(self, address: int) -> tuple:
        if not self.has_class(address, "PokerPlayerInfo"):
            raise ValueError("Unexpected player info type")
        data = (
            self.value(address, "PlayerInfo", "m_ID", "Q"),
            self.memory.managed_string(self.pointer(address, "PlayerInfo", "m_Nick")),
            self.value(address, "PlayerInfo", "Place", "i"),
            self.value(address, "PlayerInfo", "DAmount", "d"),
            self.value(address, "PokerPlayerInfo", "TableAmount", "d"),
            self.value(address, "PokerPlayerInfo", "Folded", "?"),
            self.value(address, "PokerPlayerInfo", "IsSitout", "?"),
            self.value(address, "PokerPlayerInfo", "IsPlaying", "?"),
            self.value(address, "PokerPlayerInfo", "CardsCount", "i"),
        )
        if not data[0] or any(not isfinite(value) or not 0 <= value <= 1e18 for value in data[3:5]):
            raise ValueError("Invalid player ID, stack, or wager")
        if not 0 <= data[8] <= 5:
            raise ValueError("Invalid player card count")
        return data

    def _cards(self, array: int, maximum: int) -> tuple[ObservedCard, ...]:
        result = []
        for address in array_pointers(self.memory, array, maximum=maximum):
            if not self.has_class(address, "CardInfo"):
                raise ValueError("Unexpected card type")
            id_ = self.value(address, "CardInfo", "ID", "i")
            suit = self.suits.get(self.value(address, "CardInfo", "Suite", "i"), "UNKNOWN")
            rank = self.ranks.get(self.value(address, "CardInfo", "Value", "i"), "UNKNOWN")
            code = RANKS[rank] + SUITS[suit] if rank in RANKS and suit in SUITS else None
            result.append(ObservedCard(id_, suit, rank, code))
        return tuple(result)

    def _models(self, owner: int) -> tuple[int | None, dict[int, bool]]:
        hero_ids = set()
        timers = {}
        for model in list_pointers(self.memory, self.pointer(owner, "Table", "m_Players")):
            # Check ancestry before reading inherited fields from a render model.
            cls = self.memory.pointer(model)
            manual = False
            for _ in range(16):
                if MANUAL_PLAYER in self.classes and cls == self.classes[MANUAL_PLAYER].address:
                    manual = True
                if cls == self.classes[PLAYER].address:
                    break
                cls = self.memory.pointer(cls + 0x58)
                if not cls:
                    raise ValueError("Unexpected poker player render type")
            else:
                raise ValueError("Poker player ancestry exceeds limit")
            info = self.pointer(model, PLAYER, "m_Info")
            if not info:
                continue
            if not self.has_class(info, "PokerPlayerInfo"):
                raise ValueError("Unexpected render player info type")
            player_id = self.value(info, "PlayerInfo", "m_ID", "Q")
            timers[player_id] = self.value(model, PLAYER, "<HasTimer>k__BackingField", "?")
            if manual:
                hero_ids.add(player_id)
        if len(hero_ids) > 1:
            raise ValueError("Multiple local player models found")
        return next(iter(hero_ids), None), timers

    def _capture(self) -> TableObservation:
        owner = self.owner
        if owner is None:
            raise ValueError("No table owner")
        state, session, info = self.root(owner)
        header = self._header(state)
        (player_list, dealer, board_array, bank, current, seat_array, desk_id, in_progress,
         private_array, spectators, small_blind, result_in_progress) = header
        places = self.value(info, "TableInfo", "Places", "i")
        seats = array_integers(self.memory, seat_array)
        if len(seats) != places or len(set(seats)) != places or not 2 <= places <= 10:
            raise ValueError("Invalid table seat configuration")
        spectating = self.value(session, "Session", "<Spectate>k__BackingField", "?")
        ids = list_pointers(self.memory, player_list)
        data = tuple(self._player_data(address) for address in ids)
        if len({row[0] for row in data}) != len(data) or len({row[2] for row in data}) != len(data):
            raise ValueError("Duplicate players or occupied seats")
        if any(row[2] not in seats for row in data):
            raise ValueError("Player place does not belong to the table")
        if (current != 0 and current not in seats) or (dealer != 0 and dealer not in seats):
            raise ValueError("Invalid acting/dealer seat")
        if bank < 0 or small_blind < 0 or not 0 <= spectators <= 1_000_000:
            raise ValueError("Invalid table amounts or spectator count")
        board = self._cards(board_array, 5)
        # A spectator has no personal hand, even if old cards linger during a transition.
        private = () if spectating else self._cards(private_array, 4)
        hero_id, timers = self._models(owner)
        if spectating:
            hero_id = None
        if hero_id is not None and hero_id not in {row[0] for row in data}:
            raise ValueError("Local render player does not match the state")
        game_type = self.poker_types.get(self.value(info, "PokerTableInfo", "PokerType", "i"), "Unknown")
        game_id = self.value(info, "TableInfo", "GameUID", "Q")
        if (header != self._header(state) or self.root(owner) != (state, session, info)
                or spectating != self.value(session, "Session", "<Spectate>k__BackingField", "?")
                or ids != list_pointers(self.memory, player_list)
                or data != tuple(self._player_data(address) for address in ids)
                or board != self._cards(board_array, 5)
                or (not spectating and private != self._cards(private_array, 4))):
            raise ValueError("Table changed while it was read")
        return TableObservation(
            captured_at=datetime.now(timezone.utc).isoformat(), pid=self.process.pid,
            table_id=desk_id, game_id=game_id, game_type=game_type,
            view=self.runtime.class_name(self.memory.pointer(owner)).split(".")[-1],
            spectating=spectating, spectators=spectators, seats=seats,
            dealer_seat=dealer or None,
            acting_seat=current if current and in_progress and not result_in_progress else None,
            players=tuple(ObservedPlayer(*row, is_hero=row[0] == hero_id, has_timer=timers.get(row[0])) for row in data),
            board=board, hero_id=hero_id, hero_cards=private,
            collected_pot=bank, street_bets_total=sum(row[4] for row in data), small_blind=small_blind,
            game_in_progress=in_progress, result_in_progress=result_in_progress,
        )

    def read(self) -> TableObservation:
        last_error = None
        for attempt in range(6):
            try:
                return self._capture()
            except (OSError, ValueError) as error:
                last_error = error
                if attempt == 2:
                    self.discover_table()
                time.sleep(0.01)
        raise ValueError(f"Could not read a consistent table snapshot: {last_error}")

    def pointer_report(self) -> dict[str, object]:
        """Session-specific pointer chain and discovered game field offsets."""
        state, session, info = self.root(self.owner)
        module = next((region.start for region in self.memory.regions
                       if region.path.endswith("/GameAssembly.dll") and region.file_offset == 0), None)
        return {
            "pid": self.process.pid,
            "installation": str(self.process.installation),
            "metadata_version": self.metadata.version,
            "metadata_sha256": sha256(self.metadata.data).hexdigest(),
            "metadata_base": hex(self.runtime.metadata_base),
            "game_assembly_base": hex(module) if module is not None else None,
            "owner": hex(self.owner), "state": hex(state), "session": hex(session), "table_info": hex(info),
            "state_pointer_chain": [hex(self.owner), "+" + hex(self.offset(POKER, "<State>k__BackingField"))],
            "table_id": self.value(state, "PokerTableState", "DeskID", "Q"),
            "field_offsets": {
                name: {field.name: hex(field.offset) for field in item.fields if not field.is_static}
                for name, item in self.classes.items()
                if name in {"PokerTableState", "PokerPlayerInfo", "CardInfo", "PokerTableInfo"}
            },
            "player_field_offsets": {name: hex(self.offset("PlayerInfo", name))
                                     for name in ("m_ID", "m_Nick", "DAmount", "Place")},
            "address_lifetime": "this running process only; rediscover after restart",
        }
