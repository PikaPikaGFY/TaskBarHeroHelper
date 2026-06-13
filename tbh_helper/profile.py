from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from PIL import ImageGrab

from .anchor import AnchorRect
from .portal import PortalUIConfig, StageTarget


@dataclass
class PortalProfile:
    """锚点框内的相对坐标配置（与窗口位置无关）。"""

    template_path: str | None = None
    chapter_tabs: dict[int, tuple[float, float]] = field(default_factory=dict)
    difficulty_dropdown: tuple[float, float] = (0.5, 0.15)
    difficulty_options: dict[str, tuple[float, float]] = field(default_factory=dict)
    map_scroll_area: tuple[float, float] = (0.5, 0.55)
    scroll_clicks_down_to_1_7: int = 5
    scroll_clicks_up_to_8_10: int = 5
    scroll_method: str = "sendinput"
    scroll_interval: float = 0.06
    action_delay: float = 0.35
    stages: list[dict[str, Any]] = field(default_factory=list)
    chest_open: dict[str, Any] = field(default_factory=dict)
    normal_chest: dict[str, Any] = field(default_factory=dict)
    warehouse_tab_pages: list[dict[str, Any]] = field(default_factory=list)
    warehouse_transfer_btn: list[float] | None = None
    mailbox_buttons: dict[str, list[float]] = field(default_factory=dict)
    fold_expand_btn: list[float] | None = None
    fold_portal_btn: list[float] | None = None
    fold_warehouse_btn: list[float] | None = None
    fold_confirm_btn: list[float] | None = None

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": 1,
            "template": self.template_path,
            "ui": {
                "chapter_tabs": {str(k): list(v) for k, v in self.chapter_tabs.items()},
                "difficulty_dropdown": list(self.difficulty_dropdown),
                "difficulty_options": {k: list(v) for k, v in self.difficulty_options.items()},
                "map_scroll_area": list(self.map_scroll_area),
                "scroll_clicks_down_to_1_7": self.scroll_clicks_down_to_1_7,
                "scroll_clicks_up_to_8_10": self.scroll_clicks_up_to_8_10,
                "scroll_method": self.scroll_method,
                "scroll_interval": self.scroll_interval,
                "action_delay": self.action_delay,
            },
            "stages": self.stages,
            "chest_open": self.chest_open,
            "normal_chest": self.normal_chest,
            "warehouse_tab_pages": self.warehouse_tab_pages,
            "warehouse_transfer_btn": self.warehouse_transfer_btn,
            "mailbox_buttons": self.mailbox_buttons,
            "fold_expand_btn": self.fold_expand_btn,
            "fold_portal_btn": self.fold_portal_btn,
            "fold_warehouse_btn": self.fold_warehouse_btn,
            "fold_confirm_btn": self.fold_confirm_btn,
        }
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    @classmethod
    def load_or_create(cls, path: Path) -> PortalProfile:
        if path.exists():
            return cls.load(path)
        return cls(stages=[])

    def add_stage(
        self,
        *,
        name: str,
        chapter: int,
        difficulty: str,
        stage_num: int,
        rel_x: float,
        rel_y: float,
        scroll_page: int | None = None,
    ) -> dict[str, Any]:
        stage: dict[str, Any] = {
            "name": name,
            "chapter": chapter,
            "difficulty": difficulty,
            "stage_num": stage_num,
            "rel_x": rel_x,
            "rel_y": rel_y,
        }
        if scroll_page is not None:
            stage["scroll_page"] = scroll_page
        self.stages.append(stage)
        return stage

    @staticmethod
    def default_name(chapter: int, difficulty: str, stage_num: int) -> str:
        labels = {"normal": "普通", "nightmare": "噩梦", "hell": "地狱", "torment": "折磨"}
        diff_label = labels.get(difficulty, difficulty)
        return f"{diff_label} {chapter}-{stage_num}"

    @classmethod
    def load(cls, path: Path) -> PortalProfile:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        ui = data.get("ui", {})
        tabs = {int(k): (float(v[0]), float(v[1])) for k, v in ui.get("chapter_tabs", {}).items()}
        diff_opts = {
            str(k): (float(v[0]), float(v[1]))
            for k, v in ui.get("difficulty_options", {}).items()
        }
        dd = ui.get("difficulty_dropdown", [0.5, 0.15])
        sa = ui.get("map_scroll_area", [0.5, 0.55])
        return cls(
            template_path=data.get("template"),
            chapter_tabs=tabs,
            difficulty_dropdown=(float(dd[0]), float(dd[1])),
            difficulty_options=diff_opts,
            map_scroll_area=(float(sa[0]), float(sa[1])),
            scroll_clicks_down_to_1_7=int(ui.get("scroll_clicks_down_to_1_7", 5)),
            scroll_clicks_up_to_8_10=int(ui.get("scroll_clicks_up_to_8_10", 5)),
            scroll_method=str(ui.get("scroll_method", "sendinput")),
            scroll_interval=float(ui.get("scroll_interval", 0.06)),
            action_delay=float(ui.get("action_delay", 0.35)),
            stages=list(data.get("stages", [])),
            chest_open=dict(data.get("chest_open", {})),
            normal_chest=dict(data.get("normal_chest", {})),
            warehouse_tab_pages=list(data.get("warehouse_tab_pages", [])),
            warehouse_transfer_btn=data.get("warehouse_transfer_btn"),
            mailbox_buttons=dict(data.get("mailbox_buttons", {})),
            fold_expand_btn=data.get("fold_expand_btn"),
            fold_portal_btn=data.get("fold_portal_btn"),
            fold_warehouse_btn=data.get("fold_warehouse_btn"),
            fold_confirm_btn=data.get("fold_confirm_btn"),
        )

    def capture_template(self, anchor: AnchorRect, save_path: Path) -> str:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        img = ImageGrab.grab(bbox=(anchor.left, anchor.top, anchor.right, anchor.bottom))
        img.save(save_path)
        rel = save_path.as_posix()
        self.template_path = rel
        return rel

    def to_portal_ui(self) -> PortalUIConfig:
        return PortalUIConfig(
            chapter_tabs=dict(self.chapter_tabs),
            difficulty_dropdown=self.difficulty_dropdown,
            difficulty_options=dict(self.difficulty_options),
            map_scroll_area=self.map_scroll_area,
            scroll_clicks_down_to_1_7=self.scroll_clicks_down_to_1_7,
            scroll_clicks_up_to_8_10=self.scroll_clicks_up_to_8_10,
            scroll_method=self.scroll_method,
            scroll_interval=self.scroll_interval,
            action_delay=self.action_delay,
        )

    def to_stage_targets(self) -> list[StageTarget]:
        targets: list[StageTarget] = []
        for s in self.stages:
            scroll_page = s.get("scroll_page")
            targets.append(
                StageTarget(
                    name=str(s["name"]),
                    chapter=int(s["chapter"]),
                    difficulty=s["difficulty"],
                    stage_num=int(s["stage_num"]),
                    rel_x=float(s["rel_x"]),
                    rel_y=float(s["rel_y"]),
                    scroll_page=int(scroll_page) if scroll_page is not None else None,
                )
            )
        return targets


def default_stage_defs() -> list[dict[str, Any]]:
    return [
        {"name": "普通 1-1", "chapter": 1, "difficulty": "normal", "stage_num": 1},
        {"name": "普通 1-4", "chapter": 1, "difficulty": "normal", "stage_num": 4},
        {"name": "普通 1-8", "chapter": 1, "difficulty": "normal", "stage_num": 8},
        {"name": "普通 2-3", "chapter": 2, "difficulty": "normal", "stage_num": 3},
        {"name": "普通 2-8", "chapter": 2, "difficulty": "normal", "stage_num": 8},
        {"name": "普通 3-8", "chapter": 3, "difficulty": "normal", "stage_num": 8},
        {"name": "噩梦 1-9", "chapter": 1, "difficulty": "nightmare", "stage_num": 9},
    ]


def mark_point_in_anchor(anchor: AnchorRect, label: str) -> tuple[float, float]:
    input(f"  将鼠标移到【{label}】后按 Enter…")
    import pyautogui

    mx, my = pyautogui.position()
    if not anchor.contains_screen(mx, my):
        print(f"  ⚠ 鼠标 ({mx},{my}) 不在框选区域内，仍继续记录")
    rel_x = round((mx - anchor.left) / anchor.width, 4)
    rel_y = round((my - anchor.top) / anchor.height, 4)
    print(f"     -> 框内相对坐标 ({rel_x}, {rel_y})")
    return rel_x, rel_y
