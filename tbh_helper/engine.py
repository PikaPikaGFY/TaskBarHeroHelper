"""挂机引擎：供 CLI 与 GUI 共用。"""

from __future__ import annotations

import io
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from tbh_helper.anchor import AnchorRect
from tbh_helper.chest_open import ChestOpenConfig, open_chest
from tbh_helper.config_loader import build_rotator, profile_path_from_cfg
from tbh_helper.log_watcher import DetectConfig, LogTailWatcher, box_type_label, wait_for_log
from tbh_helper.mouse import click_at
from tbh_helper.profile import PortalProfile
from tbh_helper.rotator import MapRotator
from tbh_helper.statistics import StatisticsTracker
from tbh_helper.window import expand_path, find_game_window

LogFn = Callable[[str], None]


class RotatorEngine:
    def __init__(
        self,
        cfg: dict,
        base_dir: Path,
        *,
        on_log: LogFn | None = None,
        on_switch: Callable[[str, int], None] | None = None,
        on_drop: Callable[[str, str, bool], None] | None = None,
        on_stats_update: Callable[[], None] | None = None,
        on_status: Callable[..., None] | None = None,
        on_manual_switch_done: Callable[[], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.base_dir = base_dir
        self.on_log = on_log or (lambda msg: None)
        self.on_switch = on_switch or (lambda _name, _n: None)
        self.on_drop = on_drop or (lambda _tag, _key, _trigger: None)
        self.on_stats_update = on_stats_update or (lambda: None)
        self.on_status = on_status or (lambda **kw: None)
        self.on_manual_switch_done = on_manual_switch_done or (lambda: None)

        game_cfg = cfg.get("game", {})
        self.process_name = game_cfg.get("process_name", "TaskBarHero")
        self.pid = game_cfg.get("pid")
        self.log_path = Path(expand_path(cfg.get("log", {}).get("path", "")))
        self.detect = DetectConfig.from_dict(cfg.get("log", {}), cfg.get("detect"))
        self.chest = ChestOpenConfig()
        self.normal_chest = ChestOpenConfig()
        self.warehouse_enabled: bool = False
        self.warehouse_interval_seconds: float = 0.0
        self.stats = StatisticsTracker()
        self.stage_timeout_seconds: float = 0.0
        self.poll_interval = 0.4

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._manual_switch = threading.Event()
        self._anchor: AnchorRect | None = None
        self._profile: PortalProfile | None = None
        self._rotator: MapRotator | None = None
        self._dry_run = False
        self._switch_count = 0
        self._running = False
        self._stage_entered_at: float = 0.0
        self._action_event = threading.Event()
        self._action_event.set()  # 初始空闲
        self._last_warehouse_at: float = 0.0
        self._stage_name: str = ""
        self._mailbox_pending: bool = False
        self._mailbox_done: bool = False
        self._start_index: int = 0
        self.helper_hwnd: int | None = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def switch_count(self) -> int:
        return self._switch_count

    def load_profile(self) -> PortalProfile:
        path = profile_path_from_cfg(self.cfg, self.base_dir)
        return PortalProfile.load_or_create(path)

    def set_anchor(self, anchor: AnchorRect | None) -> None:
        self._anchor = anchor

    def log(self, msg: str) -> None:
        self.on_log(msg)

    def start(self, *, dry_run: bool = False, start_index: int = 0) -> None:
        if self._running:
            self.log("已在运行中")
            return

        if self._anchor is None:
            raise RuntimeError("请先捕获游戏窗口位置")

        self._profile = self.load_profile()
        self._start_index = start_index

        # 加载宝箱配置
        def _pick(d: dict | None, default_x: float, default_y: float) -> dict:
            """从 profile 取配置，若为默认值则降级到 config.yaml。"""
            d = d or {}
            is_default = (
                not d.get("enabled")
                and d.get("rel", [default_x, default_y]) == [default_x, default_y]
            )
            if is_default:
                fallback = self.cfg.get("chest_open" if default_y == 0.2 else "normal_chest") or {}
                return fallback
            return d

        self.chest = ChestOpenConfig.from_dict(_pick(self._profile.chest_open, 0.5, 0.2))
        self.normal_chest = ChestOpenConfig.from_dict(_pick(self._profile.normal_chest, 0.5, 0.5))

        wh = self.cfg.get("warehouse", {})
        self.warehouse_enabled = bool(wh.get("enabled", False))
        self.warehouse_interval_seconds = max(0.0, float(wh.get("interval_minutes", 30))) * 60.0

        self.mailbox_check_enabled = bool(self.cfg.get("mailbox_check", {}).get("enabled", False))

        fp = self.cfg.get("fold_page", {})
        self.fold_page_mode = str(fp.get("mode", "always_expand"))

        rotation_cfg = self.cfg.get("rotation", {})
        raw = rotation_cfg.get("stage_timeout_minutes", 0)
        self.stage_timeout_seconds = max(0.0, float(raw)) * 60.0

        self._dry_run = dry_run
        self._switch_count = 0
        self._stop.clear()
        self._running = True

        self.stats.reset()

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self.stats.exit_stage()
        self.on_stats_update()
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def switch_now(self) -> None:
        """请求立即切换到下一关（线程安全）。"""
        if not self._running or self._dry_run:
            return
        self._manual_switch.set()

    def _run_exclusive(self, action, desc: str = "操作", timeout: float = 120) -> bool:
        """互斥执行：排队等待当前操作完成，最多等 timeout 秒。"""
        if self._action_event.wait(timeout=timeout):
            self._action_event.clear()
            try:
                action()
            except Exception as exc:
                self.log(f"[{desc}] 出错: {exc}")
            finally:
                self._action_event.set()
            return True
        self.log(f"[超时] {desc}：等待 {int(timeout)} 秒超时，跳过")
        return False

    def _run_loop(self) -> None:
        old_stdout = sys.stdout
        sys.stdout = _StreamCapture(self.log)
        try:
            self._run_loop_inner()
        except Exception as exc:
            self.log(f"[错误] {exc}")
        finally:
            sys.stdout = old_stdout
            self.stats.exit_stage()
            self.on_stats_update()
            self._running = False
            self.log("监控已停止")

    def _run_loop_inner(self) -> None:
        wait_for_log(self.log_path, timeout=15.0)
        watcher = LogTailWatcher(self.log_path, self.detect)
        watcher.seek_end()

        stages = [s["name"] for s in self._profile.stages]
        mode = "仅监控" if self._dry_run else "自动换图"
        self.log("=" * 40)
        self.log(f"模式: {mode}")
        self.log(f"Boss箱: 前缀 {self.detect.boss_key_prefix}，排除 {self.detect.exclude_key_prefix}")
        self.log(f"轮换: {' → '.join(stages)}")
        if self._anchor:
            self.log(
                f"锚点: {self._anchor.width}x{self._anchor.height} "
                f"@ ({self._anchor.left},{self._anchor.top})"
            )
        if self.chest.enabled:
            self.log(
                f"开宝箱: 已启用 @ 窗口({self.chest.rel_x:.3f},{self.chest.rel_y:.3f})"
                + (f"，定时 {self.chest.interval_seconds}s" if self.chest.interval_seconds > 0 else "")
            )
        if self.normal_chest.enabled:
            self.log(
                f"普通宝箱: 每 {self.normal_chest.interval_seconds}s 开启 @ "
                f"窗口({self.normal_chest.rel_x:.3f},{self.normal_chest.rel_y:.3f})"
            )
        if self.stage_timeout_seconds > 0:
            self.log(f"超时切换: {int(self.stage_timeout_seconds // 60)} 分钟无 Boss 箱则切关")
        else:
            self.log("超时切换: 未启用")
        if self.warehouse_enabled:
            tab_count = len(self._profile.warehouse_tab_pages)
            self.log(f"自动存仓库: 已启用，{tab_count} 个标签页，"
                     f"每 {int(self.warehouse_interval_seconds // 60)} 分钟执行")
        else:
            self.log("自动存仓库: 未启用")
        if self.mailbox_check_enabled:
            self.log("超时先查邮箱: 已启用（超时后先检查邮箱再等待一轮）")
        else:
            self.log("超时先查邮箱: 未启用")
        fp_mode = "每次折叠" if self._fold_before_use() else "一直展开"
        self.log(f"页面折叠: {fp_mode}")
        self.log("=" * 40)

        self.stats.start_session()
        self.on_stats_update()

        hwnd = find_game_window(process_name=self.process_name, pid=self.pid)
        if not hwnd and not self._dry_run:
            self.log("[错误] 找不到 TaskBarHero 窗口")
            return

        rotator = None
        last_interval_chest = time.time()
        last_normal_chest = time.time()
        self._last_warehouse_at = time.time()

        if hwnd:
            rotator = build_rotator(
                self.cfg,
                hwnd=hwnd,
                anchor=self._anchor,
                profile=self._profile,
                helper_hwnd=self.helper_hwnd,
            )

            # 启动后立即导航到第一个关卡，而不是等掉箱后再切换
            if not self._dry_run:
                self._action_event.clear()
                try:
                    if self._fold_before_use():
                        self._fold_expand()
                        self._fold_click_portal_btn()
                        time.sleep(0.5)
                    first = rotator.stages[self._start_index]
                    self.log(f"[初始导航] -> {first.name} (索引 {self._start_index})")
                    rotator.navigator.open_portal_if_needed()
                    rotator.navigator.navigate_to_stage(first)
                    rotator.navigator.click_stage_node(first)
                    rotator._index = (self._start_index + 1) % len(rotator.stages)
                    self.stats.enter_stage(first.name)
                    self._stage_name = first.name
                    self._stage_entered_at = time.time()
                    self._mailbox_done = False
                    self._mailbox_pending = False
                    self.on_status(state="waiting", stage=first.name)
                    self.on_stats_update()
                    time.sleep(rotator.delay_after_switch)
                    if self._fold_before_use():
                        self._fold_collapse()
                finally:
                    self._action_event.set()

            self._rotator = rotator

        while not self._stop.is_set():
            # ── 定时开宝箱（Boss 宝箱） ──
            if (
                rotator
                and self.chest.enabled
                and self.chest.interval_seconds > 0
                and not self._dry_run
                and self._action_event.is_set()
                and time.time() - last_interval_chest >= self.chest.interval_seconds
            ):
                last_interval_chest = time.time()
                self._run_exclusive(
                    lambda: self._do_interval_chest(hwnd),
                    "定时开宝箱",
                )

            # ── 定时开宝箱（普通宝箱） ──
            if (
                hwnd
                and self.normal_chest.enabled
                and self.normal_chest.interval_seconds > 0
                and not self._dry_run
                and self._action_event.is_set()
                and time.time() - last_normal_chest >= self.normal_chest.interval_seconds
            ):
                self._run_exclusive(
                    lambda: self._do_normal_interval_chest(hwnd),
                    "定时普通宝箱",
                )
                last_normal_chest = time.time()

            # ── 掉箱检测 → 换关 ──
            for event in watcher.poll_raw():
                if event.item_key.startswith(self.detect.exclude_key_prefix):
                    tag = box_type_label(event.item_key)
                    self.on_drop(tag, event.item_key, False)
                    self.log(f"[掉落] {tag} x{event.count} ItemKey={event.item_key} (忽略)")
                    continue

                if not watcher.is_boss_box(event):
                    continue

                would = watcher.would_trigger(event)
                self.on_drop("Boss箱", event.item_key, would)
                self.log(f"[Boss箱] x{event.count} ItemKey={event.item_key}")

                if self._dry_run:
                    self.log("  (仅监控，不换图)")
                    continue

                if not watcher.should_trigger(event):
                    self.log("  (防抖跳过)")
                    continue

                self.stats.record_boss_drop()
                self.on_stats_update()
                self.on_status(state="detected", stage=self._stage_name)

                if not hwnd:
                    hwnd = find_game_window(process_name=self.process_name, pid=self.pid)
                    if not hwnd:
                        self.log("[错误] 找不到游戏窗口")
                        continue
                    rotator = build_rotator(
                        self.cfg,
                        hwnd=hwnd,
                        anchor=self._anchor,
                        profile=self._profile,
                        helper_hwnd=self.helper_hwnd,
                    )
                    self._rotator = rotator

                # _run_exclusive 内部会等待当前操作完成再执行
                target_ref = [None]

                def _do_switch() -> None:
                    if self._fold_before_use():
                        self._fold_expand()
                        self._fold_click_portal_btn()
                        time.sleep(0.5)
                    t = rotator.switch_to_next(reason=event)
                    target_ref[0] = t
                    if self._fold_before_use():
                        self._fold_collapse()

                self._run_exclusive(_do_switch, "掉箱换关")
                if target_ref[0] is not None:
                    target = target_ref[0]
                    self._stage_name = target.name
                    self._switch_count += 1
                    self.stats.enter_stage(target.name)
                    self._stage_entered_at = time.time()
                    self._mailbox_done = False
                    self._mailbox_pending = False
                    self.on_status(state="waiting", stage=target.name)
                    self.on_stats_update()
                    self.on_switch(target.name, self._switch_count)

            # ── 手动切关 ──
            if self._manual_switch.is_set():
                self._manual_switch.clear()
                if rotator and self._action_event.is_set():
                    self.log("[手动切关] 切换到下一关…")
                    self.on_status(state="switching", stage=self._stage_name, target="")
                    self._run_exclusive(self._do_manual_switch, "手动切关")
                    self.on_manual_switch_done()

            # ── 超时切关（两段式：先查邮箱 → 再等待一轮 → 再切） ──
            if (
                self.stage_timeout_seconds > 0
                and self._stage_entered_at > 0
                and rotator
                and not self._dry_run
                and self._action_event.is_set()
            ):
                elapsed = time.time() - self._stage_entered_at
                if elapsed >= self.stage_timeout_seconds:
                    if self.mailbox_check_enabled and not self._mailbox_done:
                        self.log(
                            f"[超时] 当前关卡已 {int(elapsed // 60)} 分钟无 Boss 箱，"
                            f"先检查邮箱…"
                        )
                        self._mailbox_pending = True
                    else:
                        reason = "邮箱已查仍无掉落" if self._mailbox_done else "超时"
                        self.log(
                            f"[超时切关] {reason}，"
                            f"超时设定 {int(self.stage_timeout_seconds // 60)} 分钟"
                        )
                        self._mailbox_done = False
                        self._stage_entered_at = time.time()
                        self.on_status(state="timeout_switch", stage=self._stage_name, target="")
                        self._run_exclusive(self._do_manual_switch, "超时切关")

            # ── 检查邮箱（超时触发，排队执行） ──
            if (
                self.mailbox_check_enabled
                and self._mailbox_pending
                and self._action_event.is_set()
                and not self._dry_run
            ):
                self._mailbox_pending = False
                self.on_status(state="mailbox", stage=self._stage_name)
                self._run_exclusive(self._perform_mailbox_check, "检查邮箱")
                self._stage_entered_at = time.time()
                self._mailbox_done = True
                self.on_status(state="waiting", stage=self._stage_name)

            # ── 定时存仓库 ──
            if (
                self.warehouse_enabled
                and self.warehouse_interval_seconds > 0
                and not self._dry_run
                and                 self._action_event.is_set()
                and time.time() - self._last_warehouse_at >= self.warehouse_interval_seconds
            ):
                self.on_status(state="warehouse", stage=self._stage_name)
                self._run_exclusive(self._perform_warehouse, "存仓库")
                self._last_warehouse_at = time.time()
                self.on_status(state="waiting", stage=self._stage_name)

            time.sleep(self.poll_interval)


    # ── 各操作的具体实现（由 _run_exclusive 调度） ──────────

    def _do_interval_chest(self, hwnd: int) -> None:
        """定时开 Boss 宝箱。"""
        pos = open_chest(hwnd, self.chest, helper_hwnd=self.helper_hwnd, anchor=self._anchor)
        if pos:
            self.log(f"[开宝箱] 定时双击 @ ({pos[0]},{pos[1]})")

    def _do_normal_interval_chest(self, hwnd: int) -> None:
        """定时开普通宝箱。"""
        pos = open_chest(hwnd, self.normal_chest, helper_hwnd=self.helper_hwnd, anchor=self._anchor)
        if pos:
            self.log(f"[普通宝箱] 定时双击 @ ({pos[0]},{pos[1]})")

    def _do_manual_switch(self) -> None:
        """手动/超时切关。"""
        rotator = self._rotator
        if not rotator:
            return
        if self._fold_before_use():
            self._fold_expand()
            self._fold_click_portal_btn()
            time.sleep(0.5)
        target = rotator.switch_to_next()
        if self._fold_before_use():
            self._fold_collapse()
        self._stage_name = target.name
        self._switch_count += 1
        self.stats.enter_stage(target.name)
        self._stage_entered_at = time.time()
        self._mailbox_done = False
        self._mailbox_pending = False
        self.on_status(state="waiting", stage=target.name)
        self.on_stats_update()
        self.on_switch(target.name, self._switch_count)

    def _perform_warehouse(self) -> None:
        """执行仓库存储：依次点击仓库标签页，再点击转移按钮。"""
        profile = self._profile
        if not profile or not self._anchor:
            self.log("[存仓库] 没有锚点或配置，跳过")
            return

        pages = profile.warehouse_tab_pages
        if not pages:
            self.log("[存仓库] 未配置仓库标签页，跳过")
            return

        btn = profile.warehouse_transfer_btn
        if not btn or len(btn) < 2:
            self.log("[存仓库] 未配置转移按钮，跳过")
            return

        if self._fold_before_use():
            self._fold_expand()
            self._fold_click_warehouse_btn()
            time.sleep(0.5)

        hwnd = find_game_window(process_name=self.process_name, pid=self.pid)
        if not hwnd:
            self.log("[存仓库] 找不到游戏窗口")
            return

        self.log(f"[存仓库] 开始执行（{len(pages)} 个标签页，每页依次点击标签 + 转移按钮）")

        bx, by = self._anchor.to_screen(float(btn[0]), float(btn[1]))

        for i, page in enumerate(pages):
            name = page.get("name", f"第{i + 1}页")
            rx = float(page.get("rel_x", 0.5))
            ry = float(page.get("rel_y", 0.5))
            sx, sy = self._anchor.to_screen(rx, ry)

            self.log(f"  [第 {i + 1} 页] 点击标签 {name} @ ({sx},{sy})")
            click_at(hwnd, sx, sy, helper_hwnd=self.helper_hwnd)
            time.sleep(0.5)

            self.log(f"  [第 {i + 1} 页] 点击转移按钮 @ ({bx},{by})")
            click_at(hwnd, bx, by, helper_hwnd=self.helper_hwnd)
            time.sleep(0.5)

        self.log("[存仓库] 完成")
        if self._fold_before_use():
            self._fold_collapse()

    def _perform_mailbox_check(self) -> None:
        """超时后检查邮箱：打开→等待→刷新→全部接收→关闭。"""
        profile = self._profile
        if not profile or not self._anchor:
            self.log("[检查邮箱] 没有锚点或配置，跳过")
            return

        buttons = profile.mailbox_buttons
        required = ("open", "refresh", "receive_all", "close")
        missing = [k for k in required if k not in buttons or len(buttons[k]) < 2]
        if missing:
            self.log(f"[检查邮箱] 缺少按钮标记: {', '.join(missing)}，跳过")
            return

        hwnd = find_game_window(process_name=self.process_name, pid=self.pid)
        if not hwnd:
            self.log("[检查邮箱] 找不到游戏窗口")
            return

        self.log("[检查邮箱] 开始执行：打开 → 等待12秒 → 刷新 → 全部接收 → 关闭")

        if self._fold_before_use():
            self._fold_expand()
            time.sleep(0.5)

        for step_key, step_label, wait_after in (
            ("open", "打开邮箱", 12.0),
            ("refresh", "刷新邮箱", 1.0),
            ("receive_all", "全部接收", 1.0),
            ("close", "关闭邮箱", 0.5),
        ):
            pos = buttons[step_key]
            sx, sy = self._anchor.to_screen(float(pos[0]), float(pos[1]))
            self.log(f"  [邮箱] {step_label} @ ({sx},{sy})")
            click_at(hwnd, sx, sy, helper_hwnd=self.helper_hwnd)
            if wait_after > 0:
                time.sleep(wait_after)

        self.log("[检查邮箱] 完成，重置超时计时等待掉落检测")
        if self._fold_before_use():
            self._fold_collapse()

    # ── 折叠页面辅助方法 ──────────────────────────────────

    def _fold_before_use(self) -> bool:
        return getattr(self, "fold_page_mode", "always_expand") == "fold_before_use"

    def _fold_expand(self) -> None:
        """展开主页面（点击折叠/展开按钮）。"""
        self._fold_click("fold_expand_btn", "展开按钮")
        # 展开后点一下确认按钮，消除可能弹出的服务器错误对话框
        self._fold_click_confirm_btn()

    def _fold_collapse(self) -> None:
        """折叠主页面（仅点击展开/折叠按钮）。"""
        self._fold_click("fold_expand_btn", "展开按钮")

    def _fold_click_portal_btn(self) -> None:
        self._fold_click("fold_portal_btn", "传送门按钮")

    def _fold_click_warehouse_btn(self) -> None:
        self._fold_click("fold_warehouse_btn", "仓库按钮")

    def _fold_click_confirm_btn(self) -> None:
        self._fold_click("fold_confirm_btn", "确认按钮")

    def _fold_click(self, attr: str, label: str) -> None:
        profile = self._profile
        if not profile or not self._anchor:
            return
        pos = getattr(profile, attr, None)
        if not pos or len(pos) < 2:
            self.log(f"[页面折叠] {label} 未标记，跳过")
            return
        hwnd = find_game_window(process_name=self.process_name, pid=self.pid)
        if not hwnd:
            return
        rx, ry = float(pos[0]), float(pos[1])
        sx, sy = self._anchor.to_screen(rx, ry)
        click_at(hwnd, sx, sy, helper_hwnd=self.helper_hwnd)


class _StreamCapture(io.TextIOBase):
    def __init__(self, log_fn: LogFn) -> None:
        self._log_fn = log_fn
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            line = line.strip()
            if line:
                self._log_fn(line)
        return len(s)

    def flush(self) -> None:
        if self._buf.strip():
            self._log_fn(self._buf.strip())
            self._buf = ""
