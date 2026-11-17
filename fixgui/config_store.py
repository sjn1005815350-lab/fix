# -*- coding: utf-8 -*-
"""配置、下拉字典与历史委托的持久化。

所有可配置项都保存在 ``config/`` 目录下的 JSON 文件中，界面启动时读取，
修改后立即写回，因此下次打开程序仍然是上次的设置。
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


def is_frozen():
    """是否运行在 PyInstaller 打包出的 exe 里。"""
    return bool(getattr(sys, "frozen", False))


def _app_root():
    if is_frozen():
        # 打包后 __file__ 在临时解包目录里，程序目录应以 exe 所在位置为准
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


APP_ROOT = _app_root()

# 打包后的资源目录（dict/、assets/ 先放在这里，首次运行时复制到 exe 旁边）
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_ROOT)) if is_frozen() else APP_ROOT

CONFIG_DIR = APP_ROOT / "config"
RUNTIME_DIR = APP_ROOT / "runtime"
LOG_DIR = APP_ROOT / "logs"
STORE_DIR = APP_ROOT / "store"
DICT_DIR = APP_ROOT / "dict"
FIX_LOG_DIR = LOG_DIR / "fix"

SETTINGS_FILE = CONFIG_DIR / "settings.json"
OPTIONS_FILE = CONFIG_DIR / "options.json"
ORDERS_FILE = CONFIG_DIR / "orders.json"

SETTINGS_VERSION = 1

# ---------------------------------------------------------------- 连接配置 ----
# 每一项都对应 client.cfg 里的一个键，界面上全部可以修改。
DEFAULT_PROFILE = {
    # 会话标识（仅用于界面区分，不会写进报文）
    "name": "生产环境 CMSITYPROD",
    # 网络连接
    "SocketConnectHost": "47.243.250.240",
    "SocketConnectPort": "37801",
    # 会话标识
    "SenderCompID": "209TEST",
    "TargetCompID": "CMSITYPROD",
    "SenderSubID": "P1100209",
    # 协议版本
    "BeginString": "FIX.4.2",
    "DefaultApplVerID": "FIX.4.2",
    # 心跳与重连
    "HeartBtInt": "30",
    "ReconnectInterval": "60",
    "LogonTimeout": "30",
    "ResetOnLogon": True,
    # 交易时段
    "StartTime": "00:00:00",
    "EndTime": "23:59:59",
    # 路径
    "DataDictionary": "./dict/FIX42-server.xml",
    "FileStorePath": "./store/",
    "FileLogPath": "./logs/fix/",
    "UseFileLog": False,
    # 本地委托编号规则
    "ClOrdIdPrefix": "620",
    "ClOrdIdMode": "时间戳",  # 时间戳 / 顺序号
    "ClOrdIdStart": "1",
}

PROFILE_FIELDS = [
    # (键, 界面标签, 说明, 是否需要持久化)
    ("SocketConnectHost", "服务器地址 SocketConnectHost", "网关 IP 或域名", "str"),
    ("SocketConnectPort", "端口 SocketConnectPort", "网关端口，例如 37801", "str"),
    ("SenderCompID", "发送方 SenderCompID", "本方机构代码", "str"),
    ("TargetCompID", "接收方 TargetCompID", "对方机构代码", "str"),
    ("SenderSubID", "发送方子号 SenderSubID", "本方子账户/席位，可留空", "str"),
    ("BeginString", "版本 BeginString", "通常为 FIX.4.2", "str"),
    ("DefaultApplVerID", "应用版本 DefaultApplVerID", "通常与 BeginString 一致", "str"),
    ("HeartBtInt", "心跳秒数 HeartBtInt", "空闲时发送心跳的间隔", "str"),
    ("ReconnectInterval", "重连间隔 ReconnectInterval", "断线后重连等待秒数", "str"),
    ("LogonTimeout", "登录超时 LogonTimeout", "等待登录响应秒数", "str"),
    ("StartTime", "交易开始 StartTime", "HH:MM:SS", "str"),
    ("EndTime", "交易结束 EndTime", "HH:MM:SS", "str"),
    ("DataDictionary", "数据字典 DataDictionary", "校验用 XML 路径", "str"),
    ("FileStorePath", "序号存储目录 FileStorePath", "QuickFIX 会话序号文件目录", "str"),
    ("FileLogPath", "报文日志目录 FileLogPath", "QuickFIX 原始报文日志目录", "str"),
    ("ClOrdIdPrefix", "委托编号前缀", "自动生成 ClOrdID 时的前缀", "str"),
    ("ClOrdIdMode", "委托编号规则", "时间戳：前缀+毫秒；顺序号：前缀+递增序号", "str"),
    ("ClOrdIdStart", "顺序号起始值", "仅“顺序号”规则使用", "str"),
]

# ---------------------------------------------------------------- 下拉字典 ----
# 界面里所有“要填的东西”都来自这里，可以直接下拉选择。
DEFAULT_OPTIONS = {
    "account": ["P1100209", "110020901", "110025001", "P10000177", "110023501"],
    "client_id": ["1100209", "1100235"],
    "symbol": ["600000", "000001", "000036", "IM2610", "IF2612"],
    "exchange": ["SH", "SZ", "CFE"],
    "strategy": ["", "marsnew_CNY_CustomQFII", "marsg_CNY_QFII", "WE_CNY_QFII", "qq_CNY_QFII"],
    "remark": ["", "1", "XP_DATA=OPEN,,,", "marsx"],
    "qty": ["100", "200", "300", "500", "1000"],
    "price": ["", "10.10", "12.30", "21.00"],
    "currency": ["CNY", "USD", "HKD"],
    "username": ["bGxwcmFj"],
    "password": ["FV3BlvgKjsypmGV0I98BZA=="],
    "cancel_text": ["", "撤单"],
    # 附加字段预设，形如 "11000=3"
    "__extra__": ["11000=3", "921=NONE"],
}

# 下拉字典的分组（键, 界面名称）
OPTION_GROUPS = [
    ("account", "资金账号 (1)"),
    ("client_id", "客户号 (109)"),
    ("symbol", "交易标的 (55)"),
    ("exchange", "交易市场 (100)"),
    ("strategy", "策略名 (951)"),
    ("remark", "备注 (58)"),
    ("qty", "委托数量预设 (38)"),
    ("price", "委托价格预设 (44)"),
    ("currency", "币种 (15)"),
    ("cancel_text", "撤单备注 (58)"),
    ("__extra__", "附加字段预设 (自定义 tag)"),
]

# 标的 -> 市场 的自动带出记忆（用户下单后自动学习）
DEFAULT_SYMBOL_EXCHANGE = {
    "600000": "SH",
    "000001": "SZ",
    "000036": "SZ",
    "IM2610": "CFE",
    "IF2612": "CFE",
}


def default_settings():
    return {
        "version": SETTINGS_VERSION,
        "active_profile": DEFAULT_PROFILE["name"],
        "profiles": {DEFAULT_PROFILE["name"]: copy.deepcopy(DEFAULT_PROFILE)},
        "ui": {
            "geometry": "",
            "auto_clordid": True,
            "auto_symbol_exchange": True,
        },
        "symbol_exchange": copy.deepcopy(DEFAULT_SYMBOL_EXCHANGE),
        "last_order": {},
    }


def _merge(base, loaded):
    """把读取到的内容合并到默认值上，兼容旧版本/缺字段的配置文件。"""
    if not isinstance(loaded, dict):
        return copy.deepcopy(base)
    out = copy.deepcopy(base)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _ensure_bundled_resources():
    """exe 首次运行时，把打包在程序里的 dict/、assets/ 逐项释放到 exe 旁边。"""
    if BUNDLE_DIR == APP_ROOT:
        return
    for name in ("dict", "assets"):
        src = BUNDLE_DIR / name
        dst = APP_ROOT / name
        if not src.is_dir():
            continue
        for item in src.iterdir():
            target = dst / item.name
            if target.exists():
                continue
            try:
                dst.mkdir(parents=True, exist_ok=True)
                if item.is_dir():
                    shutil.copytree(str(item), str(target))
                else:
                    shutil.copy2(str(item), str(target))
            except OSError:
                # exe 目录不可写时忽略；连接时若缺字典会给出明确提示
                pass


def ensure_dirs():
    for path in (CONFIG_DIR, RUNTIME_DIR, LOG_DIR, STORE_DIR, FIX_LOG_DIR, DICT_DIR):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    _ensure_bundled_resources()


def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return copy.deepcopy(fallback)


def _write_json(path, data):
    ensure_dirs()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ------------------------------------------------------------------ 设置 ----
def load_settings():
    ensure_dirs()
    data = _read_json(SETTINGS_FILE, {})
    settings = _merge(default_settings(), data)

    profiles = settings.get("profiles") or {}
    if not isinstance(profiles, dict) or not profiles:
        settings["profiles"] = {DEFAULT_PROFILE["name"]: copy.deepcopy(DEFAULT_PROFILE)}
    for name, profile in list(settings["profiles"].items()):
        merged = _merge(DEFAULT_PROFILE, profile if isinstance(profile, dict) else {})
        merged["name"] = name
        settings["profiles"][name] = merged

    if settings.get("active_profile") not in settings["profiles"]:
        settings["active_profile"] = next(iter(settings["profiles"]))
    return settings


def save_settings(settings):
    settings["version"] = SETTINGS_VERSION
    _write_json(SETTINGS_FILE, settings)


# ------------------------------------------------------------ 下拉字典 ----
def load_options():
    ensure_dirs()
    data = _read_json(OPTIONS_FILE, {})
    options = _merge(DEFAULT_OPTIONS, data)
    for key in DEFAULT_OPTIONS:
        value = options.get(key)
        if not isinstance(value, list):
            options[key] = list(DEFAULT_OPTIONS[key])
    return options


def save_options(options):
    _write_json(OPTIONS_FILE, options)


# ------------------------------------------------------------ 历史委托 ----
def load_orders(limit=300):
    data = _read_json(ORDERS_FILE, [])
    if not isinstance(data, list):
        return []
    data = [item for item in data if isinstance(item, dict) and item.get("clordid")]
    return data[-limit:]


def save_orders(orders, limit=300):
    _write_json(ORDERS_FILE, list(orders)[-limit:])


def rel_path(path):
    """把配置里的相对路径解析成程序目录下的绝对路径。"""
    if not path:
        return path
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    return str((APP_ROOT / path.lstrip("./")).resolve())


def resolve_resource(path):
    """优先用 exe 旁边的文件，找不到再用打包内部的副本（打包运行时）。"""
    if not path:
        return path
    candidate = Path(path)
    if candidate.is_absolute():
        return str(candidate)
    local = (APP_ROOT / path.lstrip("./")).resolve()
    if local.exists():
        return str(local)
    bundled = (BUNDLE_DIR / path.lstrip("./")).resolve()
    if bundled.exists():
        return str(bundled)
    return str(local)
