# -*- coding: utf-8 -*-
"""FIX 下单助手 —— 图形界面版。

运行方式：
    pythonw main.pyw        （无控制台窗口，日常使用）
    python  main.pyw        （带控制台，便于排查问题）
    start.py                （源码 / 打包统一入口）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixgui.launcher import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
