"""TaskBarHero 挂机助手 — 图形界面。"""

from __future__ import annotations

import queue
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from tbh_helper.config_loader import load_config, profile_path_from_cfg, save_config
from tbh_helper.portal import PortalNavigator, StageTarget
from tbh_helper.chest_open import ChestOpenConfig, open_chest
from tbh_helper.engine import RotatorEngine
from tbh_helper.gui_countdown import open_countdown_capture_dialog
from tbh_helper.profile import PortalProfile
from tbh_helper.statistics import StatisticsTracker
from tbh_helper.ui_theme import (
    ACCENT,
    BG,
    BORDER,
    BORDER_WINE,
    Card,
    FONT_BOLD,
    FONT_SUB,
    FONT_TITLE,
    FONT_UI,
    GOLD,
    GOLD_HOVER,
    RoundedButton,
    SegmentedControl,
    StatusPill,
    StepRow,
    StatusFlow,
    StyledScrollbar,
    StyledScrolledText,
    SURFACE,
    SURFACE2,
    TEXT,
    TEXT2,
    apply_root_style,
    style_entry,
    style_listbox,
    style_log,
    style_option_menu,
)
from tbh_helper.mouse import click_at
from tbh_helper.paths import app_dir, ensure_runtime_files, prompt_vc_runtime
from tbh_helper.window import (
    find_game_window,
    get_client_rect_screen,
    get_cursor_pos,
    is_process_elevated,
    is_self_elevated,
)

BASE_DIR = ensure_runtime_files()
CONFIG_PATH = app_dir() / "config.yaml"

PORTAL_UI_WIZARD = [
    ("chapter_1", "第 1 章", "鼠标移到第 1 章标签"),
    ("chapter_2", "第 2 章", "鼠标移到第 2 章标签"),
    ("chapter_3", "第 3 章", "鼠标移到第 3 章标签"),
    ("diff_dropdown", "难度下拉", "鼠标移到难度下拉框"),
    ("diff_normal", "普通难度", "鼠标移到「普通」选项"),
    ("diff_nightmare", "噩梦难度", "鼠标移到「噩梦」选项"),
    ("diff_hell", "地狱难度", "鼠标移到「地狱」选项"),
    ("diff_torment", "折磨难度", "鼠标移到「折磨」选项"),
    ("scroll_area", "滚轮区域", "鼠标移到地图滚轮区域"),
]


class TBHApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("TaskBarHeroHelper")
        self.geometry("520x920")
        self.minsize(480, 800)
        apply_root_style(self)

        self.cfg = load_config(CONFIG_PATH)
        self.engine = RotatorEngine(
            self.cfg, BASE_DIR, on_log=self._enqueue_log, on_switch=self._on_switch, on_drop=self._on_drop,
            on_stats_update=self._mark_stats_dirty,
        )
        # on_status / on_manual_switch_done 在 _build_run_page 中绑定（控件创建后才可引用）
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._anchor = None
        self._drop_count = 0
        self._wizard_idx = 0

        self._build_ui()
        # 启动时自动从配置恢复窗口锚点
        self._restore_anchor()
        prompt_vc_runtime(self)
        self._check_elevation()
        self._refresh_status()
        self._refresh_setup_steps()
        self.after(100, self._drain_log_queue)

    # ── UI 构建 ───────────────────────────────────────────

    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=BG, padx=20, pady=16)
        root.pack(fill=tk.BOTH, expand=True)

        # 顶栏
        header = tk.Frame(root, bg=BG)
        header.pack(fill=tk.X, pady=(0, 14))
        tk.Label(header, text="挂机助手", font=FONT_TITLE, bg=BG, fg=TEXT).pack(side=tk.LEFT)

        right = tk.Frame(header, bg=BG)
        right.pack(side=tk.RIGHT)
        RoundedButton(
            right, "📁 配置", self._open_config_dir, width=76, height=26, radius=8, style="ghost"
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.game_pill = StatusPill(right)
        self.game_pill.pack(side=tk.LEFT)

        # 分段切换
        self.page_run = tk.Frame(root, bg=BG)
        self.page_setup = tk.Frame(root, bg=BG)
        self.page_stats = tk.Frame(root, bg=BG)
        self.page_misc = tk.Frame(root, bg=BG)
        self._seg = SegmentedControl(
            root,
            [("运行", self._show_run), ("设置", self._show_setup), ("杂项", self._show_misc), ("统计", self._show_stats)],
        )
        self._seg.pack(pady=(0, 14))
        self._seg.select(0)

        self._build_run_page(self.page_run)
        self._build_setup_page(self.page_setup)
        self._build_stats_page(self.page_stats)
        self._build_misc_page(self.page_misc)
        self.page_run.pack(fill=tk.BOTH, expand=True)
        self._show_run()

        # 布局定型
        self.update_idletasks()

    def _build_run_page(self, parent: tk.Frame) -> None:
        card = Card(parent)
        card.pack(fill=tk.X, pady=(0, 12))

        self.var_mode = tk.StringVar(value="待机")
        self.var_stats = tk.StringVar(value="Boss 箱 0  ·  换图 0")
        self.var_next = tk.StringVar(value="")

        self.lbl_mode = tk.Label(card.inner, textvariable=self.var_mode, font=FONT_SUB, bg=SURFACE, fg=TEXT)
        self.lbl_mode.pack(anchor=tk.W)
        tk.Label(card.inner, textvariable=self.var_stats, font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(anchor=tk.W, pady=(4, 0))
        tk.Label(card.inner, textvariable=self.var_next, font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(anchor=tk.W, pady=(2, 0))

        btn_row = tk.Frame(parent, bg=BG)
        btn_row.pack(fill=tk.X, pady=(0, 12))

        inner_row = tk.Frame(btn_row, bg=BG)
        inner_row.pack()

        self.btn_start = RoundedButton(inner_row, "开始挂机", self._start, width=200, height=44, radius=14)
        self.btn_start.pack(side=tk.LEFT)

        self.btn_next = RoundedButton(
            inner_row, "下一关", self._next_stage, width=88, height=44, radius=14, style="secondary"
        )
        self.btn_next.pack(side=tk.LEFT, padx=(10, 0))
        self.btn_next.configure_state(tk.DISABLED)

        # 流程状态条
        self.status_flow = StatusFlow(parent)
        self.status_flow.pack(fill=tk.X, pady=(0, 8))
        self.engine.on_status = lambda **kw: self.status_flow.show(**kw)
        self.engine.on_manual_switch_done = lambda: self.after_idle(self._on_manual_switch_done)

        log_card = Card(parent, padding=0)
        log_card.pack(fill=tk.BOTH, expand=True)
        # 子控件放入 inner，避免 Card 空 inner 框架占用空间
        tk.Label(log_card.inner, text="  日志", font=FONT_UI, bg=SURFACE, fg=GOLD, anchor=tk.W).pack(
            fill=tk.X, padx=12, pady=(10, 0)
        )
        self.log_text = StyledScrolledText(log_card.inner, height=10, state=tk.DISABLED, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        style_log(self.log_text.text)

    def _build_setup_page(self, parent: tk.Frame) -> None:
        scroll_outer = tk.Frame(parent, bg=BG)
        scroll_outer.pack(fill=tk.BOTH, expand=True)

        # 步骤 1
        self.step_anchor = StepRow(scroll_outer, 1, "捕获窗口位置", "自动获取游戏窗口客户区作为坐标基准")
        self.step_anchor.pack(fill=tk.X, pady=(0, 8))
        btn_frame1 = tk.Frame(self.step_anchor.action_slot, bg=SURFACE)
        btn_frame1.pack()
        self.btn_capture_win = RoundedButton(
            btn_frame1, "捕获窗口", self._capture_window_anchor,
            width=88, height=32, radius=10, style="secondary",
        )
        self.btn_capture_win.pack(side=tk.LEFT)
        self.btn_show_overlay = RoundedButton(
            btn_frame1, "显示范围", self._toggle_overlay,
            width=72, height=32, radius=10, style="secondary",
        )
        self.btn_show_overlay.pack(side=tk.LEFT, padx=(4, 0))
        self._overlay = None

        # 步骤 2
        self.step_ui = StepRow(scroll_outer, 2, "标定传送门 UI", "章节、难度、滚轮，一键向导")
        self.step_ui.pack(fill=tk.X, pady=(0, 8))
        RoundedButton(
            self.step_ui.action_slot,
            "向导",
            self._run_portal_ui_wizard,
            width=72,
            height=32,
            radius=10,
            style="secondary",
        ).pack()

        # 步骤 3 — 轮换节点
        stage_card = Card(scroll_outer, padding=12)
        stage_card.pack(fill=tk.X, pady=(0, 8))

        stage_head = tk.Frame(stage_card.inner, bg=SURFACE)
        stage_head.pack(fill=tk.X, pady=(0, 8))
        tk.Label(stage_head, text="步骤 3  ·  轮换节点", font=FONT_SUB, bg=SURFACE, fg=TEXT).pack(side=tk.LEFT)
        RoundedButton(
            stage_head, "＋ 添加", self._add_stage, width=72, height=28, radius=8, style="ghost"
        ).pack(side=tk.RIGHT)

        list_frame = tk.Frame(stage_card.inner, bg=SURFACE)
        list_frame.pack(fill=tk.X, pady=(0, 8))

        self.stage_list = tk.Listbox(list_frame, exportselection=False, height=4)
        self.stage_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        style_listbox(self.stage_list)

        list_scroll = StyledScrollbar(
            list_frame, command=self.stage_list.yview,
        )
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.stage_list.configure(yscrollcommand=list_scroll.set)
        self._load_stage_list()

        stage_btns = tk.Frame(stage_card.inner, bg=SURFACE)
        stage_btns.pack(fill=tk.X)
        for label, cmd, w in (
            ("编辑", self._edit_stage, 56),
            ("重标", self._mark_stage_pos, 56),
            ("点击测试", self._test_stage_click, 72),
            ("删除", self._delete_stage, 48),
            ("↑", lambda: self._move_stage(-1), 36),
            ("↓", lambda: self._move_stage(1), 36),
        ):
            RoundedButton(stage_btns, label, cmd, width=w, height=28, radius=8, style="secondary").pack(
                side=tk.LEFT, padx=(0, 4)
            )

        # 标记提示
        hint_frame = tk.Frame(stage_card.inner, bg=SURFACE)
        hint_frame.pack(fill=tk.X, pady=(2, 0))
        tk.Label(
            hint_frame,
            text="💡 1-7关拉到地图最底边标记，8-10关拉到地图最顶边标记",
            font=FONT_UI,
            bg=SURFACE,
            fg=TEXT2,
            wraplength=380,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

        # 步骤 3.5 — 超时切关
        timeout_frame = tk.Frame(stage_card.inner, bg=SURFACE)
        timeout_frame.pack(fill=tk.X, pady=(8, 0))
        tk.Label(
            timeout_frame, text="超时切关（分钟）", font=FONT_UI, bg=SURFACE, fg=TEXT2
        ).pack(side=tk.LEFT)
        self.var_timeout_minutes = tk.StringVar(
            value=str(self.cfg.get("rotation", {}).get("stage_timeout_minutes", 0))
        )
        self.entry_timeout = tk.Entry(
            timeout_frame,
            textvariable=self.var_timeout_minutes,
            width=6,
            font=FONT_UI,
            bg=SURFACE2,
            fg=TEXT,
            relief=tk.FLAT,
            justify=tk.CENTER,
        )
        self.entry_timeout.pack(side=tk.RIGHT)
        self.entry_timeout.bind("<FocusOut>", self._on_timeout_focus_out)
        self.entry_timeout.bind("<Return>", self._on_timeout_focus_out)
        tk.Label(
            timeout_frame, text="0 = 关闭", font=FONT_UI, bg=SURFACE, fg=TEXT2
        ).pack(side=tk.RIGHT, padx=(0, 6))

        # 步骤 4 — 开宝箱
        chest_card = Card(scroll_outer, padding=12)
        chest_card.pack(fill=tk.X)

        chest_cfg = ChestOpenConfig.from_dict(self.cfg.get("chest_open"))
        self.var_chest_enabled = tk.BooleanVar(value=chest_cfg.enabled)

        row = tk.Frame(chest_card.inner, bg=SURFACE)
        row.pack(fill=tk.X)
        tk.Label(row, text="步骤 4  ·  自动开宝箱", font=FONT_SUB, bg=SURFACE, fg=TEXT).pack(side=tk.LEFT)

        chest_row = tk.Frame(chest_card.inner, bg=SURFACE)
        chest_row.pack(fill=tk.X, pady=(8, 0))
        self.var_chest_hint = tk.StringVar(value=self._chest_hint_text())
        tk.Label(chest_row, text="蓝箱", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
        tk.Label(chest_row, textvariable=self.var_chest_hint, font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        chest_toggle = tk.Checkbutton(
            chest_row,
            text="启用",
            variable=self.var_chest_enabled,
            command=self._save_chest_enabled,
            bg=SURFACE,
            fg=GOLD,
            selectcolor=SURFACE2,
            activebackground=SURFACE,
            activeforeground=GOLD_HOVER,
            font=FONT_UI,
        )
        chest_toggle.pack(side=tk.RIGHT)
        RoundedButton(
            chest_row, "标记位置", self._mark_chest, width=82, height=28, radius=8, style="secondary"
        ).pack(side=tk.RIGHT, padx=(0, 4))
        RoundedButton(
            chest_row, "点击测试", self._test_chest_click, width=64, height=28, radius=8, style="ghost"
        ).pack(side=tk.RIGHT)

        # 普通宝箱
        norm_row = tk.Frame(chest_card.inner, bg=SURFACE)
        norm_row.pack(fill=tk.X, pady=(4, 0))
        self.var_norm_hint = tk.StringVar(value=self._normal_chest_hint_text())
        tk.Label(norm_row, text="白箱", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
        tk.Label(norm_row, textvariable=self.var_norm_hint, font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(
            side=tk.LEFT, padx=(6, 0)
        )
        self.var_norm_chest_enabled = tk.BooleanVar(
            value=ChestOpenConfig.from_dict(self.cfg.get("normal_chest")).enabled
        )
        norm_toggle = tk.Checkbutton(
            norm_row,
            text="启用",
            variable=self.var_norm_chest_enabled,
            command=self._save_norm_chest_enabled,
            bg=SURFACE,
            fg=GOLD,
            selectcolor=SURFACE2,
            activebackground=SURFACE,
            activeforeground=GOLD_HOVER,
            font=FONT_UI,
        )
        norm_toggle.pack(side=tk.RIGHT)
        RoundedButton(
            norm_row, "标记位置", self._mark_normal_chest, width=82, height=28, radius=8, style="secondary"
        ).pack(side=tk.RIGHT, padx=(0, 4))
        RoundedButton(
            norm_row, "点击测试", self._test_normal_chest_click, width=64, height=28, radius=8, style="ghost"
        ).pack(side=tk.RIGHT)

        # 点击方式（紧凑一行，塞在开宝箱卡片底部）
        method_row2 = tk.Frame(chest_card.inner, bg=SURFACE)
        method_row2.pack(fill=tk.X, pady=(6, 0))
        tk.Label(method_row2, text="点击方式", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
        self.var_click_method = tk.StringVar(
            value=self.cfg.get("chest_open", {}).get("click_method", "auto")
        )
        method_combo = ttk.Combobox(
            method_row2,
            textvariable=self.var_click_method,
            values=("auto", "sendinput", "mouse_event", "postmessage"),
            state="readonly",
            width=14,
            font=FONT_UI,
        )
        method_combo.pack(side=tk.RIGHT)
        method_combo.bind("<<ComboboxSelected>>", self._save_click_method)

    def _build_misc_page(self, parent: tk.Frame) -> None:
        scroll_outer = tk.Frame(parent, bg=BG)
        scroll_outer.pack(fill=tk.BOTH, expand=True)

        # ── 自动存仓库 ──
        wh_card = Card(scroll_outer, padding=12)
        wh_card.pack(fill=tk.X, pady=(0, 8))

        tk.Label(wh_card.inner, text="自动存仓库", font=FONT_SUB, bg=SURFACE, fg=TEXT).pack(
            anchor=tk.W, pady=(0, 8)
        )

        # 仓库标签页
        tab_head = tk.Frame(wh_card.inner, bg=SURFACE)
        tab_head.pack(fill=tk.X, pady=(0, 8))
        tk.Label(tab_head, text="仓库标签页", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
        RoundedButton(
            tab_head, "＋ 添加", self._add_warehouse_page, width=72, height=28, radius=8, style="ghost"
        ).pack(side=tk.RIGHT)

        list_frame = tk.Frame(wh_card.inner, bg=SURFACE)
        list_frame.pack(fill=tk.X, pady=(0, 8))

        self.warehouse_list = tk.Listbox(list_frame, exportselection=False, height=4)
        self.warehouse_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        style_listbox(self.warehouse_list)

        list_scroll = StyledScrollbar(
            list_frame, command=self.warehouse_list.yview,
        )
        list_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.warehouse_list.configure(yscrollcommand=list_scroll.set)
        self._adjust_warehouse_list_height(0)

        tab_btns = tk.Frame(wh_card.inner, bg=SURFACE)
        tab_btns.pack(fill=tk.X)
        RoundedButton(
            tab_btns, "删除页面", self._delete_warehouse_page, width=80, height=28, radius=8, style="secondary"
        ).pack(side=tk.LEFT, padx=(0, 4))
        RoundedButton(
            tab_btns, "重标", self._remark_warehouse_page, width=56, height=28, radius=8, style="secondary"
        ).pack(side=tk.LEFT, padx=(0, 4))

        # 转移按钮
        transfer_section = tk.Frame(wh_card.inner, bg=SURFACE)
        transfer_section.pack(fill=tk.X, pady=(12, 0))
        tk.Label(transfer_section, text="存仓按钮", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
        RoundedButton(
            transfer_section, "标记位置", self._mark_warehouse_transfer, width=88, height=28, radius=8, style="secondary"
        ).pack(side=tk.RIGHT)
        self.var_transfer_hint = tk.StringVar(value="未标记")
        tk.Label(
            transfer_section, textvariable=self.var_transfer_hint, font=FONT_UI, bg=SURFACE, fg=TEXT2
        ).pack(side=tk.RIGHT, padx=(0, 8))

        # 定时设置
        timer_section = tk.Frame(wh_card.inner, bg=SURFACE)
        timer_section.pack(fill=tk.X, pady=(12, 0))

        wh_cfg = self.cfg.get("warehouse", {})
        self.var_warehouse_enabled = tk.BooleanVar(value=bool(wh_cfg.get("enabled", False)))
        self.var_warehouse_interval = tk.StringVar(
            value=str(wh_cfg.get("interval_minutes", 30))
        )

        row = tk.Frame(timer_section, bg=SURFACE)
        row.pack(fill=tk.X)

        tk.Label(row, text="启用", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
        tk.Checkbutton(
            row, text="", variable=self.var_warehouse_enabled, command=self._save_warehouse_config,
            bg=SURFACE, fg=GOLD, selectcolor=SURFACE2, activebackground=SURFACE,
            activeforeground=GOLD_HOVER, font=FONT_UI,
        ).pack(side=tk.LEFT, padx=(4, 0))

        tk.Label(row, text="间隔", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT, padx=(12, 4))

        entry = tk.Entry(
            row, textvariable=self.var_warehouse_interval, width=6, font=FONT_UI,
            bg=SURFACE2, fg=TEXT, relief=tk.FLAT, justify=tk.CENTER,
        )
        entry.pack(side=tk.LEFT)
        entry.bind("<FocusOut>", self._save_warehouse_config)
        entry.bind("<Return>", self._save_warehouse_config)
        tk.Label(row, text="分钟", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT, padx=(4, 0))

        # ── 邮箱超时检查 ──
        mail_card = Card(scroll_outer, padding=12)
        mail_card.pack(fill=tk.X, pady=(8, 0))

        tk.Label(mail_card.inner, text="邮箱超时检查", font=FONT_SUB, bg=SURFACE, fg=TEXT).pack(
            anchor=tk.W, pady=(0, 8)
        )
        tk.Label(
            mail_card.inner,
            text="超时后自动打开邮箱→刷新→全部接收→关闭，再等待一轮掉箱检测",
            font=FONT_UI, bg=SURFACE, fg=TEXT2, wraplength=380, anchor=tk.W, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 6))

        mail_btn_names = [
            ("open", "打开邮箱"),
            ("refresh", "刷新邮箱"),
            ("receive_all", "全部接收"),
            ("close", "关闭邮箱"),
        ]
        self._mail_hint_vars: dict[str, tk.StringVar] = {}
        mail_row = tk.Frame(mail_card.inner, bg=SURFACE)
        mail_row.pack(fill=tk.X)

        for key, label in mail_btn_names:
            f = tk.Frame(mail_row, bg=SURFACE)
            f.pack(side=tk.LEFT, padx=(0, 6))
            var = tk.StringVar(value="✗")
            self._mail_hint_vars[key] = var
            btn = RoundedButton(
                f, label, lambda k=key: self._mark_mailbox_button(k),
                width=64, height=26, radius=8, style="secondary",
            )
            btn.pack()
            tk.Label(f, textvariable=var, font=FONT_UI, bg=SURFACE, fg=TEXT2).pack()

        mb_cfg = self.cfg.get("mailbox_check", {})
        self.var_mailbox_enabled = tk.BooleanVar(value=bool(mb_cfg.get("enabled", False)))

        mail_toggle_row = tk.Frame(mail_card.inner, bg=SURFACE)
        mail_toggle_row.pack(fill=tk.X, pady=(6, 0))
        tk.Label(
            mail_toggle_row, text="启用超时查邮箱", font=FONT_UI, bg=SURFACE, fg=TEXT2
        ).pack(side=tk.LEFT)
        tk.Checkbutton(
            mail_toggle_row, text="", variable=self.var_mailbox_enabled,
            command=self._save_mailbox_config,
            bg=SURFACE, fg=GOLD, selectcolor=SURFACE2, activebackground=SURFACE,
            activeforeground=GOLD_HOVER, font=FONT_UI,
        ).pack(side=tk.RIGHT)

        # ── 页面折叠 ──
        fold_card = Card(scroll_outer, padding=12)
        fold_card.pack(fill=tk.X, pady=(8, 0))

        tk.Label(fold_card.inner, text="页面折叠", font=FONT_SUB, bg=SURFACE, fg=TEXT).pack(
            anchor=tk.W, pady=(0, 8)
        )
        tk.Label(
            fold_card.inner,
            text="启用后，每次操作前自动展开/折叠主页面，适用于使用折叠界面的用户",
            font=FONT_UI, bg=SURFACE, fg=TEXT2, wraplength=380, anchor=tk.W, justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 6))

        # 模式选择
        fp_cfg = self.cfg.get("fold_page", {})
        self.var_fold_mode = tk.StringVar(value=str(fp_cfg.get("mode", "always_expand")))

        mode_row = tk.Frame(fold_card.inner, bg=SURFACE)
        mode_row.pack(fill=tk.X, pady=(0, 8))
        tk.Label(mode_row, text="模式", font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)

        def _on_fold_mode_change() -> None:
            self.cfg.setdefault("fold_page", {})["mode"] = self.var_fold_mode.get()
            from tbh_helper.config_loader import save_config
            save_config(CONFIG_PATH, self.cfg)

        for val, label in (("always_expand", "一直展开"), ("fold_before_use", "每次折叠")):
            rb = tk.Radiobutton(
                mode_row, text=label, variable=self.var_fold_mode, value=val,
                command=_on_fold_mode_change,
                bg=SURFACE, fg=TEXT, selectcolor=SURFACE2, activebackground=SURFACE,
                activeforeground=GOLD_HOVER, font=FONT_UI,
            )
            rb.pack(side=tk.LEFT, padx=(12, 0))

        # 四个坐标标记
        self._fold_hint_vars: dict[str, tk.StringVar] = {}
        fold_btn_configs = [
            ("fold_expand_btn", "展开按钮"),
            ("fold_portal_btn", "传送门按钮"),
            ("fold_warehouse_btn", "仓库按钮"),
            ("fold_confirm_btn", "服务器错误确认按钮"),
        ]
        for attr, label in fold_btn_configs:
            row = tk.Frame(fold_card.inner, bg=SURFACE)
            row.pack(fill=tk.X, pady=(2, 0))
            tk.Label(row, text=label, font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
            if attr == "fold_confirm_btn":
                tk.Label(
                    row, text="（不知道在哪就放背包和编队中间）", font=FONT_UI, bg=SURFACE, fg=TEXT2
                ).pack(side=tk.LEFT, padx=(4, 0))

            var = tk.StringVar(value="✗")
            self._fold_hint_vars[attr] = var
            tk.Label(
                row, textvariable=var, font=FONT_UI, bg=SURFACE, fg=TEXT2
            ).pack(side=tk.RIGHT, padx=(0, 4))

            RoundedButton(
                row, "标记位置",
                lambda a=attr, l=label: self._mark_fold_button(a, l),
                width=88, height=26, radius=8, style="secondary",
            ).pack(side=tk.RIGHT)

        self._refresh_fold_hints()

    def _mark_fold_button(self, attr: str, label: str) -> None:
        """标记折叠页面的一个按钮坐标（相对锚点）。"""
        if not self._require_idle() or not self._require_anchor():
            return

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor(warn_outside=False)
            if rel is None:
                return False
            profile = self._get_profile()
            setattr(profile, attr, [rel[0], rel[1]])
            self._save_profile(profile, capture_template=bool(self._anchor))
            self._append_log(f">>> {label} @ ({rel[0]}, {rel[1]})")
            self._refresh_fold_hints()
            return True

        self._run_countdown_capture(
            title=f"标记 · {label}",
            prompt=f"鼠标移到游戏内「{label}」位置",
            capture_fn=capture,
        )

    def _refresh_fold_hints(self) -> None:
        if not hasattr(self, "_fold_hint_vars"):
            return
        profile = self._get_profile()
        for attr, var in self._fold_hint_vars.items():
            pos = getattr(profile, attr, None)
            if pos and len(pos) >= 2:
                var.set(f"({pos[0]:.3f}, {pos[1]:.3f})")
            else:
                var.set("✗")

    def _save_fold_config(self) -> None:
        """保存折叠页面模式到 config.yaml。"""
        self.cfg.setdefault("fold_page", {})["mode"] = self.var_fold_mode.get()
        from tbh_helper.config_loader import save_config
        save_config(CONFIG_PATH, self.cfg)

    def _show_run(self) -> None:
        if hasattr(self, "_seg"):
            self._seg.select(0)
        self.page_setup.pack_forget()
        self.page_stats.pack_forget()
        self.page_misc.pack_forget()
        self._stats_visible = False
        self.page_run.pack(fill=tk.BOTH, expand=True)

    def _show_setup(self) -> None:
        if hasattr(self, "_seg"):
            self._seg.select(1)
        self.page_run.pack_forget()
        self.page_stats.pack_forget()
        self.page_misc.pack_forget()
        self._stats_visible = False
        self.page_setup.pack(fill=tk.BOTH, expand=True)
        self._load_stage_list()
        self._refresh_setup_steps()

    def _show_stats(self) -> None:
        if hasattr(self, "_seg"):
            self._seg.select(3)
        self.page_run.pack_forget()
        self.page_setup.pack_forget()
        self.page_misc.pack_forget()
        self._stats_visible = True
        self.page_stats.pack(fill=tk.BOTH, expand=True)
        self._stats_dirty = True
        self._refresh_stats()
        self._poll_stats()

    def _show_misc(self) -> None:
        if hasattr(self, "_seg"):
            self._seg.select(2)
        self.page_run.pack_forget()
        self.page_setup.pack_forget()
        self.page_stats.pack_forget()
        self._stats_visible = False
        self.page_misc.pack(fill=tk.BOTH, expand=True)
        self._refresh_warehouse_ui()
        self._refresh_fold_hints()

    # ── 统计页面（推送更新、无滚动条、自适应列宽）───────

    def _mark_stats_dirty(self) -> None:
        """引擎回调（任意线程），仅设置脏标记。"""
        self._stats_dirty = True

    def _reset_stats(self) -> None:
        """手动重置统计数据。"""
        self.engine.stats.reset()
        self._stats_dirty = True
        self._refresh_stats()
        self._append_log(">>> 统计已重置")

    def _poll_stats(self) -> None:
        if not self._stats_visible:
            return
        # 每秒至少刷新运行时长
        self._update_elapsed()
        if self._stats_dirty:
            self._refresh_stats()
        self._stats_poll_id = self.after(1000, self._poll_stats)

    def _update_elapsed(self) -> None:
        """只刷新运行时长（轻量，每秒调用）。"""
        stats = self.engine.stats
        summary = stats.snapshot_summary()
        total = summary.elapsed_seconds
        h, m = int(total // 3600), int((total % 3600) // 60)
        s = int(total % 60)
        if h:
            self._sv_elapsed.set(f"{h}h {m}m")
        elif m:
            self._sv_elapsed.set(f"{m}m {s}s")
        else:
            self._sv_elapsed.set(f"{s}s")

    def _build_stats_page(self, parent: tk.Frame) -> None:
        container = tk.Frame(parent, bg=BG)
        container.pack(fill=tk.BOTH, expand=True)

        # 无滚动条的画布
        self._stats_canvas = tk.Canvas(container, bg=BG, highlightthickness=0)
        self._stats_canvas.pack(fill=tk.BOTH, expand=True)

        self._stats_inner = tk.Frame(self._stats_canvas, bg=BG)
        self._stats_cw = self._stats_canvas.create_window(
            (0, 0), window=self._stats_inner, anchor=tk.NW
        )

        def _on_cfg(_event):
            self._stats_canvas.itemconfig(self._stats_cw, width=_event.width)
        self._stats_canvas.bind("<Configure>", _on_cfg)

        def _on_inner(_event):
            self._stats_canvas.configure(scrollregion=self._stats_canvas.bbox("all"))
        self._stats_inner.bind("<Configure>", _on_inner)

        self._stats_canvas.bind(
            "<MouseWheel>",
            lambda e: self._stats_canvas.yview_scroll(-1 * (e.delta // 120), "units"),
        )

        # ── 会话摘要（持久化 StringVar） ──
        sum_card = tk.Frame(self._stats_inner, bg=SURFACE, highlightbackground=BORDER_WINE, highlightthickness=1)
        sum_card.pack(fill=tk.X, pady=(0, 10))

        sum_title_row = tk.Frame(sum_card, bg=SURFACE)
        sum_title_row.pack(fill=tk.X, padx=14, pady=(12, 6))
        tk.Label(sum_title_row, text="会话摘要", font=FONT_SUB, bg=SURFACE, fg=GOLD).pack(side=tk.LEFT)
        RoundedButton(
            sum_title_row, "重置统计", self._reset_stats, width=80, height=26, radius=8, style="secondary"
        ).pack(side=tk.RIGHT)
        grid = tk.Frame(sum_card, bg=SURFACE)
        grid.pack(fill=tk.X, padx=14, pady=(0, 12))

        self._sv_elapsed = tk.StringVar(value="—")
        self._sv_drops = tk.StringVar(value="—")

        items = [
            ("运行时长", self._sv_elapsed),
            ("首领箱子", self._sv_drops),
        ]
        for i, (label, sv) in enumerate(items):
            f = tk.Frame(grid, bg=SURFACE)
            f.grid(row=0, column=i, sticky=tk.W, padx=(0, 24), pady=2)
            tk.Label(f, text=label, font=FONT_UI, bg=SURFACE, fg=TEXT2).pack(side=tk.LEFT)
            tk.Label(f, textvariable=sv, font=FONT_BOLD, bg=SURFACE, fg=TEXT).pack(side=tk.LEFT, padx=(6, 0))

        # ── 关卡明细（持久化表头 + 行池） ──
        self._stats_table_card = tk.Frame(
            self._stats_inner, bg=SURFACE, highlightbackground=BORDER_WINE, highlightthickness=1
        )
        self._stats_table_card.pack(fill=tk.X)

        tk.Label(self._stats_table_card, text="关卡明细", font=FONT_SUB, bg=SURFACE, fg=GOLD).pack(
            anchor=tk.W, padx=14, pady=(12, 4)
        )

        # 表头 — 四列等宽 grid
        head = tk.Frame(self._stats_table_card, bg=ACCENT)
        head.pack(fill=tk.X, padx=10, pady=(6, 0))
        head.grid_columnconfigure((0, 1, 2, 3), weight=1)

        hdrs = [("关卡", tk.W), ("首领箱子", tk.CENTER), ("平均用时", tk.CENTER), ("间隔周期", tk.CENTER)]
        for i, (text, anchor) in enumerate(hdrs):
            tk.Label(head, text=text, font=FONT_UI, bg=ACCENT, fg="#FFFFFF", anchor=anchor).grid(
                row=0, column=i, sticky=tk.EW, padx=2, pady=3
            )

        # 行容器
        self._stats_rows_frame = tk.Frame(self._stats_table_card, bg=SURFACE)
        self._stats_rows_frame.pack(fill=tk.X, padx=10, pady=(2, 10))
        self._stats_rows: list[tk.Frame] = []
        self._stats_empty = tk.Label(
            self._stats_rows_frame,
            text="暂无数据，开始挂机后自动统计",
            font=FONT_UI,
            bg=SURFACE,
            fg=TEXT2,
        )
        self._stats_empty.pack(pady=10)

        self._stats_dirty = False
        self._stats_visible = False

    def _refresh_stats(self) -> None:
        self._stats_dirty = False
        stats = self.engine.stats
        records = stats.snapshot()
        summary = stats.snapshot_summary()

        # 摘要
        self._update_elapsed()
        self._sv_drops.set(f"{summary.total_boss_drops} 次")
        # 表
        if not records:
            self._stats_empty.pack(pady=10)
            for row in self._stats_rows:
                row.pack_forget()
            return
        self._stats_empty.pack_forget()

        n = len(records)
        # 调整行数
        while len(self._stats_rows) < n:
            row = self._create_stats_row()
            row.pack(fill=tk.X, pady=1)
            self._stats_rows.append(row)
        while len(self._stats_rows) > n:
            self._stats_rows.pop().destroy()

        for i, r in enumerate(records):
            self._update_stats_row(self._stats_rows[i], r, i)

    def _create_stats_row(self) -> tk.Frame:
        row = tk.Frame(self._stats_rows_frame, bg=SURFACE)
        row.grid_columnconfigure((0, 1, 2, 3), weight=1)
        lbl_name = tk.Label(row, text="", font=FONT_UI, bg=SURFACE, fg=TEXT, anchor=tk.W)
        lbl_name.grid(row=0, column=0, sticky=tk.EW, padx=2, pady=2)
        cells: list[tk.Label] = []
        for i in range(1, 4):
            lbl = tk.Label(row, text="", font=FONT_UI, bg=SURFACE, fg=TEXT2, anchor=tk.CENTER)
            lbl.grid(row=0, column=i, sticky=tk.EW, padx=2, pady=2)
            cells.append(lbl)
        row._name = lbl_name
        row._cells = cells
        return row

    def _update_stats_row(self, row: tk.Frame, r, idx: int) -> None:
        bg = SURFACE2 if idx % 2 == 0 else SURFACE
        row.configure(bg=bg)
        row._name.configure(text=r.name, bg=bg)

        # 平均出箱用时
        bt = int(r.avg_boss_time)
        boss_str = f"{bt // 60}m{bt % 60}s" if bt >= 60 else f"{bt}s" if bt > 0 else "—"

        # 轮换间隔
        ct = int(r.avg_cycle_interval)
        cm, cs = ct // 60, ct % 60
        cycle_str = f"{cm}m{cs}s" if cm else f"{cs}s" if ct > 0 else "—"

        texts = [
            (str(r.boss_drops), GOLD),
            (boss_str, TEXT2),
            (cycle_str, TEXT2),
        ]
        for lbl, (text, fg) in zip(row._cells, texts):
            lbl.configure(text=text, fg=fg, bg=bg)

    def _chest_hint_text(self) -> str:
        c = ChestOpenConfig.from_dict(self.cfg.get("chest_open"))
        if c.enabled:
            return f"已标记 ({c.rel_x:.2f}, {c.rel_y:.2f})"
        return "换图前自动开宝箱"

    # ── 配置 / 状态 ───────────────────────────────────────

    def _profile_path(self) -> Path:
        return profile_path_from_cfg(self.cfg, BASE_DIR)

    def _get_profile(self) -> PortalProfile:
        return PortalProfile.load_or_create(self._profile_path())

    def _save_profile(self, profile: PortalProfile, *, capture_template: bool = False) -> None:
        path = self._profile_path()
        if capture_template and self._anchor:
            profile.capture_template(self._anchor, path.parent / "portal_anchor.png")
        profile.save(path)
        self.cfg.setdefault("portal", {})
        self.cfg["portal"]["profile"] = str(path.relative_to(BASE_DIR)).replace("\\", "/")
        save_config(CONFIG_PATH, self.cfg)
        self.engine.cfg = self.cfg
        self._load_stage_list()
        self._refresh_warehouse_ui()
        self._refresh_status()
        self._refresh_setup_steps()

    def _refresh_setup_steps(self) -> None:
        profile = self._get_profile()
        ui_ok = bool(profile.chapter_tabs and profile.difficulty_options)
        self.step_anchor.set_status("done" if self._anchor else "active")
        self.step_ui.set_status("done" if ui_ok else ("active" if self._anchor else "pending"))
        chest = ChestOpenConfig.from_dict(self.cfg.get("chest_open"))

    def _refresh_status(self) -> None:
        hwnd = find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        )

        if hasattr(self, "var_chest_hint"):
            self.var_chest_hint.set(self._chest_hint_text())
        if hasattr(self, "var_norm_hint"):
            self.var_norm_hint.set(self._normal_chest_hint_text())

        # 权限提示
        if hwnd and is_process_elevated(hwnd) and not is_self_elevated():
            self.game_pill.set_ok(True, "游戏以管理员运行 — 助手也需『以管理员身份运行』")
        elif hwnd:
            self.game_pill.set_ok(True, "游戏在线")
        else:
            self.game_pill.set_ok(False, "未检测到游戏")

    def _open_config_dir(self) -> None:
        """在文件管理器中打开配置文件夹。"""
        try:
            import os
            os.startfile(str(BASE_DIR))
        except Exception as exc:
            messagebox.showerror("错误", f"无法打开配置文件夹\n{exc}", parent=self)

    def _check_elevation(self) -> None:
        """启动时检测权限不匹配并提示。"""
        hwnd = find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        )
        if not hwnd:
            return
        if is_process_elevated(hwnd) and not is_self_elevated():
            self._append_log(
                "⚠ 检测到游戏以管理员权限运行，但助手不是。"
                "已自动切换为 postmessage 模式。"
                "也可关闭助手后右键 bat → 以管理员身份运行以提升稳定性。"
            )

    def _restore_anchor(self) -> None:
        """从配置恢复之前捕获的窗口锚点。"""
        r = self.cfg.get("portal", {}).get("window_rect")
        if r and len(r) == 4:
            from tbh_helper.anchor import AnchorRect
            self._anchor = AnchorRect(left=r[0], top=r[1], width=r[2], height=r[3])
            self.engine.set_anchor(self._anchor)
            self._append_log(
                f">>> 已恢复窗口锚点: {r[2]}×{r[3]} @ ({r[0]},{r[1]})"
            )

    def _require_idle(self) -> bool:
        if self.engine.is_running:
            messagebox.showwarning("提示", "请先停止挂机", parent=self)
            return False
        return True

    def _require_anchor(self) -> bool:
        if self._anchor is None:
            messagebox.showinfo("提示", "请先在设置中捕获窗口", parent=self)
            return False
        return True

    def _capture_cursor_in_anchor(self, *, warn_outside: bool = True) -> tuple[float, float] | None:
        if not self._anchor:
            return None
        mx, my = get_cursor_pos()
        if warn_outside and not self._anchor.contains_screen(mx, my):
            # 诊断：检查游戏窗口实际位置
            diag = ""
            hwnd = find_game_window(
                process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
                pid=self.cfg.get("game", {}).get("pid"),
            )
            if hwnd:
                try:
                    from tbh_helper.window import get_window_rect, get_client_rect_screen
                    wr = get_window_rect(hwnd)
                    cr = get_client_rect_screen(hwnd)
                    diag = (
                        f"\n\n诊断信息："
                        f"\n鼠标位置: ({mx}, {my})"
                        f"\n窗口区域: ({wr.left},{wr.top}) {wr.width}×{wr.height}"
                        f"\n客户区  : ({cr.left},{cr.top}) {cr.width}×{cr.height}"
                        f"\n已捕获  : ({self._anchor.left},{self._anchor.top}) "
                        f"{self._anchor.width}×{self._anchor.height}"
                    )
                    if (cr.left, cr.top, cr.width, cr.height) != (
                        self._anchor.left, self._anchor.top,
                        self._anchor.width, self._anchor.height
                    ):
                        diag += "\n→ 窗口位置已变动，请重新「捕获窗口」"
                except Exception:
                    pass
            messagebox.showwarning("位置警告",
                f"鼠标不在窗口客户区内，请移入游戏窗口内再试。{diag}",
                parent=self)
            return None
        return self._anchor.screen_to_rel(mx, my)

    def _run_countdown_capture(self, *, title: str, prompt: str, capture_fn, seconds: int = 5, on_skip=None) -> None:
        open_countdown_capture_dialog(self, title=title, prompt=prompt, seconds=seconds, capture_fn=capture_fn, on_skip=on_skip)

    # ── 传送门 UI 向导 ─────────────────────────────────────

    def _apply_portal_ui_mark(self, kind: str, rel: tuple[float, float]) -> None:
        profile = self._get_profile()
        mapping = {
            "chapter_1": lambda: profile.chapter_tabs.__setitem__(1, rel),
            "chapter_2": lambda: profile.chapter_tabs.__setitem__(2, rel),
            "chapter_3": lambda: profile.chapter_tabs.__setitem__(3, rel),
            "diff_dropdown": lambda: setattr(profile, "difficulty_dropdown", rel),
            "diff_normal": lambda: profile.difficulty_options.__setitem__("normal", rel),
            "diff_nightmare": lambda: profile.difficulty_options.__setitem__("nightmare", rel),
            "diff_hell": lambda: profile.difficulty_options.__setitem__("hell", rel),
            "diff_torment": lambda: profile.difficulty_options.__setitem__("torment", rel),
            "scroll_area": lambda: setattr(profile, "map_scroll_area", rel),
        }
        mapping[kind]()
        self._save_profile(profile, capture_template=True)

    def _run_portal_ui_wizard(self) -> None:
        if not self._require_idle() or not self._require_anchor():
            return
        self._wizard_idx = 0
        self._append_log(">>> 开始传送门 UI 标定向导")
        self._wizard_next_step()

    def _wizard_next_step(self) -> None:
        if self._wizard_idx >= len(PORTAL_UI_WIZARD):
            self._append_log(">>> 传送门 UI 标定完成")
            self._refresh_setup_steps()
            messagebox.showinfo("完成", "传送门 UI 已全部标定", parent=self)
            return

        kind, title, prompt = PORTAL_UI_WIZARD[self._wizard_idx]

        if kind.startswith("diff_") and kind != "diff_dropdown":
            self._append_log(f">>> 标定 {title}（可跳过）")

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor()
            if rel is None:
                return False
            self._apply_portal_ui_mark(kind, rel)
            self._append_log(f">>> {title}: ({rel[0]}, {rel[1]})")
            self._wizard_idx += 1
            self.after(400, self._wizard_next_step)
            return True

        def skip_diff() -> None:
            self._append_log(f">>> 跳过 {title}")
            self._wizard_idx += 1
            self.after(200, self._wizard_next_step)

        is_difficulty_option = kind.startswith("diff_") and kind != "diff_dropdown"
        self._run_countdown_capture(
            title=f"标定 · {title}", prompt=prompt, capture_fn=capture,
            on_skip=skip_diff if is_difficulty_option else None,
        )

    def _mark_portal_ui(self, kind: str) -> None:
        if not self._require_idle() or not self._require_anchor():
            return
        labels = {k: (t, p) for k, t, p in PORTAL_UI_WIZARD}
        title, prompt = labels.get(kind, ("标记", "移动鼠标到目标位置"))

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor()
            if rel is None:
                return False
            self._apply_portal_ui_mark(kind, rel)
            self._append_log(f">>> {title}: ({rel[0]}, {rel[1]})")
            return True

        self._run_countdown_capture(title=title, prompt=prompt, capture_fn=capture)

    # ── 轮换节点 ───────────────────────────────────────────

    def _load_stage_list(self) -> None:
        if not hasattr(self, "stage_list"):
            return
        self.stage_list.delete(0, tk.END)
        profile = self._get_profile()
        if not profile.stages:
            self.stage_list.insert(tk.END, "  暂无节点，点击「＋ 添加」")
            self._adjust_stage_list_height(0)
            return
        for i, s in enumerate(profile.stages, 1):
            self.stage_list.insert(tk.END, f"  {i}.  {s['name']}")
        self._adjust_stage_list_height(len(profile.stages))

    def _adjust_stage_list_height(self, n: int) -> None:
        """动态调整 Listbox 行数：空=4行，1-6行匹配，超过6行固定6行+滑条。"""
        if n <= 0:
            rows = 4
        elif n <= 6:
            rows = n
        else:
            rows = 6
        self.stage_list.configure(height=rows)

    def _adjust_warehouse_list_height(self, n: int) -> None:
        """动态调整仓库列表 Listbox 行数：空=4行，1-6行匹配，超过6行固定6行。"""
        if n <= 0:
            rows = 4
        elif n <= 6:
            rows = n
        else:
            rows = 6
        self.warehouse_list.configure(height=rows)

    def _selected_stage_index(self) -> int | None:
        sel = self.stage_list.curselection()
        profile = self._get_profile()
        if not sel or not profile.stages:
            return None
        idx = int(sel[0])
        return idx if idx < len(profile.stages) else None

    def _open_stage_meta_dialog(self, *, title: str, initial: dict | None = None, on_submit, auto_name: bool = True) -> None:
        initial = initial or {}
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.configure(bg=BG)
        dlg.transient(self)
        dlg.resizable(False, False)

        shell = tk.Frame(dlg, bg=SURFACE, highlightbackground=BORDER_WINE, highlightthickness=1)
        shell.pack(padx=16, pady=16)
        form = tk.Frame(shell, bg=SURFACE, padx=20, pady=16)
        form.pack()

        var_name = tk.StringVar(value=str(initial.get("name", "")))
        var_chapter = tk.StringVar(value=str(initial.get("chapter", 1)))
        var_diff = tk.StringVar(value=str(initial.get("difficulty", "normal")))
        var_num = tk.StringVar(value=str(initial.get("stage_num", 1)))

        fields = [
            ("名称", var_name, None),
            ("章节", var_chapter, ("1", "2", "3")),
            ("难度", var_diff, ("normal", "nightmare", "hell", "torment")),
            ("关卡", var_num, tuple(str(i) for i in range(1, 11))),
        ]

        for row_i, (label, var, values) in enumerate(fields):
            tk.Label(form, text=label, bg=SURFACE, fg=TEXT2, font=FONT_UI).grid(
                row=row_i, column=0, sticky=tk.W, pady=6, padx=(0, 12)
            )
            if values:
                om = tk.OptionMenu(form, var, *values)
                style_option_menu(om)
                om.grid(row=row_i, column=1, sticky=tk.W, pady=6)
            else:
                ent = tk.Entry(form, textvariable=var, width=20)
                style_entry(ent)
                ent.grid(row=row_i, column=1, sticky=tk.W, pady=6)

        if auto_name:
            def sync_name(*_) -> None:
                try:
                    var_name.set(PortalProfile.default_name(int(var_chapter.get()), var_diff.get(), int(var_num.get())))
                except (ValueError, tk.TclError):
                    pass
            for v in (var_chapter, var_diff, var_num):
                v.trace_add("write", sync_name)
            sync_name()

        def close_dialog() -> None:
            if dlg.winfo_exists():
                dlg.destroy()

        def submit() -> None:
            try:
                meta = {
                    "name": var_name.get().strip()
                    or PortalProfile.default_name(int(var_chapter.get()), var_diff.get(), int(var_num.get())),
                    "chapter": int(var_chapter.get()),
                    "difficulty": var_diff.get(),
                    "stage_num": int(var_num.get()),
                }
            except (ValueError, tk.TclError):
                messagebox.showerror("错误", "请填写有效参数", parent=dlg)
                return
            close_dialog()
            self.after(10, lambda m=meta: on_submit(m))

        btn_row = tk.Frame(form, bg=SURFACE)
        btn_row.grid(row=len(fields), column=0, columnspan=2, pady=(12, 0))
        RoundedButton(btn_row, "标记位置", submit, width=100, height=34, radius=10).pack(side=tk.LEFT, padx=4)
        RoundedButton(btn_row, "取消", close_dialog, width=72, height=34, radius=10, style="secondary").pack(
            side=tk.LEFT, padx=4
        )
        dlg.protocol("WM_DELETE_WINDOW", close_dialog)
        dlg.update_idletasks()
        dlg.geometry(f"+{self.winfo_x() + 40}+{self.winfo_y() + 60}")
        dlg.lift()

    def _begin_stage_position_capture(self, meta: dict, *, edit_index: int | None = None) -> None:
        num = int(meta["stage_num"])
        view = "8-10" if num >= 8 else "1-7"
        prompt = f"切到 {meta['name']}（{view} 视图），鼠标移到关卡节点上"

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor()
            if rel is None:
                return False
            profile = self._get_profile()
            stage = {**meta, "rel_x": rel[0], "rel_y": rel[1]}
            if edit_index is not None:
                profile.stages[edit_index] = stage
            else:
                profile.stages.append(stage)
            self._save_profile(profile, capture_template=bool(self._anchor))
            self._append_log(f">>> 节点 {stage['name']}")
            return True

        self._run_countdown_capture(title=meta["name"], prompt=prompt, capture_fn=capture)

    def _add_stage(self) -> None:
        if not self._require_idle():
            return

        def on_meta(meta: dict) -> None:
            if not self._require_anchor():
                return
            self._begin_stage_position_capture(meta)

        self._open_stage_meta_dialog(title="添加节点", on_submit=on_meta)

    def _edit_stage(self) -> None:
        if not self._require_idle():
            return
        idx = self._selected_stage_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选中一个节点", parent=self)
            return
        stage = self._get_profile().stages[idx]

        def on_meta(meta: dict) -> None:
            profile = self._get_profile()
            meta["rel_x"] = stage["rel_x"]
            meta["rel_y"] = stage["rel_y"]
            profile.stages[idx] = meta
            self._save_profile(profile)
            self._append_log(f">>> 已更新 {meta['name']}")

        self._open_stage_meta_dialog(title="编辑节点", initial=stage, on_submit=on_meta, auto_name=False)

    def _mark_stage_pos(self) -> None:
        if not self._require_idle() or not self._require_anchor():
            return
        idx = self._selected_stage_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选中一个节点", parent=self)
            return
        s = self._get_profile().stages[idx]
        meta = {"name": s["name"], "chapter": int(s["chapter"]), "difficulty": s["difficulty"], "stage_num": int(s["stage_num"])}
        self._begin_stage_position_capture(meta, edit_index=idx)

    def _test_stage_click(self) -> None:
        """模拟完整换关流程：选难度 → 选章节 → 滚轮 → 点击节点。"""
        if not self._require_idle() or not self._require_anchor():
            return
        idx = self._selected_stage_index()
        if idx is None:
            messagebox.showinfo("提示", "请先选中一个节点", parent=self)
            return
        s = self._get_profile().stages[idx]
        anchor = self._anchor
        if not anchor:
            return
        hwnd = find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        )
        if not hwnd:
            messagebox.showerror("错误", "找不到游戏窗口", parent=self)
            return

        profile = self._get_profile()
        target = StageTarget(
            name=str(s["name"]),
            chapter=int(s["chapter"]),
            difficulty=str(s["difficulty"]),
            stage_num=int(s["stage_num"]),
            rel_x=float(s["rel_x"]),
            rel_y=float(s["rel_y"]),
        )
        navigator = PortalNavigator(
            profile.to_portal_ui(),
            anchor,
            hwnd=hwnd,
            helper_hwnd=self.winfo_id(),
        )
        try:
            self._append_log(f">>> 测试 {target.name}：开始模拟…")
            navigator.reset_state()
            navigator.navigate_to_stage(target)
            self._append_log(f">>> 难度/章节/滚轮 已完成")
            navigator.click_stage_node(target)
            self._append_log(f">>> 节点点击完成")
        except Exception as exc:
            self._append_log(f">>> 测试失败: {exc}")

    def _delete_stage(self) -> None:
        if not self._require_idle():
            return
        idx = self._selected_stage_index()
        if idx is None:
            self.after(1, lambda: messagebox.showinfo("提示", "请先选中要删除的节点", parent=self))
            return
        profile = self._get_profile()
        if idx >= len(profile.stages):
            return
        name = profile.stages[idx]["name"]

        def confirm() -> None:
            if not messagebox.askyesno("删除", f"删除「{name}」？", parent=self):
                return
            p = self._get_profile()
            if idx >= len(p.stages):
                return
            p.stages.pop(idx)
            self._save_profile(p)
            self._append_log(f">>> 已删除 {name}")

        self.after(1, confirm)

    def _move_stage(self, delta: int) -> None:
        if not self._require_idle():
            return
        idx = self._selected_stage_index()
        if idx is None:
            return
        new_idx = idx + delta
        profile = self._get_profile()
        if new_idx < 0 or new_idx >= len(profile.stages):
            return
        profile.stages[idx], profile.stages[new_idx] = profile.stages[new_idx], profile.stages[idx]
        self._save_profile(profile)
        self.stage_list.selection_clear(0, tk.END)
        self.stage_list.selection_set(new_idx)

    # ── 开宝箱 ─────────────────────────────────────────────

    def _update_chest_config(self, chest: ChestOpenConfig) -> None:
        self.cfg.setdefault("chest_open", {})
        self.cfg["chest_open"] = chest.to_dict()
        save_config(CONFIG_PATH, self.cfg)
        self.engine.cfg = self.cfg
        self.engine.chest = chest
        # 同步写入 profile（引擎启动时优先读取 profile）
        try:
            profile = self._get_profile()
            profile.chest_open = chest.to_dict()
            self._save_profile(profile)
        except Exception:
            pass
        self.var_chest_enabled.set(chest.enabled)
        if hasattr(self, "var_chest_hint"):
            self.var_chest_hint.set(self._chest_hint_text())

    def _save_chest_enabled(self) -> None:
        chest = ChestOpenConfig.from_dict(self.cfg.get("chest_open"))
        chest.enabled = bool(self.var_chest_enabled.get())
        self._update_chest_config(chest)

    # ── 普通宝箱 ──────────────────────────────────────────

    def _normal_chest_hint_text(self) -> str:
        nc = ChestOpenConfig.from_dict(self.cfg.get("normal_chest"))
        if nc.enabled:
            return f"已标记 ({nc.rel_x:.2f}, {nc.rel_y:.2f})"
        return "每15分钟自动开宝箱"

    def _update_normal_chest_config(self, nc: ChestOpenConfig) -> None:
        self.cfg.setdefault("normal_chest", {})
        self.cfg["normal_chest"] = nc.to_dict()
        save_config(CONFIG_PATH, self.cfg)
        self.engine.cfg = self.cfg
        self.engine.normal_chest = nc
        # 同步写入 profile
        try:
            profile = self._get_profile()
            profile.normal_chest = nc.to_dict()
            self._save_profile(profile)
        except Exception:
            pass
        self.var_norm_chest_enabled.set(nc.enabled)
        if hasattr(self, "var_norm_hint"):
            self.var_norm_hint.set(self._normal_chest_hint_text())

    def _save_norm_chest_enabled(self) -> None:
        nc = ChestOpenConfig.from_dict(self.cfg.get("normal_chest"))
        nc.enabled = bool(self.var_norm_chest_enabled.get())
        self._update_normal_chest_config(nc)

    def _mark_normal_chest(self) -> None:
        if not self._require_idle():
            return
        if not find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        ):
            messagebox.showerror("错误", "找不到游戏窗口", parent=self)
            return
        self._run_countdown_capture(
            title="普通宝箱位置",
            prompt="鼠标移到普通宝箱按钮或箱子上",
            capture_fn=self._capture_normal_chest_pos,
        )

    def _capture_normal_chest_pos(self) -> bool:
        if not self._anchor:
            messagebox.showerror("错误", "请先在设置中捕获窗口", parent=self)
            return False
        mx, my = get_cursor_pos()
        rel_x, rel_y = self._anchor.screen_to_rel(mx, my)
        nc = ChestOpenConfig.from_dict(self.cfg.get("normal_chest"))
        nc.rel_x = round(rel_x, 4)
        nc.rel_y = round(rel_y, 4)
        nc.enabled = True
        nc.interval_seconds = 900
        self._update_normal_chest_config(nc)
        self._append_log(f">>> 普通宝箱 ({nc.rel_x}, {nc.rel_y})")
        return True

    def _save_click_method(self, _=None) -> None:
        method = self.var_click_method.get()
        # 写入 chest_open
        self.cfg.setdefault("chest_open", {})
        self.cfg["chest_open"]["click_method"] = method
        # 写入 portal.ui
        self.cfg.setdefault("portal", {}).setdefault("ui", {})
        self.cfg["portal"]["ui"]["click_method"] = method
        save_config(CONFIG_PATH, self.cfg)
        self.engine.cfg = self.cfg
        self._append_log(f">>> 点击方式已切换为: {method}")

    def _mark_chest(self) -> None:
        if not self._require_idle():
            return
        if not find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        ):
            messagebox.showerror("错误", "找不到游戏窗口", parent=self)
            return
        self._run_countdown_capture(
            title="开宝箱位置",
            prompt="鼠标移到开宝箱按钮或箱子上",
            capture_fn=self._capture_chest_pos,
        )

    def _capture_chest_pos(self) -> bool:
        if not self._anchor:
            messagebox.showerror("错误", "请先在设置中捕获窗口", parent=self)
            return False
        mx, my = get_cursor_pos()
        rel_x, rel_y = self._anchor.screen_to_rel(mx, my)
        chest = ChestOpenConfig.from_dict(self.cfg.get("chest_open"))
        chest.rel_x = round(rel_x, 4)
        chest.rel_y = round(rel_y, 4)
        chest.enabled = True
        self._update_chest_config(chest)
        self._append_log(f">>> 开宝箱 ({chest.rel_x}, {chest.rel_y})")
        return True

    def _test_chest_click(self) -> None:
        """测试 Boss 箱位置点击。"""
        self._test_click("chest_open", "蓝箱")

    def _test_normal_chest_click(self) -> None:
        """测试普通怪物宝箱（白箱）位置点击。"""
        self._test_click("normal_chest", "白箱")

    def _test_click(self, cfg_key: str, label: str) -> None:
        """读取配置中的坐标，对游戏窗口执行一次点击。"""
        chest = ChestOpenConfig.from_dict(self.cfg.get(cfg_key))
        if not chest.enabled:
            messagebox.showinfo("提示", f"{label}未启用，请先标记位置", parent=self)
            return
        hwnd = find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        )
        if not hwnd:
            messagebox.showerror("错误", "找不到游戏窗口", parent=self)
            return
        if not self._anchor:
            messagebox.showerror("错误", "请先捕获窗口位置", parent=self)
            return
        try:
            used = open_chest(
                hwnd, chest, helper_hwnd=self.winfo_id(), anchor=self._anchor,
            )
            if used:
                self._append_log(
                    f">>> [{label} 测试] 点击 @ ({used[0]},{used[1]}) 成功"
                )
            else:
                self._append_log(f">>> [{label} 测试] 位置无效，跳过")
        except Exception as exc:
            self._append_log(f">>> [{label} 测试] 失败: {exc}")
            messagebox.showerror("点击失败", str(exc), parent=self)

    # ── 运行控制 ───────────────────────────────────────────

    def _enqueue_log(self, msg: str) -> None:
        self._log_queue.put(msg)

    def _append_log(self, msg: str) -> None:
        txt = self.log_text.text
        txt.configure(state=tk.NORMAL)
        txt.insert(tk.END, msg + "\n")
        txt.see(tk.END)
        txt.configure(state=tk.DISABLED)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                self._append_log(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._drain_log_queue)

    def _on_switch(self, stage_name: str, count: int) -> None:
        self.after(0, lambda: self.var_next.set(f"下次 → {stage_name} 之后"))
        self.after(0, lambda: self.var_stats.set(f"Boss 箱 {self._drop_count}  ·  换图 {count}"))

    def _on_drop(self, tag: str, item_key: str, triggered: bool) -> None:
        if triggered or tag == "Boss箱":
            self._drop_count += 1
        self.after(
            0,
            lambda: self.var_stats.set(f"Boss 箱 {self._drop_count}  ·  换图 {self.engine.switch_count}"),
        )

    def _set_running(self, running: bool) -> None:
        self.btn_capture_win.configure_state(tk.NORMAL if not running else tk.DISABLED)
        self.btn_next.configure_state(tk.NORMAL if running else tk.DISABLED)
        text = "停止挂机" if running else "开始挂机"
        self.btn_start.configure(text=text)
        self.btn_start.configure_state(tk.NORMAL)
        self.var_mode.set("挂机中" if running else "待机")
        if hasattr(self, "lbl_mode"):
            self.lbl_mode.configure(fg=GOLD if running else TEXT)

    def _capture_window_anchor(self) -> None:
        """捕获游戏窗口客户区作为锚点。"""
        if self.engine.is_running:
            messagebox.showwarning("提示", "请先停止挂机", parent=self)
            return
        hwnd = find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        )
        if not hwnd:
            messagebox.showerror("未找到窗口", "请先启动 TaskBarHero", parent=self)
            return
        rect = get_client_rect_screen(hwnd)
        # 诊断：对比窗口完整矩形和客户区，检查偏移量
        try:
            from tbh_helper.window import get_window_rect
            wr = get_window_rect(hwnd)
            self._append_log(
                f"  [诊断] 窗口: ({wr.left},{wr.top}) {wr.width}×{wr.height}  "
                f"| 客户区: ({rect.left},{rect.top}) {rect.width}×{rect.height}  "
                f"| 偏移: ({rect.left - wr.left},{rect.top - wr.top})"
            )
        except Exception:
            pass
        # 保存到 config
        self.cfg.setdefault("portal", {})
        self.cfg["portal"]["window_rect"] = [rect.left, rect.top, rect.width, rect.height]
        save_config(CONFIG_PATH, self.cfg)
        # 立即创建锚点
        from tbh_helper.anchor import AnchorRect
        self._anchor = AnchorRect(left=rect.left, top=rect.top, width=rect.width, height=rect.height)
        self.engine.set_anchor(self._anchor)
        self._append_log(
            f">>> 窗口锚点已捕获: {rect.width}×{rect.height} @ ({rect.left},{rect.top})"
        )
        self._refresh_status()
        self._refresh_setup_steps()

    def _toggle_overlay(self) -> None:
        """开关：在游戏窗口上方显示/隐藏半透明绿色蒙层，直观确认捕获范围。"""
        # 如果已有蒙层，销毁它
        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:
                pass
            self._overlay = None
            self.btn_show_overlay.configure(text="显示范围")
            self._append_log(">>> 范围显示已关闭")
            return

        # 没有蒙层，创建
        if not self._anchor:
            if not self.cfg.get("portal", {}).get("window_rect"):
                messagebox.showinfo("提示", "请先点击「捕获窗口」", parent=self)
                return
            r = self.cfg["portal"]["window_rect"]
            from tbh_helper.anchor import AnchorRect
            self._anchor = AnchorRect(left=r[0], top=r[1], width=r[2], height=r[3])
            self.engine.set_anchor(self._anchor)

        # 检查当前游戏窗口位置是否与锚点一致
        hwnd = find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        )
        if hwnd:
            try:
                from tbh_helper.window import get_window_rect
                wr = get_window_rect(hwnd)
                self._append_log(
                    f"  [对比] 当前窗口: ({wr.left},{wr.top}) {wr.width}×{wr.height}  "
                    f"| 已捕获: ({self._anchor.left},{self._anchor.top}) {self._anchor.width}×{self._anchor.height}"
                )
            except Exception:
                pass

        a = self._anchor
        self._append_log(
            f">>> 窗口范围: ({a.left},{a.top}) ~ ({a.right},{a.bottom}) "
            f"→ {a.width}×{a.height}  （绿色蒙层覆盖区域）"
        )

        overlay = tk.Toplevel(self)
        overlay.overrideredirect(True)
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.35)
        overlay.configure(bg="#00FF00")
        overlay.geometry(f"{a.width}x{a.height}+{a.left}+{a.top}")

        # 绿色边框
        tk.Frame(overlay, bg="#00FF00", highlightthickness=0).place(
            x=0, y=0, width=a.width, height=2)
        tk.Frame(overlay, bg="#00FF00", highlightthickness=0).place(
            x=0, y=a.height - 2, width=a.width, height=2)
        tk.Frame(overlay, bg="#00FF00", highlightthickness=0).place(
            x=0, y=0, width=2, height=a.height)
        tk.Frame(overlay, bg="#00FF00", highlightthickness=0).place(
            x=a.width - 2, y=0, width=2, height=a.height)

        # 点蒙层也关闭
        def _close(evt=None) -> None:
            self._toggle_overlay()

        overlay.bind("<Escape>", _close)
        overlay.bind("<Button-1>", _close)

        self._overlay = overlay
        self.btn_show_overlay.configure(text="关闭显示")
        self._append_log(">>> 范围显示已打开（Esc 或点击蒙层也可以关闭）")

    def _start(self) -> None:
        self._start_engine(dry_run=False)

    def _start_watch(self) -> None:
        self._start_engine(dry_run=True)

    def _pick_start_stage(self, stages: list[dict]) -> int | None:
        """弹窗让用户选择从哪个关卡开始刷，返回索引（0-based）。"""
        if len(stages) <= 1:
            return 0

        names = [s.get("name", f"关卡 {i + 1}") for i, s in enumerate(stages)]
        dialog = tk.Toplevel(self)
        dialog.title("选择起始关卡")
        dialog.configure(bg=BG)
        dialog.resizable(False, False)

        dialog.transient(self)
        dialog.grab_set()

        result: list[int | None] = [None]

        tk.Label(dialog, text="选择挂机开始的关卡：", font=FONT_UI,
                 bg=BG, fg=TEXT, anchor=tk.W).pack(fill=tk.X, padx=16, pady=(14, 6))

        # 动态高度：最少 4 行，最多 6 行，超出滚动
        n = len(names)
        visible_rows = max(4, min(n, 6))
        row_h = 22  # 近似行高
        list_h = visible_rows * row_h

        frame = tk.Frame(dialog, bg=BG)
        frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        lb = tk.Listbox(frame, bg=SURFACE, fg=TEXT, selectbackground=ACCENT,
                        selectforeground="#FFFFFF", font=FONT_UI,
                        relief=tk.FLAT, borderwidth=0, highlightthickness=0,
                        height=visible_rows)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        style_listbox(lb)

        scroll = StyledScrollbar(frame, command=lb.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        lb.configure(yscrollcommand=scroll.set)

        for name in names:
            lb.insert(tk.END, name)
        lb.selection_set(0)  # 默认选中第一个

        def _confirm() -> None:
            sel = lb.curselection()
            if sel:
                result[0] = sel[0]
            dialog.destroy()

        def _cancel() -> None:
            dialog.destroy()

        # 双击直接选择
        lb.bind("<Double-Button-1>", lambda _: _confirm())

        btn_frame = tk.Frame(dialog, bg=BG)
        btn_frame.pack(fill=tk.X, padx=16, pady=(0, 14))

        btn_cancel = RoundedButton(btn_frame, "取消", _cancel, width=90, height=34, radius=10)
        btn_cancel.pack(side=tk.LEFT)

        btn_ok = RoundedButton(btn_frame, "确认", _confirm, width=90, height=34, radius=10)
        btn_ok.pack(side=tk.RIGHT)

        dialog.protocol("WM_DELETE_WINDOW", _cancel)

        # 计算窗口尺寸：标题 + 列表 + 按钮 + padding
        title_h = 32  # 近似
        btn_h = 34
        pad_v = 14 + 6 + 8 + 14  # pady 总和
        win_h = title_h + list_h + btn_h + pad_v
        win_w = 360
        px = self.winfo_x() + (self.winfo_width() - win_w) // 2
        py = self.winfo_y() + (self.winfo_height() - win_h) // 2
        dialog.geometry(f"{win_w}x{win_h}+{px}+{py}")

        dialog.wait_window()
        return result[0]

    def _start_engine(self, *, dry_run: bool) -> None:
        if self.engine.is_running:
            self._stop()
            return

        # ── 锚点准备：使用窗口客户区作为锚点 ──
        portal_cfg = self.cfg.get("portal", {})
        saved_rect = portal_cfg.get("window_rect")
        if not saved_rect or len(saved_rect) != 4:
            messagebox.showinfo("提示", "请先在「设置」中点击「捕获窗口」", parent=self)
            return

        hwnd = find_game_window(
            process_name=self.cfg.get("game", {}).get("process_name", "TaskBarHero"),
            pid=self.cfg.get("game", {}).get("pid"),
        )
        if not hwnd:
            messagebox.showerror("未找到窗口", "请先启动 TaskBarHero", parent=self)
            return

        cur_rect = get_client_rect_screen(hwnd)
        if [cur_rect.left, cur_rect.top, cur_rect.width, cur_rect.height] != saved_rect:
            msg = (
                f"游戏窗口位置已变动！\n\n"
                f"之前记录: @ ({saved_rect[0]},{saved_rect[1]}) {saved_rect[2]}×{saved_rect[3]}\n"
                f"当前窗口: @ ({cur_rect.left},{cur_rect.top}) {cur_rect.width}×{cur_rect.height}\n\n"
                f"是否重新捕获窗口位置？"
            )
            if not messagebox.askyesno("窗口位置变动", msg, parent=self):
                return
            self.cfg["portal"]["window_rect"] = [
                cur_rect.left, cur_rect.top, cur_rect.width, cur_rect.height
            ]
            save_config(CONFIG_PATH, self.cfg)
            self._append_log(f">>> 窗口位置已更新: {cur_rect.width}×{cur_rect.height}")

        from tbh_helper.anchor import AnchorRect
        self._anchor = AnchorRect(
            left=cur_rect.left, top=cur_rect.top,
            width=cur_rect.width, height=cur_rect.height,
        )
        self.engine.set_anchor(self._anchor)
        profile = self._get_profile()
        if not profile.stages:
            messagebox.showerror("缺少节点", "请先在设置中添加轮换节点", parent=self)
            return
        if not profile.chapter_tabs or not profile.difficulty_options:
            if not messagebox.askyesno("未完成标定", "传送门 UI 尚未标定，换图可能失败。继续？", parent=self):
                return

        # 选择起始关卡
        start_idx = self._pick_start_stage(profile.stages)
        if start_idx is None:
            return  # 用户取消

        # 验证并保存超时配置
        raw = self.var_timeout_minutes.get().strip()
        if not self._validate_timeout_input(raw):
            return
        # 验证后重新读取（验证可能将空值设为 "0"）
        timeout_val = int(self.var_timeout_minutes.get().strip())
        self.cfg.setdefault("rotation", {})
        self.cfg["rotation"]["stage_timeout_minutes"] = timeout_val

        # 保存仓库定时配置
        wh_raw = self.var_warehouse_interval.get().strip()
        try:
            wh_val = int(wh_raw) if wh_raw else 30
            if wh_val < 0:
                wh_val = 30
        except (ValueError, TypeError):
            wh_val = 30
        self.cfg.setdefault("warehouse", {})
        self.cfg["warehouse"]["enabled"] = self.var_warehouse_enabled.get()
        self.cfg["warehouse"]["interval_minutes"] = wh_val

        self.cfg.setdefault("mailbox_check", {})["enabled"] = self.var_mailbox_enabled.get()

        self.cfg.setdefault("fold_page", {})["mode"] = self.var_fold_mode.get()

        save_config(CONFIG_PATH, self.cfg)

        self.engine.set_anchor(self._anchor)
        self._drop_count = 0
        self.engine.helper_hwnd = self.winfo_id()
        try:
            self.engine.start(dry_run=dry_run, start_index=start_idx)
        except Exception as exc:
            messagebox.showerror("启动失败", str(exc), parent=self)
            return

        self._set_running(True)
        self.var_mode.set("仅监控" if dry_run else "挂机中")
        self._append_log(">>> 已启动")

    def _stop(self) -> None:
        self.engine.stop()
        self._set_running(False)
        self._append_log(f">>> 已停止，换图 {self.engine.switch_count} 次")

    def _next_stage(self) -> None:
        """手动请求切换到下一关——按钮立即变灰，切换完成后恢复。"""
        if not self.engine.is_running:
            return
        self.btn_next.configure_state(tk.DISABLED)
        self.engine.switch_now()
        self._append_log(">>> 请求切换到下一关")

    def _on_manual_switch_done(self) -> None:
        """手动切关完成后重新点亮按钮。"""
        if self.engine.is_running:
            self.btn_next.configure_state(tk.NORMAL)

    def _validate_timeout_input(self, raw: str) -> bool:
        """验证超时切关分钟数，必须为非负整数，0=关闭。"""
        if not raw:
            self.var_timeout_minutes.set("0")
            return True
        try:
            val = int(raw)
        except ValueError:
            messagebox.showerror("输入错误", "超时切关必须输入整数（分钟）\n输入 0 关闭此功能", parent=self)
            self.entry_timeout.focus_set()
            return False
        if val < 0:
            messagebox.showerror("输入错误", "超时切关分钟数不能为负数", parent=self)
            self.entry_timeout.focus_set()
            return False
        return True

    def _on_timeout_focus_out(self, _=None) -> None:
        """焦点离开超时输入框时验证并保存。"""
        raw = self.var_timeout_minutes.get().strip()
        if self._validate_timeout_input(raw):
            # 重新读取（验证可能将空值设为 "0"）
            val = int(self.var_timeout_minutes.get().strip())
            self.var_timeout_minutes.set(str(val))
            self.cfg.setdefault("rotation", {})
            self.cfg["rotation"]["stage_timeout_minutes"] = val
            save_config(CONFIG_PATH, self.cfg)

    def on_close(self) -> None:
        if self.engine.is_running:
            if not messagebox.askyesno("退出", "挂机仍在运行，确定退出？", parent=self):
                return
            self.engine.stop()
        self._stats_visible = False
        self.destroy()

    # ── 仓库标签页 ──────────────────────────────────────────

    def _add_warehouse_page(self) -> None:
        if not self._require_idle() or not self._require_anchor():
            return
        profile = self._get_profile()
        idx = len(profile.warehouse_tab_pages) + 1
        default_name = f"第{idx}页"

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor(warn_outside=False)
            if rel is None:
                return False
            page = {"name": default_name, "rel_x": rel[0], "rel_y": rel[1]}
            profile = self._get_profile()
            profile.warehouse_tab_pages.append(page)
            self._save_profile(profile, capture_template=bool(self._anchor))
            self._append_log(f">>> 添加仓库标签页 {default_name} @ ({rel[0]}, {rel[1]})")
            self._refresh_warehouse_ui()
            return True

        self._run_countdown_capture(
            title="添加仓库标签页",
            prompt=f"鼠标移到「{default_name}」标签位置",
            capture_fn=capture,
        )

    def _remark_warehouse_page(self) -> None:
        if not self._require_idle() or not self._require_anchor():
            return
        sel = self.warehouse_list.curselection()
        if not sel:
            messagebox.showinfo("提示", "请先选中一个标签页", parent=self)
            return
        idx = sel[0]
        profile = self._get_profile()
        if idx >= len(profile.warehouse_tab_pages):
            return
        page = profile.warehouse_tab_pages[idx]
        name = page.get("name", f"第{idx + 1}页")

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor(warn_outside=False)
            if rel is None:
                return False
            profile = self._get_profile()
            profile.warehouse_tab_pages[idx]["rel_x"] = rel[0]
            profile.warehouse_tab_pages[idx]["rel_y"] = rel[1]
            self._save_profile(profile, capture_template=bool(self._anchor))
            self._append_log(f">>> 重标仓库标签页 {name} @ ({rel[0]}, {rel[1]})")
            self._refresh_warehouse_ui()
            return True

        self._run_countdown_capture(
            title=f"重标 · {name}",
            prompt=f"鼠标移到「{name}」标签位置",
            capture_fn=capture,
        )

    def _delete_warehouse_page(self) -> None:
        if not self._require_idle():
            return
        sel = self.warehouse_list.curselection()
        if not sel:
            self.after(1, lambda: messagebox.showinfo("提示", "请先选中要删除的标签页", parent=self))
            return
        idx = sel[0]
        profile = self._get_profile()
        if idx >= len(profile.warehouse_tab_pages):
            return
        name = profile.warehouse_tab_pages[idx].get("name", f"第{idx + 1}页")
        ok = messagebox.askyesno("确认删除", f"确定删除仓库标签页「{name}」？", parent=self)
        if not ok:
            return
        del profile.warehouse_tab_pages[idx]
        # 重命名后续页面
        for i, p in enumerate(profile.warehouse_tab_pages):
            p["name"] = f"第{i + 1}页"
        self._save_profile(profile, capture_template=bool(self._anchor))
        self._append_log(f">>> 已删除仓库标签页 {name}")
        self._refresh_warehouse_ui()

    def _mark_warehouse_transfer(self) -> None:
        if not self._require_idle() or not self._require_anchor():
            return

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor(warn_outside=False)
            if rel is None:
                return False
            profile = self._get_profile()
            profile.warehouse_transfer_btn = [rel[0], rel[1]]
            self._save_profile(profile, capture_template=bool(self._anchor))
            self._append_log(f">>> 存仓按钮 @ ({rel[0]}, {rel[1]})")
            self._refresh_warehouse_ui()
            return True

        self._run_countdown_capture(
            title="标记存仓按钮",
            prompt="鼠标移到「从背包转移到仓库」按钮位置",
            capture_fn=capture,
        )

    def _refresh_warehouse_ui(self) -> None:
        """刷新仓库标签页列表和转移按钮提示。"""
        if not hasattr(self, "warehouse_list"):
            return
        profile = self._get_profile()

        # 刷新标签页列表
        self.warehouse_list.delete(0, tk.END)
        pages = profile.warehouse_tab_pages
        if not pages:
            self.warehouse_list.insert(tk.END, "  暂无标签页，点击「＋ 添加」")
            self._adjust_warehouse_list_height(0)
        else:
            for i, p in enumerate(pages, 1):
                name = p.get("name", f"第{i}页")
                self.warehouse_list.insert(tk.END, f"  {i}.  {name}")
            self._adjust_warehouse_list_height(len(pages))

        # 刷新转移按钮提示
        btn = profile.warehouse_transfer_btn
        if btn and len(btn) >= 2:
            self.var_transfer_hint.set(f"({btn[0]:.3f}, {btn[1]:.3f})")
        else:
            self.var_transfer_hint.set("未标记")
        # 刷新邮箱按钮提示
        self._refresh_mailbox_hints()

    def _save_warehouse_config(self, _=None) -> None:
        """保存仓库定时配置。"""
        raw = self.var_warehouse_interval.get().strip()
        try:
            val = int(raw) if raw else 30
            if val < 0:
                raise ValueError
        except (ValueError, TypeError):
            messagebox.showerror("输入错误", "间隔分钟数请输入非负整数", parent=self)
            self.var_warehouse_interval.set("30")
            return
        self.cfg.setdefault("warehouse", {})["enabled"] = self.var_warehouse_enabled.get()
        self.cfg["warehouse"]["interval_minutes"] = val
        save_config(CONFIG_PATH, self.cfg)
        self.engine.cfg = self.cfg
        self._append_log(f">>> 仓库配置已保存（{'启用' if self.var_warehouse_enabled.get() else '关闭'}，每 {val} 分钟）")

    # ── 邮箱检查按钮标记 ────────────────────────────────────

    MAILBOX_BUTTON_LABELS = {
        "open": "打开邮箱",
        "refresh": "刷新邮箱",
        "receive_all": "全部接收",
        "close": "关闭邮箱",
    }

    def _mark_mailbox_button(self, key: str) -> None:
        if not self._require_idle() or not self._require_anchor():
            return
        label = self.MAILBOX_BUTTON_LABELS.get(key, key)

        def capture() -> bool:
            rel = self._capture_cursor_in_anchor(warn_outside=False)
            if rel is None:
                return False
            profile = self._get_profile()
            profile.mailbox_buttons[key] = [rel[0], rel[1]]
            self._save_profile(profile, capture_template=bool(self._anchor))
            self._append_log(f">>> {label} @ ({rel[0]}, {rel[1]})")
            self._refresh_mailbox_hints()
            return True

        self._run_countdown_capture(
            title=f"标记 · {label}",
            prompt=f"鼠标移到游戏内「{label}」按钮位置",
            capture_fn=capture,
        )

    def _refresh_mailbox_hints(self) -> None:
        if not hasattr(self, "_mail_hint_vars"):
            return
        profile = self._get_profile()
        for key, var in self._mail_hint_vars.items():
            pos = profile.mailbox_buttons.get(key)
            if pos and len(pos) >= 2:
                var.set(f"({pos[0]:.3f}, {pos[1]:.3f})")
            else:
                var.set("✗")

    def _save_mailbox_config(self) -> None:
        """保存邮箱检查开关。"""
        val = self.var_mailbox_enabled.get()
        self.cfg.setdefault("mailbox_check", {})["enabled"] = val
        save_config(CONFIG_PATH, self.cfg)
        self.engine.cfg = self.cfg
        self.engine.mailbox_check_enabled = val
        self._append_log(
            f">>> 邮箱超时检查已{'启用' if val else '关闭'}"
        )


def main() -> None:
    if sys.platform == "win32":
        try:
            from tbh_helper.window import enable_dpi_awareness
            enable_dpi_awareness()
        except Exception:
            pass
    app = TBHApp()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()

