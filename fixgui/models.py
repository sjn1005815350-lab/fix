# -*- coding: utf-8 -*-
"""界面用到的枚举选项与委托记录结构。"""
from __future__ import annotations


class Choice(object):
    """下拉框选项：显示中文标签，保存 FIX 原始值。"""

    def __init__(self, pairs):
        self.pairs = list(pairs)
        self.labels = [label for _value, label in self.pairs]
        self._label_to_value = {label: value for value, label in self.pairs}
        self._value_to_label = {value: label for value, label in self.pairs}

    def value(self, label):
        """标签 -> FIX 值；如果用户手动输入了别的内容，原样返回。"""
        if label in self._label_to_value:
            return self._label_to_value[label]
        for value, text in self.pairs:
            if label == value:
                return value
        return label

    def label(self, value):
        return self._value_to_label.get(value, value)


SIDE = Choice([("buy", "买入 (buy)"), ("sell", "卖出 (sell)")])

ORD_TYPE = Choice([("Limit", "限价 (Limit)"), ("Market", "市价 (Market)")])

TIME_IN_FORCE = Choice([
    ("Day", "当日有效 (Day)"),
    ("FillAndKill", "立即成交剩余撤销 (IOC)"),
    ("FillOrKill", "全部成交否则撤销 (FOK)"),
])

HANDL_INST = Choice([
    ("DMA", "DMA 自动执行 (1)"),
    ("DMA审批", "DMA 需经纪商确认 (2)"),
    ("Manual Order", "人工执行 (3)"),
])

POSITION_EFFECT = Choice([
    ("default", "默认 (D)"),
    ("open", "开仓 (O)"),
    ("close", "平仓 (C)"),
])

SECURITY_TYPE = Choice([
    ("STOCK", "股票 STOCK → CS"),
    ("INDEX_FUTURE", "股指期货 INDEX_FUTURE → FUT"),
])

CLORDID_MODE = Choice([
    ("时间戳", "前缀 + 毫秒时间戳"),
    ("顺序号", "前缀 + 递增序号"),
])

# 委托列表列定义：(内部键, 标题, 宽度)
ORDER_COLUMNS = [
    ("time", "委托时间", 66),
    ("clordid", "本地委托号", 140),
    ("symbol", "代码", 60),
    ("side", "方向", 42),
    ("qty", "成交量/委托", 96),
    ("price", "价格", 58),
    ("status", "状态", 56),
    ("orderid", "柜台委托号", 100),
]

# 委托记录的默认值
def empty_order():
    return {
        "time": "",
        "clordid": "",
        "orig_clordid": "",
        "orderid": "",
        "symbol": "",
        "side": "",
        "qty": "",
        "price": "",
        "status": "",
        "filled": "0",
        "leaves": "",
        "avg_px": "",
        "account": "",
        "text": "",
        "last_raw": "",
        "active": True,
        # 单笔委托的回报时间线：报单 / 撤单请求 / 委托回报 / 成交回报 / 撤单回报 / 撤单拒绝
        "events": [],
        "created": "",
        "updated": "",
    }
