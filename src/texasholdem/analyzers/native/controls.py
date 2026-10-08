from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite

from ...agents.models import turn_key
from ...models.observation import TableObservation
from .collections import list_int64, list_pointers
from .pokerist import POKER, PokeristReader


SCREEN_VM = "Casino.Games.Poker.ViewModels.PokerScreenViewModel"
BAR_VM = "Casino.Games.Poker.ViewModels.PokerControlBarViewModel"
BUTTON_VM = "Casino.Games.Poker.ViewModels.PokerControlBarButtonViewModel"
SCREEN = "Casino.Games.Poker.View.UIPokerScreen"
BAR = "Casino.Games.Poker.View.UIPokerControlBar"
BUTTON = "Casino.Games.Poker.View.UIPokerControlBarButton"
TYPES = {SCREEN_VM, BAR_VM, BUTTON_VM, SCREEN, BAR, BUTTON, "UINode", "Children",
         "Binding.Binder", "UIButton", "GUIControlBarRaiseControl", "UIRaiseBet", "UIRaiseQuick",
         "UIRaiseQuickPoker", "UISlider", "Poker3DRaiseButtonWrapper"}


@dataclass(frozen=True, slots=True)
class ControlButton:
    action: str
    title: str
    enabled: bool
    rect: tuple[float, float, float, float] | None


@dataclass(frozen=True, slots=True)
class ControlFrame:
    observation: TableObservation
    hand_number: int
    instant: bool
    buttons: tuple[ControlButton, ...]
    canvas: tuple[float, float]
    raise_open: bool = False
    raise_min: int | None = None
    raise_max: int | None = None
    raise_value: int | None = None
    raise_confirm: tuple[float, float, float, float] | None = None
    raise_slider: tuple[float, float, float, float] | None = None
    raise_increase: tuple[float, float, float, float] | None = None
    raise_decrease: tuple[float, float, float, float] | None = None
    raise_all_in: tuple[float, float, float, float] | None = None
    raise_steps: tuple[int, ...] = ()

    @property
    def key(self) -> tuple:
        return turn_key(self.observation, self.hand_number)

    @property
    def legal(self) -> tuple[str, ...]:
        if not self.instant or self.observation.acting_player_id != self.observation.hero_id:
            return ()
        return tuple(b.action for b in self.buttons if b.enabled and b.rect and b.action in ("fold", "check", "call", "raise"))

    def as_dict(self) -> dict:
        return {"hand_number": self.hand_number, "legal_actions": self.legal,
                "buttons": [asdict(b) for b in self.buttons], "raise_open": self.raise_open,
                "raise_min": self.raise_min, "raise_max": self.raise_max, "raise_value": self.raise_value,
                "raise_steps": self.raise_steps}


class PokeristControls:
    """Read action permissions and UI layout through the table's own UI tree."""

    def __init__(self, reader: PokeristReader):
        self.reader = reader
        reader.classes.update(reader.runtime.find_classes(tuple(t for t in reader.metadata.types if t.full_name in TYPES)))
        for name in TYPES:
            if name not in reader.classes or not reader.classes[name].fields:
                raise ValueError(f"Unsupported Pokerist control layout: {name}")
        self.button_types = reader.field_enum(BUTTON_VM, "<Type>k__BackingField")
        self.states = reader.field_enum(BAR_VM, "<CurrentState>k__BackingField")

    def rect(self, node: int, screen: int) -> tuple[float, float, float, float] | None:
        r, m = self.reader, self.reader.memory
        if node and r.has_class(node, "Poker3DRaiseButtonWrapper"):
            node = r.pointer(node, "Poker3DRaiseButtonWrapper", "m_Button")
        if node and r.has_class(node, BUTTON):
            node = r.pointer(node, BUTTON, "m_Button")
        if not node or not m.pointer(node + 16):
            return None
        cls = m.pointer(node)
        for _ in range(32):
            if cls == r.classes["UINode"].address:
                break
            cls = m.pointer(cls + 0x58)
            if not cls:
                return None
        else:
            return None
        x, y, w, h = m.unpack("<ffff", node + r.offset("UINode", "m_FinalRect"))
        if not all(isfinite(v) for v in (x, y, w, h)) or min(w, h) <= 0:
            return None
        current, seen = node, set()
        for _ in range(64):
            if current == screen:
                return x, y, w, h
            if not current or current in seen:
                return None
            seen.add(current)
            if r.value(current, "UINode", "m_IsHidden", "?") or r.value(current, "UINode", "<Destroying>k__BackingField", "?"):
                return None
            current = r.pointer(current, "UINode", "m_Parent")
            if current and current != screen:
                dx, dy, _, _ = m.unpack("<ffff", current + r.offset("UINode", "m_FinalRect"))
                x, y = x + dx, y + dy
        return None

    def nodes(self, node: int):
        r, seen, pending = self.reader, set(), [node]
        while pending:
            current = pending.pop()
            if current in seen:
                raise ValueError("Cycle in Pokerist UI tree")
            seen.add(current)
            if len(seen) > 2048:
                raise ValueError("Pokerist control tree is too large")
            yield current
            children = r.pointer(current, "UINode", "m_Childs")
            if children:
                if not r.has_class(children, "Children"):
                    raise ValueError("Unexpected Pokerist child collection")
                pending.extend(list_pointers(r.memory, r.pointer(children, "Children", "m_Children"), maximum=512))

    def read(self) -> ControlFrame:
        r = self.reader
        before = r.read()
        owner = r.owner
        hand = r.value(owner, POKER, "<HandsPlayed>k__BackingField", "i")
        screen = r.pointer(owner, POKER, "m_UIPokerScreen")
        vm = r.pointer(owner, POKER, "m_ScreenViewModel")
        bar = r.pointer(screen, SCREEN, "m_ControlBar")
        bar_vm = r.pointer(vm, SCREEN_VM, "<ControlBarViewModel>k__BackingField")
        state = self.states.get(r.value(bar_vm, BAR_VM, "<CurrentState>k__BackingField", "i"))
        buttons = []
        for node in self.nodes(bar):
            if not r.has_class(node, BUTTON):
                continue
            binder = r.pointer(node, BUTTON, "m_Binder")
            model = r.pointer(binder, "Binding.Binder", "m_ModelInstance")
            if not r.has_class(model, BUTTON_VM):
                continue
            btn = r.pointer(node, BUTTON, "m_Button")
            type_ = self.button_types.get(r.value(model, BUTTON_VM, "<Type>k__BackingField", "i"), "NONE").lower()
            enabled = (r.value(model, BUTTON_VM, "<IsActive>k__BackingField", "?")
                       and not r.value(model, BUTTON_VM, "<IsDarkened>k__BackingField", "?")
                       and not r.value(model, BUTTON_VM, "<ToggleMode>k__BackingField", "?")
                       and not r.value(model, BUTTON_VM, "<IgnoreEvents>k__BackingField", "?")
                       and r.value(btn, "UIButton", "m_IsEnabled", "?"))
            title = (r.memory.managed_string(r.pointer(model, BUTTON_VM, "<Title>k__BackingField")) or type_).replace("\uf800", "· ")
            buttons.append(ControlButton(type_, title,
                                         enabled, self.rect(btn, screen)))
        _, _, cw, ch = r.memory.unpack("<ffff", screen + r.offset("UINode", "m_FinalRect"))
        if not all(isfinite(v) and 0 < v <= 20000 for v in (cw, ch)):
            raise ValueError("Invalid Pokerist canvas")
        opened = r.value(bar_vm, BAR_VM, "<IsRaiseControlActiveNow>k__BackingField", "?")
        kwargs = {}
        if opened:
            ctrl = r.pointer(bar, BAR, "m_RaiseControl")
            slider = r.pointer(ctrl, "GUIControlBarRaiseControl", "<RaiseControlSlider>k__BackingField")
            quick = r.pointer(ctrl, "GUIControlBarRaiseControl", "<QuickRaiseButtons>k__BackingField")
            for label, field in (("raise_min", "<Min>k__BackingField"), ("raise_max", "<Max>k__BackingField"), ("raise_value", "m_Val")):
                value = r.value(slider, "UIRaiseBet", field, "d")
                if not isfinite(value) or not 0 <= value <= 10**15 or value != int(value):
                    raise ValueError("Invalid raise amount")
                kwargs[label] = int(value)
            steps = list_int64(r.memory, r.pointer(quick, "UIRaiseQuick", "m_Steps"))
            if any(value <= 0 for value in steps) or tuple(sorted(set(steps))) != steps:
                raise ValueError("Invalid native raise steps")
            kwargs["raise_steps"] = tuple(sorted({kwargs["raise_min"], kwargs["raise_max"],
                                                 *(value for value in steps if kwargs["raise_min"] <= value <= kwargs["raise_max"])}))
            for label, obj in (
                ("raise_confirm", r.pointer(slider, "UIRaiseBet", "m_ConfirmButton")),
                ("raise_slider", r.pointer(slider, "UIRaiseBet", "<Slider>k__BackingField")),
                ("raise_increase", r.pointer(quick, "UIRaiseQuick", "m_IncreaseButton")),
                ("raise_decrease", r.pointer(quick, "UIRaiseQuick", "m_DecreaseButton")),
                ("raise_all_in", r.pointer(quick, "UIRaiseQuick", "m_AllInButton")),
            ):
                kwargs[label] = self.rect(obj, screen)
        after = r.read()
        if turn_key(before, hand) != turn_key(after, r.value(owner, POKER, "<HandsPlayed>k__BackingField", "i")) or owner != r.owner:
            raise ValueError("Turn changed while reading the controls")
        return ControlFrame(after, hand, state == "INSTANT_ACTIONS", tuple(buttons), (cw, ch), opened, **kwargs)
