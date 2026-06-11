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
    ) -> None:
        self.cfg = cfg
        self.base_dir = base_dir
        self.on_log = on_log or (lambda msg: None)
        self.on_switch = on_switch or (lambda _name, _n: None)
        self.on_drop = on_drop or (lambda _tag, _key, _trigger: None)
        self.on_stats_update = on_stats_update or (lambda: None)

        game_cfg = cfg.get("game", {})
        self.process_name = game_cfg.get("process_name", "TaskBarHero")
        self.pid = game_cfg.get("pid")
        self.log_path = Path(expand_path(cfg.get("log", {}).get("path", "")))
        self.detect = DetectConfig.from_dict(cfg.get("log", {}), cfg.get("detect"))
        self.chest = ChestOpenConfig()
        self.normal_chest = ChestOpenConfig()
        self.stats = StatisticsTracker()
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

    def start(self, *, dry_run: bool = False) -> None:
        if self._running:
            self.log("已在运行中")
            return

        if bool(self.cfg.get("portal", {}).get("use_anchor", True)) and self._anchor is None:
            raise RuntimeError("请先框选传送门区域")

        self._profile = self.load_profile()

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
                first = rotator.stages[0]
                self.log(f"[初始导航] -> {first.name}")
                rotator.navigator.open_portal_if_needed()
                rotator.navigator.navigate_to_stage(first)
                rotator.navigator.click_stage_node(first)
                rotator._index = 1  # 已进入第一关，下次掉箱后切换到第二关
                self.stats.enter_stage(first.name)
                self.on_stats_update()
                time.sleep(rotator.delay_after_switch)

            self._rotator = rotator

        while not self._stop.is_set():
            if (
                rotator
                and self.chest.enabled
                and self.chest.interval_seconds > 0
                and not self._dry_run
                and time.time() - last_interval_chest >= self.chest.interval_seconds
            ):
                pos = open_chest(hwnd, self.chest, helper_hwnd=self.helper_hwnd, anchor=self._anchor)
                if pos:
                    self.log(f"[开宝箱] 定时双击 @ ({pos[0]},{pos[1]})")
                last_interval_chest = time.time()

            if (
                hwnd
                and self.normal_chest.enabled
                and self.normal_chest.interval_seconds > 0
                and not self._dry_run
                and time.time() - last_normal_chest >= self.normal_chest.interval_seconds
            ):
                pos = open_chest(hwnd, self.normal_chest, helper_hwnd=self.helper_hwnd, anchor=self._anchor)
                if pos:
                    self.log(f"[普通宝箱] 定时双击 @ ({pos[0]},{pos[1]})")
                last_normal_chest = time.time()

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

                target = rotator.switch_to_next(reason=event)
                self._switch_count += 1
                self.stats.enter_stage(target.name)
                self.on_stats_update()
                self.on_switch(target.name, self._switch_count)

            # 手动切关请求（点击「下一关」按钮）
            if self._manual_switch.is_set():
                self._manual_switch.clear()
                if rotator:
                    self.log("[手动切关] 切换到下一关…")
                    try:
                        target = rotator.switch_to_next()
                        self._switch_count += 1
                        self.stats.enter_stage(target.name)
                        self.on_stats_update()
                        self.on_switch(target.name, self._switch_count)
                    except Exception as exc:
                        self.log(f"[手动切关] 失败: {exc}")

            time.sleep(self.poll_interval)


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
