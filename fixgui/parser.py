# -*- coding: utf-8 -*-
"""FIX 报文解析：把 quickfix 消息拆成 tag/值，并识别成交回报、查询结果。"""
from __future__ import annotations

SOH = "\x01"

# 委托状态（39）
ORD_STATUS_CN = {
    "0": "已报", "1": "部成", "2": "已成", "3": "部撤", "4": "已撤",
    "5": "已改", "6": "待撤", "8": "拒绝", "9": "挂起", "A": "待报",
    "B": "计算中", "C": "已过期", "D": "已报", "E": "待改",
}

# 执行类型（150）
EXEC_TYPE_CN = {
    "0": "已报", "1": "部成", "2": "已成", "3": "完成", "4": "已撤",
    "5": "已改", "6": "待撤", "7": "成交", "8": "拒绝", "9": "挂起",
    "A": "待报", "B": "计算中", "C": "已过期", "D": "已报", "E": "待改",
    "F": "成交", "G": "待确认", "H": "已确认", "I": "已取消",
}

# 查询应答的消息类型
QUERY_RESPONSE_TYPES = {
    "FP": "资金查询结果",
    "AP": "持仓查询结果",
    "SP": "额度查询结果",
    "LS": "登录结果",
    "QS": "查询结果",
}

ACTIVE_STATUS = {"已报", "部成", "待撤", "待报", "已改", "挂起", "计算中"}


def raw_text(message):
    """把消息转成可读的单行文本（SOH 换成 |）。"""
    try:
        text = message.toString()
    except Exception:  # noqa: BLE001
        text = str(message)
    return text.replace(SOH, "|")


def pairs(message):
    """把消息拆成 [(tag 字符串, 值)]，保持原始顺序。"""
    text = message if isinstance(message, str) else raw_text(message)
    out = []
    for chunk in text.split("|" if "|" in text else SOH):
        if not chunk:
            continue
        if "=" in chunk:
            tag, value = chunk.split("=", 1)
            out.append((tag.strip(), value))
    return out


def get(message, tag, default=None):
    """读取第一个匹配的字段值。message 可以是消息对象、原始字符串或 pairs 列表。"""
    if isinstance(message, list):
        items = message
    else:
        items = pairs(message)
    tag = str(tag)
    for item_tag, value in items:
        if item_tag == tag:
            return value
    return default


def msg_type(message):
    return get(message, 35)


def status_display(ord_status, exec_type):
    """根据 39/150 计算界面显示的中文状态。"""
    if ord_status and ord_status in ORD_STATUS_CN:
        return ORD_STATUS_CN[ord_status]
    if exec_type and exec_type in EXEC_TYPE_CN:
        return EXEC_TYPE_CN[exec_type]
    return ""


def is_active(status):
    return status in ACTIVE_STATUS


def parse_exec_report(message):
    """成交回报 -> 订单字段字典。"""
    items = pairs(message)
    data = {
        "clordid": get(items, 11),
        "orig_clordid": get(items, 41),
        "orderid": get(items, 37),
        "execid": get(items, 17),
        "exec_type": get(items, 150),
        "ord_status": get(items, 39),
        "cum_qty": get(items, 14),
        "leaves_qty": get(items, 151),
        "avg_px": get(items, 6),
        "last_px": get(items, 31),
        "last_qty": get(items, 32),
        "symbol": get(items, 55),
        "side": get(items, 54),
        "qty": get(items, 38),
        "price": get(items, 44),
        "text": get(items, 58),
        "account": get(items, 1),
        "transact_time": get(items, 60),
        "ord_type": get(items, 40),
        "time_in_force": get(items, 59),
        "rej_reason": get(items, 103) or get(items, 102),
    }
    data["status"] = status_display(data["ord_status"], data["exec_type"])
    data["active"] = is_active(data["status"])
    data["pairs"] = items
    return data


def parse_query_response(message):
    """查询应答 -> 字段字典（字段名取自数据字典）。"""
    items = pairs(message)
    msgtype = get(items, 35) or ""
    data = {
        "msgtype": msgtype,
        "clordid": get(items, 11),
        "account": get(items, 1),
        "text": get(items, 58),
        "pairs": items,
    }
    return data


def side_text(side):
    s = (side or "").strip()
    if s.upper() in ("1", "B", "BUY"):
        return "买入"
    if s.upper() in ("2", "S", "SELL"):
        return "卖出"
    return s
