# -*- coding: utf-8 -*-
"""打包成单文件 exe：python tools\\build_exe.py

产物：dist/FIX-Order-Desk.exe（约 11 MB，双击即可运行，无需安装 Python）
"""
import io
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)


def stamp_version():
    """把当前时间写进 fixgui/version.py 的 BUILD_TIME，打包进 exe。"""
    import datetime
    import re
    path = os.path.join(ROOT, "fixgui", "version.py")
    with io.open(path, encoding="utf-8") as fh:
        text = fh.read()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    text = re.sub(r'BUILD_TIME = ".*?"', 'BUILD_TIME = "%s"' % now, text, count=1)
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    print("构建时间：%s" % now)
    return now


def main():
    stamp_version()
    for folder in ("build", "dist"):
        shutil.rmtree(os.path.join(ROOT, folder), ignore_errors=True)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile", "--windowed",
        "--name", "FIX-Order-Desk",
        "--icon", os.path.join("assets", "app.ico"),
        "--add-data", "dict;dict",
        "--add-data", "assets;assets",
        "--hidden-import", "_quickfix",
        "start.py",
    ]
    print(" ".join(cmd))
    code = subprocess.call(cmd)
    if code != 0:
        print("打包失败，退出码", code)
        return code

    exe = os.path.join(ROOT, "dist", "FIX-Order-Desk.exe")
    if not os.path.isfile(exe):
        print("没有找到产物：", exe)
        return 1
    print("\n打包完成：%s（%.1f MB）" % (exe, os.path.getsize(exe) / 1024.0 / 1024.0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
