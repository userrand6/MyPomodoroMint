from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
import math
from typing import Callable


class PomodoroPhase(str, Enum):
    WORK = "work"
    BREAK = "breakTime"

    @property
    def display_name(self) -> str:
        return "Work" if self == PomodoroPhase.WORK else "Break"

    @property
    def next(self) -> PomodoroPhase:
        return PomodoroPhase.BREAK if self == PomodoroPhase.WORK else PomodoroPhase.WORK


class PomodoroStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    RINGING = "ringing"


@dataclass(frozen=True)
class HeatmapDay:
    date_key: str
    day: date
    minutes: int


class PomodoroTimer:
    DEFAULT_WORK_MINUTES = 25
    DEFAULT_BREAK_MINUTES = 5
    DEFAULT_TARGET_CYCLES = 4
    MIN_MINUTES = 1
    MAX_MINUTES = 180
    MIN_CYCLES = 1
    MAX_CYCLES = 20
    MAX_HISTORY_DAYS = 365

    def __init__(
        self,
        work_minutes: int = DEFAULT_WORK_MINUTES,
        break_minutes: int = DEFAULT_BREAK_MINUTES,
        target_cycles: int = DEFAULT_TARGET_CYCLES,
        daily_worked_seconds: dict[str, float] | None = None,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.work_minutes = self._clamp_minutes(work_minutes)
        self.break_minutes = self._clamp_minutes(break_minutes)
        self.target_cycles = self._clamp_cycles(target_cycles)
        self._now = now

        self.phase: PomodoroPhase = PomodoroPhase.WORK
        self.status: PomodoroStatus = PomodoroStatus.IDLE
        self.completed_cycles_in_set: int = 0
        self.completed_work_sessions: int = 0
        self.remaining_seconds: int = self.work_minutes * 60

        current = self._now()
        self.worked_date_key: str = self.date_key(current)
        self.daily_worked_seconds: dict[str, float] = {
            k: float(v) for k, v in (daily_worked_seconds or {}).items() if v > 0
        }
        self._prune_old_history(current.date())

        self._target_end_time: datetime | None = None
        self._last_work_accounted_time: datetime | None = None

    @property
    def current_cycle_number(self) -> int:
        return min(self.target_cycles, self.completed_cycles_in_set + 1)

    @property
    def worked_seconds_today(self) -> float:
        return self.daily_worked_seconds.get(self.worked_date_key, 0.0)

    @property
    def worked_minutes_today(self) -> int:
        return int(self.worked_seconds_today) // 60

    @property
    def configured_minutes_for_current_phase(self) -> int:
        return self.configured_minutes(self.phase)

    def configured_minutes(self, target_phase: PomodoroPhase) -> int:
        return self.work_minutes if target_phase == PomodoroPhase.WORK else self.break_minutes

    @property
    def formatted_remaining_time(self) -> str:
        return self.format_seconds(self.remaining_seconds)

    @staticmethod
    def format_seconds(total_seconds: int) -> str:
        clamped = max(0, int(total_seconds))
        minutes, seconds = divmod(clamped, 60)
        return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    def date_key(dt: datetime | date) -> str:
        if isinstance(dt, datetime):
            dt = dt.date()
        return dt.strftime("%Y-%m-%d")

    def start(self) -> None:
        self.sync_daily_date_if_needed()
        if self.status in (PomodoroStatus.IDLE, PomodoroStatus.PAUSED):
            duration = max(1, self.remaining_seconds)
            self.remaining_seconds = duration
            current = self._now()
            self._target_end_time = current + timedelta(seconds=duration)
            self._last_work_accounted_time = current if self.phase == PomodoroPhase.WORK else None
            self.status = PomodoroStatus.RUNNING

    def pause(self) -> None:
        if self.status != PomodoroStatus.RUNNING:
            return
        self._account_for_elapsed_work()
        self._sync_remaining_from_clock()
        self._target_end_time = None
        self._last_work_accounted_time = None
        if self.remaining_seconds > 0:
            self.status = PomodoroStatus.PAUSED
        else:
            self._finish_current_phase()

    def toggle_start_pause(self) -> None:
        if self.status in (PomodoroStatus.IDLE, PomodoroStatus.PAUSED):
            self.start()
        elif self.status == PomodoroStatus.RUNNING:
            self.pause()

    def reset(self) -> None:
        self._account_for_elapsed_work()
        self._target_end_time = None
        self._last_work_accounted_time = None
        self.status = PomodoroStatus.IDLE
        self.remaining_seconds = self.configured_minutes(self.phase) * 60

    def reset_cycle_progress(self) -> None:
        self.reset()
        self.completed_cycles_in_set = 0

    def skip_current_phase(self) -> None:
        self._account_for_elapsed_work()
        self._advance_to_next_phase()

    def acknowledge(self, auto_start_next: bool = False) -> bool:
        if self.status != PomodoroStatus.RINGING:
            return False
        self._advance_to_next_phase()
        if auto_start_next:
            self.start()
        return True

    def extend_current_cycle(self, minutes: int) -> None:
        if minutes <= 0:
            return
        if self.status == PomodoroStatus.RINGING:
            if self.phase == PomodoroPhase.WORK:
                self.completed_work_sessions = max(0, self.completed_work_sessions - 1)
            added_seconds = min(self.MAX_MINUTES * 60, minutes * 60)
            self.remaining_seconds = added_seconds
            current = self._now()
            self._target_end_time = current + timedelta(seconds=added_seconds)
            self._last_work_accounted_time = current if self.phase == PomodoroPhase.WORK else None
            self.status = PomodoroStatus.RUNNING
            return

        updated_seconds = min(self.MAX_MINUTES * 60, self.remaining_seconds + minutes * 60)
        applied_delta = updated_seconds - self.remaining_seconds
        self.remaining_seconds = updated_seconds
        if self.status == PomodoroStatus.RUNNING and self._target_end_time is not None:
            self._target_end_time = self._target_end_time + timedelta(seconds=applied_delta)

    def set_work_minutes(self, minutes: int) -> None:
        self.work_minutes = self._clamp_minutes(minutes)
        if self.status == PomodoroStatus.IDLE and self.phase == PomodoroPhase.WORK:
            self.remaining_seconds = self.work_minutes * 60

    def set_break_minutes(self, minutes: int) -> None:
        self.break_minutes = self._clamp_minutes(minutes)
        if self.status == PomodoroStatus.IDLE and self.phase == PomodoroPhase.BREAK:
            self.remaining_seconds = self.break_minutes * 60

    def set_target_cycles(self, cycles: int) -> None:
        self.target_cycles = self._clamp_cycles(cycles)
        if self.completed_cycles_in_set >= self.target_cycles:
            self.completed_cycles_in_set = 0

    def reset_durations_to_default(self) -> None:
        self.work_minutes = self.DEFAULT_WORK_MINUTES
        self.break_minutes = self.DEFAULT_BREAK_MINUTES
        self.target_cycles = self.DEFAULT_TARGET_CYCLES
        if self.completed_cycles_in_set >= self.target_cycles:
            self.completed_cycles_in_set = 0
        if self.status == PomodoroStatus.IDLE:
            self.remaining_seconds = self.configured_minutes(self.phase) * 60

    def reset_worked_today(self) -> None:
        current = self._now()
        self.worked_date_key = self.date_key(current)
        self.daily_worked_seconds.pop(self.worked_date_key, None)
        if self.status == PomodoroStatus.RUNNING and self.phase == PomodoroPhase.WORK:
            self._last_work_accounted_time = current

    def worked_minutes(self, date_key: str) -> int:
        return int(self.daily_worked_seconds.get(date_key, 0.0)) // 60

    def heatmap_grid(self, weeks: int = 19) -> list[list[HeatmapDay | None]]:
        clamped_weeks = max(1, weeks)
        today = self._now().date()
        # Python weekday(): Monday=0..Sunday=6. Convert to Sunday=0..Saturday=6.
        days_since_sunday = (today.weekday() + 1) % 7
        current_week_sunday = today - timedelta(days=days_since_sunday)
        first_week_sunday = current_week_sunday - timedelta(days=(clamped_weeks - 1) * 7)

        grid: list[list[HeatmapDay | None]] = []
        for week_idx in range(clamped_weeks):
            col: list[HeatmapDay | None] = []
            for day_idx in range(7):
                cell_date = first_week_sunday + timedelta(days=week_idx * 7 + day_idx)
                if cell_date > today:
                    col.append(None)
                else:
                    key = self.date_key(cell_date)
                    col.append(HeatmapDay(date_key=key, day=cell_date, minutes=self.worked_minutes(key)))
            grid.append(col)
        return grid

    def sync_daily_date_if_needed(self) -> bool:
        current = self._now()
        today_key = self.date_key(current)
        if today_key == self.worked_date_key:
            return False
        self.worked_date_key = today_key
        self._prune_old_history(current.date())
        return True

    def tick(self) -> bool:
        self.sync_daily_date_if_needed()
        if self.status != PomodoroStatus.RUNNING:
            return False
        self._account_for_elapsed_work()
        self._sync_remaining_from_clock()
        if self.remaining_seconds <= 0:
            self._finish_current_phase()
            return True
        return False

    def _advance_to_next_phase(self) -> None:
        finished = self.phase
        self.phase = finished.next
        if finished == PomodoroPhase.BREAK:
            self.completed_cycles_in_set += 1
            if self.completed_cycles_in_set >= self.target_cycles:
                self.completed_cycles_in_set = 0
        self._target_end_time = None
        self._last_work_accounted_time = None
        self.status = PomodoroStatus.IDLE
        self.remaining_seconds = self.configured_minutes(self.phase) * 60

    def _account_for_elapsed_work(self) -> None:
        if self.status != PomodoroStatus.RUNNING or self.phase != PomodoroPhase.WORK:
            return
        current = self._now()
        if self._last_work_accounted_time is None:
            self._last_work_accounted_time = current
            return
        elapsed = max(0.0, (current - self._last_work_accounted_time).total_seconds())
        if self._target_end_time is not None:
            max_accountable = max(0.0, (self._target_end_time - self._last_work_accounted_time).total_seconds())
        else:
            max_accountable = elapsed
        accountable = min(elapsed, max_accountable)
        if accountable > 0:
            self.daily_worked_seconds[self.worked_date_key] = (
                self.daily_worked_seconds.get(self.worked_date_key, 0.0) + accountable
            )
        self._last_work_accounted_time = current

    def _sync_remaining_from_clock(self) -> None:
        if self._target_end_time is None:
            return
        seconds_left = math.ceil((self._target_end_time - self._now()).total_seconds())
        self.remaining_seconds = max(0, seconds_left)

    def _finish_current_phase(self) -> None:
        self._target_end_time = None
        self._last_work_accounted_time = None
        self.remaining_seconds = 0
        self.status = PomodoroStatus.RINGING
        if self.phase == PomodoroPhase.WORK:
            self.completed_work_sessions += 1

    def _prune_old_history(self, reference_date: date) -> None:
        cutoff_key = self.date_key(reference_date - timedelta(days=self.MAX_HISTORY_DAYS))
        self.daily_worked_seconds = {
            k: v for k, v in self.daily_worked_seconds.items() if k >= cutoff_key and v > 0
        }

    @classmethod
    def _clamp_minutes(cls, value: int) -> int:
        return min(cls.MAX_MINUTES, max(cls.MIN_MINUTES, int(value)))

    @classmethod
    def _clamp_cycles(cls, value: int) -> int:
        return min(cls.MAX_CYCLES, max(cls.MIN_CYCLES, int(value)))
