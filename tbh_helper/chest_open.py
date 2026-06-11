from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .anchor import AnchorRect
from .mouse import double_click_at
from .window import get_client_rect_screen


@dataclass
class ChestOpenConfig:
    enabled: bool = False
    rel_x: float = 0.5
    rel_y: float = 0.2
    delay_before: float = 0.3
    delay_after: float = 0.5
    interval_seconds: float = 0.0
    click_interval: float = 0.12
    click_method: str = "auto"
    focus_delay: float = 0.2
    move_delay: float = 0.08
    click_hold: float = 0.05

    @classmethod
    def from_dict(cls, data: dict | None) -> ChestOpenConfig:
        data = data or {}
        pos = data.get("rel", data.get("position", [0.5, 0.2]))
        return cls(
            enabled=bool(data.get("enabled", False)),
            rel_x=float(pos[0]) if pos else 0.5,
            rel_y=float(pos[1]) if pos else 0.2,
            delay_before=float(data.get("delay_before", 0.3)),
            delay_after=float(data.get("delay_after", 0.5)),
            interval_seconds=float(data.get("interval_seconds", 0)),
            click_interval=float(data.get("click_interval", 0.12)),
            click_method=str(data.get("click_method", "auto")),
            focus_delay=float(data.get("focus_delay", 0.2)),
            move_delay=float(data.get("move_delay", 0.08)),
            click_hold=float(data.get("click_hold", 0.05)),
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "rel": [round(self.rel_x, 4), round(self.rel_y, 4)],
            "delay_before": self.delay_before,
            "delay_after": self.delay_after,
            "interval_seconds": self.interval_seconds,
            "click_interval": self.click_interval,
            "click_method": self.click_method,
            "focus_delay": self.focus_delay,
            "move_delay": self.move_delay,
            "click_hold": self.click_hold,
        }


def _click_kwargs(config: ChestOpenConfig, helper_hwnd: int | None) -> dict:
    return {
        "helper_hwnd": helper_hwnd,
        "method": config.click_method,  # type: ignore[arg-type]
        "focus_delay": config.focus_delay,
        "move_delay": config.move_delay,
        "click_hold": config.click_hold,
        "click_interval": config.click_interval,
    }


def double_click_window_rel(
    hwnd: int,
    rel_x: float,
    rel_y: float,
    *,
    config: ChestOpenConfig | None = None,
    helper_hwnd: int | None = None,
    click_interval: float | None = None,
    anchor: AnchorRect | None = None,
) -> tuple[int, int]:
    cfg = config or ChestOpenConfig()
    if anchor is not None:
        x, y = anchor.to_screen(rel_x, rel_y)
    else:
        rect = get_client_rect_screen(hwnd)
        x, y = rect.to_screen(rel_x, rel_y)
    kwargs = _click_kwargs(cfg, helper_hwnd)
    if click_interval is not None:
        kwargs["click_interval"] = click_interval
    double_click_at(hwnd, x, y, **kwargs)
    return x, y


def open_chest(
    hwnd: int,
    config: ChestOpenConfig,
    *,
    helper_hwnd: int | None = None,
    anchor: AnchorRect | None = None,
) -> tuple[int, int] | None:
    if not config.enabled:
        return None
    if config.delay_before > 0:
        time.sleep(config.delay_before)
    pos = double_click_window_rel(
        hwnd,
        config.rel_x,
        config.rel_y,
        config=config,
        helper_hwnd=helper_hwnd,
        anchor=anchor,
    )
    if config.delay_after > 0:
        time.sleep(config.delay_after)
    return pos
