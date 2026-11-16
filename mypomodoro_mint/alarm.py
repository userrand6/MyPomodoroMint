from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import time
from typing import Callable


class AlarmPlayer:
    AVAILABLE_SOUNDS = [
        "complete",
        "bell",
        "alarm-clock-elapsed",
        "message-new-instant",
        "dialog-information",
    ]
    DEFAULT_MAX_RING_DURATION = 60.0

    def __init__(
        self,
        timeout_add_ms: Callable[[int, Callable[[], bool]], int] | None = None,
        source_remove: Callable[[int], None] | None = None,
        on_pulse: Callable[[], None] | None = None,
        on_timeout: Callable[[], None] | None = None,
    ) -> None:
        self._timeout_add_ms = timeout_add_ms
        self._source_remove = source_remove
        self.on_pulse = on_pulse
        self.on_timeout = on_timeout

        self._timer_id: int | None = None
        self._ring_start: float | None = None
        self._active_proc: subprocess.Popen[bytes] | None = None
        self.is_ringing: bool = False

    def start(self, sound_name: str, max_duration: float = DEFAULT_MAX_RING_DURATION) -> None:
        self.stop()
        self.is_ringing = True
        self._ring_start = time.monotonic()
        self.play_once(sound_name)

        if self._timeout_add_ms is None:
            return

        def on_tick() -> bool:
            if not self.is_ringing:
                return False
            if self._ring_start is not None and (time.monotonic() - self._ring_start) >= max_duration:
                self.stop()
                if self.on_timeout is not None:
                    self.on_timeout()
                return False
            self.play_once(sound_name)
            if self.on_pulse is not None:
                self.on_pulse()
            return True

        self._timer_id = self._timeout_add_ms(1800, on_tick)

    def stop(self) -> None:
        self.is_ringing = False
        self._ring_start = None
        if self._timer_id is not None and self._source_remove is not None:
            self._source_remove(self._timer_id)
        self._timer_id = None
        self._stop_active_process()

    def play_once(self, sound_name: str) -> None:
        self._stop_active_process()
        cmd = self._resolve_command(sound_name)
        if cmd is None:
            return
        try:
            self._active_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._active_proc = None

    def _stop_active_process(self) -> None:
        if self._active_proc is None:
            return
        try:
            if self._active_proc.poll() is None:
                self._active_proc.terminate()
        except OSError:
            pass
        self._active_proc = None

    @staticmethod
    def _resolve_command(sound_name: str) -> list[str] | None:
        if shutil.which("canberra-gtk-play"):
            return ["canberra-gtk-play", "-i", sound_name]

        sound_dirs = [
            Path("/usr/share/sounds/freedesktop/stereo"),
            Path("/usr/share/sounds/LinuxMint/stereo"),
        ]
        for directory in sound_dirs:
            for ext in (".oga", ".ogg", ".wav"):
                candidate = directory / f"{sound_name}{ext}"
                if candidate.exists():
                    if shutil.which("pw-play"):
                        return ["pw-play", str(candidate)]
                    if shutil.which("paplay"):
                        return ["paplay", str(candidate)]
        return None
