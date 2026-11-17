# -*- coding: utf-8 -*-
"""FIX 下单助手：可视化界面。"""
from __future__ import annotations

import copy
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, simpledialog, ttk

from . import config_store, messaging, models, parser
from .config_store import APP_ROOT, OPTION_GROUPS, PROFILE_FIELDS
from .dictionary import get_dictionary
from .engine import EngineError, FixEngine
from .version import version_text
from .messaging import _FULLWIDTH_TABLE

FONT = ("Microsoft YaHei UI", 9)
FONT_BOLD = ("Microsoft YaHei UI", 9, "bold")
FONT_TITLE = ("Microsoft YaHei UI", 14, "bold")
FONT_SUB = ("Microsoft YaHei UI", 9)
FONT_SMALL = ("Microsoft YaHei UI", 8)
FONT_MONO = ("Consolas", 9)

COLOR_BG = "#f3f5f9"
COLOR_PANEL = "#ffffff"
COLOR_HEADER = "#132a4a"
COLOR_ACCENT = "#1677ff"
COLOR_OK = "#148a52"
COLOR_WARN = "#b26a00"
COLOR_ERR = "#c0392b"
COLOR_MUTED = "#6b7280"

LOG_COLORS = {
    "send": "#0b5cad",
    "recv": "#0f7b3f",
    "admin": "#6b7280",
    "heartbeat": "#9aa4b2",
    "system": "#7c3aed",
    "error": "#c0392b",
}

# 查询应答里不需要展示的会话级字段
QUERY_SKIP_TAGS = {"8", "9", "10", "34", "35", "49", "50", "52", "56", "57", "43", "97", "122", "369"}

STATE_STYLE = {
    "idle": ("未连接", "#8a94a6"),
    "connecting": ("连接中…", COLOR_WARN),
    "created": ("会话已创建", "#2b6cb0"),
    "starting": ("启动中…", COLOR_WARN),
    "logon": ("已登录", COLOR_OK),
    "logout": ("已断开", COLOR_ERR),
    "stopped": ("未连接", "#8a94a6"),
    "logging_out": ("正在登出…", COLOR_WARN),
    "error": ("连接失败", COLOR_ERR),
}


class FixOrderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = config_store.load_settings()
        self.options = config_store.load_options()
        self.dictionary = get_dictionary(str(config_store.DICT_DIR / "FIX42-server.xml"))

        self.events = queue.Queue()
        self.engine = FixEngine(self.events.put)

        self.orders = {}
        self.cancel_map = {}   # 撤单请求的 ClOrdID -> 原委托 ClOrdID
        for record in config_store.load_orders():
            if record.get("clordid"):
                self.orders[record["clordid"]] = record
        self._clord_seq = 0

        self.log_entries = []

        self.profile_vars = {}
        self.order_vars = {}
        self.option_combos = {}
        self.option_linked = []
        self.extra_rows = []
        self.dict_working = copy.deepcopy(self.options)
        self.dict_current = OPTION_GROUPS[0][0]

        self._connected_buttons = []
        self._state = "idle"

        self.title("FIX 下单助手 %s —— 可视化下单 / 撤单 / 查询" % version_text())
        self.configure(bg=COLOR_BG)
        self.minsize(1180, 760)
        icon = APP_ROOT / "assets" / "app.ico"
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass

        self._setup_style()
        self._font_normal = tkfont.Font(family=FONT[0], size=FONT[1])
        self._font_bold = tkfont.Font(family=FONT[0], size=FONT[1], weight="bold")
        self._build_header()
        self._build_notebook()
        self._build_statusbar()
        self._build_menu()

        self._load_profile_into_form(self.settings.get("active_profile"))
        self._refresh_profile_combo()
        self._apply_last_order()
        self._refresh_order_tree()
        self._render_log()

        geometry = (self.settings.get("ui") or {}).get("geometry")
        if geometry:
            try:
                self.geometry(geometry)
            except tk.TclError:
                self.geometry(self._default_geometry())
        else:
            self.geometry(self._default_geometry())

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(80, self._poll_events)
        self._set_state("idle")
        self._log("system", "程序已启动，配置目录：%s" % APP_ROOT)

    # ================================================================ 样式 ==
    def _setup_style(self):
        style = ttk.Style(self)
        for theme in ("vista", "winnative", "clam"):
            if theme in style.theme_names():
                try:
                    style.theme_use(theme)
                    break
                except tk.TclError:
                    continue

        style.configure(".", font=FONT)
        style.configure("TLabel", background=COLOR_BG, font=FONT)
        style.configure("TLabelframe", background=COLOR_BG, borderwidth=1)
        style.configure("TLabelframe.Label", font=FONT_BOLD, foreground="#1b2a41")
        style.configure("TFrame", background=COLOR_BG)
        style.configure("Panel.TFrame", background=COLOR_PANEL)
        style.configure("TNotebook", background=COLOR_BG, borderwidth=0)
        style.configure("TNotebook.Tab", font=FONT, padding=(16, 7))
        style.configure("TCheckbutton", background=COLOR_BG, font=FONT)
        style.configure("TButton", font=FONT, padding=(10, 4))
        style.configure("Treeview", font=FONT, rowheight=23, fieldbackground=COLOR_PANEL)
        style.configure("Treeview.Heading", font=FONT_BOLD)
        style.configure("TEntry", font=FONT)
        style.configure("TCombobox", font=FONT)
        style.map("TCombobox", fieldbackground=[("readonly", COLOR_PANEL)])
        style.configure("Hint.TLabel", foreground=COLOR_MUTED, font=FONT_SMALL)

    @staticmethod
    def _select_all_widget(widget):
        try:
            widget.selection_range(0, "end")
            widget.icursor("end")
        except tk.TclError:
            pass

    def _default_geometry(self):
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = min(1440, int(screen_w * 0.94))
        height = min(900, int(screen_h * 0.84))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        return "%dx%d+%d+%d" % (width, height, x, y)

    def _fit_width(self, title, samples=(), padding=18, minimum=48, maximum=320):
        """按当前字体/DPI 实测文字宽度，避免高分屏下表格文字被截断。"""
        width = self._font_bold.measure(title)
        for sample in samples:
            width = max(width, self._font_normal.measure(str(sample)))
        return max(minimum, min(maximum, width + padding))

    # ================================================================ 顶栏 ==
    def _build_header(self):
        header = tk.Frame(self, bg=COLOR_HEADER, height=80)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=COLOR_HEADER)
        left.pack(side="left", padx=18, pady=10)
        tk.Label(left, text="FIX 下单助手", bg=COLOR_HEADER, fg="#ffffff", font=FONT_TITLE).pack(anchor="w")
        tk.Label(
            left,
            text="连接参数、下单字段全部可视化配置 · 下拉选择即可下单",
            bg=COLOR_HEADER, fg="#9fb4d0", font=FONT_SUB,
        ).pack(anchor="w", pady=(2, 0))

        right = tk.Frame(header, bg=COLOR_HEADER)
        right.pack(side="right", padx=18)
        self.state_dot = tk.Label(right, text="●", bg=COLOR_HEADER, fg="#8a94a6", font=("Segoe UI", 13))
        self.state_dot.pack(side="left", padx=(0, 6))
        self.state_label = tk.Label(right, text="未连接", bg=COLOR_HEADER, fg="#ffffff", font=FONT_BOLD)
        self.state_label.pack(side="left")
        self.session_label = tk.Label(right, text="", bg=COLOR_HEADER, fg="#9fb4d0", font=FONT_SMALL)
        self.session_label.pack(side="left", padx=(12, 0))

    # ================================================================ 主体 ==
    def _build_notebook(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=(10, 0))

        self.tab_conn = ttk.Frame(self.notebook, padding=12)
        self.tab_trade = ttk.Frame(self.notebook, padding=10)
        self.tab_query = ttk.Frame(self.notebook, padding=10)
        self.tab_dict = ttk.Frame(self.notebook, padding=12)
        self.tab_log = ttk.Frame(self.notebook, padding=10)

        self.notebook.add(self.tab_conn, text=" 连接配置 ")
        self.notebook.add(self.tab_trade, text=" 交 易 ")
        self.notebook.add(self.tab_query, text=" 查 询 ")
        self.notebook.add(self.tab_dict, text=" 字段字典 ")
        self.notebook.add(self.tab_log, text=" 运行日志 ")

        self._build_tab_connection()
        self._build_tab_trade()
        self._build_tab_query()
        self._build_tab_dict()
        self._build_tab_log()

    # ------------------------------------------------------------ 连接页 --
    def _build_tab_connection(self):
        tab = self.tab_conn
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        # 档案
        box = ttk.LabelFrame(tab, text="配置档案", padding=(12, 8))
        box.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="当前档案").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.profile_combo = ttk.Combobox(box, state="readonly", width=34)
        self.profile_combo.grid(row=0, column=1, sticky="w")
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_selected)

        btns = ttk.Frame(box)
        btns.grid(row=0, column=2, sticky="e")
        ttk.Button(btns, text="保存", command=self._save_profile).pack(side="left", padx=2)
        ttk.Button(btns, text="另存为…", command=self._save_profile_as).pack(side="left", padx=2)
        ttk.Button(btns, text="删除", command=self._delete_profile).pack(side="left", padx=2)
        ttk.Button(btns, text="恢复默认值", command=self._reset_profile_form).pack(side="left", padx=2)

        ttk.Label(
            box,
            text="提示：这里的每一项都会写进自动生成的 client.cfg，修改后点击“保存”即可长期生效。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        # 参数
        params = ttk.LabelFrame(tab, text="会话参数（等同 client.cfg）", padding=(12, 10))
        params.grid(row=1, column=0, sticky="nsew")
        params.columnconfigure(0, weight=1)
        params.columnconfigure(1, weight=1)

        left = ttk.Frame(params)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 24))
        right = ttk.Frame(params)
        right.grid(row=0, column=1, sticky="nsew")
        for frame in (left, right):
            frame.columnconfigure(1, weight=1)

        half = (len(PROFILE_FIELDS) + 1) // 2
        for index, (key, label, _hint, _kind) in enumerate(PROFILE_FIELDS):
            parent = left if index < half else right
            row = index if index < half else index - half
            var = tk.StringVar()
            self.profile_vars[key] = var
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=4)
            widget = ttk.Entry(parent, textvariable=var, width=26)
            widget.grid(row=row, column=1, sticky="ew", pady=4)
            if key in ("DataDictionary", "FileStorePath", "FileLogPath"):
                ttk.Button(parent, text="…", width=3,
                           command=lambda k=key: self._pick_path(k)).grid(row=row, column=2, padx=(4, 0))
            elif key == "ClOrdIdMode":
                widget.destroy()
                combo = ttk.Combobox(parent, textvariable=var, values=models.CLORDID_MODE.labels,
                                     state="readonly", width=24)
                combo.grid(row=row, column=1, sticky="ew", pady=4)

        toggles = ttk.Frame(params)
        toggles.grid(row=1, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.reset_on_logon_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(toggles, text="登录时重置序号（ResetOnLogon=Y）",
                        variable=self.reset_on_logon_var).pack(side="left", padx=(0, 20))
        self.use_file_log_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(toggles, text="保存 QuickFIX 原始报文日志（FileLogPath）",
                        variable=self.use_file_log_var).pack(side="left")

        # 操作
        actions = ttk.Frame(tab)
        actions.grid(row=2, column=0, sticky="new", pady=(12, 0))

        self.btn_connect = tk.Button(
            actions, text="连接交易网关", command=self.connect_session,
            bg=COLOR_ACCENT, fg="white", activebackground="#0b5fd0", activeforeground="white",
            relief="flat", font=FONT_BOLD, padx=18, pady=7, cursor="hand2",
        )
        self.btn_connect.pack(side="left")
        self.btn_disconnect = ttk.Button(actions, text="断开", command=self.disconnect_session)
        self.btn_disconnect.pack(side="left", padx=(10, 0))
        self.btn_logout = ttk.Button(actions, text="登出会话", command=self.logout_session)
        self.btn_logout.pack(side="left", padx=(8, 0))
        self.btn_reset = ttk.Button(actions, text="重置序号并重连", command=self.reset_sequence)
        self.btn_reset.pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="查看生成的 client.cfg", command=self.show_cfg).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="打开配置目录", command=self.open_config_dir).pack(side="left", padx=(8, 0))

        self.conn_hint = ttk.Label(tab, text="", style="Hint.TLabel")
        self.conn_hint.grid(row=3, column=0, sticky="w", pady=(8, 0))

    def _pick_path(self, key):
        current = self.profile_vars[key].get().strip()
        if key == "DataDictionary":
            path = filedialog.askopenfilename(title="选择数据字典 XML", filetypes=[("FIX 字典", "*.xml"), ("全部文件", "*.*")])
        else:
            path = filedialog.askdirectory(title="选择目录")
        if path:
            try:
                rel = os.path.relpath(path, str(APP_ROOT)).replace("\\", "/")
                if not rel.startswith(".."):
                    path = "./" + rel
            except ValueError:
                pass
            self.profile_vars[key].set(path)

    # -------------------------------------------------------------- 交易页 --
    def _build_tab_trade(self):
        paned = ttk.Panedwindow(self.tab_trade, orient="horizontal")
        paned.pack(fill="both", expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=3)
        paned.add(right, weight=4)

        # ---------- 下单参数 ----------
        form = ttk.LabelFrame(left, text="下单参数（全部可下拉选择）", padding=(12, 10))
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        self._add_order_field(form, 0, 0, "account", "资金账号 (1)")
        self._add_order_field(form, 0, 2, "client_id", "客户号 (109)")

        self._add_order_field(form, 1, 0, "symbol", "交易标的 (55)")
        self._add_order_field(form, 1, 2, "exchange", "交易市场 (100)")

        self._add_order_field(form, 2, 0, "security_type", "证券类型 (167)", choices=models.SECURITY_TYPE)
        self._add_order_field(form, 2, 2, "currency", "币种 (15)")

        self._add_order_field(form, 3, 0, "side", "买卖方向 (54)", choices=models.SIDE)
        self._add_order_field(form, 3, 2, "ordtype", "委托类型 (40)", choices=models.ORD_TYPE)

        self._add_order_field(form, 4, 0, "qty", "委托数量 (38)")
        self._add_order_field(form, 4, 2, "price", "委托价格 (44)")

        self._add_order_field(form, 5, 0, "tif", "有效期 (59)", choices=models.TIME_IN_FORCE)
        self._add_order_field(form, 5, 2, "handl_inst", "交易指令 (21)", choices=models.HANDL_INST)

        self._add_order_field(form, 6, 0, "position_effect", "持仓效果 (77)", choices=models.POSITION_EFFECT)
        self._add_order_field(form, 6, 2, "strategy", "策略名 (951)")

        self._add_order_field(form, 7, 0, "remark", "备注 (58)", wide=True)
        self._add_clordid_field(form, 8)

        auto_row = ttk.Frame(form)
        auto_row.grid(row=9, column=0, columnspan=4, sticky="w", pady=(2, 0))
        ui_cfg = self.settings.get("ui") or {}
        self.auto_symbol_exchange = tk.BooleanVar(value=bool(ui_cfg.get("auto_symbol_exchange", True)))
        ttk.Checkbutton(auto_row, text="选择标的自动带出交易市场", variable=self.auto_symbol_exchange).pack(side="left", padx=(0, 16))
        self.auto_clordid_var = tk.BooleanVar(value=bool(ui_cfg.get("auto_clordid", True)))
        ttk.Checkbutton(auto_row, text="自动生成本地委托号", variable=self.auto_clordid_var,
                        command=self._toggle_clordid).pack(side="left")

        ttk.Label(
            form,
            text="提示：所有字段都能直接键盘输入，也能从下拉里选；聚焦时会自动全选，直接输入即覆盖。",
            style="Hint.TLabel",
        ).grid(row=10, column=0, columnspan=4, sticky="w", pady=(6, 0))

        # 附加字段
        extra_box = ttk.LabelFrame(left, text="附加字段（可选，例如 11000=3 融券标志）", padding=(12, 8))
        extra_box.pack(fill="both", expand=True, pady=(10, 0))
        extra_box.columnconfigure(0, weight=1)
        extra_box.rowconfigure(1, weight=1)

        bar = ttk.Frame(extra_box)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.extra_input = ttk.Combobox(bar, values=self.options.get("__extra__", []), width=20)
        self.extra_input.pack(side="left")
        self.extra_input.set("")
        self.extra_input.bind("<Escape>", lambda _e: self._clear_extra_input())
        ttk.Button(bar, text="添加", width=5, command=self._add_extra).pack(side="left", padx=4)
        ttk.Button(bar, text="删除选中", width=8, command=self._remove_extra).pack(side="left")
        ttk.Button(bar, text="清空列表", width=8, command=self._clear_extras).pack(side="left", padx=4)
        ttk.Button(bar, text="清除输入", width=8, command=self._clear_extra_input).pack(side="left")

        columns = ("tag", "value")
        self.extra_tree = ttk.Treeview(extra_box, columns=columns, show="headings", height=3)
        self.extra_tree.heading("tag", text="Tag")
        self.extra_tree.heading("value", text="值")
        self.extra_tree.column("tag", width=90, anchor="center")
        self.extra_tree.column("value", width=220, anchor="w")
        self.extra_tree.grid(row=1, column=0, sticky="nsew")

        # 下单按钮
        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=(10, 0))
        self.btn_send_order = tk.Button(
            buttons, text="发送委托", command=self.send_order,
            bg=COLOR_ACCENT, fg="white", activebackground="#0b5fd0", activeforeground="white",
            relief="flat", font=FONT_BOLD, padx=22, pady=7, cursor="hand2",
        )
        self.btn_send_order.pack(side="left")
        ttk.Button(buttons, text="预览报文", command=self.preview_order).pack(side="left", padx=(10, 0))
        ttk.Button(buttons, text="重置表单", command=self.reset_order_form).pack(side="left", padx=(8, 0))

        # ---------- 委托与成交回报 ----------
        listbox = ttk.LabelFrame(
            right, text="委托列表（每行一笔委托的最新状态；双击或右键看全部回报）", padding=(10, 8))
        listbox.pack(fill="both", expand=True)
        listbox.rowconfigure(1, weight=1)
        listbox.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(listbox)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(toolbar, text="撤单备注 (58)").pack(side="left")
        self.cancel_text_var = tk.StringVar()
        self.cancel_text_box = ttk.Combobox(
            toolbar, textvariable=self.cancel_text_var,
            values=self.options.get("cancel_text", []), width=16)
        self.cancel_text_box.pack(side="left", padx=(6, 10))
        self.option_combos["cancel_text"] = self.cancel_text_box
        self.btn_cancel = tk.Button(
            toolbar, text="撤单选中", command=self.cancel_selected,
            bg="#d9480f", fg="white", activebackground="#b93b0c", activeforeground="white",
            relief="flat", font=FONT_BOLD, padx=16, pady=5, cursor="hand2",
        )
        self.btn_cancel.pack(side="left")
        ttk.Button(toolbar, text="预览撤单", command=self.preview_cancel_selected).pack(side="left", padx=(8, 0))
        ttk.Button(toolbar, text="刷新列表", command=self._refresh_order_tree).pack(side="right")

        columns = [key for key, _title, _width in models.ORDER_COLUMNS]
        self.order_tree = ttk.Treeview(listbox, columns=columns, show="headings", height=16)
        samples = {
            "time": ["09:31:10"],
            "clordid": ["6201794888900101"],
            "symbol": ["IM2610"],
            "side": ["买入", "卖出"],
            "qty": ["100/100"],
            "price": ["5980.25"],
            "status": ["撤单拒绝"],
            "orderid": ["ORD-1001-001"],
        }
        for key, title, width in models.ORDER_COLUMNS:
            self.order_tree.heading(key, text=title)
            self.order_tree.column(
                key,
                width=max(width, self._fit_width(title, samples.get(key, []))),
                minwidth=40, stretch=False,
                anchor="w" if key in ("clordid", "orderid", "time") else "center")
        self.order_tree.grid(row=1, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(listbox, orient="vertical", command=self.order_tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        xscroll = ttk.Scrollbar(listbox, orient="horizontal", command=self.order_tree.xview)
        xscroll.grid(row=2, column=0, sticky="ew")
        self.order_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        self.order_tree.tag_configure("active", background="#e8f2ff")
        self.order_tree.tag_configure("done", background="#e9f8ec")
        self.order_tree.tag_configure("rejected", background="#ffe3e0", foreground="#a8071a")
        self.order_tree.bind("<Double-1>", self._show_order_detail)
        self.order_tree.bind("<Button-3>", self._show_order_menu)

        self.order_menu = tk.Menu(self, tearoff=0)
        self.order_menu.add_command(label="撤单选中", command=self.cancel_selected)
        self.order_menu.add_command(label="预览撤单报文", command=self.preview_cancel_selected)
        self.order_menu.add_separator()
        self.order_menu.add_command(label="复制委托号", command=self._copy_selected_clordid)
        self.order_menu.add_command(label="查看回报明细", command=self._show_order_detail)

        btn_row = ttk.Frame(listbox)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btn_row, text="查看回报明细", command=self._show_order_detail).pack(side="left")
        ttk.Button(btn_row, text="复制委托号", command=self._copy_selected_clordid).pack(side="left", padx=6)
        ttk.Button(btn_row, text="清空已完成", command=self._clear_finished_orders).pack(side="left")

    def _add_order_field(self, parent, row, column, key, label, choices=None, wide=False):
        var = tk.StringVar()
        self.order_vars[key] = var
        ttk.Label(parent, text=label).grid(row=row, column=column, sticky="w", padx=(0, 6) if column == 0 else (16, 6), pady=4)

        if choices is not None:
            values = choices.labels
            widget = ttk.Combobox(parent, textvariable=var, values=values, state="readonly", width=17)
            var.set(values[0] if values else "")
        else:
            values = self.options.get(key, [])
            widget = ttk.Combobox(parent, textvariable=var, values=values, width=17)
            self.option_combos[key] = widget
        if wide:
            widget.grid(row=row, column=column + 1, columnspan=3, sticky="ew", pady=4)
        else:
            widget.grid(row=row, column=column + 1, sticky="ew", pady=4)
        if values:
            var.set(values[0])
        if choices is None:
            # 点击后强制聚焦，聚焦时全选，直接输入即可覆盖原值
            widget.bind("<Button-1>", lambda _e, w=widget: w.focus_set(), add="+")
            widget.bind("<FocusIn>", lambda _e, w=widget: self._select_all_widget(w))
        if key == "symbol":
            widget.bind("<<ComboboxSelected>>", self._on_symbol_selected)
        if key == "ordtype":
            widget.bind("<<ComboboxSelected>>", self._on_ordtype_selected)
        return widget

    def _add_clordid_field(self, parent, row):
        var = tk.StringVar()
        self.order_vars["clordid"] = var
        ttk.Label(parent, text="本地委托号 (11)").grid(row=row, column=0, sticky="w", padx=(0, 6), pady=4)
        holder = ttk.Frame(parent)
        holder.grid(row=row, column=1, columnspan=3, sticky="ew", pady=4)
        holder.columnconfigure(0, weight=1)
        self.clordid_entry = ttk.Entry(holder, textvariable=var, width=26)
        self.clordid_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(holder, text="重新生成", width=10,
                   command=self._regen_clordid).grid(row=0, column=1, padx=(6, 0))

    # -------------------------------------------------------------- 查询页 --
    def _build_tab_query(self):
        tab = self.tab_query
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)

        query_box = ttk.LabelFrame(tab, text="查询请求", padding=(12, 10))
        query_box.grid(row=0, column=0, sticky="ew")
        query_box.columnconfigure(1, weight=1)

        self.query_account = tk.StringVar()
        ttk.Label(query_box, text="查询账号 (1)").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.query_account_combo = ttk.Combobox(query_box, textvariable=self.query_account,
                                                values=self.options.get("account", []), width=26)
        self.query_account_combo.grid(row=0, column=1, sticky="w")
        self.option_combos["query_account"] = self.query_account_combo
        if self.options.get("account"):
            self.query_account.set(self.options["account"][0])

        buttons = ttk.Frame(query_box)
        buttons.grid(row=0, column=2, sticky="e")
        ttk.Button(buttons, text="资金查询 FD", command=self.query_fund).pack(side="left", padx=2)
        ttk.Button(buttons, text="持仓查询 AN", command=self.query_position).pack(side="left", padx=2)
        ttk.Button(buttons, text="额度查询 SC", command=self.query_quota).pack(side="left", padx=2)
        ttk.Button(buttons, text="清空结果", command=self.clear_query_result).pack(side="left", padx=(12, 0))

        title = ttk.Label(tab, text="查询结果（按应答类型分表）", style="TLabel")
        title.grid(row=1, column=0, sticky="w", pady=(12, 4))

        nb = ttk.Notebook(tab)
        nb.grid(row=2, column=0, sticky="nsew")
        self.query_notebook = nb
        self.query_tables = {}

        for key, caption in (("FP", "资金"), ("AP", "持仓"), ("SP", "额度"), ("OTHER", "其他")):
            frame = ttk.Frame(nb, padding=4)
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            tree = ttk.Treeview(frame, show="headings")
            tree.grid(row=0, column=0, sticky="nsew")
            yscroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
            yscroll.grid(row=0, column=1, sticky="ns")
            xscroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
            xscroll.grid(row=1, column=0, sticky="ew")
            tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            nb.add(frame, text=" %s " % caption)
            self.query_tables[key] = {"tree": tree, "rows": [], "columns": [], "frame": frame,
                                      "caption": caption}

        frame_raw = ttk.Frame(nb, padding=4)
        nb.add(frame_raw, text=" 原始报文 ")
        self.query_raw = scrolledtext.ScrolledText(frame_raw, font=FONT_MONO, wrap="none", height=12)
        self.query_raw.pack(fill="both", expand=True)

    # -------------------------------------------------------------- 字典页 --
    def _build_tab_dict(self):
        tab = self.tab_dict
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        head = ttk.Frame(tab)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ttk.Label(head, text="这里维护每个下拉框的可选项：下单时直接下拉选择，不用手工输入。",
                  style="Hint.TLabel").pack(side="left")

        paned = ttk.Panedwindow(tab, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=1)
        paned.add(right, weight=3)

        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)
        ttk.Label(left, text="字段分组").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.dict_groups = ttk.Treeview(left, show="tree", selectmode="browse")
        self.dict_groups.grid(row=1, column=0, sticky="nsew")
        for key, title in OPTION_GROUPS:
            self.dict_groups.insert("", "end", iid=key, text=title)
        self.dict_groups.bind("<<TreeviewSelect>>", self._on_dict_group)

        box = ttk.LabelFrame(right, text="选项内容", padding=(12, 10))
        box.pack(fill="both", expand=True)
        box.rowconfigure(1, weight=1)
        box.columnconfigure(0, weight=1)

        self.dict_title = ttk.Label(box, text="", font=FONT_BOLD)
        self.dict_title.grid(row=0, column=0, sticky="w", pady=(0, 6))

        self.dict_list_frame = ttk.Frame(box)
        self.dict_list_frame.grid(row=1, column=0, sticky="nsew")
        self.dict_list_frame.rowconfigure(0, weight=1)
        self.dict_list_frame.columnconfigure(0, weight=1)

        self.dict_listbox = tk.Listbox(self.dict_list_frame, font=FONT, activestyle="none",
                                       selectmode="extended", relief="flat", highlightthickness=1)
        self.dict_listbox.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(self.dict_list_frame, orient="vertical", command=self.dict_listbox.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.dict_listbox.configure(yscrollcommand=scroll.set)

        self.dict_text_frame = ttk.Frame(box)
        self.dict_text_frame.rowconfigure(0, weight=1)
        self.dict_text_frame.columnconfigure(0, weight=1)
        self.dict_text = scrolledtext.ScrolledText(self.dict_text_frame, font=FONT_MONO, height=10)
        self.dict_text.grid(row=0, column=0, sticky="nsew")

        editor = ttk.Frame(box)
        editor.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        editor.columnconfigure(0, weight=1)
        self.dict_input = ttk.Entry(editor)
        self.dict_input.grid(row=0, column=0, sticky="ew")
        self.dict_input.bind("<Return>", lambda _e: self._dict_add())
        ttk.Button(editor, text="添加", command=self._dict_add).grid(row=0, column=1, padx=(6, 0))
        ttk.Button(editor, text="删除选中", command=self._dict_remove).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(editor, text="上移", command=lambda: self._dict_move(-1)).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(editor, text="下移", command=lambda: self._dict_move(1)).grid(row=0, column=4, padx=(6, 0))

        footer = ttk.Frame(tab)
        footer.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(footer, text="保存字典", command=self._dict_save).pack(side="left")
        ttk.Button(footer, text="恢复默认字典", command=self._dict_reset).pack(side="left", padx=8)
        ttk.Button(footer, text="放弃修改", command=self._dict_reload).pack(side="left")
        ttk.Label(footer, text="（修改会立即用于下拉框，保存后下次启动仍然有效）",
                  style="Hint.TLabel").pack(side="left", padx=12)

        self.dict_groups.selection_set(OPTION_GROUPS[0][0])
        self.dict_groups.focus(OPTION_GROUPS[0][0])
        self._dict_load()

    # -------------------------------------------------------------- 日志页 --
    def _build_tab_log(self):
        tab = self.tab_log
        tab.rowconfigure(1, weight=1)
        tab.columnconfigure(0, weight=1)

        bar = ttk.Frame(tab)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.log_filters = {}
        for key, label, default in (
            ("send", "发送", True),
            ("recv", "接收", True),
            ("admin", "管理报文", True),
            ("heartbeat", "心跳", False),
            ("system", "系统", True),
        ):
            var = tk.BooleanVar(value=default)
            self.log_filters[key] = var
            ttk.Checkbutton(bar, text=label, variable=var,
                            command=self._render_log).pack(side="left", padx=(0, 10))

        self.log_autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="自动滚动", variable=self.log_autoscroll).pack(side="left", padx=(10, 16))
        ttk.Button(bar, text="清空日志", command=self._clear_log).pack(side="left")
        ttk.Button(bar, text="导出日志", command=self._export_log).pack(side="left", padx=8)
        ttk.Label(bar, text="报文按 SOH(\\x01) 拆成“|”显示", style="Hint.TLabel").pack(side="right")

        self.log_text = scrolledtext.ScrolledText(tab, font=FONT_MONO, wrap="none", state="disabled")
        self.log_text.grid(row=1, column=0, sticky="nsew")
        for key, color in LOG_COLORS.items():
            self.log_text.tag_configure(key, foreground=color)
        self.log_text.tag_configure("time", foreground="#98a2b3")

    # ============================================================ 状态栏 ==
    def _build_statusbar(self):
        bar = tk.Frame(self, bg="#e7ebf2", height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.status_left = tk.Label(bar, text="未连接", bg="#e7ebf2", fg="#3d4b5c", font=FONT_SMALL, anchor="w")
        self.status_left.pack(side="left", padx=12)
        self.status_right = tk.Label(bar, text="", bg="#e7ebf2", fg="#3d4b5c", font=FONT_SMALL, anchor="e")
        self.status_right.pack(side="right", padx=12)
        self._update_counters()

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="保存当前配置", command=self._save_profile)
        file_menu.add_command(label="打开配置目录", command=self.open_config_dir)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        session_menu = tk.Menu(menubar, tearoff=0)
        session_menu.add_command(label="连接", command=self.connect_session)
        session_menu.add_command(label="断开", command=self.disconnect_session)
        session_menu.add_command(label="登出会话", command=self.logout_session)
        session_menu.add_command(label="重置序号并重连", command=self.reset_sequence)
        menubar.add_cascade(label="会话", menu=session_menu)

        tools = tk.Menu(menubar, tearoff=0)
        tools.add_command(label="字段字典", command=lambda: self.notebook.select(self.tab_dict))
        tools.add_command(label="运行日志", command=lambda: self.notebook.select(self.tab_log))
        tools.add_command(label="查看生成的 client.cfg", command=self.show_cfg)
        menubar.add_cascade(label="工具", menu=tools)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="使用说明", command=self.show_help)
        help_menu.add_command(label="关于", command=self.show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.configure(menu=menubar)

        self.bind_all("<Control-Return>", lambda _e: self.send_order())
        self.bind_all("<F5>", lambda _e: self._refresh_order_tree())

    # ========================================================== 配置档案 ==
    @property
    def profile_name(self):
        return self.settings.get("active_profile")

    @property
    def profile(self):
        return self.settings["profiles"][self.profile_name]

    def _refresh_profile_combo(self):
        names = list(self.settings["profiles"].keys())
        self.profile_combo.configure(values=names)
        self.profile_combo.set(self.profile_name)

    def _load_profile_into_form(self, name):
        if name not in self.settings["profiles"]:
            name = next(iter(self.settings["profiles"]))
        self.settings["active_profile"] = name
        profile = self.settings["profiles"][name]
        for key, _label, _hint, _kind in PROFILE_FIELDS:
            self.profile_vars[key].set(str(profile.get(key, "")).strip())
        self.reset_on_logon_var.set(bool(profile.get("ResetOnLogon", True)))
        self.use_file_log_var.set(bool(profile.get("UseFileLog", False)))

    def _collect_profile(self):
        profile = {"name": self.profile_name}
        for key, _label, _hint, _kind in PROFILE_FIELDS:
            profile[key] = self.profile_vars[key].get().strip()
        profile["ResetOnLogon"] = bool(self.reset_on_logon_var.get())
        profile["UseFileLog"] = bool(self.use_file_log_var.get())
        return profile

    def _save_profile(self, silent=False):
        name = self.profile_name
        profile = self._collect_profile()
        profile["name"] = name
        self.settings["profiles"][name] = profile
        try:
            config_store.save_settings(self.settings)
        except OSError as exc:
            messagebox.showerror("保存失败", "无法写入配置文件：%s" % exc, parent=self)
            return False
        if not silent:
            self._log("system", "配置档案“%s”已保存" % name)
            self.conn_hint.configure(text="已保存到 config/settings.json")
        return True

    def _save_profile_as(self):
        name = simpledialog.askstring("另存为", "新档案名称：", initialvalue=self.profile_name + " 副本", parent=self)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        profile = self._collect_profile()
        profile["name"] = name
        self.settings["profiles"][name] = profile
        self.settings["active_profile"] = name
        self._refresh_profile_combo()
        config_store.save_settings(self.settings)
        self._log("system", "已新建配置档案：%s" % name)

    def _delete_profile(self):
        name = self.profile_name
        if len(self.settings["profiles"]) <= 1:
            messagebox.showinfo("提示", "至少保留一个配置档案。", parent=self)
            return
        if not messagebox.askyesno("删除档案", "确定删除配置档案“%s”吗？" % name, parent=self):
            return
        self.settings["profiles"].pop(name, None)
        self.settings["active_profile"] = next(iter(self.settings["profiles"]))
        self._refresh_profile_combo()
        self._load_profile_into_form(self.settings["active_profile"])
        config_store.save_settings(self.settings)

    def _reset_profile_form(self):
        defaults = copy.deepcopy(config_store.DEFAULT_PROFILE)
        for key, _label, _hint, _kind in PROFILE_FIELDS:
            self.profile_vars[key].set(str(defaults.get(key, "")))
        self.reset_on_logon_var.set(bool(defaults.get("ResetOnLogon", True)))
        self.use_file_log_var.set(bool(defaults.get("UseFileLog", False)))

    def _on_profile_selected(self, _event=None):
        name = self.profile_combo.get()
        if name and name in self.settings["profiles"]:
            self._load_profile_into_form(name)
            config_store.save_settings(self.settings)

    # ============================================================== 会话 ==
    def connect_session(self):
        if self._state in ("connecting", "starting", "created", "logon", "logging_out"):
            return
        try:
            profile = self._collect_profile()
            self.engine.build_cfg(profile)  # 先校验一遍，错误立刻提示
        except EngineError as exc:
            messagebox.showerror("连接参数有误", str(exc), parent=self)
            return

        self._save_profile(silent=True)
        self._set_state("connecting")
        self.conn_hint.configure(text="正在连接 %s:%s …" % (profile["SocketConnectHost"], profile["SocketConnectPort"]))

        def worker():
            try:
                self.engine.start(profile)
            except EngineError as exc:
                self.events.put({"kind": "connect_error", "text": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self.events.put({"kind": "connect_error", "text": "连接异常：%s" % exc})

        threading.Thread(target=worker, daemon=True).start()

    def disconnect_session(self):
        self._set_state("stopped")
        threading.Thread(target=self.engine.stop, daemon=True).start()

    def logout_session(self):
        try:
            self.engine.logout()
        except EngineError as exc:
            messagebox.showinfo("提示", str(exc), parent=self)

    def reset_sequence(self):
        profile = self._collect_profile()
        if not messagebox.askyesno(
            "重置序号",
            "将删除本地序号文件（%s-*-*.*），下次登录从 1 开始，且会立即重连。\n确定继续吗？"
            % (profile.get("BeginString") or "FIX.4.2"),
            parent=self,
        ):
            return
        try:
            self.engine.reset_sequence(profile)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("重置失败", str(exc), parent=self)
            return
        self.connect_session()

    def show_cfg(self):
        try:
            text = self.engine.build_cfg(self._collect_profile())
        except EngineError as exc:
            messagebox.showerror("配置有误", str(exc), parent=self)
            return
        win = tk.Toplevel(self)
        win.title("自动生成的 client.cfg")
        win.geometry("720x560")
        win.transient(self)
        box = scrolledtext.ScrolledText(win, font=FONT_MONO, wrap="none")
        box.pack(fill="both", expand=True, padx=10, pady=10)
        box.insert("1.0", text)
        box.configure(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 10))

    def open_config_dir(self):
        try:
            os.startfile(str(APP_ROOT))
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开失败", str(exc), parent=self)

    # ============================================================== 下单 ==
    def _order_extra_list(self):
        return [(self.extra_tree.item(iid, "values")[0], self.extra_tree.item(iid, "values")[1])
                for iid in self.extra_tree.get_children()]

    def _add_extra(self):
        text = self.extra_input.get().strip()
        if not text:
            return
        if "=" not in text:
            messagebox.showwarning("格式不对", "请按 “tag=值” 填写，例如 11000=3", parent=self)
            return
        tag, value = text.split("=", 1)
        tag, value = tag.strip(), value.strip()
        if not tag.isdigit():
            messagebox.showwarning("格式不对", "tag 必须是数字", parent=self)
            return
        for iid in self.extra_tree.get_children():
            values = self.extra_tree.item(iid, "values")
            if values and values[0] == tag:
                self.extra_tree.item(iid, values=(tag, value))
                return
        self.extra_tree.insert("", "end", values=(tag, value))
        self.extra_input.set("")

    def _remove_extra(self):
        for iid in self.extra_tree.selection():
            self.extra_tree.delete(iid)

    def _clear_extras(self):
        for iid in self.extra_tree.get_children():
            self.extra_tree.delete(iid)

    def _clear_extra_input(self):
        self.extra_input.set("")
        self.extra_input.focus_set()

    def _on_ordtype_selected(self, _event=None):
        # 市价单不需要价格：切到市价时清空，切回限价时保持可编辑
        if models.ORD_TYPE.value(self.order_vars["ordtype"].get()) == "Market":
            self.order_vars["price"].set("")

    def _on_symbol_selected(self, _event=None):
        if not self.auto_symbol_exchange.get():
            return
        symbol = self.order_vars["symbol"].get().strip()
        mapping = self.settings.get("symbol_exchange") or {}
        exchange = mapping.get(symbol)
        if exchange:
            self.order_vars["exchange"].set(exchange)
        else:
            guessed = self._guess_exchange(symbol)
            if guessed:
                self.order_vars["exchange"].set(guessed)

    @staticmethod
    def _guess_exchange(symbol):
        if not symbol:
            return ""
        upper = symbol.upper()
        if upper.startswith(("IF", "IH", "IC", "IM", "T", "TF")):
            return "CFE"
        if symbol.startswith(("6", "5", "9")):
            return "SH"
        if symbol.startswith(("0", "1", "2", "3")):
            return "SZ"
        return ""


    def _toggle_clordid(self):
        if self.auto_clordid_var.get():
            self.clordid_entry.configure(state="disabled")
            self._regen_clordid()
        else:
            self.clordid_entry.configure(state="normal")

    def next_clordid(self):
        profile = self.profile
        prefix = str(profile.get("ClOrdIdPrefix", "")).strip()
        mode = str(profile.get("ClOrdIdMode", "时间戳")).strip()
        self._clord_seq += 1
        if mode == "顺序号":
            try:
                start = int(str(profile.get("ClOrdIdStart", "1")).strip() or "1")
            except ValueError:
                start = 1
            candidate = "%s%d" % (prefix, start + self._clord_seq - 1)
            while candidate in self.orders:
                self._clord_seq += 1
                candidate = "%s%d" % (prefix, start + self._clord_seq - 1)
            self._last_clordid = candidate
            return candidate

        base = "%s%d" % (prefix, int(time.time() * 1000))
        candidate = base
        while candidate in self.orders or candidate == getattr(self, "_last_clordid", ""):
            candidate = "%s%02d" % (base, self._clord_seq % 100)
            self._clord_seq += 1
        self._last_clordid = candidate
        return candidate

    def _regen_clordid(self):
        if self.auto_clordid_var.get():
            self.order_vars["clordid"].set(self.next_clordid())

    def _collect_order(self):
        def value(key):
            text = self.order_vars[key].get().strip()
            if key in ("qty", "price"):
                # 中文输入法容易打出全角数字，这里统一转半角
                text = text.translate(_FULLWIDTH_TABLE)
            return text

        return {
            "clordid": value("clordid"),
            "account": value("account"),
            "client_id": value("client_id"),
            "symbol": value("symbol"),
            "exchange": value("exchange"),
            "security_type": models.SECURITY_TYPE.value(value("security_type")),
            "side": models.SIDE.value(value("side")),
            "ordtype": models.ORD_TYPE.value(value("ordtype")),
            "qty": value("qty"),
            "price": value("price"),
            "tif": models.TIME_IN_FORCE.value(value("tif")),
            "handl_inst": models.HANDL_INST.value(value("handl_inst")),
            "position_effect": models.POSITION_EFFECT.value(value("position_effect")),
            "strategy": value("strategy"),
            "currency": value("currency"),
            "remark": value("remark"),
            "extras": self._order_extra_list(),
        }

    def _validate_order(self, order):
        if not order["symbol"]:
            messagebox.showwarning("缺少交易标的", "请选择交易标的（55）。", parent=self)
            return False
        if not order["qty"]:
            messagebox.showwarning("缺少委托数量", "请选择或输入委托数量（38）。", parent=self)
            return False
        try:
            qty = float(order["qty"])
            if qty <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("数量不合法", "委托数量必须是大于 0 的数字。", parent=self)
            return False
        if order["ordtype"] == "Limit":
            if not order["price"]:
                messagebox.showwarning("缺少价格", "限价单必须填写委托价格（44）。", parent=self)
                return False
            try:
                float(order["price"])
            except ValueError:
                messagebox.showwarning("价格不合法", "委托价格必须是数字。", parent=self)
                return False
        return True

    def send_order(self):
        if not self.order_vars["clordid"].get().strip():
            self._regen_clordid()
        order = self._collect_order()
        if not self._validate_order(order):
            return
        if not self.engine.logged_on():
            if not messagebox.askyesno(
                "会话未登录",
                "当前会话还没有登录成功，继续发送可能会失败。\n\n仍然要发送吗？",
                parent=self,
            ):
                return
        try:
            message = self.engine.send_new_order(order)
        except (EngineError, messaging.MessageBuildError) as exc:
            messagebox.showerror("发送失败", str(exc), parent=self)
            return
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("发送失败", "未知错误：%s" % exc, parent=self)
            return

        record = models.empty_order()
        record.update({
            "time": time.strftime("%H:%M:%S"),
            "clordid": order["clordid"],
            "symbol": order["symbol"],
            "side": parser.side_text(order["side"]),
            "qty": order["qty"],
            "price": order["price"],
            "status": "已发送",
            "account": order["account"],
            "text": order["remark"],
            "active": True,
            "last_raw": messaging.message_text(message),
            "created": time.strftime("%H:%M:%S"),
        })
        self._append_event(
            record, "报单", "已发送",
            data={"text": order["remark"], "leaves_qty": order["qty"]},
            raw=messaging.message_text(message))
        self.orders[record["clordid"]] = record
        self._upsert_order_row(record)
        self._remember_symbol_exchange(order["symbol"], order["exchange"])
        self._log("send", "已发送委托 %s %s %s %s@%s" % (
            order["clordid"], order["symbol"], record["side"], order["qty"], order["price"] or "市价"))
        self._update_counters()
        config_store.save_orders(list(self.orders.values()))
        self._regen_clordid()

    def preview_order(self):
        order = self._collect_order()
        try:
            message = messaging.build_new_order(order, self._sender_sub_id())
        except messaging.MessageBuildError as exc:
            messagebox.showwarning("无法生成报文", str(exc), parent=self)
            return
        self._show_message("新建委托报文预览（35=D）", message)

    def _sender_sub_id(self):
        return self.profile_vars["SenderSubID"].get().strip()

    # ============================================================== 撤单 ==
    def _show_order_menu(self, event):
        iid = self.order_tree.identify_row(event.y)
        if not iid:
            return
        self.order_tree.selection_set(iid)
        self.order_tree.focus(iid)
        try:
            self.order_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.order_menu.grab_release()

    def _selected_order_record(self):
        selection = self.order_tree.selection()
        if not selection:
            return None
        return self.orders.get(selection[0])

    @staticmethod
    def _record_side(record):
        side = (record.get("side") or "").strip()
        if side == "买入":
            return "buy"
        if side == "卖出":
            return "sell"
        return side or "buy"

    def _cancel_payload(self, record):
        return {
            "clordid": self.next_clordid(),
            "orig_clordid": record.get("clordid", ""),
            "symbol": record.get("symbol", ""),
            "side": self._record_side(record),
            "account": record.get("account", ""),
            "text": self.cancel_text_var.get().strip(),
        }

    def _require_cancelable(self):
        record = self._selected_order_record()
        if record is None:
            messagebox.showwarning(
                "请选择委托",
                "请先在右侧「委托与成交回报」列表里选中一笔委托，再点「撤单选中」。",
                parent=self)
            return None
        if not record.get("active", True):
            messagebox.showinfo(
                "无法撤单",
                "这笔委托已经结束（状态：%s），不能再撤单。" % (record.get("status") or "未知"),
                parent=self)
            return None
        if not record.get("symbol"):
            messagebox.showwarning("缺少交易标的", "这笔委托没有交易标的，无法撤单。", parent=self)
            return None
        return record

    def cancel_selected(self):
        record = self._require_cancelable()
        if record is None:
            return
        summary = (
            "本地委托号：%s\n"
            "交易标的：%s\n"
            "买卖方向：%s\n"
            "数量(成交/委托)：%s/%s\n"
            "当前状态：%s"
            % (record.get("clordid", ""), record.get("symbol", ""), record.get("side", ""),
               record.get("filled", "0"), record.get("qty", ""), record.get("status", "")))
        if not messagebox.askyesno("确认撤单", "确定要撤销这笔委托吗？\n\n" + summary, parent=self):
            return

        order = self._cancel_payload(record)
        try:
            message = self.engine.send_cancel(order)
        except (EngineError, messaging.MessageBuildError) as exc:
            messagebox.showerror("撤单失败", str(exc), parent=self)
            return

        self.cancel_map[order["clordid"]] = record.get("clordid", "")
        record["status"] = "撤单已发送"
        record["active"] = True
        self._append_event(
            record, "撤单请求", "撤单已发送",
            data={"text": order.get("text", ""), "orderid": record.get("orderid", "")},
            raw=messaging.message_text(message))
        self._upsert_order_row(record)
        config_store.save_orders(list(self.orders.values()))
        self._log("send", "已发送撤单：原始委托号 %s，撤单委托号 %s"
                  % (order["orig_clordid"], order["clordid"]))

    def preview_cancel_selected(self):
        record = self._require_cancelable()
        if record is None:
            return
        order = self._cancel_payload(record)
        try:
            message = messaging.build_cancel_order(order, self._sender_sub_id())
        except messaging.MessageBuildError as exc:
            messagebox.showwarning("无法生成报文", str(exc), parent=self)
            return
        self._show_message("撤单报文预览（35=F）", message)

    # ============================================================== 查询 ==
    def _query_order(self):
        return {"clordid": self.next_clordid(), "account": self.query_account.get().strip()}

    def query_fund(self):
        self._do_query("资金查询", self.engine.send_fund_query)

    def query_position(self):
        self._do_query("持仓查询", self.engine.send_position_query)

    def query_quota(self):
        self._do_query("额度查询", self.engine.send_quota_query)

    def _do_query(self, name, func):
        order = self._query_order()
        if not order["account"]:
            messagebox.showwarning("缺少账号", "请先选择查询账号。", parent=self)
            return
        try:
            func(order)
        except (EngineError, messaging.MessageBuildError) as exc:
            messagebox.showerror("%s失败" % name, str(exc), parent=self)
            return
        self._log("send", "已发送%s，账号 %s，ClOrdID %s" % (name, order["account"], order["clordid"]))

    def clear_query_result(self):
        for key, table in self.query_tables.items():
            table["rows"] = []
            table["columns"] = []
            for item in table["tree"].get_children():
                table["tree"].delete(item)
            table["tree"].configure(columns=())
            self.query_notebook.tab(table["frame"], text=" %s " % table["caption"])
        self.query_raw.delete("1.0", "end")

    # ============================================================== 字典 ==
    def _on_dict_group(self, _event=None):
        selection = self.dict_groups.selection()
        if not selection:
            return
        key = selection[0]
        if key == self.dict_current:
            return
        self._dict_flush()
        self.dict_current = key
        self._dict_load()

    def _dict_load(self):
        key = self.dict_current
        title = dict(OPTION_GROUPS).get(key, key)
        self.dict_title.configure(text=title)
        if key == "__extra__":
            self.dict_list_frame.grid_remove()
            self.dict_text_frame.grid(row=1, column=0, sticky="nsew")
            self.dict_text.delete("1.0", "end")
            self.dict_text.insert("1.0", "\n".join(self.dict_working.get(key, [])))
            self.dict_input.configure(state="disabled")
        else:
            self.dict_text_frame.grid_remove()
            self.dict_list_frame.grid(row=1, column=0, sticky="nsew")
            self.dict_listbox.delete(0, "end")
            for item in self.dict_working.get(key, []):
                self.dict_listbox.insert("end", item)
            self.dict_input.configure(state="normal")

    def _dict_flush(self):
        key = self.dict_current
        if key == "__extra__":
            lines = [line.strip() for line in self.dict_text.get("1.0", "end").splitlines() if line.strip()]
            self.dict_working[key] = lines
        else:
            self.dict_working[key] = list(self.dict_listbox.get(0, "end"))

    def _dict_add(self):
        if self.dict_current == "__extra__":
            return
        text = self.dict_input.get().strip()
        if not text:
            return
        if text in self.dict_listbox.get(0, "end"):
            messagebox.showinfo("已存在", "“%s”已经在列表里了。" % text, parent=self)
            return
        self.dict_listbox.insert("end", text)
        self.dict_input.delete(0, "end")

    def _dict_remove(self):
        if self.dict_current == "__extra__":
            return
        for index in reversed(self.dict_listbox.curselection()):
            self.dict_listbox.delete(index)

    def _dict_move(self, offset):
        if self.dict_current == "__extra__":
            return
        selection = list(self.dict_listbox.curselection())
        if not selection:
            return
        items = list(self.dict_listbox.get(0, "end"))
        target = selection[0] + offset
        if target < 0 or target >= len(items):
            return
        items[selection[0]], items[target] = items[target], items[selection[0]]
        self.dict_listbox.delete(0, "end")
        for item in items:
            self.dict_listbox.insert("end", item)
        self.dict_listbox.selection_set(target)

    def _dict_save(self):
        self._dict_flush()
        if self.dict_current == "__extra__":
            bad = [line for line in self.dict_working["__extra__"] if "=" not in line or not line.split("=", 1)[0].strip().isdigit()]
            if bad:
                messagebox.showwarning("格式不对", "附加字段必须写成 tag=值：\n%s" % "\n".join(bad), parent=self)
                return
        self.options = copy.deepcopy(self.dict_working)
        config_store.save_options(self.options)
        self._apply_options_to_widgets()
        self._log("system", "字段字典已保存到 config/options.json")

    def _dict_reset(self):
        if not messagebox.askyesno("恢复默认", "确定把所有下拉字典恢复成默认值吗？", parent=self):
            return
        self.dict_working = copy.deepcopy(config_store.DEFAULT_OPTIONS)
        self._dict_load()

    def _dict_reload(self):
        self.dict_working = copy.deepcopy(self.options)
        self._dict_load()

    def _apply_options_to_widgets(self):
        for key, widget in self.option_combos.items():
            option_key = "account" if key == "query_account" else key
            values = self.options.get(option_key, [])
            try:
                widget.configure(values=values)
            except tk.TclError:
                pass

        for widget, option_key in self.option_linked:
            try:
                widget.configure(values=self.options.get(option_key, []))
            except tk.TclError:
                pass
        try:
            self.extra_input.configure(values=self.options.get("__extra__", []))
        except tk.TclError:
            pass

    # ========================================================== 事件处理 ==
    def _poll_events(self):
        try:
            for _ in range(200):
                event = self.events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.after(80, self._poll_events)
        except tk.TclError:
            pass

    def _handle_event(self, event):
        kind = event.get("kind")
        if kind == "raw":
            self._on_raw(event)
        elif kind == "session":
            self._on_session(event)
        elif kind == "exec":
            self._on_exec(event)
        elif kind == "cancel_reject":
            self._on_cancel_reject(event)
        elif kind == "query":
            self._on_query(event)
        elif kind == "error":
            self._log("error", event.get("text", ""))
        elif kind == "connect_error":
            self._set_state("error")
            self.conn_hint.configure(text=event.get("text", ""))
            self._log("error", "连接失败：%s" % event.get("text", ""))
            messagebox.showerror("连接失败", event.get("text", ""), parent=self)
        elif kind == "system":
            self._log("system", event.get("text", ""))

    def _on_raw(self, event):
        direction = event.get("direction")
        category = event.get("category")
        msgtype = event.get("msgtype", "")
        text = event.get("text", "")
        stamp = event.get("time", "")
        if category == "heartbeat":
            self._log("heartbeat", "%s 心跳 %s" % ("→" if direction == "S" else "←", text))
            return
        name = self.dictionary.message_name(msgtype)
        prefix = "→ 发送" if direction == "S" else "← 接收"
        if category == "admin":
            self._log("admin", "%s [%s %s] %s" % (prefix, msgtype, name, text))
        else:
            key = "send" if direction == "S" else "recv"
            self._log(key, "%s [%s %s] %s" % (prefix, msgtype, name, text))
        if direction == "S":
            self._sent_count += 1
        else:
            self._recv_count += 1
        self._update_counters()

    def _on_session(self, event):
        state = event.get("state", "")
        detail = event.get("detail", "")
        if state == "created":
            self._set_state("created")
            self.session_label.configure(text=detail)
            self._log("system", "会话已创建：%s" % detail)
        elif state == "logon":
            self._set_state("logon")
            self.session_label.configure(text=detail)
            self.conn_hint.configure(text="登录成功，可以下单了。")
            self._log("system", "登录成功：%s" % detail)
        elif state == "logout":
            self._set_state("logout")
            self._log("system", "会话已断开：%s" % detail)
        elif state == "connecting":
            self._set_state("connecting")
            self._log("system", "正在连接 %s …" % detail)
        elif state == "started":
            if self._state not in ("logon",):
                self._set_state("starting")
            self.conn_hint.configure(text="引擎已启动，等待网关登录响应…")
        elif state == "stopped":
            self._set_state("idle")
            self.session_label.configure(text="")
            self._log("system", "会话已停止")
        elif state == "logging_out":
            self._set_state("logging_out")

    def _set_state(self, state):
        self._state = state
        text, color = STATE_STYLE.get(state, ("未知", COLOR_MUTED))
        try:
            self.state_label.configure(text=text)
            self.state_dot.configure(fg=color)
        except tk.TclError:
            return
        self.status_left.configure(text="会话状态：%s" % text)
        busy = state in ("connecting", "starting", "created", "logon", "logging_out")
        try:
            self.btn_connect.configure(state="disabled" if busy else "normal")
            self.btn_disconnect.configure(state="normal" if self.engine.running else "disabled")
            self.btn_logout.configure(state="normal" if state == "logon" else "disabled")
        except tk.TclError:
            pass

    @staticmethod
    def _exec_action(data):
        """把执行回报归类成界面上的“动作”。"""
        etype = (data.get("exec_type") or "").strip()
        if etype in ("4", "6"):
            return "撤单回报"
        if etype in ("1", "2", "F", "7"):
            return "成交回报"
        if etype == "8":
            return "拒绝回报"
        if etype in ("0", "D", "A"):
            return "委托回报"
        return "其他回报"

    def _append_event(self, record, action, status, data=None, raw="", stamp=""):
        """给单笔委托追加一条回报记录（时间线）。"""
        data = data or {}
        events = record.setdefault("events", [])
        events.append({
            "time": stamp or time.strftime("%H:%M:%S"),
            "action": action,
            "status": status or "",
            "cum": str(data.get("cum_qty") or ""),
            "leaves": str(data.get("leaves_qty") or ""),
            "last_px": str(data.get("last_px") or ""),
            "avg_px": str(data.get("avg_px") or ""),
            "orderid": str(data.get("orderid") or ""),
            "execid": str(data.get("execid") or ""),
            "text": str(data.get("text") or ""),
            "raw": raw,
        })
        if len(events) > 200:
            del events[:-200]
        record["updated"] = events[-1]["time"]
        if not record.get("created"):
            record["created"] = events[0]["time"]

    def _on_exec(self, event):
        data = event.get("data") or {}
        clordid = data.get("clordid") or ""
        orig = data.get("orig_clordid") or ""
        # 撤单的回报里 11 是撤单委托号，必须落回原委托，不能新开一行
        target = self.cancel_map.get(clordid) or ""
        if not target:
            if orig and orig in self.orders:
                target = orig
            else:
                target = clordid or orig
        if not target:
            return

        record = self.orders.get(target)
        if record is None:
            record = models.empty_order()
            record.update({
                "time": event.get("time", ""),
                "clordid": target,
                "symbol": data.get("symbol") or "",
                "side": parser.side_text(data.get("side") or ""),
                "qty": data.get("qty") or "",
                "price": data.get("price") or "",
                "account": data.get("account") or "",
                "status": "已报",
                "filled": "0",
                "created": event.get("time", ""),
            })
            self.orders[target] = record

        if data.get("symbol"):
            record["symbol"] = data["symbol"]
        if data.get("orderid"):
            record["orderid"] = data["orderid"]
        status = data.get("status") or record.get("status") or ""
        if status:
            record["status"] = status
        if data.get("cum_qty") not in (None, ""):
            record["filled"] = data["cum_qty"]
        if data.get("leaves_qty") is not None:
            record["leaves"] = data["leaves_qty"]
        if data.get("avg_px"):
            record["avg_px"] = data["avg_px"]
        if data.get("last_px"):
            record["price"] = record.get("price") or data["last_px"]
        if data.get("text"):
            record["text"] = data["text"]
        record["active"] = bool(data.get("active", True))

        raw = " | ".join("%s=%s" % (t, v) for t, v in (data.get("pairs") or []))
        record["last_raw"] = raw
        self._append_event(record, self._exec_action(data), record["status"],
                           data, raw, event.get("time", ""))
        self._upsert_order_row(record)
        config_store.save_orders(list(self.orders.values()))

        self._log("system", "回报 %s：%s / %s，累计成交 %s，剩余 %s%s" % (
            target, self._exec_action(data), record["status"], record.get("filled", "-"),
            record.get("leaves", "-"),
            ("，说明 " + data["text"]) if data.get("text") else ""))

    def _on_cancel_reject(self, event):
        data = event.get("data") or {}
        clordid = data.get("clordid") or ""
        orig = data.get("orig_clordid") or ""
        target = self.cancel_map.get(clordid) or orig or clordid
        if not target:
            return
        record = self.orders.get(target)
        if record:
            record["status"] = "撤单拒绝"
            record["active"] = True
            if data.get("text"):
                record["text"] = data["text"]
            raw = " | ".join("%s=%s" % (t, v) for t, v in (data.get("pairs") or []))
            record["last_raw"] = raw
            self._append_event(record, "撤单拒绝", "撤单拒绝", data, raw, event.get("time", ""))
            self._upsert_order_row(record)
            config_store.save_orders(list(self.orders.values()))
        self._log("error", "撤单被拒绝 %s：%s" % (target, data.get("text") or ""))

    def _on_query(self, event):
        data = event.get("data") or {}
        label = data.get("label", "查询结果")
        pairs = data.get("pairs") or []
        msgtype = data.get("msgtype") or "OTHER"
        table = self.query_tables.get(msgtype) or self.query_tables["OTHER"]
        row = {"时间": event.get("time", "")}
        for tag, value in pairs:
            if tag in QUERY_SKIP_TAGS:
                continue
            name = self.dictionary.name(tag)
            column = name if name != tag else "Tag%s" % tag
            if column == "时间":
                column = "时间(%s)" % tag
            row[column] = self.dictionary.value_label(tag, value)
        table["rows"].append(row)
        if len(table["rows"]) > 500:
            table["rows"] = table["rows"][-500:]
        self._rebuild_query_table(table)
        self.query_notebook.tab(table["frame"],
                                text=" %s (%d) " % (table["caption"], len(table["rows"])))
        raw = " | ".join("%s=%s" % (t, v) for t, v in pairs)
        self.query_raw.insert("end", "[%s] %s %s\n%s\n\n" % (event.get("time", ""), label, msgtype, raw))
        self.query_raw.see("end")
        self._log("recv", "收到%s：%s" % (label, raw))

    def _rebuild_query_table(self, table):
        columns = ["时间"]
        for row in table["rows"]:
            for key in row:
                if key not in columns:
                    columns.append(key)
        columns = columns[:40]
        tree = table["tree"]
        if columns != table["columns"]:
            table["columns"] = columns
            tree.configure(columns=columns)
            for column in columns:
                tree.heading(column, text=column)
                if column == "时间":
                    sample = ["09:32:01"]
                elif column in ("Account", "Symbol", "SecurityExchange", "PositionType"):
                    sample = ["P1100209"]
                elif column == "ClOrdID":
                    sample = ["6201794888900101"]
                elif column in ("TransactTime", "SendingTime"):
                    sample = ["20261117-09:32:01"]
                else:
                    sample = ["000000000000"]
                tree.column(column, width=self._fit_width(column, sample, maximum=300),
                            minwidth=90, stretch=False, anchor="w")
        for item in tree.get_children():
            tree.delete(item)
        for row in table["rows"]:
            values = [row.get(column, "") for column in columns]
            tree.insert("", "end", values=values)

    # ========================================================== 委托列表 ==
    def _upsert_order_row(self, record):
        clordid = record.get("clordid")
        if not clordid:
            return
        values = []
        for key, _title, _width in models.ORDER_COLUMNS:
            if key == "qty":
                qty = str(record.get("qty", "") or "")
                filled = str(record.get("filled", "") or "")
                if filled and filled not in ("0", "0.0", "0.00"):
                    values.append("%s/%s" % (filled, qty))
                else:
                    values.append(qty)
            else:
                values.append(str(record.get(key, "") or ""))
        tag = "active" if record.get("active", True) else "done"
        if record.get("status") in ("拒绝", "撤单拒绝"):
            tag = "rejected"
        if self.order_tree.exists(clordid):
            self.order_tree.item(clordid, values=values, tags=(tag,))
        else:
            self.order_tree.insert("", "end", iid=clordid, values=values, tags=(tag,))
        self.order_tree.see(clordid)

    def _refresh_order_tree(self):
        for item in self.order_tree.get_children():
            self.order_tree.delete(item)
        for record in self.orders.values():
            self._upsert_order_row(record)

    def _clear_finished_orders(self):
        finished = [cid for cid, rec in self.orders.items() if not rec.get("active", True)]
        if not finished:
            messagebox.showinfo("提示", "没有已完成的委托。", parent=self)
            return
        if not messagebox.askyesno("清空", "从列表中移除 %d 笔已完成的委托（本机记录）？" % len(finished), parent=self):
            return
        for cid in finished:
            self.orders.pop(cid, None)
            if self.order_tree.exists(cid):
                self.order_tree.delete(cid)
        config_store.save_orders(list(self.orders.values()))

    def _show_order_detail(self, _event=None):
        selection = self.order_tree.selection()
        if not selection:
            return
        record = self.orders.get(selection[0])
        if not record:
            return

        win = tk.Toplevel(self)
        win.title("委托明细 - %s %s %s" % (
            record.get("clordid", ""), record.get("symbol", ""), record.get("side", "")))
        win.geometry("1020x720")
        win.minsize(840, 560)
        win.transient(self)

        body = ttk.Frame(win, padding=(12, 10))
        body.pack(fill="both", expand=True)

        buttons = ttk.Frame(body)
        buttons.pack(side="bottom", fill="x", pady=(8, 0))
        ttk.Button(buttons, text="复制委托号",
                   command=lambda: self._copy_text(record.get("clordid", ""))).pack(side="left")
        ttk.Button(buttons, text="关闭", command=win.destroy).pack(side="right")

        summary = ttk.LabelFrame(body, text="委托概要（最新状态）", padding=(10, 8))
        summary.pack(fill="x")
        summary.columnconfigure(1, weight=1)
        summary.columnconfigure(3, weight=1)
        pairs = [
            ("本地委托号", record.get("clordid")),
            ("柜台委托号", record.get("orderid")),
            ("交易标的", record.get("symbol")),
            ("买卖方向", record.get("side")),
            ("委托数量", record.get("qty")),
            ("委托价格", record.get("price")),
            ("累计成交", record.get("filled")),
            ("当前状态", record.get("status")),
            ("资金账号", record.get("account")),
            ("最后更新", record.get("updated")),
        ]
        for index, (label, value) in enumerate(pairs):
            row, col = divmod(index, 2)
            base = col * 2
            ttk.Label(summary, text=label, style="Hint.TLabel").grid(
                row=row, column=base, sticky="w", padx=(0, 6), pady=2)
            ttk.Label(summary, text=str(value if value not in (None, "") else "-")).grid(
                row=row, column=base + 1, sticky="w", padx=(0, 20))

        timeline = ttk.LabelFrame(
            body, text="回报时间线（报单 → 委托回报 → 成交回报 / 撤单回报，按时间排序）", padding=(10, 8))
        timeline.pack(fill="both", expand=True, pady=(10, 0))
        timeline.rowconfigure(0, weight=1)
        timeline.columnconfigure(0, weight=1)

        fields = ("time", "action", "status", "cum", "leaves", "last_px", "avg_px", "text")
        titles = {"time": "时间", "action": "动作", "status": "状态", "cum": "累计成交",
                  "leaves": "剩余", "last_px": "成交价", "avg_px": "成交均价", "text": "说明"}
        tree = ttk.Treeview(timeline, columns=fields, show="headings", height=10)
        samples = {"time": ["13:52:30.123"], "action": ["撤单请求"], "status": ["部分成交"],
                   "cum": ["2000"], "leaves": ["1000"], "last_px": ["10.23"],
                   "avg_px": ["10.22"], "text": ["这是一段说明文字"]}
        for key in fields:
            tree.heading(key, text=titles[key])
            tree.column(key, width=max(70, self._fit_width(titles[key], samples.get(key, []))),
                        minwidth=60, stretch=(key == "text"), anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(timeline, orient="vertical", command=tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        tree.configure(yscrollcommand=scroll.set)

        tree.tag_configure("order", background="#f2f8ff")
        tree.tag_configure("fill", background="#e9f8ec")
        tree.tag_configure("cancel", background="#fff4e6")
        tree.tag_configure("reject", background="#ffe3e0", foreground="#a8071a")

        raw_frame = ttk.LabelFrame(body, text="原始报文（点上面任意一条查看）", padding=(8, 6))
        raw_frame.pack(fill="both", expand=False, pady=(10, 0))
        raw_text = scrolledtext.ScrolledText(raw_frame, font=FONT_MONO, height=7, wrap="none")
        raw_text.pack(fill="both", expand=True)

        events = sorted(record.get("events") or [], key=lambda item: item.get("time") or "")
        if not events:
            tree.insert("", "end", values=("-", "无记录", "-", "-", "-", "-", "-",
                                           "这笔委托还没有回报记录（可能是升级前下的单）"))
        mapping = {}
        for index, ev in enumerate(events):
            action = ev.get("action") or ""
            if action in ("报单", "撤单请求"):
                tag = "order" if action == "报单" else "cancel"
            elif action == "成交回报":
                tag = "fill"
            elif action in ("拒绝回报", "撤单拒绝"):
                tag = "reject"
            elif action == "撤单回报":
                tag = "cancel"
            else:
                tag = "order"
            iid = tree.insert("", "end", values=(
                ev.get("time", ""), action, ev.get("status", ""), ev.get("cum", ""),
                ev.get("leaves", ""), ev.get("last_px", ""), ev.get("avg_px", ""),
                ev.get("text", "")), tags=(tag,))
            mapping[iid] = ev

        def show_raw(_event=None):
            selection_ids = tree.selection()
            if not selection_ids:
                return
            ev = mapping.get(selection_ids[0])
            if not ev:
                return
            raw_text.configure(state="normal")
            raw_text.delete("1.0", "end")
            raw_text.insert("1.0", ev.get("raw", "") or "（没有保存原始报文）")
            raw_text.configure(state="disabled")

        tree.bind("<<TreeviewSelect>>", show_raw)
        if events:
            first = tree.get_children()[0]
            tree.selection_set(first)
            tree.focus(first)
            show_raw()
        else:
            raw_text.configure(state="disabled")

    def _copy_text(self, text):
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)

    def _copy_selected_clordid(self):
        selection = self.order_tree.selection()
        if not selection:
            return
        self.clipboard_clear()
        self.clipboard_append(selection[0])
        self._log("system", "已复制委托号：%s" % selection[0])

    def _remember_symbol_exchange(self, symbol, exchange):
        if not symbol or not exchange:
            return
        mapping = self.settings.setdefault("symbol_exchange", {})
        if mapping.get(symbol) != exchange:
            mapping[symbol] = exchange
            config_store.save_settings(self.settings)

    # ============================================================== 日志 ==
    def _log(self, category, text):
        stamp = time.strftime("%H:%M:%S")
        if category == "heartbeat" and not self.log_filters["heartbeat"].get():
            self.log_entries.append((stamp, category, text))
            return
        self.log_entries.append((stamp, category, text))
        if len(self.log_entries) > 8000:
            self.log_entries = self.log_entries[-6000:]
            self._render_log()
            return
        if self._log_visible(category):
            self._append_log_line(stamp, category, text)

    def _log_visible(self, category):
        if category == "error":
            return True
        key = category if category in self.log_filters else "system"
        try:
            return bool(self.log_filters[key].get())
        except KeyError:
            return True

    def _append_log_line(self, stamp, category, text):
        widget = self.log_text
        widget.configure(state="normal")
        widget.insert("end", stamp + "  ", ("time",))
        tag = category if category in LOG_COLORS else "system"
        widget.insert("end", text + "\n", (tag,))
        widget.configure(state="disabled")
        if self.log_autoscroll.get():
            widget.see("end")

    def _render_log(self):
        widget = self.log_text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        for stamp, category, text in self.log_entries:
            if not self._log_visible(category):
                continue
            widget.insert("end", stamp + "  ", ("time",))
            widget.insert("end", text + "\n", (category if category in LOG_COLORS else "system",))
        widget.configure(state="disabled")
        if self.log_autoscroll.get():
            widget.see("end")

    def _clear_log(self):
        self.log_entries = []
        self._render_log()

    def _export_log(self):
        path = filedialog.asksaveasfilename(
            title="导出日志", defaultextension=".log",
            initialfile="fix-%s.log" % time.strftime("%Y%m%d-%H%M%S"),
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                for stamp, category, text in self.log_entries:
                    fh.write("%s  [%s]  %s\n" % (stamp, category, text))
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self)
            return
        messagebox.showinfo("导出成功", "日志已保存到：\n%s" % path, parent=self)

    # ============================================================ 统计等 ==
    _sent_count = 0
    _recv_count = 0

    def _update_counters(self):
        total = len(self.orders)
        active = sum(1 for rec in self.orders.values() if rec.get("active", True))
        self.status_right.configure(
            text="委托 %d 笔（进行中 %d）   发送 %d 条 / 接收 %d 条"
            % (total, active, self._sent_count, self._recv_count))

    # ========================================================== 报文预览 ==
    def _show_message(self, title, message):
        text = messaging.message_text(message)
        win = tk.Toplevel(self)
        win.title(title)
        win.geometry("940x660")
        win.transient(self)
        top = ttk.Frame(win, padding=(10, 8))
        top.pack(fill="both", expand=True)
        top.rowconfigure(0, weight=1)
        top.columnconfigure(0, weight=1)

        box = scrolledtext.ScrolledText(top, font=FONT_MONO, wrap="char", height=8)
        box.grid(row=0, column=0, sticky="nsew")
        box.insert("1.0", text)
        box.configure(state="disabled")

        ttk.Label(
            top,
            text="提示：8/9/34/49/52/56/10 等会话级字段由 QuickFIX 在发送时自动填充，这里只展示将要发送的业务字段。",
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        ttk.Label(top, text="字段明细").grid(row=2, column=0, sticky="w", pady=(8, 4))
        columns = ("tag", "name", "value")
        tree = ttk.Treeview(top, columns=columns, show="headings", height=10)
        tree.heading("tag", text="Tag")
        tree.heading("name", text="字段名")
        tree.heading("value", text="值")
        tree.column("tag", width=60, anchor="center")
        tree.column("name", width=180)
        tree.column("value", width=560)
        tree.grid(row=3, column=0, sticky="nsew")
        top.rowconfigure(3, weight=1)

        for tag, value in messaging.message_pairs(message):
            tree.insert("", "end", values=(tag, self.dictionary.name(tag), value))

        buttons = ttk.Frame(top)
        buttons.grid(row=4, column=0, sticky="e", pady=(8, 0))

        def copy():
            self.clipboard_clear()
            self.clipboard_append(text)

        ttk.Button(buttons, text="复制报文", command=copy).pack(side="left", padx=4)
        ttk.Button(buttons, text="关闭", command=win.destroy).pack(side="left")

    # ========================================================== 帮助/关闭 ==
    def show_help(self):
        win = tk.Toplevel(self)
        win.title("使用说明")
        win.geometry("760x600")
        win.transient(self)
        text = scrolledtext.ScrolledText(win, font=FONT, wrap="word")
        text.pack(fill="both", expand=True, padx=12, pady=12)
        text.insert("1.0", HELP_TEXT)
        text.configure(state="disabled")

    def show_about(self):
        messagebox.showinfo(
            "关于",
            "FIX 下单助手 %s\n\n" % version_text() +
            "由原 fix-test 命令行脚本改写的图形界面版本：\n"
            "· 连接参数全部可视化配置（等同 client.cfg）\n"
            "· 下单字段全部下拉选择，支持自定义字典\n"
            "· 支持新建委托 / 撤单 / 资金、持仓、额度查询\n"
            "· 下单、撤单、成交回报都在同一个「交易」页\n\n"
            "配置目录：%s" % APP_ROOT,
            parent=self)

    def _apply_last_order(self):
        last = self.settings.get("last_order") or {}
        for key, value in last.items():
            if key in self.order_vars and value != "":
                try:
                    self.order_vars[key].set(value)
                except tk.TclError:
                    pass
        if self.auto_clordid_var.get():
            self.clordid_entry.configure(state="disabled")
        else:
            self.clordid_entry.configure(state="normal")
        self._regen_clordid()

    def _collect_last_order(self):
        return {key: var.get() for key, var in self.order_vars.items() if key != "clordid"}

    def reset_order_form(self):
        enum_defaults = {
            "security_type": models.SECURITY_TYPE,
            "side": models.SIDE,
            "ordtype": models.ORD_TYPE,
            "tif": models.TIME_IN_FORCE,
            "handl_inst": models.HANDL_INST,
            "position_effect": models.POSITION_EFFECT,
        }
        for key, var in self.order_vars.items():
            if key == "clordid":
                continue
            widget = self.option_combos.get(key)
            if widget is not None:
                values = list(widget.cget("values") or [])
                var.set(values[0] if values else "")
            elif key in enum_defaults:
                var.set(enum_defaults[key].labels[0])
        self._clear_extras()
        self.auto_clordid_var.set(True)
        self.clordid_entry.configure(state="disabled")
        self._regen_clordid()

    def on_close(self):
        try:
            self.update_idletasks()
            self.settings["ui"] = self.settings.get("ui") or {}
            self.settings["ui"]["geometry"] = self.geometry()
            self.settings["ui"]["auto_clordid"] = bool(self.auto_clordid_var.get())
            self.settings["ui"]["auto_symbol_exchange"] = bool(self.auto_symbol_exchange.get())
            self.settings["last_order"] = self._collect_last_order()
            config_store.save_settings(self.settings)
            config_store.save_options(self.options)
            config_store.save_orders(list(self.orders.values()))
        except Exception:  # noqa: BLE001
            pass
        try:
            self.engine.stop()
        except Exception:  # noqa: BLE001
            pass
        self.destroy()


HELP_TEXT = """FIX 下单助手 使用说明
=====================================

一、连接配置
1. “连接配置”页里的每个参数都会写进自动生成的 runtime/client_runtime.cfg：
   服务器地址、端口、SenderCompID、TargetCompID、SenderSubID、版本号、心跳、
   重连间隔、登录超时、交易时段、数据字典路径、序号存储目录等。
2. 填好后点“保存”，配置会记在 config/settings.json 里，下次启动自动带出。
3. 点“连接交易网关”启动会话；顶部状态变成绿色“已登录”后即可下单。
4. 更换网关或账号时，建议点“重置序号并重连”，避免序号冲突导致登录被拒。
5. 可以建多个配置档案（生产/测试），在下拉框里切换。

二、交易（下单 + 撤单 + 回报在同一页）
1. 所有字段都是下拉框，选项来自“字段字典”页，也可以直接在框里输入新值。
2. 选择交易标的时会自动带出交易市场（可记忆你实际用过的对应关系）。
3. “本地委托号”默认自动生成，规则在连接配置里设置（前缀 + 时间戳/顺序号）。
4. 选择“市价”时会自动清空价格；限价单必须填价格。
5. 附加字段用于写入非标准 tag，例如 11000=3（融券标志）、951 策略名等，
   可以从下拉预设里选，也可以手填 “tag=值” 后点添加。
6. “预览报文”可以先看看将要发出去的 FIX 报文，不会真正发送。
7. Ctrl+Enter 快捷键 = 发送委托。

三、委托列表与撤单
右侧列表每行是一笔委托的“最新状态”，不是流水：时间、本地委托号、代码、方向、
成交量/委托量、价格、状态、柜台委托号。
1. 看单笔的完整过程：双击这一行（或右键 → 查看回报明细），会弹出该笔委托的回报时间线，
   按时间顺序列出：报单 → 委托回报 → 成交回报 / 撤单请求 / 撤单回报 / 撤单拒绝，
   点其中任意一条，下方显示对应的原始 FIX 报文。
2. 撤单：在列表里选中一笔委托，点“撤单选中”，确认后发送；原始委托号、代码、方向、
   账号都取自这一行，不需要手输。
“撤单备注”会写进 58 字段；撤单结果（已撤 / 撤单拒绝）会追加到该笔委托的回报时间线里，
列表里的状态同步更新。“预览撤单”可以先看报文，不会真发。

四、查询
选择账号后点“资金查询 / 持仓查询 / 额度查询”，应答会以表格 + 原始报文两种方式展示。

五、字段字典
每组下拉选项都可以增删、排序；附加字段预设按 “tag=值” 每行一个。
保存后立即作用到所有下拉框，并写入 config/options.json。

六、运行日志
所有收发的 FIX 报文、成交回报、错误都会记录，可按类别过滤并导出成文件。
报文中的 SOH(\\x01) 统一显示为 “|”。

七、常见问题
· 登录被拒绝并提示序号不匹配：点“重置序号并重连”。
· 提示“数据字典文件不存在”：检查连接配置里的 DataDictionary 路径。
· 程序目录不要放在含中文的路径下：QuickFIX 读取配置时不支持中文路径。
"""
