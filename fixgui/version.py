# -*- coding: utf-8 -*-
"""版本信息。

- VERSION：手工维护的版本号
- BUILD_TIME：打包时由 tools/build_exe.py 自动写入（源码运行时为最后一次打包时间）
"""
from __future__ import annotations

import datetime
import os
import sys

VERSION = "1.0.2"

# 由打包脚本覆盖，例如 "2026-11-17 17:05"
BUILD_TIME = "2026-11-17 16:45"


def _mtime_text():
    try:
        if getattr(sys, "frozen", False):
            path = sys.executable
        else:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.py")
        stamp = os.path.getmtime(path)
        return datetime.datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return ""


def build_time():
    return BUILD_TIME or _mtime_text()


def version_text(with_time=True):
    """例如：v1.0.2（2026-11-17 17:05）"""
    build = build_time()
    if with_time and build:
        return "v%s（%s）" % (VERSION, build)
    return "v%s" % VERSION
