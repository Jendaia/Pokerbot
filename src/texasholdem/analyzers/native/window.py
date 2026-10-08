from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


def game_environment(pid: int) -> dict[str, str]:
    environment = os.environ.copy()
    for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
        key, _, value = entry.partition(b"=")
        if key in (b"DISPLAY", b"XAUTHORITY"):
            text = value.decode(errors="replace")
            if key == b"XAUTHORITY" and not Path(text).is_file():
                text = str(Path(f"/proc/{pid}/root") / text.lstrip("/"))
            environment[key.decode()] = text
    return environment


def game_window(pid: int) -> dict[str, object] | None:
    """Best-effort X11 client bounds. This does not capture screen pixels."""
    try:
        environment = game_environment(pid)
        result = subprocess.run(["xwininfo", "-root", "-tree"], capture_output=True,
                                text=True, timeout=3, env=environment, check=True)
        matches = re.findall(r'(0x[0-9a-fA-F]+) "Texas Poker"[^\n]*?\s(\d+)x(\d+)([+-]\d+)([+-]\d+)\s+([+-]\d+)([+-]\d+)', result.stdout)
        if len(matches) != 1:
            return None
        id_, width, height, _, _, x, y = matches[0]
        return {"id": id_, "title": "Texas Poker", "x": int(x), "y": int(y),
                "width": int(width), "height": int(height), "coordinates": "X11 root pixels"}
    except (OSError, subprocess.SubprocessError):
        return None


def input_window(pid: int) -> dict[str, object]:
    """Resolve the verified Steam client and its Proton rendering child."""
    window = game_window(pid)
    if window is None:
        raise ValueError("Cannot uniquely locate the Pokerist X11 window")
    environment = game_environment(pid)
    properties = subprocess.run(["xprop", "-id", window["id"], "_NET_WM_PID", "WM_CLASS"],
                                capture_output=True, text=True, timeout=3, check=True, env=environment).stdout
    match = re.search(r"_NET_WM_PID\(CARDINAL\) = (\d+)", properties)
    if not match or int(match[1]) != pid or '"steam_app_3174070"' not in properties:
        raise ValueError("Pokerist window does not belong to the selected Steam process")
    tree = subprocess.run(["xwininfo", "-id", window["id"], "-tree"], capture_output=True,
                          text=True, timeout=3, check=True, env=environment).stdout
    children = re.findall(r'^\s+(0x[0-9a-fA-F]+) \(has no name\):.*?\s(\d+)x(\d+)([+-]\d+)([+-]\d+)\s+([+-]\d+)([+-]\d+)', tree, re.MULTILINE)
    candidates = [(id_, int(w), int(h), int(x), int(y)) for id_, w, h, _, _, x, y in children
                  if int(w) >= .8 * window["width"] and int(h) >= .8 * window["height"]]
    if len(candidates) != 1:
        raise ValueError("Cannot uniquely locate Pokerist's rendering viewport")
    child, width, height, x, y = candidates[0]
    return {**window, "child": child, "width": width, "height": height, "x": x, "y": y}
