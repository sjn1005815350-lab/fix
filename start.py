# -*- coding: utf-8 -*-
"""打包 / 命令行入口（PyInstaller 以本文件为入口）。

日常使用请双击 run.bat 或 main.pyw。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixgui.launcher import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
