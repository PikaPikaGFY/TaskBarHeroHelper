from __future__ import annotations

import time
from typing import Optional

from .anchor import AnchorRect
from .chest_open import ChestOpenConfig, open_chest
from .log_watcher import BoxDropEvent
from .portal import PortalNavigator, StageTarget


class MapRotator:
    def __init__(
        self,
        stages: list[StageTarget],
        navigator: PortalNavigator,
        *,
        hwnd: int,
        chest: ChestOpenConfig | None = None,
        helper_hwnd: int | None = None,
        delay_before_switch: float = 2.0,
        delay_after_switch: float = 3.0,
        min_switch_interval: float = 15.0,
        anchor: AnchorRect | None = None,
    ) -> None:
        if not stages:
            raise ValueError("至少配置一个轮换关卡")
        self.stages = stages
        self.navigator = navigator
        self.hwnd = hwnd
        self.helper_hwnd = helper_hwnd
        self.chest = chest or ChestOpenConfig()
        self.anchor = anchor
        self.delay_before_switch = delay_before_switch
        self.delay_after_switch = delay_after_switch
        self.min_switch_interval = min_switch_interval
        self._index = 0
        self._last_switch_at = 0.0
        self._current_stage: Optional[str] = None

    @property
    def current_stage(self) -> Optional[str]:
        return self._current_stage

    def open_chest_if_enabled(self) -> tuple[int, int] | None:
        if not self.chest.enabled:
            return None
        pos = open_chest(self.hwnd, self.chest, helper_hwnd=self.helper_hwnd, anchor=self.anchor)
        if pos:
            print(f"[开宝箱] 双击 @ ({pos[0]},{pos[1]})")
        return pos

    def switch_to_next(self, reason: Optional[BoxDropEvent] = None) -> StageTarget:
        now = time.time()
        elapsed = now - self._last_switch_at
        if elapsed < self.min_switch_interval:
            wait = self.min_switch_interval - elapsed
            print(f"[等待] 距上次换图仅 {elapsed:.1f}s，再等 {wait:.1f}s")
            time.sleep(wait)

        if self.delay_before_switch > 0:
            time.sleep(self.delay_before_switch)

        self.open_chest_if_enabled()

        target = self.stages[self._index]
        self._index = (self._index + 1) % len(self.stages)

        key_info = f" ItemKey={reason.item_key}" if reason else ""
        scroll = target.resolved_scroll_page()
        view = "1-7视图(向下滚到底)" if scroll == 0 else "8-10视图(向上滚到底)"
        print(
            f"[换图] 检测到Boss箱{key_info} -> {target.name} "
            f"(第{target.chapter}章 / {target.difficulty} / 节点{target.stage_num} / {view})"
        )

        self.navigator.open_portal_if_needed()
        self.navigator.navigate_to_stage(target)
        self.navigator.click_stage_node(target)

        if self.delay_after_switch > 0:
            time.sleep(self.delay_after_switch)

        self._last_switch_at = time.time()
        self._current_stage = target.name
        return target
