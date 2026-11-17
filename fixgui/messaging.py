# -*- coding: utf-8 -*-
"""FIX 报文组装。

移植自原项目 ``fix_application.py``，保留全部字段映射，改为从界面收集的字典生成报文。
"""
from __future__ import annotations

from datetime import datetime

import quickfix as q

SOH = "\x01"
MSG_TYPE_NEW_ORDER = q.MsgType_NewOrderSingle          # D
MSG_TYPE_CANCEL = q.MsgType_OrderCancelRequest         # F


class MessageBuildError(Exception):
    """报文参数不合法时抛出，界面直接提示用户。"""


# 中文输入法全角字符 -> 半角，避免 "１０．５" 这类输入被判为非法
_FULLWIDTH_TABLE = str.maketrans(
    "０１２３４５６７８９．，－＋", "0123456789.,-+"
)


def number(value):
    """把界面上的文本转成 int / float；空值返回 None。"""
    if value is None:
        return None
    text = str(value).translate(_FULLWIDTH_TABLE).strip().replace(",", "")
    if text == "":
        return None
    try:
        num = float(text)
    except ValueError:
        raise MessageBuildError("“%s”不是合法数字" % value)
    return int(num) if num.is_integer() else num


def _new(msgtype, sender_sub_id=None):
    message = q.Message()
    header = message.getHeader()
    if sender_sub_id:
        header.setField(q.SenderSubID(sender_sub_id))
    header.setField(q.MsgType(msgtype))
    return message


def _set_transact_time(message):
    field = q.TransactTime()
    # 与原脚本保持一致：%Y%m%d-%H:%M:%S.mmm，用 setString 绕开 UTC 时间格式校验
    field.setString(datetime.now().strftime("%Y%m%d-%H:%M:%S.%f")[:-3])
    message.setField(field)


def _side(value):
    text = str(value or "").strip()
    upper = text.upper()
    if upper in ("BUY", "B", "1", "买入") or text == "buy":
        return q.Side_BUY
    if upper in ("SELL", "S", "2", "卖出") or text == "sell":
        return q.Side_SELL
    return text


def _ord_type(value):
    text = str(value or "").strip()
    if text in ("Limit", "LIMIT", "2", "限价"):
        return q.OrdType_LIMIT
    if text in ("Market", "MARKET", "1", "市价"):
        return q.OrdType_MARKET
    return text


def _time_in_force(value):
    text = str(value or "").strip()
    mapping = {
        "Day": q.TimeInForce_DAY,
        "DAY": q.TimeInForce_DAY,
        "0": q.TimeInForce_DAY,
        "FillAndKill": q.TimeInForce_IMMEDIATE_OR_CANCEL,
        "IOC": q.TimeInForce_IMMEDIATE_OR_CANCEL,
        "3": q.TimeInForce_IMMEDIATE_OR_CANCEL,
        "FillOrKill": q.TimeInForce_FILL_OR_KILL,
        "FOK": q.TimeInForce_FILL_OR_KILL,
        "4": q.TimeInForce_FILL_OR_KILL,
    }
    return mapping.get(text, text)


def _handl_inst(value):
    text = str(value or "").strip()
    mapping = {
        "DMA": q.HandlInst_AUTOMATED_EXECUTION_ORDER_PRIVATE_NO_BROKER_INTERVENTION,      # 1
        "DMA审批": q.HandlInst_AUTOMATED_EXECUTION_ORDER_PUBLIC_BROKER_INTERVENTION_OK,    # 2
        "DMA审批下单": q.HandlInst_AUTOMATED_EXECUTION_ORDER_PUBLIC_BROKER_INTERVENTION_OK,
        "Manual Order": q.HandlInst_MANUAL_ORDER_BEST_EXECUTION,                           # 3
        "Manual": q.HandlInst_MANUAL_ORDER_BEST_EXECUTION,
        "1": q.HandlInst_AUTOMATED_EXECUTION_ORDER_PRIVATE_NO_BROKER_INTERVENTION,
        "2": q.HandlInst_AUTOMATED_EXECUTION_ORDER_PUBLIC_BROKER_INTERVENTION_OK,
        "3": q.HandlInst_MANUAL_ORDER_BEST_EXECUTION,
    }
    return mapping.get(text, text)


def _position_effect(value):
    text = str(value or "").strip()
    mapping = {
        "open": q.PositionEffect_OPEN,
        "O": q.PositionEffect_OPEN,
        "close": q.PositionEffect_CLOSE,
        "C": q.PositionEffect_CLOSE,
        "default": q.PositionEffect_DEFAULT,
        "D": q.PositionEffect_DEFAULT,
        "rolled": q.PositionEffect_ROLLED,
    }
    return mapping.get(text, text)


def _security_type(value):
    text = str(value or "").strip()
    mapping = {"STOCK": "CS", "INDEX_FUTURE": "FUT"}
    return mapping.get(text, text)


def apply_extras(message, extras):
    """写入用户自定义的附加字段（tag=value）。"""
    for tag, value in extras or []:
        tag_text = str(tag).strip()
        if not tag_text:
            continue
        try:
            tag_int = int(tag_text)
        except ValueError:
            raise MessageBuildError("附加字段的 tag 必须是数字：%s" % tag_text)
        message.setField(tag_int, str(value))


def build_new_order(order, sender_sub_id=None):
    """新建委托（35=D）。

    order 支持字段：
        clordid / account / client_id / symbol / exchange / security_type /
        side / ordtype / qty / price / tif / handl_inst / position_effect /
        strategy / currency / remark / extras
    """
    if not order.get("symbol"):
        raise MessageBuildError("下单缺少交易标的（55 Symbol）")
    if number(order.get("qty")) is None:
        raise MessageBuildError("下单缺少委托数量（38 OrderQty）")

    message = _new(MSG_TYPE_NEW_ORDER, sender_sub_id)
    message.setField(q.ClOrdID(order["clordid"]))
    if order.get("account"):
        message.setField(q.Account(order["account"]))
    if order.get("currency"):
        message.setField(q.Currency(order["currency"]))
    if order.get("exchange"):
        message.setField(q.SecurityExchange(order["exchange"]))
    message.setField(q.Symbol(order["symbol"]))
    if order.get("side"):
        message.setField(q.Side(_side(order["side"])))
    message.setField(q.OrderQty(number(order["qty"])))
    # 市价单不带价格字段（即使界面上残留了价格）
    ordtype_value = _ord_type(order["ordtype"]) if order.get("ordtype") else None
    if ordtype_value is not None:
        message.setField(q.OrdType(ordtype_value))
    price = number(order.get("price"))
    if price is not None and ordtype_value != q.OrdType_MARKET:
        message.setField(q.Price(price))
    if order.get("tif"):
        message.setField(q.TimeInForce(_time_in_force(order["tif"])))
    if order.get("handl_inst"):
        message.setField(q.HandlInst(_handl_inst(order["handl_inst"])))
    if order.get("remark"):
        message.setField(q.Text(order["remark"]))
    if order.get("client_id"):
        message.setField(q.ClientID(order["client_id"]))
    if order.get("security_type"):
        message.setField(q.SecurityType(_security_type(order["security_type"])))
    if order.get("position_effect"):
        message.setField(q.PositionEffect(_position_effect(order["position_effect"])))
    if order.get("strategy"):
        message.setField(951, str(order["strategy"]))

    apply_extras(message, order.get("extras"))
    _set_transact_time(message)
    return message


def build_cancel_order(order, sender_sub_id=None):
    """撤单（35=F）。"""
    if not order.get("orig_clordid"):
        raise MessageBuildError("撤单缺少原始委托号（41 OrigClOrdID）")
    if not order.get("symbol"):
        raise MessageBuildError("撤单缺少交易标的（55 Symbol）")

    message = _new(MSG_TYPE_CANCEL, sender_sub_id)
    message.setField(q.ClOrdID(order["clordid"]))
    message.setField(q.OrigClOrdID(order["orig_clordid"]))
    if order.get("account"):
        message.setField(q.Account(order["account"]))
    if order.get("symbol"):
        message.setField(q.Symbol(order["symbol"]))
    if order.get("side"):
        message.setField(q.Side(_side(order["side"])))
    if order.get("text"):
        message.setField(q.Text(order["text"]))
    apply_extras(message, order.get("extras"))
    _set_transact_time(message)
    return message


def _build_query(msgtype, order, sender_sub_id=None):
    message = _new(msgtype, sender_sub_id)
    message.setField(q.ClOrdID(order["clordid"]))
    if order.get("account"):
        message.setField(q.Account(order["account"]))
    if order.get("text"):
        message.setField(q.Text(order["text"]))
    apply_extras(message, order.get("extras"))
    return message


def build_fund_query(order, sender_sub_id=None):
    """资金查询 35=FD。"""
    return _build_query("FD", order, sender_sub_id)


def build_position_query(order, sender_sub_id=None):
    """持仓查询 35=AN。"""
    return _build_query("AN", order, sender_sub_id)


def build_quota_query(order, sender_sub_id=None):
    """额度查询 35=SC。"""
    return _build_query("SC", order, sender_sub_id)


def build_login(user_name, password, sender_sub_id=None):
    """登录 35=LR（931 用户名 / 932 密码）。"""
    if not user_name:
        raise MessageBuildError("登录缺少用户名（931）")
    if not password:
        raise MessageBuildError("登录缺少密码（932）")
    message = _new("LR", sender_sub_id)
    message.setField(931, str(user_name))
    message.setField(932, str(password))
    return message


def message_text(message):
    """单行可读报文（SOH -> |）。"""
    return message.toString().replace(SOH, "|")


def message_pairs(message):
    text = message_text(message)
    out = []
    for chunk in text.split("|"):
        if chunk and "=" in chunk:
            tag, value = chunk.split("=", 1)
            out.append((tag, value))
    return out
