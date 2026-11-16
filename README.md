# MyPomodoroMint

A lightweight Linux Mint (Cinnamon / GTK 3) system tray Pomodoro timer — pure Python + PyGObject (`gtk3` + `XApp.StatusIcon`), zero `pip` dependencies, and minimal CPU/RAM usage.

## Features

- **System tray live countdown** — Displays remaining `MM:SS` directly in the Linux Mint Cinnamon panel (`XApp.StatusIcon`, with automatic fallback to `AyatanaAppIndicator3` / `Gtk.StatusIcon`).
- **Auto-open & repeating alarm (60s cap)** — Opens the popup automatically when a timer finishes and plays a repeating Freedesktop/Mint system sound until acknowledged, or stops after 60 seconds if unacknowledged.
- **Current-cycle `+1 min` / `+5 min` & `Skip Work/Break`** — Extend the active cycle (even after time ends while ringing) without modifying saved Settings, or skip straight to the next phase.
- **Cycle settings, mute, autostart & daily counter** — Configure Work/Break cycle lengths, cycle count (`Cycle X/Y`), alarm sound, mute toggle, autostart at login (`~/.config/autostart/mypomodoro.desktop`), auto-start next after Acknowledge, and daily worked minutes (`Today: X min`).
- **Optional GitHub-style activity heatmap** — Enable **Show activity heatmap** in Settings for a 19-week Cairo-rendered contribution grid with per-day hover tooltips.
- **Persistent state** — Saved as JSON in `~/.config/mypomodoro/state.json`.

## Requirements (Linux Mint)

Linux Mint includes Python 3 and GTK 3 by default. Ensure the GIR bindings and sound tool are installed:

```sh
sudo apt update
sudo apt install -y python3-gi gir1.2-gtk-3.0 gir1.2-xapp-1.0 libcanberra-gtk3-module
```

## Run & Install

Run directly:

```sh
./mypomodoro &
```

Or install to `~/.local/bin/mypomodoro` and add a desktop menu entry:

```sh
make install
```

Run unit tests:

```sh
make test
```
