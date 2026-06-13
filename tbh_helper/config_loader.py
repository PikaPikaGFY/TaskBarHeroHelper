from __future__ import annotations

from pathlib import Path

import yaml

from tbh_helper.anchor import AnchorRect
from tbh_helper.chest_open import ChestOpenConfig
from tbh_helper.portal import PortalNavigator, PortalUIConfig, StageTarget
from tbh_helper.profile import PortalProfile
from tbh_helper.rotator import MapRotator
from tbh_helper.window import WindowRect, get_client_rect_screen


def load_config(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def save_config(path: Path, cfg: dict) -> None:
    with path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)


def profile_path_from_cfg(cfg: dict, base_dir: Path) -> Path:
    portal = cfg.get("portal", {})
    rel = portal.get("profile", "profiles/portal_profile.yaml")
    path = Path(rel)
    if not path.is_absolute():
        path = base_dir / path
    return path


def build_portal_ui(portal_cfg: dict) -> PortalUIConfig:
    ui = portal_cfg.get("ui", {})
    tabs_raw = ui.get("chapter_tabs", {})
    chapter_tabs = {int(k): (float(v[0]), float(v[1])) for k, v in tabs_raw.items()}

    diff_dropdown = ui.get("difficulty_dropdown", [0.5, 0.15])
    diff_opts_raw = ui.get("difficulty_options", {})
    difficulty_options = {
        str(k): (float(v[0]), float(v[1])) for k, v in diff_opts_raw.items()
    }

    scroll_area = ui.get("map_scroll_area", [0.5, 0.55])

    down_to_1_7 = ui.get("scroll_clicks_down_to_1_7")
    if down_to_1_7 is None:
        down_to_1_7 = ui.get("scroll_clicks_page2", 5)

    up_to_8_10 = ui.get("scroll_clicks_up_to_8_10")
    if up_to_8_10 is None:
        up_to_8_10 = ui.get("scroll_clicks_reset", 5)

    return PortalUIConfig(
        chapter_tabs=chapter_tabs,
        difficulty_dropdown=(float(diff_dropdown[0]), float(diff_dropdown[1])),
        difficulty_options=difficulty_options,
        map_scroll_area=(float(scroll_area[0]), float(scroll_area[1])),
        scroll_clicks_down_to_1_7=int(down_to_1_7),
        scroll_clicks_up_to_8_10=int(up_to_8_10),
        scroll_method=str(ui.get("scroll_method", "sendinput")),
        scroll_interval=float(ui.get("scroll_interval", 0.06)),
        action_delay=float(ui.get("action_delay", 0.35)),
        click_method=str(ui.get("click_method", "auto")),
        focus_delay=float(ui.get("focus_delay", 0.2)),
        move_delay=float(ui.get("move_delay", 0.08)),
        click_hold=float(ui.get("click_hold", 0.05)),
    )


def build_stage_targets(stages_cfg: list[dict]) -> list[StageTarget]:
    targets: list[StageTarget] = []
    for s in stages_cfg:
        scroll_page = s.get("scroll_page")
        targets.append(
            StageTarget(
                name=str(s["name"]),
                chapter=int(s["chapter"]),
                difficulty=s["difficulty"],
                stage_num=int(s["stage_num"]),
                rel_x=float(s.get("rel_x", 0.5)),
                rel_y=float(s.get("rel_y", 0.5)),
                scroll_page=int(scroll_page) if scroll_page is not None else None,
            )
        )
    return targets


def build_rotator(
    cfg: dict,
    *,
    hwnd: int,
    anchor: AnchorRect | None = None,
    profile: PortalProfile | None = None,
    helper_hwnd: int | None = None,
) -> MapRotator:
    portal = cfg.get("portal", {})
    rotation = cfg.get("rotation", {})
    button_rel = portal.get("button_rel", [0.52, 0.92])
    window_rect = get_client_rect_screen(hwnd)

    # 使用锚点 + profile 模式
    ui = profile.to_portal_ui()
    stages = profile.to_stage_targets()
    coord_space = anchor

    navigator = PortalNavigator(
        ui,
        coord_space,
        hwnd=hwnd,
        open_portal=bool(portal.get("open_before_switch", False)),
        portal_button_rel=(float(button_rel[0]), float(button_rel[1])),
        portal_button_space=window_rect,
        helper_hwnd=helper_hwnd,
    )
    return MapRotator(
        stages,
        navigator,
        hwnd=hwnd,
        helper_hwnd=helper_hwnd,
        chest=ChestOpenConfig.from_dict(
            profile.chest_open if (profile and profile.chest_open) else cfg.get("chest_open")
        ),
        delay_before_switch=float(rotation.get("delay_before_switch", 2.0)),
        delay_after_switch=float(rotation.get("delay_after_switch", 3.0)),
        min_switch_interval=float(rotation.get("min_switch_interval", 15.0)),
        anchor=anchor,
    )
