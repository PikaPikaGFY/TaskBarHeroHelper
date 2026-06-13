"""挂机统计：每关卡平均出箱用时 + 轮换间隔。"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class StageRecord:
    """单关卡统计。"""

    name: str = ""
    visits: int = 0           # 游玩次数（导航到此关的次数）
    boss_drops: int = 0       # Boss 箱掉落次数
    boss_time_sum: float = 0.0   # 从进关到出 Boss 箱的累计秒数（跨多次访问累加）
    accumulated_wait: float = 0.0  # 被切关/跳过关卡时积累的等待时间
    cycle_sum: float = 0.0       # 两次轮回到同一关的累计间隔秒数
    last_visit_at: float = 0.0   # 上次进入该关的时间戳

    @property
    def avg_boss_time(self) -> float:
        """平均出箱用时（秒）。"""
        if self.boss_drops == 0:
            return 0.0
        return self.boss_time_sum / self.boss_drops

    @property
    def avg_cycle_interval(self) -> float:
        """平均轮换间隔（秒）—— 打完一轮再回到这关的时间。"""
        if self.visits < 2:
            return 0.0
        return self.cycle_sum / (self.visits - 1)


@dataclass
class SessionSummary:
    """会话级汇总。"""

    total_visits: int = 0
    total_boss_drops: int = 0
    total_seconds: float = 0.0
    started_at: float = 0.0

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at == 0:
            return 0.0
        return time.time() - self.started_at

    @property
    def avg_boss_time(self) -> float:
        if self.total_boss_drops == 0:
            return 0.0
        return 0.0  # 汇总级不提供全局平均出箱用时


class StatisticsTracker:
    """线程安全统计追踪器。

    调用时机：
    - enter_stage(name)    —— 引擎导航到新关卡
    - record_boss_drop()   —— 检测到 Boss 箱
    - exit_stage()         —— 引擎停止时结算
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, StageRecord] = {}
        self._current_stage: str = ""
        self._current_entered_at: float = 0.0
        self.summary = SessionSummary()

    # ── 写入 ──────────────────────────────────────────────

    def reset(self) -> None:
        """重置所有统计数据。"""
        with self._lock:
            self._records.clear()
            self._current_stage = ""
            self._current_entered_at = 0.0
            self.summary = SessionSummary()

    def start_session(self) -> None:
        with self._lock:
            self.summary.started_at = time.time()

    def enter_stage(self, name: str) -> None:
        """引擎导航到目标关卡时调用。"""
        now = time.time()
        with self._lock:
            # 结算上一关耗时
            if self._current_stage and self._current_entered_at:
                elapsed = now - self._current_entered_at
                rec = self._records.get(self._current_stage)
                if rec:
                    # 上一关没有掉 Boss 箱，把等待时间累计到 accumulated_wait 中
                    rec.accumulated_wait += elapsed
                    rec.total_seconds = getattr(rec, "total_seconds", 0) + elapsed
                self.summary.total_seconds += elapsed

            self._current_stage = name
            self._current_entered_at = now

            rec = self._records.setdefault(name, StageRecord(name=name))
            if rec.last_visit_at > 0:
                rec.cycle_sum += now - rec.last_visit_at
            rec.last_visit_at = now
            rec.visits += 1
            self.summary.total_visits += 1

    def record_boss_drop(self) -> None:
        """检测到 Boss 箱掉落时调用。"""
        now = time.time()
        with self._lock:
            if self._current_stage:
                rec = self._records.setdefault(
                    self._current_stage, StageRecord(name=self._current_stage)
                )
                rec.boss_drops += 1
                if self._current_entered_at:
                    # 把之前多次访问积累的等待时间 + 本次进关到出箱的时间 都算进去
                    total = rec.accumulated_wait + (now - self._current_entered_at)
                    rec.boss_time_sum += total
                    rec.accumulated_wait = 0.0  # 清零，下次重新积累
                self.summary.total_boss_drops += 1

    def exit_stage(self) -> None:
        now = time.time()
        with self._lock:
            if self._current_stage and self._current_entered_at:
                elapsed = now - self._current_entered_at
                rec = self._records.get(self._current_stage)
                if rec:
                    rec.accumulated_wait += elapsed
                    rec.total_seconds = getattr(rec, "total_seconds", 0) + elapsed
                self.summary.total_seconds += elapsed
            self._current_stage = ""
            self._current_entered_at = 0.0

    # ── 读取 ──────────────────────────────────────────────

    def snapshot(self) -> list[StageRecord]:
        """返回各关卡统计快照（按游玩次数降序）。"""
        with self._lock:
            records = list(self._records.values())
            records.sort(key=lambda r: r.visits, reverse=True)
            return records

    def snapshot_summary(self) -> SessionSummary:
        with self._lock:
            extra = (
                time.time() - self._current_entered_at
                if self._current_stage and self._current_entered_at
                else 0
            )
            return SessionSummary(
                total_visits=self.summary.total_visits,
                total_boss_drops=self.summary.total_boss_drops,
                total_seconds=self.summary.total_seconds + extra,
                started_at=self.summary.started_at,
            )
