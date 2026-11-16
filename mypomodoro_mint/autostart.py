from __future__ import annotations

import os
from pathlib import Path
import sys


class AutostartManager:
    def __init__(self, desktop_path: Path | None = None, exec_command: str | None = None) -> None:
        if desktop_path is None:
            config_home = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
            desktop_path = config_home / "autostart" / "mypomodoro.desktop"
        self.desktop_path = desktop_path
        self.exec_command = exec_command or f"{sys.executable} -m mypomodoro_mint"

    @property
    def is_enabled(self) -> bool:
        return self.desktop_path.exists()

    def set_enabled(self, enabled: bool) -> bool:
        try:
            if enabled:
                self.desktop_path.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    "[Desktop Entry]\n"
                    "Type=Application\n"
                    "Name=MyPomodoro\n"
                    "Comment=Lightweight Linux Mint Pomodoro tray timer\n"
                    f"Exec={self.exec_command}\n"
                    "Icon=alarm-symbolic\n"
                    "Terminal=false\n"
                    "Categories=Utility;Clock;\n"
                    "X-GNOME-Autostart-enabled=true\n"
                )
                self.desktop_path.write_text(content, encoding="utf-8")
            else:
                if self.desktop_path.exists():
                    self.desktop_path.unlink()
            return self.is_enabled == enabled
        except OSError:
            return False
