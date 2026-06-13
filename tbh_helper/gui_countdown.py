"""非阻塞倒计时采集对话框（标记鼠标位置等）。"""

from __future__ import annotations

from collections.abc import Callable

import tkinter as tk
from tkinter import ttk

from .ui_theme import (
    BG,
    BORDER,
    BORDER_WINE,
    FONT_COUNTDOWN,
    FONT_UI,
    GOLD,
    SURFACE,
    TEXT,
    TEXT2,
)


def open_countdown_capture_dialog(
    parent: tk.Misc,
    *,
    title: str,
    prompt: str,
    seconds: int = 5,
    capture_fn: Callable[[], bool],
    on_success: Callable[[], None] | None = None,
    on_skip: Callable[[], None] | None = None,
) -> None:
    dlg = tk.Toplevel(parent)
    dlg.title(title)
    dlg.configure(bg=BG)
    dlg.attributes("-topmost", True)
    dlg.resizable(False, False)
    dlg.transient(parent)
    try:
        dlg.geometry(f"+{parent.winfo_x() + 48}+{parent.winfo_y() + 72}")
    except tk.TclError:
        pass

    shell = tk.Frame(dlg, bg=SURFACE, highlightbackground=BORDER_WINE, highlightthickness=1)
    shell.pack(padx=16, pady=16)

    inner = tk.Frame(shell, bg=SURFACE, padx=24, pady=20)
    inner.pack()

    msg = tk.StringVar(value=prompt)
    tk.Label(inner, textvariable=msg, justify=tk.CENTER, wraplength=300, bg=SURFACE, fg=TEXT, font=FONT_UI).pack(
        pady=(0, 12)
    )
    count_var = tk.StringVar(value=str(seconds))
    tk.Label(inner, textvariable=count_var, font=FONT_COUNTDOWN, bg=SURFACE, fg=GOLD).pack(pady=4)
    tk.Label(inner, text="切换到游戏窗口，将鼠标移到目标位置", bg=SURFACE, fg=TEXT2, font=FONT_UI).pack(pady=(0, 8))

    btn_row = tk.Frame(inner, bg=SURFACE)
    btn_row.pack(pady=(4, 0))

    def close_dialog() -> None:
        if dlg.winfo_exists():
            dlg.destroy()

    def do_capture() -> None:
        if capture_fn():
            msg.set("已记录 ✓")
            count_var.set("")
            if on_success:
                on_success()
            dlg.after(500, close_dialog)

    def tick(n: int = seconds) -> None:
        if not dlg.winfo_exists():
            return
        if n > 0:
            count_var.set(str(n))
            msg.set(prompt)
            dlg.after(1000, lambda: tick(n - 1))
        else:
            count_var.set("…")
            msg.set("正在记录…")
            dlg.after(50, do_capture)

    ttk.Button(btn_row, text="立即记录", command=do_capture).pack(side=tk.LEFT, padx=4)
    if on_skip:
        ttk.Button(
            btn_row, text="跳过",
            command=lambda: (on_skip(), close_dialog()),
        ).pack(side=tk.LEFT, padx=4)
    ttk.Button(btn_row, text="取消", command=close_dialog).pack(side=tk.LEFT, padx=4)
    dlg.protocol("WM_DELETE_WINDOW", close_dialog)
    tick(seconds)
