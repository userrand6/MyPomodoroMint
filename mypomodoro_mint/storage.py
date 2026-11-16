from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
from typing import Any

from .timer import PomodoroTimer


@dataclass
class AppSettings:
    work_minutes: int = PomodoroTimer.DEFAULT_WORK_MINUTES
    break_minutes: int = PomodoroTimer.DEFAULT_BREAK_MINUTES
    target_cycles: int = PomodoroTimer.DEFAULT_TARGET_CYCLES
    sound_name: str = "complete"
    is_muted: bool = False
    auto_start_next: bool = False
    show_heatmap: bool = False
    daily_worked_seconds: dict[str, float] = field(default_factory=dict)


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        if path is None:
            config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            path = config_home / "mypomodoro" / "state.json"
        self.path = path

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppSettings()

        history_raw = raw.get("daily_worked_seconds", {})
        history: dict[str, float] = {}
        if isinstance(history_raw, dict):
            for k, v in history_raw.items():
                if isinstance(k, str) and isinstance(v, (int, float)) and v > 0:
                    history[k] = float(v)

        return AppSettings(
            work_minutes=int(raw.get("work_minutes", PomodoroTimer.DEFAULT_WORK_MINUTES)),
            break_minutes=int(raw.get("break_minutes", PomodoroTimer.DEFAULT_BREAK_MINUTES)),
            target_cycles=int(raw.get("target_cycles", PomodoroTimer.DEFAULT_TARGET_CYCLES)),
            sound_name=str(raw.get("sound_name", "complete")),
            is_muted=bool(raw.get("is_muted", False)),
            auto_start_next=bool(raw.get("auto_start_next", False)),
            show_heatmap=bool(raw.get("show_heatmap", False)),
            daily_worked_seconds=history,
        )

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "work_minutes": settings.work_minutes,
            "break_minutes": settings.break_minutes,
            "target_cycles": settings.target_cycles,
            "sound_name": settings.sound_name,
            "is_muted": settings.is_muted,
            "auto_start_next": settings.auto_start_next,
            "show_heatmap": settings.show_heatmap,
            "daily_worked_seconds": settings.daily_worked_seconds,
        }
        tmp_path = self.path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp_path, self.path)
