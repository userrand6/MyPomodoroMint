from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from mypomodoro_mint.autostart import AutostartManager
from mypomodoro_mint.storage import AppSettings, SettingsStore
from mypomodoro_mint.timer import PomodoroPhase, PomodoroStatus, PomodoroTimer


class PomodoroTimerTests(unittest.TestCase):
    def test_initial_defaults(self) -> None:
        timer = PomodoroTimer()
        self.assertEqual(timer.phase, PomodoroPhase.WORK)
        self.assertEqual(timer.status, PomodoroStatus.IDLE)
        self.assertEqual(timer.work_minutes, 25)
        self.assertEqual(timer.break_minutes, 5)
        self.assertEqual(timer.target_cycles, 4)
        self.assertEqual(timer.current_cycle_number, 1)
        self.assertEqual(timer.remaining_seconds, 25 * 60)
        self.assertEqual(timer.formatted_remaining_time, "25:00")
        self.assertEqual(timer.completed_work_sessions, 0)
        self.assertEqual(timer.worked_minutes_today, 0)

    def test_countdown_transitions_to_ringing_and_increments_sessions(self) -> None:
        now = [datetime(2026, 11, 16, 10, 0, 0)]
        timer = PomodoroTimer(work_minutes=1, break_minutes=5, now=lambda: now[0])

        timer.start()
        self.assertEqual(timer.status, PomodoroStatus.RUNNING)
        self.assertEqual(timer.remaining_seconds, 60)

        now[0] += timedelta(seconds=25)
        self.assertFalse(timer.tick())
        self.assertEqual(timer.remaining_seconds, 35)
        self.assertEqual(timer.formatted_remaining_time, "00:35")

        now[0] += timedelta(seconds=35)
        self.assertTrue(timer.tick())
        self.assertEqual(timer.status, PomodoroStatus.RINGING)
        self.assertEqual(timer.remaining_seconds, 0)
        self.assertEqual(timer.completed_work_sessions, 1)
        self.assertEqual(timer.worked_minutes_today, 1)

        self.assertFalse(timer.tick())
        self.assertEqual(timer.status, PomodoroStatus.RINGING)

    def test_start_ignored_until_acknowledged(self) -> None:
        now = [datetime(2026, 11, 16, 10, 0, 0)]
        timer = PomodoroTimer(work_minutes=1, break_minutes=2, now=lambda: now[0])

        timer.start()
        now[0] += timedelta(seconds=60)
        self.assertTrue(timer.tick())
        self.assertEqual(timer.status, PomodoroStatus.RINGING)

        timer.start()
        self.assertEqual(timer.status, PomodoroStatus.RINGING)

        self.assertTrue(timer.acknowledge())
        self.assertEqual(timer.status, PomodoroStatus.IDLE)
        self.assertEqual(timer.phase, PomodoroPhase.BREAK)
        self.assertEqual(timer.remaining_seconds, 120)

    def test_acknowledge_auto_start_next(self) -> None:
        now = [datetime(2026, 11, 16, 10, 0, 0)]
        timer = PomodoroTimer(work_minutes=1, break_minutes=3, now=lambda: now[0])

        timer.start()
        now[0] += timedelta(seconds=60)
        timer.tick()

        self.assertTrue(timer.acknowledge(auto_start_next=True))
        self.assertEqual(timer.phase, PomodoroPhase.BREAK)
        self.assertEqual(timer.status, PomodoroStatus.RUNNING)
        self.assertEqual(timer.remaining_seconds, 180)

    def test_cycle_count_progresses_and_wraps(self) -> None:
        now = [datetime(2026, 11, 16, 10, 0, 0)]
        timer = PomodoroTimer(work_minutes=1, break_minutes=1, target_cycles=2, now=lambda: now[0])
        self.assertEqual(timer.current_cycle_number, 1)

        for expected_cycle, phase in (
            (1, PomodoroPhase.WORK),
            (1, PomodoroPhase.BREAK),
            (2, PomodoroPhase.WORK),
            (2, PomodoroPhase.BREAK),
        ):
            self.assertEqual(timer.current_cycle_number, expected_cycle)
            self.assertEqual(timer.phase, phase)
            timer.start()
            now[0] += timedelta(seconds=60)
            self.assertTrue(timer.tick())
            self.assertTrue(timer.acknowledge())

        self.assertEqual(timer.phase, PomodoroPhase.WORK)
        self.assertEqual(timer.current_cycle_number, 1)

    def test_extend_current_cycle_and_ringing_resume(self) -> None:
        now = [datetime(2026, 11, 16, 10, 0, 0)]
        timer = PomodoroTimer(work_minutes=1, break_minutes=1, now=lambda: now[0])

        timer.extend_current_cycle(1)
        self.assertEqual(timer.work_minutes, 1)
        self.assertEqual(timer.remaining_seconds, 120)

        timer.start()
        now[0] += timedelta(seconds=120)
        self.assertTrue(timer.tick())
        self.assertEqual(timer.status, PomodoroStatus.RINGING)
        self.assertEqual(timer.completed_work_sessions, 1)

        timer.extend_current_cycle(5)
        self.assertEqual(timer.status, PomodoroStatus.RUNNING)
        self.assertEqual(timer.phase, PomodoroPhase.WORK)
        self.assertEqual(timer.remaining_seconds, 300)
        self.assertEqual(timer.completed_work_sessions, 0)

        now[0] += timedelta(seconds=300)
        self.assertTrue(timer.tick())
        self.assertEqual(timer.completed_work_sessions, 1)
        self.assertEqual(timer.worked_minutes_today, 7)

    def test_skip_and_worked_minutes_rollover_and_heatmap(self) -> None:
        now = [datetime(2026, 11, 16, 12, 0, 0)]  # Monday
        timer = PomodoroTimer(
            work_minutes=10,
            break_minutes=5,
            target_cycles=2,
            daily_worked_seconds={"2026-11-15": 45 * 60, "2020-01-01": 60 * 60},
            now=lambda: now[0],
        )
        self.assertNotIn("2020-01-01", timer.daily_worked_seconds)

        timer.start()
        now[0] += timedelta(seconds=120)
        timer.skip_current_phase()
        self.assertEqual(timer.phase, PomodoroPhase.BREAK)
        self.assertEqual(timer.worked_minutes_today, 2)

        grid = timer.heatmap_grid(weeks=4)
        self.assertEqual(len(grid), 4)
        self.assertTrue(all(len(col) == 7 for col in grid))
        self.assertEqual(grid[3][0].minutes, 45)
        self.assertEqual(grid[3][1].minutes, 2)
        self.assertIsNone(grid[3][2])

        now[0] += timedelta(days=1)
        self.assertTrue(timer.sync_daily_date_if_needed())
        self.assertEqual(timer.worked_minutes_today, 0)

    def test_storage_and_autostart_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = SettingsStore(tmp_path / "state.json")
            settings = AppSettings(
                work_minutes=30,
                break_minutes=10,
                target_cycles=6,
                sound_name="bell",
                is_muted=True,
                auto_start_next=True,
                show_heatmap=True,
                daily_worked_seconds={"2026-11-16": 1800.0},
            )
            store.save(settings)
            loaded = store.load()
            self.assertEqual(loaded, settings)

            autostart = AutostartManager(tmp_path / "autostart" / "mypomodoro.desktop", exec_command="mypomodoro")
            self.assertFalse(autostart.is_enabled)
            self.assertTrue(autostart.set_enabled(True))
            self.assertTrue(autostart.is_enabled)
            self.assertTrue(autostart.set_enabled(False))
            self.assertFalse(autostart.is_enabled)


if __name__ == "__main__":
    unittest.main()
