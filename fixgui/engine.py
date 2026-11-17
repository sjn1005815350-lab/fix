# -*- coding: utf-8 -*-
"""QuickFIX 会话引擎：根据界面配置生成 client.cfg、启动/停止会话、发送报文。"""
from __future__ import annotations

import os
import threading

import quickfix as q

from . import config_store, messaging
from .application import FixApplication
from .config_store import APP_ROOT, RUNTIME_DIR


class EngineError(Exception):
    """连接/发送失败，界面直接弹窗提示。"""


REQUIRED_KEYS = ("SocketConnectHost", "SocketConnectPort", "SenderCompID", "TargetCompID")


class FixEngine(object):
    def __init__(self, emit):
        self.emit = emit
        self._lock = threading.RLock()
        self.initiator = None
        self.application = None
        self.settings = None
        self.profile = None
        self.cfg_path = RUNTIME_DIR / "client_runtime.cfg"
        self.cfg_text = ""

    # ------------------------------------------------------------ 状态 --
    @property
    def session_id(self):
        return self.application.session_id if self.application else None

    @property
    def sender_sub_id(self):
        return self.application.sender_sub_id if self.application else ""

    @property
    def running(self):
        return self.initiator is not None

    def logged_on(self):
        try:
            if self.session_id is None:
                return False
            session = q.Session.lookupSession(self.session_id)
            return bool(session and session.isLoggedOn())
        except Exception:  # noqa: BLE001
            return False

    def session_text(self):
        if self.session_id is None:
            return "未建立会话"
        try:
            return self.session_id.toString()
        except Exception:  # noqa: BLE001
            return "未知会话"

    # ------------------------------------------------------------ 配置 --
    def build_cfg(self, profile):
        """把界面上的连接参数渲染成 QuickFIX 配置文本。"""
        missing = [key for key in REQUIRED_KEYS if not str(profile.get(key, "")).strip()]
        if missing:
            raise EngineError("以下连接参数不能为空：%s" % "、".join(missing))

        try:
            port = int(str(profile.get("SocketConnectPort")).strip())
        except ValueError:
            raise EngineError("端口必须是数字：%s" % profile.get("SocketConnectPort"))
        if not (0 < port < 65536):
            raise EngineError("端口超出范围：%d" % port)

        for key in ("HeartBtInt", "ReconnectInterval", "LogonTimeout"):
            value = str(profile.get(key, "")).strip()
            if value:
                try:
                    int(value)
                except ValueError:
                    raise EngineError("%s 必须是数字：%s" % (key, value))

        dictionary = config_store.resolve_resource(profile.get("DataDictionary"))
        if not os.path.isfile(dictionary):
            raise EngineError("数据字典文件不存在：%s" % dictionary)
        # 正常情况下用相对路径；打包后若字典只在程序内部，才退回绝对路径
        local_dictionary = config_store.rel_path(profile.get("DataDictionary"))
        if os.path.normcase(local_dictionary) == os.path.normcase(dictionary):
            dictionary_setting = self._relative(profile.get("DataDictionary"))
        else:
            dictionary_setting = dictionary

        store_path = config_store.rel_path(profile.get("FileStorePath"))
        os.makedirs(store_path, exist_ok=True)

        reset = "Y" if profile.get("ResetOnLogon") else "N"
        lines = [
            "# 本文件由“FIX 下单助手”根据界面配置自动生成，每次连接都会被覆盖。",
            "[DEFAULT]",
            "ConnectionType=initiator",
            "BeginString=%s" % (profile.get("BeginString") or "FIX.4.2"),
            "DefaultApplVerID=%s" % (profile.get("DefaultApplVerID") or profile.get("BeginString") or "FIX.4.2"),
            "SenderCompID=%s" % profile.get("SenderCompID"),
            "TargetCompID=%s" % profile.get("TargetCompID"),
            "SocketConnectHost=%s" % str(profile.get("SocketConnectHost")).strip(),
            "SocketConnectPort=%d" % port,
            "HeartBtInt=%s" % (str(profile.get("HeartBtInt")).strip() or "30"),
            "ReconnectInterval=%s" % (str(profile.get("ReconnectInterval")).strip() or "60"),
            "LogonTimeout=%s" % (str(profile.get("LogonTimeout")).strip() or "30"),
            "ResetOnLogon=%s" % reset,
            "StartTime=%s" % (str(profile.get("StartTime")).strip() or "00:00:00"),
            "EndTime=%s" % (str(profile.get("EndTime")).strip() or "23:59:59"),
            "DataDictionary=%s" % dictionary_setting,
            "FileStorePath=%s" % self._relative(profile.get("FileStorePath"), ensure_slash=True),
        ]
        if profile.get("UseFileLog"):
            lines.append("FileLogPath=%s" % self._relative(profile.get("FileLogPath"), ensure_slash=True))
        lines.append("")
        lines.append("# session definition")
        lines.append("[SESSION]")
        lines.append("SenderSubID=%s" % (profile.get("SenderSubID") or ""))
        lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _relative(path, ensure_slash=False):
        """配置里统一使用相对路径，避免含中文的绝对路径让 QuickFIX 打不开文件。"""
        if not path:
            return path
        text = str(path).strip()
        if text.startswith("./") or text.startswith("../"):
            result = text
        else:
            candidate = os.path.abspath(text)
            try:
                rel = os.path.relpath(candidate, str(APP_ROOT))
            except ValueError:
                rel = text
            result = "./" + rel.replace("\\", "/") if not os.path.isabs(rel) else text
        if ensure_slash and not result.endswith("/"):
            result += "/"
        return result

    # ------------------------------------------------------------ 连接 --
    def start(self, profile):
        with self._lock:
            self.stop(quiet=True)
            os.chdir(str(APP_ROOT))

            text = self.build_cfg(profile)
            self.cfg_text = text
            self.cfg_path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(self.cfg_path), "w", encoding="utf-8") as fh:
                fh.write(text)

            self.emit({"kind": "session", "state": "connecting",
                       "detail": "%s:%s" % (profile.get("SocketConnectHost"), profile.get("SocketConnectPort"))})

            try:
                settings = q.SessionSettings("runtime/client_runtime.cfg")
                application = FixApplication(self.emit)
                application.set_settings(settings)
                store_factory = q.FileStoreFactory(settings)
                initiator = q.SocketInitiator(application, store_factory, settings)
                self.settings = settings
                self.application = application
                self.initiator = initiator
                self.profile = dict(profile)
                initiator.start()
            except Exception as exc:  # noqa: BLE001
                self.initiator = None
                self.application = None
                self.settings = None
                raise EngineError("启动会话失败：%s" % exc)

            self.emit({"kind": "session", "state": "started", "detail": self.session_text()})

    def stop(self, quiet=False):
        with self._lock:
            initiator = self.initiator
            self.initiator = None
            if initiator is not None:
                try:
                    initiator.stop()
                except Exception as exc:  # noqa: BLE001
                    self.emit({"kind": "error", "text": "停止会话异常：%s" % exc})
            self.application = None
            self.settings = None
            if not quiet:
                self.emit({"kind": "session", "state": "stopped", "detail": ""})

    def logout(self):
        try:
            if self.session_id is not None:
                session = q.Session.lookupSession(self.session_id)
                if session and session.isLoggedOn():
                    session.logout()
                    self.emit({"kind": "session", "state": "logging_out", "detail": ""})
                    return
        except Exception as exc:  # noqa: BLE001
            raise EngineError("登出失败：%s" % exc)
        raise EngineError("当前没有已登录的会话")

    def reset_sequence(self, profile):
        """删除本地序号文件，让下一次连接从 1 开始。"""
        self.stop()
        store_path = config_store.rel_path(profile.get("FileStorePath")) or str(config_store.STORE_DIR)
        begin = (profile.get("BeginString") or "FIX.4.2").replace(":", "-")
        prefix = "%s-%s-%s." % (begin, profile.get("SenderCompID"), profile.get("TargetCompID"))
        removed = 0
        if os.path.isdir(store_path):
            for name in os.listdir(store_path):
                if name.startswith(prefix):
                    try:
                        os.remove(os.path.join(store_path, name))
                        removed += 1
                    except OSError:
                        pass
        self.emit({"kind": "system", "text": "已重置序号文件 %d 个（%s）" % (removed, prefix + "*")})
        return removed

    # ------------------------------------------------------------ 发送 --
    def _send(self, message, description):
        if self.initiator is None or self.session_id is None:
            raise EngineError("会话尚未建立，请先到“连接配置”页点击“连接”")
        if not self.logged_on():
            raise EngineError("会话还没有登录成功，请等待登录完成后再%s" % description)
        try:
            ok = q.Session.sendToTarget(message, self.session_id)
        except Exception as exc:  # noqa: BLE001
            raise EngineError("发送%s失败：%s" % (description, exc))
        if not ok:
            raise EngineError("发送%s失败：会话不可用" % description)
        return message

    def send_new_order(self, order):
        message = messaging.build_new_order(order, self.sender_sub_id)
        return self._send(message, "委托")

    def send_cancel(self, order):
        message = messaging.build_cancel_order(order, self.sender_sub_id)
        return self._send(message, "撤单")


    def send_fund_query(self, order):
        message = messaging.build_fund_query(order, self.sender_sub_id)
        return self._send(message, "资金查询")

    def send_position_query(self, order):
        message = messaging.build_position_query(order, self.sender_sub_id)
        return self._send(message, "持仓查询")

    def send_quota_query(self, order):
        message = messaging.build_quota_query(order, self.sender_sub_id)
        return self._send(message, "额度查询")

    def send_login(self, user_name, password):
        message = messaging.build_login(user_name, password, self.sender_sub_id)
        return self._send(message, "登录请求")
