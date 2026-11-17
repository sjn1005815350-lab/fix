# -*- coding: utf-8 -*-
"""开发辅助：造一批演示数据并截图（不会写入 config/ 下的真实数据）。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import ctypes  # noqa: E402

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:  # noqa: BLE001
    pass

from PIL import ImageGrab  # noqa: E402

from fixgui import config_store, parser  # noqa: E402
from fixgui.ui import FixOrderApp  # noqa: E402

# 演示期间不要落盘，避免污染真实配置
config_store.save_orders = lambda *args, **kwargs: None
config_store.save_settings = lambda *args, **kwargs: None


def exec_event(raw, stamp):
    data = parser.parse_exec_report(raw)
    assert data["status"], raw
    return {"kind": "exec", "data": data, "time": stamp}


def build_exec(clordid, orderid, exec_type, status, cum, leaves, avg, text, symbol="600000"):
    return (
        "8=FIX.4.2|9=0|35=8|11=%s|37=%s|17=E%s|150=%s|39=%s|55=%s|54=1|38=100|44=10.10|"
        "14=%s|151=%s|6=%s|58=%s|10=000|"
        % (clordid, orderid, orderid, exec_type, status, symbol, cum, leaves, avg, text)
    )


def main():
    app = FixOrderApp()
    app.geometry("1440x900+80+60")
    app.update()
    app.order_vars["price"].set("10.55")
    app.order_vars["qty"].set("100")
    app.orders.clear()
    for _item in app.order_tree.get_children():
        app.order_tree.delete(_item)

    orders = [
        ("6201794888900101", "ORD-1001", "0", "0", "0", "100", "0", "已报", "已报"),
        ("6201794888900102", "ORD-1002", "1", "1", "30", "70", "10.10", "部成", "部成"),
        ("6201794888900103", "ORD-1003", "2", "2", "100", "0", "10.09", "全部成交", "已成"),
        ("6201794888900104", "ORD-1004", "8", "8", "0", "100", "0", "资金不足", "拒绝"),
        ("6201794888900105", "ORD-1005", "4", "4", "0", "0", "0", "用户撤单", "已撤"),
    ]
    for index, (clordid, orderid, etype, status, cum, leaves, avg, text, _label) in enumerate(orders):
        app.events.put(exec_event(
            build_exec(clordid, orderid, etype, status, cum, leaves, avg, text),
            "09:31:%02d" % (10 + index)))
    app.events.put({"kind": "raw", "direction": "S", "category": "app", "msgtype": "D",
                    "text": "8=FIX.4.2|9=213|35=D|34=2|49=209TEST|50=P1100209|56=CMSITYPROD|"
                            "1=P1100209|11=6201794888900101|15=CNY|21=1|38=100|40=2|44=10.1|"
                            "54=1|55=600000|58=1|59=0|167=CS|207=SH|10=144|",
                    "time": "09:31:05"})
    app.events.put({"kind": "raw", "direction": "R", "category": "app", "msgtype": "8",
                    "text": "8=FIX.4.2|9=268|35=8|34=5|49=CMSITYPROD|56=209TEST|"
                            "37=ORD-1002|11=6201794888900102|17=EX0002|150=1|39=1|55=600000|"
                            "54=1|38=100|44=10.10|14=30|151=70|6=10.10|58=部成|10=201|",
                    "time": "09:31:12"})
    app._poll_events()
    time.sleep(0.3)

    # 查询结果
    fund = ("8=FIX.4.2|9=0|35=FP|1=P1100209|11=6201794888900201|15=CNY|"
            "60=20261117-09:32:01|58=查询成功|10015=12503456.78|8001=1|8002=1|8003=1|10=000|")
    app.events.put({"kind": "query", "data": dict(parser.parse_query_response(fund), label="资金查询结果"),
                    "time": "09:32:01"})
    for index, (symbol, qty, cost, avail) in enumerate(
            [("600000", "10000", "10.12", "10000"), ("000001", "5000", "11.30", "5000"),
             ("IM2610", "2", "5980.2", "2")]):
        pos = ("8=FIX.4.2|9=0|35=AP|1=P1100209|11=6201794888900202|55=%s|10023=1|100=SH|"
               "6=%s|10008=%s|10007=%s|8001=3|8002=%d|8003=%d|58=ok|10=000|"
               % (symbol, cost, qty, avail, index + 1, 1 if index == 2 else 0))
        app.events.put({"kind": "query", "data": dict(parser.parse_query_response(pos),
                                                      label="持仓查询结果"), "time": "09:32:02"})
    # 给演示订单补上“报单 / 撤单请求”时间线，并打开明细弹窗截图
    rec_sub = app.orders.get("6201794888900102")
    if rec_sub:
        app._append_event(
            rec_sub, "报单", "已发送",
            data={"text": "1", "leaves_qty": "100"},
            raw="8=FIX.4.2|9=213|35=D|34=2|49=209TEST|50=P1100209|56=CMSITYPROD|"
                "1=P1100209|11=6201794888900102|15=CNY|21=1|38=100|40=2|44=10.10|54=1|"
                "55=600000|58=1|59=0|167=CS|207=SH|10=144|",
            stamp="09:31:10")
    rec_cancel = app.orders.get("6201794888900105")
    if rec_cancel:
        app._append_event(
            rec_cancel, "撤单请求", "撤单已发送",
            data={"text": "用户撤单"},
            raw="8=FIX.4.2|9=108|35=F|34=6|49=209TEST|50=P1100209|56=CMSITYPROD|"
                "1=P1100209|11=6201794888900205|41=6201794888900105|54=1|55=600000|"
                "58=用户撤单|60=20261117-09:31:20.100|10=187|",
            stamp="09:31:20.100")

    app._poll_events()
    app.update()
    time.sleep(0.4)

    app.lift()
    try:
        app.attributes("-topmost", True)
    except Exception:  # noqa: BLE001
        pass

    shots = (
        (1, "order", None),
        (2, "query", lambda: app.query_notebook.select(app.query_tables["FP"]["frame"])),
        (2, "query-position", lambda: app.query_notebook.select(app.query_tables["AP"]["frame"])),
    )
    for index, name, prepare in shots:
        app.notebook.select(index)
        if prepare:
            prepare()
        app.update_idletasks()
        app.update()
        time.sleep(0.5)
        x, y = app.winfo_rootx(), app.winfo_rooty()
        w, h = app.winfo_width(), app.winfo_height()
        path = os.path.join(ROOT, "docs", "screenshot-%s.png" % name)
        os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
        ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True).save(path)
        print("saved", path)

    # 明细弹窗（回报时间线）
    app.notebook.select(1)
    app.update()
    app.order_tree.selection_set("6201794888900102")
    app.update()
    app._show_order_detail()
    app.update(); time.sleep(0.6)
    dlg = next((c for c in app.winfo_children() if isinstance(c, __import__("tkinter").Toplevel)), None)
    if dlg is not None:
        dlg.attributes("-topmost", True)
        dlg.lift(); dlg.update(); time.sleep(0.5)
        dx, dy = dlg.winfo_rootx(), dlg.winfo_rooty()
        dw, dh = dlg.winfo_width(), dlg.winfo_height()
        ImageGrab.grab(bbox=(dx, dy, dx + dw, dy + dh), all_screens=True).save(
            os.path.join(ROOT, "docs", "screenshot-detail.png"))
        print("saved detail", dw, dh)

    app.destroy()
    print("demo done")


if __name__ == "__main__":
    main()
