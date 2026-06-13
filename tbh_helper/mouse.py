"""Windows 原生鼠标点击，多层 fallback，兼容各种 Windows 环境与 Unity 游戏。"""

from __future__ import annotations

import ctypes
import logging
import time
from ctypes import wintypes
from typing import Literal

import win32api
import win32con
import win32gui

from .window import focus_window

logger = logging.getLogger(__name__)

ClickMethod = Literal["auto", "sendinput", "mouse_event", "postmessage"]

INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
MK_LBUTTON = 0x0001


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


# ── 鼠标移动 ────────────────────────────────────────────


def _move_cursor(screen_x: int, screen_y: int, pause: float) -> None:
    win32api.SetCursorPos((screen_x, screen_y))
    if pause > 0:
        time.sleep(pause)


# ── 点击：SendInput ─────────────────────────────────────


def _click_sendinput(*, hold: float) -> None:
    down = INPUT()
    down.type = INPUT_MOUSE
    down.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, None)
    up = INPUT()
    up.type = INPUT_MOUSE
    up.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, None)
    user32 = ctypes.windll.user32
    if user32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT)) != 1:
        raise OSError("SendInput 按下失败")
    if hold > 0:
        time.sleep(hold)
    if user32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT)) != 1:
        raise OSError("SendInput 抬起失败")


# ── 点击：mouse_event（传统 API，部分环境下受限更少）───


def _click_mouse_event(*, hold: float) -> None:
    win32api.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    if hold > 0:
        time.sleep(hold)
    win32api.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


# ── 点击：PostMessage（直接发消息到窗口，完全绕过 UIPI）──


def _click_postmessage(hwnd: int, screen_x: int, screen_y: int, *, hold: float) -> None:
    """通过 PostMessage 直接向窗口发送鼠标消息，无需焦点，绕过 UIPI。"""
    # 找到鼠标位置下的实际子窗口
    target = win32gui.WindowFromPoint((screen_x, screen_y))
    if not target or not win32gui.IsWindow(target):
        target = hwnd

    # PostMessage 的 lParam 需要客户区坐标，而非屏幕坐标
    cx, cy = win32gui.ScreenToClient(target, (screen_x, screen_y))
    packed = win32api.MAKELONG(cx & 0xFFFF, cy & 0xFFFF)
    win32gui.PostMessage(target, WM_LBUTTONDOWN, MK_LBUTTON, packed)
    if hold > 0:
        time.sleep(hold)
    win32gui.PostMessage(target, WM_LBUTTONUP, 0, packed)


# ── 调拨 ────────────────────────────────────────────────


def _dispatch_click(
    method: ClickMethod, *, hwnd: int, screen_x: int, screen_y: int, hold: float
) -> None:
    if method == "sendinput":
        _click_sendinput(hold=hold)
    elif method == "mouse_event":
        _click_mouse_event(hold=hold)
    elif method == "postmessage":
        _click_postmessage(hwnd, screen_x, screen_y, hold=hold)
    else:
        raise ValueError(f"未知点击方式: {method}")


# ── UIPI 检测：SendInput 被拦截时静默失败，需提前判断 ───


def _sendinput_likely_blocked(hwnd: int) -> bool:
    """检测 UIPI 是否会拦截 SendInput / mouse_event 到目标窗口。"""
    try:
        from .window import is_process_elevated, is_self_elevated

        return is_process_elevated(hwnd) and not is_self_elevated()
    except Exception:
        return False


# ── 公开接口 ────────────────────────────────────────────────

ClickMethodName = Literal["sendinput", "mouse_event", "postmessage"]


def click_at(
    hwnd: int,
    screen_x: int,
    screen_y: int,
    *,
    helper_hwnd: int | None = None,
    method: ClickMethod = "sendinput",
    focus_delay: float = 0.2,
    move_delay: float = 0.08,
    click_hold: float = 0.05,
    after_delay: float = 0.05,
) -> str:
    """
    单击。auto 模式会自动避开被 UIPI 拦截的方式。

    返回实际使用的点击方式名（sendinput / mouse_event / postmessage）。
    """
    # auto 模式下先检测 UIPI 拦截
    if method == "auto":
        blocked = _sendinput_likely_blocked(hwnd)
        if blocked:
            logger.info("SendInput 可能被 UIPI 拦截，直接使用 postmessage")
            methods: list[ClickMethod] = ["postmessage"]
        else:
            methods = ["sendinput", "mouse_event", "postmessage"]
    else:
        methods = [method]

    if "postmessage" not in methods:
        focus_window(hwnd, helper_hwnd=helper_hwnd)
        if focus_delay > 0:
            time.sleep(focus_delay)

    last_error: Exception | None = None
    for candidate in methods:
        try:
            if candidate != "postmessage":
                _move_cursor(screen_x, screen_y, move_delay)
            _dispatch_click(candidate, hwnd=hwnd, screen_x=screen_x, screen_y=screen_y, hold=click_hold)
            if after_delay > 0:
                time.sleep(after_delay)
            logger.info("click_at %s -> %s", (screen_x, screen_y), candidate)
            return candidate
        except Exception as exc:
            last_error = exc
            logger.warning("click_at %s with %s failed: %s", (screen_x, screen_y), candidate, exc)
            continue

    raise RuntimeError(f"所有点击方式均失败，最后错误: {last_error}")


def double_click_at(
    hwnd: int,
    screen_x: int,
    screen_y: int,
    *,
    helper_hwnd: int | None = None,
    method: ClickMethod = "sendinput",
    focus_delay: float = 0.2,
    move_delay: float = 0.08,
    click_hold: float = 0.05,
    click_interval: float = 0.12,
    after_delay: float = 0.05,
) -> str:
    """聚焦后在屏幕坐标处双击。返回实际使用的点击方式名。"""
    used = click_at(
        hwnd,
        screen_x,
        screen_y,
        helper_hwnd=helper_hwnd,
        method=method,
        focus_delay=focus_delay,
        move_delay=move_delay,
        click_hold=click_hold,
        after_delay=click_interval,
    )
    click_at(
        hwnd,
        screen_x,
        screen_y,
        helper_hwnd=helper_hwnd,
        method=used,  # type: ignore[arg-type]
        focus_delay=0,
        move_delay=0,
        click_hold=click_hold,
        after_delay=after_delay,
    )
    return used
