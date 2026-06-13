from __future__ import annotations

import ctypes
import os
from dataclasses import dataclass
from typing import Optional

import win32api
import win32gui
import win32process

_dpi_initialized = False


def enable_dpi_awareness() -> None:
    """避免高 DPI 下 GetWindowRect 与 GetCursorPos 坐标系不一致。"""
    global _dpi_initialized
    if _dpi_initialized:
        return
    _dpi_initialized = True
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


enable_dpi_awareness()


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def to_screen(self, rel_x: float, rel_y: float) -> tuple[int, int]:
        x = self.left + int(self.width * rel_x)
        y = self.top + int(self.height * rel_y)
        return x, y


def _pid_for_hwnd(hwnd: int) -> int:
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    return pid


def find_game_window(process_name: str = "TaskBarHero", pid: Optional[int] = None) -> Optional[int]:
    """通过进程可执行文件名（如 taskbarhero.exe）查找游戏窗口，不依赖窗口标题。"""
    import psutil

    target_exe = process_name.lower()
    if not target_exe.endswith(".exe"):
        target_exe += ".exe"

    # 如果给了 pid，优先验证
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            if proc.name().lower() == target_exe:
                # 找该 pid 下第一个可见窗口
                for hwnd in _enum_windows_for_pid(pid):
                    return hwnd
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # 遍历所有进程，匹配 exe 名
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if proc.info["name"] and proc.info["name"].lower() == target_exe:
                hwnd = _find_window_for_process(proc.info["pid"])
                if hwnd:
                    return hwnd
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def _enum_windows_for_pid(pid: int) -> list[int]:
    """枚举指定 pid 下的所有顶层可见窗口。"""
    result: list[int] = []

    def callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            try:
                _, p = win32process.GetWindowThreadProcessId(hwnd)
                if p == pid:
                    result.append(hwnd)
            except Exception:
                pass
        return True

    win32gui.EnumWindows(callback, None)
    return result


def _find_window_for_process(pid: int) -> Optional[int]:
    """查找指定 pid 下第一个可见窗口。"""
    for hwnd in _enum_windows_for_pid(pid):
        return hwnd
    return None


def get_window_rect(hwnd: int) -> WindowRect:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return WindowRect(left=left, top=top, width=right - left, height=bottom - top)


def get_client_rect_screen(hwnd: int) -> WindowRect:
    """游戏可点击区域（不含标题栏/边框），屏幕坐标。"""
    _, _, right, bottom = win32gui.GetClientRect(hwnd)
    sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
    return WindowRect(left=sx, top=sy, width=right, height=bottom)


def screen_to_client_rel(hwnd: int, screen_x: int, screen_y: int) -> tuple[float, float]:
    rect = get_client_rect_screen(hwnd)
    if rect.width <= 0 or rect.height <= 0:
        raise ValueError("游戏窗口客户端区域无效")
    rel_x = (screen_x - rect.left) / rect.width
    rel_y = (screen_y - rect.top) / rect.height
    return rel_x, rel_y


def focus_window(hwnd: int, helper_hwnd: int | None = None) -> None:
    """尽量把游戏窗口切到前台；GUI 挂机时可传入助手窗口句柄先最小化。"""
    import time

    import win32con

    if helper_hwnd:
        try:
            if win32gui.IsWindow(helper_hwnd) and win32gui.GetForegroundWindow() == helper_hwnd:
                win32gui.ShowWindow(helper_hwnd, win32con.SW_MINIMIZE)
                time.sleep(0.05)
        except Exception:
            pass

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.08)

    if win32gui.GetForegroundWindow() == hwnd:
        return

    try:
        fg = win32gui.GetForegroundWindow()
        fg_thread, _ = win32process.GetWindowThreadProcessId(fg)
        target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
        current_thread = win32api.GetCurrentThreadId()

        win32api.AttachThreadInput(current_thread, fg_thread, True)
        win32api.AttachThreadInput(target_thread, fg_thread, True)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)
        win32gui.SetForegroundWindow(hwnd)
        win32api.AttachThreadInput(target_thread, fg_thread, False)
        win32api.AttachThreadInput(current_thread, fg_thread, False)
    except Exception:
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass


def get_cursor_pos() -> tuple[int, int]:
    return win32api.GetCursorPos()


def expand_path(path: str) -> str:
    return os.path.normpath(os.path.expandvars(os.path.expanduser(path)))


# ── 进程权限检测 ──────────────────────────────────────────


def _get_process_integrity_level(pid: int) -> int:
    """返回进程完整性级别（0=不可信, 1=低, 2=中, 3=高, 4=系统）。"""
    try:
        import win32security
        import ntsecuritycon

        handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)  # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ
        try:
            token = win32security.OpenProcessToken(handle, 0x0008)  # TOKEN_QUERY
            try:
                sid = win32security.GetTokenInformation(token, win32security.TokenIntegrityLevel)
                sia = win32security.ConvertSidToStringSid(sid)
                # SID 格式 S-1-16-{level}
                if sia:
                    return int(sia.rsplit("-", 1)[-1])
            finally:
                win32api.CloseHandle(token)
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return -1  # 未知
    return -1


def is_process_elevated(hwnd: int) -> bool:
    """判断目标窗口所属进程是否以管理员权限运行。"""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        level = _get_process_integrity_level(pid)
        # 完整性 ≥ 0x3000（高）即管理员
        return level >= 0x3000
    except Exception:
        return False


def is_self_elevated() -> bool:
    """判断当前脚本是否以管理员权限运行。"""
    return _get_process_integrity_level(os.getpid()) >= 0x3000
