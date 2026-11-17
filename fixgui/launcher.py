# -*- coding: utf-8 -*-
"""程序启动逻辑（主程序与打包后的 exe 共用）。"""
from __future__ import annotations

import os
import sys


def app_root():
    """程序目录：源码运行时是项目根目录，打包后是 exe 所在目录。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _prepare_streams(root):
    """pythonw / 打包后的窗口程序没有控制台，sys.stdout/stderr 为 None，先重定向到日志。"""
    log_dir = os.path.join(root, "logs")
    try:
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "console.log")
        stream = open(path, "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def _set_dpi_aware():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:  # noqa: BLE001
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def _fatal(title, message):
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror(title, message)
        root.destroy()
    except Exception:  # noqa: BLE001
        try:
            sys.stderr.write("%s\n%s\n" % (title, message))
        except Exception:  # noqa: BLE001
            pass


def main():
    root = app_root()
    _prepare_streams(root)
    _set_dpi_aware()
    os.chdir(root)
    if root not in sys.path:
        sys.path.insert(0, root)
    if getattr(sys, "frozen", False):
        # 打包后资源在 _MEIPASS，模块已内嵌，不需额外路径
        pass

    try:
        from fixgui.ui import FixOrderApp
    except ImportError as exc:
        _fatal(
            "缺少依赖",
            "程序无法启动：%s\n\n"
            "本程序需要 Python 3.8+、tkinter 和 QuickFIX。\n"
            "源码运行前请执行：\n"
            "    python -m pip install quickfix\n\n"
            "当前解释器：%s" % (exc, sys.executable),
        )
        return 1

    try:
        app = FixOrderApp()
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        _fatal("启动失败", "界面初始化失败：\n%s" % exc)
        return 1

    app.mainloop()
    return 0
