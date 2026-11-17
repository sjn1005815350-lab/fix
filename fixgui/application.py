# -*- coding: utf-8 -*-
"""QuickFIX 应用回调：把会话事件、原始报文、成交回报抛给界面。"""
from __future__ import annotations

from datetime import datetime

import quickfix as q

from . import parser


def _now():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


class FixApplication(q.Application):
    """移植自原 ``Application``，去掉了 print，改为事件回调。"""

    def __init__(self, emit):
        q.Application.__init__(self)
        self.emit = emit
        self.session_id = None
        self.settings = None
        self.sender_sub_id = ""

    def set_settings(self, settings):
        self.settings = settings

    # ---------------------------------------------------------- 生命周期 --
    def onCreate(self, sessionID):
        try:
            self.session_id = sessionID
            try:
                self.sender_sub_id = self.settings.get(sessionID).getString("SenderSubID")
            except Exception:  # noqa: BLE001 - 未配置 SenderSubID 属于正常情况
                self.sender_sub_id = ""
            self._emit("session", state="created", detail=sessionID.toString())
        except Exception as exc:  # noqa: BLE001
            self._emit("error", text="onCreate 异常: %s" % exc)

    def onLogon(self, sessionID):
        self._emit("session", state="logon", detail=sessionID.toString())

    def onLogout(self, sessionID):
        self._emit("session", state="logout", detail=sessionID.toString())

    # ---------------------------------------------------------- 管理员报文 --
    def toAdmin(self, message, sessionID):
        try:
            msgtype = parser.msg_type(message)
            if msgtype == q.MsgType_Heartbeat:
                self._raw("S", "heartbeat", msgtype, message)
                return
            if self.sender_sub_id:
                message.getHeader().setField(q.SenderSubID(self.sender_sub_id))
            self._raw("S", "admin", msgtype, message)
        except Exception as exc:  # noqa: BLE001
            self._emit("error", text="toAdmin 异常: %s" % exc)

    def fromAdmin(self, message, sessionID):
        try:
            msgtype = parser.msg_type(message)
            if msgtype == q.MsgType_Heartbeat:
                self._raw("R", "heartbeat", msgtype, message)
                return
            self._raw("R", "admin", msgtype, message)
        except Exception as exc:  # noqa: BLE001
            self._emit("error", text="fromAdmin 异常: %s" % exc)

    # ---------------------------------------------------------- 业务报文 --
    def toApp(self, message, sessionID):
        try:
            self._raw("S", "app", parser.msg_type(message), message)
        except Exception as exc:  # noqa: BLE001
            self._emit("error", text="toApp 异常: %s" % exc)

    def fromApp(self, message, sessionID):
        try:
            msgtype = parser.msg_type(message)
            self._raw("R", "app", msgtype, message)
            self.dispatch(message, msgtype)
        except Exception as exc:  # noqa: BLE001
            self._emit("error", text="fromApp 异常: %s" % exc)

    # ---------------------------------------------------------- 内部工具 --
    def dispatch(self, message, msgtype=None):
        """识别成交回报、撤单拒绝、查询应答。"""
        msgtype = msgtype or parser.msg_type(message)
        if msgtype == q.MsgType_ExecutionReport:      # 8
            self._emit("exec", data=parser.parse_exec_report(message), time=_now())
        elif msgtype == q.MsgType_OrderCancelReject:  # 9
            self._emit("cancel_reject", data=parser.parse_exec_report(message), time=_now())
        elif msgtype in parser.QUERY_RESPONSE_TYPES:
            data = parser.parse_query_response(message)
            data["label"] = parser.QUERY_RESPONSE_TYPES[msgtype]
            self._emit("query", data=data, time=_now())
        elif msgtype:
            data = parser.parse_query_response(message)
            data["label"] = "未知应答 (%s)" % msgtype
            self._emit("query", data=data, time=_now())

    def _raw(self, direction, category, msgtype, message):
        self._emit(
            "raw",
            direction=direction,
            category=category,
            msgtype=msgtype or "",
            text=parser.raw_text(message),
            time=_now(),
        )

    def _emit(self, kind, **payload):
        payload["kind"] = kind
        try:
            self.emit(payload)
        except Exception:  # noqa: BLE001 - 界面已退出时不再抛错
            pass
