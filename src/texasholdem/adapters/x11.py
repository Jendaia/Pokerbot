from __future__ import annotations

import ctypes as C
import os
import threading
import time

from ..analyzers.native.window import game_environment, input_window


def canvas_point(rect: tuple, canvas: tuple, viewport: dict) -> tuple[int, int]:
    x, y, w, h = rect
    cw, ch = canvas
    if min(w, h, cw, ch) <= 0 or x < -1 or y < -1 or x + w > cw + 1 or y + h > ch + 1:
        raise ValueError("Action button lies outside the Pokerist canvas")
    scale = min(viewport["width"] / cw, viewport["height"] / ch)
    left = viewport["x"] + (viewport["width"] - cw * scale) / 2
    top = viewport["y"] + (viewport["height"] - ch * scale) / 2
    return round(left + (x + w / 2) * scale), round(top + (y + h / 2) * scale)


class X11Input:
    """Ordinary XTest mouse input, restricted to a verified Pokerist window."""

    _environment_lock = threading.Lock()

    def __init__(self, pid: int):
        self.pid, self.display = pid, None
        self.lock = threading.RLock()
        self.x = C.CDLL("libX11.so.6")
        self.xt = C.CDLL("libXtst.so.6")
        declarations = {
            "XOpenDisplay": ([C.c_char_p], C.c_void_p),
            "XCloseDisplay": ([C.c_void_p], C.c_int),
            "XRaiseWindow": ([C.c_void_p, C.c_ulong], C.c_int),
            "XSetInputFocus": ([C.c_void_p, C.c_ulong, C.c_int, C.c_ulong], C.c_int),
            "XGetInputFocus": ([C.c_void_p, C.POINTER(C.c_ulong), C.POINTER(C.c_int)], C.c_int),
            "XSync": ([C.c_void_p, C.c_int], C.c_int),
            "XQueryPointer": ([C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong),
                               C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int),
                               C.POINTER(C.c_int), C.POINTER(C.c_uint)], C.c_int),
        }
        for name, (args, result) in declarations.items():
            getattr(self.x, name).argtypes, getattr(self.x, name).restype = args, result
        self.x.XInitThreads()
        self.xt.XTestFakeMotionEvent.argtypes = [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong]
        self.xt.XTestFakeButtonEvent.argtypes = [C.c_void_p, C.c_uint, C.c_int, C.c_ulong]
        environment = game_environment(pid)
        with self._environment_lock:
            old = os.environ.get("XAUTHORITY")
            if environment.get("XAUTHORITY"):
                os.environ["XAUTHORITY"] = environment["XAUTHORITY"]
            try:
                self.display = self.x.XOpenDisplay(environment.get("DISPLAY", "").encode())
            finally:
                if old is None:
                    os.environ.pop("XAUTHORITY", None)
                else:
                    os.environ["XAUTHORITY"] = old
        if not self.display:
            raise ValueError("Cannot connect to Pokerist's X11 display")
        try:
            self.viewport = input_window(pid)
        except BaseException:
            self.close()
            raise

    def close(self):
        with self.lock:
            if self.display:
                self.x.XCloseDisplay(self.display)
                self.display = None

    def click(self, rect: tuple, canvas: tuple, guard) -> None:
        with self.lock:
            if not self.display:
                raise ValueError("Pokerist input is closed")
            viewport = input_window(self.pid)
            wid = int(viewport["id"], 16)
            self.x.XRaiseWindow(self.display, wid)
            self.x.XSetInputFocus(self.display, wid, 2, 0)
            self.x.XSync(self.display, False)
            x, y = canvas_point(rect, canvas, viewport)
            self.xt.XTestFakeMotionEvent(self.display, -1, x, y, 0)
            self.x.XSync(self.display, False)
            # Re-read the entire native turn immediately before mouse down.
            guard()
            focus, revert = C.c_ulong(), C.c_int()
            self.x.XGetInputFocus(self.display, C.byref(focus), C.byref(revert))
            if focus.value not in (wid, int(viewport["child"], 16)):
                raise ValueError("Pokerist lost focus before the action")
            root, child, rx, ry, wx, wy, mask = C.c_ulong(), C.c_ulong(), C.c_int(), C.c_int(), C.c_int(), C.c_int(), C.c_uint()
            self.x.XQueryPointer(self.display, wid, C.byref(root), C.byref(child), C.byref(rx), C.byref(ry), C.byref(wx), C.byref(wy), C.byref(mask))
            if (rx.value, ry.value) != (x, y) or child.value != int(viewport["child"], 16):
                raise ValueError("The action button is covered or the mouse moved")
            self.xt.XTestFakeButtonEvent(self.display, 1, True, 0)
            self.x.XSync(self.display, False)
            time.sleep(.035)
            self.xt.XTestFakeButtonEvent(self.display, 1, False, 0)
            self.x.XSync(self.display, False)
