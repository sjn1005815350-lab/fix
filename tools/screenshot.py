# -*- coding: utf-8 -*-
"""开发辅助：抓取程序窗口截图，用于检查界面排版。"""
import ctypes
import sys
import time
from ctypes import wintypes

from PIL import ImageGrab

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()


def find_window(title_part):
    result = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if title_part in buffer.value:
            result.append((hwnd, buffer.value))
        return True

    user32.EnumWindows(callback, 0)
    return result


def main():
    title = sys.argv[1] if len(sys.argv) > 1 else "FIX"
    out = sys.argv[2] if len(sys.argv) > 2 else "shot.png"
    windows = find_window(title)
    if not windows:
        print("window not found")
        return 1
    hwnd, name = windows[0]
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.8)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    left, top = max(rect.left, 0), max(rect.top, 0)
    right, bottom = rect.right, rect.bottom
    print("window:", name, rect.left, rect.top, rect.right, rect.bottom)
    image = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    image.save(out)
    print("saved", out, image.size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
