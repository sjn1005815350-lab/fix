# -*- coding: utf-8 -*-
"""开发辅助：真实鼠标点击 + 键盘输入，验证价格框可编辑。"""
import ctypes
import os
import sys
import time
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:  # noqa: BLE001
    pass

from fixgui import config_store  # noqa: E402
from fixgui.ui import FixOrderApp  # noqa: E402

config_store.save_settings = lambda *a, **k: None
config_store.save_orders = lambda *a, **k: None

u = ctypes.windll.user32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("padding", ctypes.c_byte * 24)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def send_char(ch):
    for flags in (0x0004, 0x0004 | 0x0002):
        inp = INPUT()
        inp.type = 1
        inp.ki.wVk = 0
        inp.ki.wScan = ord(ch)
        inp.ki.dwFlags = flags
        inp.ki.time = 0
        inp.ki.dwExtraInfo = ctypes.pointer(ctypes.c_ulong(0))
        u.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.03)


def click(x, y):
    u.SetCursorPos(int(x), int(y))
    time.sleep(0.15)
    u.mouse_event(0x0002, 0, 0, 0, 0)
    u.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.25)


app = FixOrderApp()
app.update()
app.notebook.select(1)
app.update()
app.deiconify()
app.lift()
app.attributes("-topmost", True)
app.update()
time.sleep(1.0)


def step1():
    widget = app.option_combos["price"]
    x = widget.winfo_rootx() + 20
    y = widget.winfo_rooty() + widget.winfo_height() // 2
    print("window:", app.winfo_rootx(), app.winfo_rooty(), app.winfo_width(), app.winfo_height())
    print("click at", x, y, "state:", widget.cget("state"), "foreground:",
          u.GetForegroundWindow() == int(app.wm_frame(), 16))
    click(x, y)
    app.update()
    print("focus:", app.focus_get())
    app.after(300, step2)


def step2():
    for ch in "10.55":
        send_char(ch)
        app.update()
    app.after(500, step3)


def step3():
    widget = app.option_combos["price"]
    value = widget.get()
    print("value:", repr(value))
    print("RESULT:", "OK" if value == "10.55" else "FAILED")
    app.destroy()


app.after(900, step1)
app.mainloop()
