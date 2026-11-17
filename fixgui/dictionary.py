# -*- coding: utf-8 -*-
"""FIX 数据字典：把 tag 号翻译成字段名、枚举值翻译成中文/英文说明。"""
from __future__ import annotations

import xml.etree.ElementTree as ET

# 字典加载失败时的兜底映射，保证界面仍然可读
_FALLBACK_TAGS = {
    1: "Account", 6: "AvgPx", 8: "BeginString", 9: "BodyLength", 10: "CheckSum",
    11: "ClOrdID", 14: "CumQty", 15: "Currency", 17: "ExecID", 18: "ExecInst",
    21: "HandlInst", 22: "SecurityIDSource", 30: "LastMkt", 31: "LastPx",
    32: "LastQty", 34: "MsgSeqNum", 35: "MsgType", 37: "OrderID", 38: "OrderQty",
    39: "OrdStatus", 40: "OrdType", 41: "OrigClOrdID", 43: "PossDupFlag",
    44: "Price", 49: "SenderCompID", 50: "SenderSubID", 52: "SendingTime",
    54: "Side", 55: "Symbol", 56: "TargetCompID", 57: "TargetSubID",
    58: "Text", 59: "TimeInForce", 60: "TransactTime", 77: "PositionEffect",
    89: "Signature", 90: "SecureDataLen", 91: "SecureData", 93: "SignatureLength",
    95: "RawDataLength", 96: "RawData", 97: "PossResend", 98: "EncryptMethod",
    99: "StopPx", 100: "SecurityExchange", 102: "CxlRejReason", 103: "OrdRejReason",
    106: "Issuer", 107: "SecurityDesc", 108: "HeartBtInt", 109: "ClientID",
    110: "MinQty", 111: "MaxFloor", 112: "TestReqID", 141: "ResetSeqNumFlag",
    150: "ExecType", 151: "LeavesQty", 167: "SecurityType", 198: "SecondaryOrderID",
    207: "SecurityExchange", 381: "GrossTradeAmt", 423: "PriceType",
    448: "PartyID", 452: "PartyRole", 453: "NoPartyIDs", 931: "LoginUserName",
    932: "LoginPassWord", 951: "StrategyName", 11000: "LendingFlag",
}

# 常见枚举的中文说明（字典里有就用字典的）
_ENUM_CN = {
    ("54", "1"): "买入",
    ("54", "2"): "卖出",
    ("40", "1"): "市价",
    ("40", "2"): "限价",
    ("59", "0"): "当日有效",
    ("59", "3"): "IOC 立即成交剩余撤销",
    ("59", "4"): "FOK 全部成交否则撤销",
    ("39", "0"): "已报",
    ("39", "1"): "部分成交",
    ("39", "2"): "全部成交",
    ("39", "3"): "部分撤单",
    ("39", "4"): "已撤单",
    ("39", "5"): "已改单",
    ("39", "6"): "待撤单",
    ("39", "8"): "已拒绝",
    ("39", "9"): "挂起",
    ("39", "A"): "待报",
    ("39", "C"): "已过期",
    ("150", "0"): "已报",
    ("150", "1"): "部分成交",
    ("150", "2"): "全部成交",
    ("150", "4"): "已撤单",
    ("150", "5"): "已改单",
    ("150", "6"): "待撤单",
    ("150", "8"): "已拒绝",
    ("150", "9"): "挂起",
    ("150", "F"): "成交",
    ("21", "1"): "DMA 自动执行",
    ("21", "2"): "DMA 需经纪商干预",
    ("21", "3"): "人工执行",
    ("77", "O"): "开仓",
    ("77", "C"): "平仓",
    ("77", "D"): "默认",
    ("77", "R"): "转开仓",
}


class FixDictionary(object):
    """懒加载的 FIX 字典。"""

    def __init__(self, path=None):
        self.path = str(path) if path else None
        self.tags = {}
        self.enums = {}
        self.messages = {}
        self.loaded = False
        self.error = ""
        if self.path:
            self.load(self.path)

    # ------------------------------------------------------------------
    def load(self, path):
        try:
            root = ET.parse(path).getroot()
        except Exception as exc:  # noqa: BLE001 - 字典缺失不应让程序启动失败
            self.error = str(exc)
            return False

        for node in root.iter("field"):
            number = node.get("number")
            if not number:
                continue
            try:
                tag = int(number)
            except ValueError:
                continue
            name = node.get("name")
            if name and tag not in self.tags:
                self.tags[tag] = name
            values = {}
            for value in node.findall("value"):
                enum = value.get("enum")
                desc = value.get("description") or ""
                if enum is not None:
                    values[enum] = desc
            if values:
                self.enums[tag] = values

        for node in root.iter("message"):
            msgtype = node.get("msgtype")
            if msgtype:
                self.messages[msgtype] = node.get("name") or msgtype

        self.loaded = True
        return True

    # ------------------------------------------------------------------
    def name(self, tag):
        try:
            tag = int(tag)
        except (TypeError, ValueError):
            return str(tag)
        name = self.tags.get(tag) or _FALLBACK_TAGS.get(tag)
        return name or str(tag)

    def label(self, tag):
        name = self.name(tag)
        if name == str(tag):
            return str(tag)
        return "%s (%s)" % (name, tag)

    def value_label(self, tag, value):
        """把字段值翻译成“值 说明”，用于日志和结果表。"""
        try:
            tag_int = int(tag)
        except (TypeError, ValueError):
            return str(value)
        text = str(value)
        cn = _ENUM_CN.get((str(tag_int), text))
        if cn:
            return "%s (%s)" % (text, cn)
        desc = (self.enums.get(tag_int) or {}).get(text)
        if desc:
            return "%s (%s)" % (text, desc)
        return text

    def message_name(self, msgtype):
        if not msgtype:
            return ""
        return self.messages.get(msgtype, msgtype)

    def describe_pairs(self, pairs):
        """[(tag, value)] -> [(tag, 名称, 值)]"""
        return [(tag, self.label(tag), self.value_label(tag, value)) for tag, value in pairs]


_instance = None


def get_dictionary(path=None):
    global _instance
    if _instance is None:
        _instance = FixDictionary(path)
    elif path and not _instance.loaded and _instance.path != str(path):
        _instance = FixDictionary(path)
    return _instance
