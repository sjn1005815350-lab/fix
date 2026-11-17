# -*- coding: utf-8 -*-
"""离线自检：不连接网关，只验证配置、报文组装、字典与界面能否正常构建。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from fixgui import config_store, messaging, parser  # noqa: E402
from fixgui.dictionary import get_dictionary  # noqa: E402


def main():
    settings = config_store.load_settings()
    options = config_store.load_options()
    profile = settings["profiles"][settings["active_profile"]]
    print("[1] 配置档案:", settings["active_profile"])
    print("    host=%s port=%s sender=%s target=%s sub=%s"
          % (profile["SocketConnectHost"], profile["SocketConnectPort"],
             profile["SenderCompID"], profile["TargetCompID"], profile["SenderSubID"]))
    print("    下拉字典组:", len(options), "资金账号:", options["account"][:3])

    order = {
        "clordid": "620170000000000001",
        "account": "P1100209",
        "client_id": "1100209",
        "symbol": "600000",
        "exchange": "SH",
        "security_type": "STOCK",
        "side": "buy",
        "ordtype": "Limit",
        "qty": "100",
        "price": "10.10",
        "tif": "Day",
        "handl_inst": "DMA",
        "position_effect": "default",
        "strategy": "",
        "currency": "CNY",
        "remark": "1",
        "extras": [("11000", "3")],
    }
    msg = messaging.build_new_order(order, profile["SenderSubID"])
    print("[2] 新建委托:", messaging.message_text(msg))

    cancel = {"clordid": "620170000000000002", "orig_clordid": order["clordid"],
              "symbol": "600000", "side": "buy", "account": "P1100209", "text": "撤单"}
    print("[3] 撤单:", messaging.message_text(messaging.build_cancel_order(cancel, "P1100209")))

    query = {"clordid": "620170000000000003", "account": "P1100209"}
    print("[5] 资金查询:", messaging.message_text(messaging.build_fund_query(query, "P1100209")))
    print("[6] 登录:", messaging.message_text(messaging.build_login("user", "pwd", "P1100209")))

    dictionary = get_dictionary(str(config_store.DICT_DIR / "FIX42-server.xml"))
    print("[7] 字典:", dictionary.loaded, "字段数", len(dictionary.tags),
          "| 39 名称", dictionary.name(39), "| 39=2 ->", dictionary.value_label(39, "2"),
          "| 35=8 ->", dictionary.message_name("8"))

    sample = ("8=FIX.4.2|9=200|35=8|34=5|11=620170000000000001|37=123456|17=EX1|"
              "150=2|39=2|55=600000|54=1|38=100|44=10.10|14=100|151=0|6=10.10|58=全部成交|10=123|")
    data = parser.parse_exec_report(sample)
    print("[8] 回报解析:", data["clordid"], data["status"], "成交", data["cum_qty"], "剩余", data["leaves_qty"])

    from fixgui.engine import FixEngine
    engine = FixEngine(lambda event: None)
    print("[9] 生成 cfg:\n" + engine.build_cfg(profile))

    from fixgui.ui import FixOrderApp
    app = FixOrderApp()
    app.update_idletasks()
    app.update()
    print("[10] 界面构建成功: %dx%d，标签页 %d 个"
          % (app.winfo_width(), app.winfo_height(), len(app.notebook.tabs())))
    app.destroy()
    print("OK 全部自检通过")


if __name__ == "__main__":
    main()
