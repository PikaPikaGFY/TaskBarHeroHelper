"""深色主题：黑底 · 酒红辅助 · 深金点缀 · 微软雅黑。"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

# ── 字体 ────────────────────────────────────────────────
FONT = "Microsoft YaHei UI"
FONT_UI = (FONT, 10)
FONT_TITLE = (FONT, 20, "bold")
FONT_SUB = (FONT, 11)
FONT_MONO = (FONT, 9)
FONT_COUNTDOWN = (FONT, 36, "bold")
FONT_BOLD = (FONT, 10, "bold")

# ── 调色板 ──────────────────────────────────────────────
BG = "#0C0C0C"
SURFACE = "#161616"
SURFACE2 = "#1E1E1E"
BORDER = "#2E2E2E"
BORDER_WINE = "#4A2830"

TEXT = "#ECECEC"
TEXT2 = "#8A8A8A"

# 酒红（主强调）
ACCENT = "#9B2335"
ACCENT_HOVER = "#B82E45"
ACCENT_PRESSED = "#7A1C2A"

# 深金（次强调 / 完成态 / 点缀）
GOLD = "#B8941F"
GOLD_HOVER = "#D4AD2E"
GOLD_DIM = "#8A7118"

SUCCESS = GOLD
WARNING = GOLD_HOVER
DANGER = "#C0392B"

LOG_BG = "#080808"
LOG_FG = "#C8C8C8"
LOG_ACCENT = GOLD_DIM


def apply_root_style(root: tk.Tk) -> None:
    root.configure(bg=BG)


def _lerp_color(c1: str, c2: str, t: float) -> str:
    r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
    r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _round_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, r: int, **kwargs) -> int:
    points = [
        x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
        x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
        x1, y2, x1, y2 - r, x1, y1 + r, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


def _light_text_on(fill: str) -> str:
    r, g, b = int(fill[1:3], 16), int(fill[3:5], 16), int(fill[5:7], 16)
    lum = r * 299 + g * 587 + b * 114
    return "#FFFFFF" if lum < 140000 else TEXT


class RoundedButton(tk.Canvas):
    """圆角按钮，带悬停/按下过渡。"""

    def __init__(
        self,
        parent: tk.Misc,
        text: str,
        command: Callable[[], None] | None = None,
        *,
        width: int = 140,
        height: int = 38,
        radius: int = 12,
        fill: str = ACCENT,
        fill_hover: str = ACCENT_HOVER,
        fill_pressed: str = ACCENT_PRESSED,
        fg: str = "#FFFFFF",
        font: tuple = FONT_UI,
        style: str = "primary",
        **kwargs,
    ) -> None:
        if style == "secondary":
            fill, fill_hover, fill_pressed = SURFACE2, "#282828", "#323232"
            fg = TEXT
        elif style == "ghost":
            fill, fill_hover, fill_pressed = BG, SURFACE, SURFACE2
            fg = GOLD
        elif style == "gold":
            fill, fill_hover, fill_pressed = GOLD_DIM, GOLD, GOLD_HOVER
            fg = "#FFFFFF"
        elif style == "danger":
            fill, fill_hover, fill_pressed = DANGER, "#D44637", "#A93226"
            fg = "#FFFFFF"

        super().__init__(
            parent,
            width=width,
            height=height,
            highlightthickness=0,
            bg=parent.cget("bg") if hasattr(parent, "cget") else BG,
            **kwargs,
        )
        self._text = text
        self._command = command
        self._radius = radius
        self._fill_base = fill
        self._fill_hover = fill_hover
        self._fill_pressed = fill_pressed
        self._fg = fg
        self._font = font
        self._style = style
        self._current = fill
        self._target = fill
        self._anim_id: str | None = None
        self._enabled = True
        self._pressed = False
        self._outline = BORDER_WINE if style == "primary" else BORDER

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._draw()

    def configure(self, **kwargs) -> None:
        if "text" in kwargs:
            self._text = kwargs.pop("text")
        super().configure(**kwargs)
        self._draw()

    def configure_state(self, state: str) -> None:
        self._enabled = state != tk.DISABLED
        self.configure(cursor="hand2" if self._enabled else "arrow")
        if not self._enabled:
            self._target = "#1A1A1A"
            self._fg = TEXT2
            self._current = "#1A1A1A"
        else:
            self._target = self._fill_base
            self._current = self._fill_base
            self._fg = _light_text_on(self._fill_base) if self._style != "ghost" else GOLD
        self._draw()

    def _animate_to(self, color: str) -> None:
        if self._anim_id:
            self.after_cancel(self._anim_id)
        self._target = color
        self._step_animate()

    def _step_animate(self) -> None:
        if self._current == self._target:
            self._anim_id = None
            return
        self._current = _lerp_color(self._current, self._target, 0.35)
        if abs(int(self._current[1:3], 16) - int(self._target[1:3], 16)) < 3:
            self._current = self._target
        self._draw()
        if self._current != self._target:
            self._anim_id = self.after(16, self._step_animate)

    def _draw(self) -> None:
        self.delete("all")
        w, h = int(self.cget("width")), int(self.cget("height"))
        _round_rect(self, 1, 1, w - 1, h - 1, self._radius, fill=self._current, outline=self._outline)
        self.create_text(w // 2, h // 2, text=self._text, fill=self._fg, font=self._font)

    def _on_enter(self, _=None) -> None:
        if self._enabled and not self._pressed:
            self._animate_to(self._fill_hover)

    def _on_leave(self, _=None) -> None:
        if self._enabled:
            self._pressed = False
            self._animate_to(self._fill_base)

    def _on_press(self, _=None) -> None:
        if not self._enabled:
            return
        self._pressed = True
        self._animate_to(self._fill_pressed)

    def _on_release(self, event=None) -> None:
        if not self._enabled:
            return
        self._pressed = False
        x, y = event.x, event.y
        w, h = int(self.cget("width")), int(self.cget("height"))
        inside = 0 <= x <= w and 0 <= y <= h
        self._animate_to(self._fill_hover if inside else self._fill_base)
        if inside and self._command:
            self.after(1, self._command)


class Card(tk.Frame):
    """深色卡片。"""

    def __init__(self, parent: tk.Misc, *, padding: int = 16, **kwargs) -> None:
        super().__init__(parent, bg=SURFACE, highlightbackground=BORDER_WINE, highlightthickness=1, **kwargs)
        self.inner = tk.Frame(self, bg=SURFACE)
        self.inner.pack(fill=tk.BOTH, expand=True, padx=padding, pady=padding)


class StepRow(tk.Frame):
    """流程步骤行。"""

    def __init__(
        self,
        parent: tk.Misc,
        step: int,
        title: str,
        subtitle: str = "",
        **kwargs,
    ) -> None:
        super().__init__(parent, bg=SURFACE, **kwargs)
        self.var_status = tk.StringVar(value="pending")

        self.dot = tk.Canvas(self, width=28, height=28, bg=SURFACE, highlightthickness=0)
        self.dot.pack(side=tk.LEFT, padx=(0, 10))
        self._draw_dot("pending")

        text_col = tk.Frame(self, bg=SURFACE)
        text_col.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(
            text_col,
            text=f"步骤 {step}  ·  {title}",
            font=FONT_SUB,
            bg=SURFACE,
            fg=TEXT,
            anchor=tk.W,
        ).pack(fill=tk.X)
        if subtitle:
            tk.Label(text_col, text=subtitle, font=FONT_UI, bg=SURFACE, fg=TEXT2, anchor=tk.W).pack(fill=tk.X)

        self.action_slot = tk.Frame(self, bg=SURFACE)
        self.action_slot.pack(side=tk.RIGHT)

    def _draw_dot(self, status: str) -> None:
        self.dot.delete("all")
        colors = {"pending": BORDER, "active": ACCENT, "done": GOLD}
        fill = colors.get(status, BORDER)
        self.dot.create_oval(4, 4, 24, 24, fill=fill, outline="")
        if status == "done":
            self.dot.create_text(14, 14, text="✓", fill=BG, font=FONT_BOLD)
        elif status == "active":
            self.dot.create_text(14, 14, text="→", fill="#FFFFFF", font=FONT_BOLD)
        else:
            self.dot.create_text(14, 14, text="·", fill=TEXT2, font=(FONT, 14))

    def set_status(self, status: str) -> None:
        self.var_status.set(status)
        self._draw_dot(status)


class SegmentedControl(tk.Frame):
    """分段切换（运行 / 设置）。"""

    def __init__(
        self,
        parent: tk.Misc,
        options: list[tuple[str, Callable[[], None]]],
        **kwargs,
    ) -> None:
        super().__init__(parent, bg=BG, **kwargs)
        self._buttons: list[RoundedButton] = []
        self._active = 0
        row = tk.Frame(self, bg=BG)
        row.pack()
        for i, (label, cb) in enumerate(options):

            def make_handler(idx: int, callback: Callable[[], None]) -> Callable[[], None]:
                def handler() -> None:
                    self.select(idx)
                    callback()
                return handler

            btn = RoundedButton(
                row,
                label,
                make_handler(i, cb),
                width=100,
                height=34,
                radius=10,
                style="secondary" if i else "primary",
            )
            btn.pack(side=tk.LEFT, padx=3)
            self._buttons.append(btn)

    def select(self, index: int) -> None:
        self._active = index
        for i, btn in enumerate(self._buttons):
            if i == index:
                btn._fill_base = ACCENT
                btn._fill_hover = ACCENT_HOVER
                btn._fill_pressed = ACCENT_PRESSED
                btn._fg = "#FFFFFF"
                btn._current = ACCENT
                btn._outline = BORDER_WINE
            else:
                btn._fill_base = SURFACE2
                btn._fill_hover = "#282828"
                btn._fill_pressed = "#323232"
                btn._fg = TEXT2
                btn._current = SURFACE2
                btn._outline = BORDER
            btn._draw()


class StatusPill(tk.Frame):
    def __init__(self, parent: tk.Misc, **kwargs) -> None:
        super().__init__(parent, bg=BG, **kwargs)
        self.dot = tk.Canvas(self, width=10, height=10, bg=BG, highlightthickness=0)
        self.dot.pack(side=tk.LEFT, padx=(0, 6))
        self.var = tk.StringVar()
        tk.Label(self, textvariable=self.var, font=FONT_UI, bg=BG, fg=TEXT2).pack(side=tk.LEFT)
        self.set_ok(False, "检测中…")

    def set_ok(self, ok: bool, text: str) -> None:
        self.var.set(text)
        self.dot.delete("all")
        self.dot.create_oval(1, 1, 9, 9, fill=GOLD if ok else TEXT2, outline="")


def style_listbox(lb: tk.Listbox) -> None:
    lb.configure(
        bg=SURFACE2,
        fg=TEXT,
        selectbackground=ACCENT,
        selectforeground="#FFFFFF",
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=BORDER_WINE,
        highlightcolor=ACCENT,
        activestyle="none",
        borderwidth=0,
        font=FONT_UI,
    )


def style_log(text: tk.Text) -> None:
    text.configure(
        bg=LOG_BG,
        fg=LOG_FG,
        insertbackground=GOLD,
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=BORDER_WINE,
        font=FONT_MONO,
        padx=12,
        pady=10,
        spacing1=2,
    )


def style_option_menu(widget: tk.Misc) -> None:
    widget.configure(
        bg=SURFACE2,
        fg=TEXT,
        activebackground=ACCENT,
        activeforeground="#FFFFFF",
        highlightthickness=0,
        font=FONT_UI,
    )


def style_entry(widget: tk.Entry) -> None:
    widget.configure(
        bg=SURFACE2,
        fg=TEXT,
        insertbackground=GOLD,
        relief=tk.FLAT,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        font=FONT_UI,
    )


class StyledScrollbar(tk.Canvas):
    """深色主题自定义滚动条（Canvas 绘制）。"""

    THUMB_MIN = 24
    WIDTH = 12

    def __init__(self, parent: tk.Misc, *, command: Callable, **kwargs) -> None:
        super().__init__(
            parent,
            width=self.WIDTH,
            height=0,  # 不贡献父容器高度，由 fill=tk.Y 拉伸
            bg=BG,
            highlightthickness=0,
            **kwargs,
        )
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._dragging = False
        self._drag_start_y = 0
        self._drag_start_first = 0.0

        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set(self, first: float, last: float) -> None:
        self._first = float(first)
        self._last = float(last)
        self._draw()

    def _draw(self) -> None:
        self.delete("all")
        w = self.WIDTH
        try:
            h = max(int(self.winfo_height()), 20)
        except tk.TclError:
            h = 20

        # 轨道
        self.create_rectangle(0, 0, w, h, fill=BG, outline="")

        # 滑块尺寸
        visible = self._last - self._first
        if visible >= 1.0 or visible <= 0.0:
            return
        thumb_h = max(int(h * visible), self.THUMB_MIN)
        thumb_y = int(self._first * h)
        if thumb_y + thumb_h > h:
            thumb_y = h - thumb_h

        r = 4
        _round_rect(self, 2, thumb_y, w - 2, thumb_y + thumb_h, r, fill=SURFACE2, outline="")

    def _on_press(self, event) -> None:
        self._dragging = True
        self._drag_start_y = event.y_root
        self._drag_start_first = self._first

    def _on_drag(self, event) -> None:
        if not self._dragging:
            return
        h = max(int(self.winfo_height()), 20)
        visible = self._last - self._first
        thumb_h = max(int(h * visible), self.THUMB_MIN)
        available = h - thumb_h
        if available <= 0:
            return
        dy = event.y_root - self._drag_start_y
        new_first = max(0.0, min(1.0 - visible, self._drag_start_first + dy / available))
        self._command("moveto", new_first)

    def _on_release(self, event) -> None:
        self._dragging = False


class StyledScrolledText(tk.Frame):
    """带深色自定义滚动条的文本框，替换 ScrolledText。"""

    def __init__(self, parent: tk.Misc, **kwargs) -> None:
        super().__init__(parent, bg=BG)
        self.text = tk.Text(self, **kwargs)
        self.scrollbar = StyledScrollbar(self, command=self.text.yview)
        self.text.configure(yscrollcommand=self.scrollbar.set)

        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)


class StatusFlow(tk.Frame):
    """水平流程状态条，用 Canvas 绘制节点 + 连线。"""

    NODE_W = 86
    NODE_H = 30
    COL_GAP = 28

    _DONE_BG = "#2E7D32"
    _DONE_FG = "#FFFFFF"
    _CURRENT_BG = ACCENT
    _CURRENT_FG = "#FFFFFF"
    _PENDING_BG = SURFACE2
    _PENDING_FG = TEXT2
    _ARROW_DONE = "#4CAF50"
    _ARROW_NEXT = "#FF9800"
    _ARROW_PENDING = "#444444"

    def __init__(self, parent: tk.Misc, **kwargs) -> None:
        super().__init__(parent, bg=BG, height=86, **kwargs)
        self.pack_propagate(False)
        self.canvas = tk.Canvas(self, bg=BG, highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self._state = "idle"
        self._data: dict = {}
        self._queue: list[tuple[str, dict]] = []
        self._animating = False

        self.canvas.bind("<Configure>", lambda _: self._redraw())

    def show(self, state: str, **data) -> None:
        self._state = state
        self._data = data
        self.after_idle(self._redraw)

    # ── 节点定义 ──────────────────────────────────────────

    def _build_nodes(self) -> list[dict]:
        s = self._state
        d = self._data
        stage = d.get("stage", "")
        target = d.get("target", "")

        if s == "idle":
            return [{"label": "待机中", "status": "current"}]

        if s in ("fighting",):
            return [
                {"label": f"刷关 {stage}", "status": "current"},
                {"label": "等待掉落", "status": "pending"},
                {"label": "检测箱子", "status": "pending"},
            ]

        if s == "waiting":
            return [
                {"label": f"刷关 {stage}", "status": "done"},
                {"label": "等待掉落", "status": "current"},
                {"label": "检测箱子", "status": "pending"},
            ]

        if s == "detected":
            return [
                {"label": f"刷关 {stage}", "status": "done"},
                {"label": "等待掉落", "status": "done"},
                {"label": "检测箱子", "status": "current",
                 "branch": ("是→换关", "否→等待")},
                {"label": "换关", "status": "pending"},
            ]

        if s == "switching":
            return [
                {"label": f"刷关 {stage}", "status": "done"},
                {"label": "等待掉落", "status": "done"},
                {"label": "检测箱子", "status": "done"},
                {"label": f"换关 {target}", "status": "current"},
            ]

        if s == "mailbox":
            return [
                {"label": f"刷关 {stage}", "status": "done"},
                {"label": "超时", "status": "done"},
                {"label": "查邮箱", "status": "current"},
                {"label": "等待掉落", "status": "pending"},
            ]

        if s == "warehouse":
            return [
                {"label": f"刷关 {stage}", "status": "done"},
                {"label": "存仓库", "status": "current"},
                {"label": "刷关", "status": "pending"},
            ]

        if s == "timeout_switch":
            return [
                {"label": f"刷关 {stage}", "status": "done"},
                {"label": "超时", "status": "done"},
                {"label": f"换关 {target}", "status": "current"},
            ]

        return []

    # ── 绘制 ──────────────────────────────────────────────

    def _node_color(self, status: str) -> tuple[str, str]:
        if status == "done":
            return self._DONE_BG, self._DONE_FG
        if status == "current":
            return self._CURRENT_BG, self._CURRENT_FG
        return self._PENDING_BG, self._PENDING_FG

    def _redraw(self) -> None:
        c = self.canvas
        c.delete("all")
        cw = max(c.winfo_width(), 100)
        cy = 42  # vertical center

        nodes = self._build_nodes()
        if not nodes:
            return

        n = len(nodes)
        total_w = n * self.NODE_W + (n - 1) * self.COL_GAP
        ox = max(10, (cw - total_w) // 2)

        for i, nd in enumerate(nodes):
            x = ox + i * (self.NODE_W + self.COL_GAP)

            # 箭头（画在节点之前，位于下层）
            if i > 0:
                px = ox + (i - 1) * (self.NODE_W + self.COL_GAP) + self.NODE_W
                prev = nodes[i - 1]
                arrow_color = self._ARROW_DONE
                if prev.get("status") == "current":
                    arrow_color = self._ARROW_NEXT
                elif prev.get("status") == "pending":
                    arrow_color = self._ARROW_PENDING
                # 若前一个节点有分支标注，改为橙色强调
                if prev.get("branch"):
                    arrow_color = self._ARROW_NEXT
                self._draw_arrow(c, px, cy, x, cy, arrow_color)

                # 分支标注
                branch = prev.get("branch")
                if branch:
                    mx = (px + x) // 2
                    c.create_text(mx, cy - 18, text=branch[0],
                                  fill=self._ARROW_NEXT, font=FONT_UI)
                    c.create_text(mx, cy + 18, text=branch[1],
                                  fill=TEXT2, font=FONT_UI)

            # 节点
            bg, fg = self._node_color(nd.get("status", "pending"))
            r = 6
            _round_rect(c, x, cy - self.NODE_H // 2, x + self.NODE_W,
                        cy + self.NODE_H // 2, r, fill=bg)
            c.create_text(x + self.NODE_W // 2, cy, text=nd["label"],
                          fill=fg, font=FONT_UI)

    def _draw_arrow(self, c: tk.Canvas, x1: int, y1: int,
                    x2: int, y2: int, color: str) -> None:
        c.create_line(x1, y1, x2, y2, fill=color, width=2)
        # 三角箭头
        ah = 6
        c.create_polygon(x2, y2, x2 - ah, y2 - 4, x2 - ah, y2 + 4,
                         fill=color, outline="")
