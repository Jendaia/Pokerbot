from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess


def game_window(pid: int) -> dict[str, object] | None:
    """Best-effort X11 client bounds. This does not capture screen pixels."""
    environment = os.environ.copy()
    try:
        for entry in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0"):
            key, _, value = entry.partition(b"=")
            if key in (b"DISPLAY", b"XAUTHORITY"):
                text = value.decode(errors="replace")
                if key == b"XAUTHORITY" and not Path(text).is_file():
                    text = str(Path(f"/proc/{pid}/root") / text.lstrip("/"))
                environment[key.decode()] = text
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
