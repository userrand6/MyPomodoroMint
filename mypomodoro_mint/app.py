from __future__ import annotations

import signal

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .alarm import AlarmPlayer  # noqa: E402
from .autostart import AutostartManager  # noqa: E402
from .heatmap import HeatmapDrawingArea  # noqa: E402
from .storage import AppSettings, SettingsStore  # noqa: E402
from .timer import PomodoroPhase, PomodoroStatus, PomodoroTimer  # noqa: E402

try:
    gi.require_version("XApp", "1.0")
    from gi.repository import XApp  # type: ignore

    HAS_XAPP = True
except (ImportError, ValueError):
    XApp = None  # type: ignore
    HAS_XAPP = False

try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3  # type: ignore

    HAS_INDICATOR = True
except (ImportError, ValueError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3  # type: ignore

        HAS_INDICATOR = True
    except (ImportError, ValueError):
        AppIndicator3 = None  # type: ignore
        HAS_INDICATOR = False


CSS = b"""
.phase-work { color: #2ecc71; font-weight: bold; font-size: 12px; }
.phase-break { color: #1abc9c; font-weight: bold; font-size: 12px; }
.phase-paused { color: #e67e22; font-weight: bold; font-size: 12px; }
.phase-ringing { color: #e74c3c; font-weight: bold; font-size: 12px; }
.countdown-label { font-family: monospace; font-size: 38px; font-weight: bold; }
.countdown-ringing { color: #e74c3c; font-family: monospace; font-size: 38px; font-weight: bold; }
.muted-label { color: #888888; font-size: 11px; }
.status-ringing { color: #e74c3c; font-size: 11px; font-weight: bold; }
.status-paused { color: #e67e22; font-size: 11px; font-weight: bold; }
.ack-btn { color: #e74c3c; font-weight: bold; }
"""


class MyPomodoroMintApp:
    def __init__(self) -> None:
        self.store = SettingsStore()
        self.settings: AppSettings = self.store.load()
        self.autostart = AutostartManager()

        self.timer = PomodoroTimer(
            work_minutes=self.settings.work_minutes,
            break_minutes=self.settings.break_minutes,
            target_cycles=self.settings.target_cycles,
            daily_worked_seconds=self.settings.daily_worked_seconds,
        )
        self._save_daily_worked()

        self.alarm = AlarmPlayer(
            timeout_add_ms=GLib.timeout_add,
            source_remove=GLib.source_remove,
            on_pulse=self._on_alarm_pulse,
            on_timeout=self._on_alarm_timeout,
        )

        self._tick_source_id: int | None = None
        self._last_displayed_second: int = -1
        self._last_saved_worked_minute: int = self.timer.worked_minutes_today
        self._ring_pulse_on: bool = False
        self._showing_settings: bool = False
        self._syncing_ui: bool = False
        self._last_tray_label: str | None = None
        self._last_tray_icon: str | None = None

        self._apply_css()
        self._build_window()
        self._setup_tray()
        self._refresh_ui()

    def run(self) -> None:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self._quit)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self._quit)
        Gtk.main()

    def _apply_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        screen = Gdk.Screen.get_default()
        if screen is not None:
            Gtk.StyleContext.add_provider_for_screen(
                screen,
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

    def _build_window(self) -> None:
        self.window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.window.set_title("MyPomodoro")
        self.window.set_decorated(False)
        self.window.set_resizable(False)
        self.window.set_skip_taskbar_hint(True)
        self.window.set_skip_pager_hint(True)
        self.window.set_keep_above(True)
        self.window.stick()
        self.window.set_border_width(12)
        self.window.connect("key-press-event", self._on_window_key_press)
        self.window.connect("focus-out-event", self._on_window_focus_out)
        self.window.connect("delete-event", lambda *_: self._hide_window() or True)

        self.stack = Gtk.Stack()
        self.stack.set_vhomogeneous(False)
        self.stack.set_hhomogeneous(False)
        self.window.add(self.stack)

        self._build_timer_page()
        self._build_settings_page()
        self.stack.set_visible_child_name("timer")

    def _build_timer_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_size_request(280, -1)

        # Header
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.phase_label = Gtk.Label(label="WORK • Cycle 1/4")
        self.phase_label.set_xalign(0.0)
        self.worked_today_label = Gtk.Label(label="Today: 0 min")
        self.worked_today_label.get_style_context().add_class("muted-label")
        self.worked_today_label.set_xalign(1.0)
        header.pack_start(self.phase_label, True, True, 0)
        header.pack_end(self.worked_today_label, False, False, 0)
        box.pack_start(header, False, False, 0)

        # Countdown & status
        self.countdown_label = Gtk.Label(label="25:00")
        self.countdown_label.get_style_context().add_class("countdown-label")
        box.pack_start(self.countdown_label, False, False, 2)

        self.status_label = Gtk.Label(label="Ready")
        self.status_label.get_style_context().add_class("muted-label")
        box.pack_start(self.status_label, False, False, 0)

        # Normal controls
        self.normal_controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.normal_controls.set_homogeneous(True)
        self.start_pause_btn = Gtk.Button(label="Start")
        self.start_pause_btn.connect("clicked", lambda *_: self._on_start_pause())
        self.reset_btn = Gtk.Button(label="Reset")
        self.reset_btn.connect("clicked", lambda *_: self._on_reset())
        self.normal_controls.pack_start(self.start_pause_btn, True, True, 0)
        self.normal_controls.pack_start(self.reset_btn, True, True, 0)
        box.pack_start(self.normal_controls, False, False, 2)

        # Ringing controls
        self.ringing_controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.ack_btn = Gtk.Button(label="Acknowledge")
        self.ack_btn.get_style_context().add_class("ack-btn")
        self.ack_btn.connect("clicked", lambda *_: self._on_acknowledge(self.settings.auto_start_next))
        self.ack_alt_btn = Gtk.Button(label="Acknowledge & Start Break")
        self.ack_alt_btn.connect("clicked", lambda *_: self._on_acknowledge(not self.settings.auto_start_next))
        self.ringing_controls.pack_start(self.ack_btn, False, False, 0)
        self.ringing_controls.pack_start(self.ack_alt_btn, False, False, 0)
        self.ringing_controls.set_no_show_all(True)
        self.ringing_controls.hide()
        box.pack_start(self.ringing_controls, False, False, 2)

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # Current cycle extension (+1 min / +5 min)
        extend_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        extend_label = Gtk.Label(label="This cycle")
        extend_label.get_style_context().add_class("muted-label")
        extend_label.set_xalign(0.0)
        self.extend_1_btn = Gtk.Button(label="+1 min")
        self.extend_1_btn.set_tooltip_text("Add 1 minute to the current cycle only")
        self.extend_1_btn.connect("clicked", lambda *_: self._on_extend(1))
        self.extend_5_btn = Gtk.Button(label="+5 min")
        self.extend_5_btn.set_tooltip_text("Add 5 minutes to the current cycle only")
        self.extend_5_btn.connect("clicked", lambda *_: self._on_extend(5))
        extend_row.pack_start(extend_label, True, True, 0)
        extend_row.pack_end(self.extend_5_btn, False, False, 0)
        extend_row.pack_end(self.extend_1_btn, False, False, 0)
        box.pack_start(extend_row, False, False, 0)

        # Optional heatmap
        self.heatmap_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.heatmap_box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
        self.heatmap_view = HeatmapDrawingArea()
        self.heatmap_box.pack_start(self.heatmap_view, False, False, 0)
        self.heatmap_box.set_no_show_all(True)
        self.heatmap_box.hide()
        box.pack_start(self.heatmap_box, False, False, 0)

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 2)

        # Footer
        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.skip_btn = Gtk.Button(label="Skip Work")
        self.skip_btn.connect("clicked", lambda *_: self._on_skip_phase())
        self.mute_btn = Gtk.Button()
        self.mute_btn.connect("clicked", lambda *_: self._on_toggle_mute())
        settings_btn = Gtk.Button.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON)
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", lambda *_: self._show_settings_page())
        quit_btn = Gtk.Button(label="Quit")
        quit_btn.connect("clicked", lambda *_: self._quit())

        footer.pack_start(self.skip_btn, False, False, 0)
        footer.pack_end(quit_btn, False, False, 0)
        footer.pack_end(settings_btn, False, False, 0)
        footer.pack_end(self.mute_btn, False, False, 0)
        box.pack_start(footer, False, False, 0)

        self.stack.add_named(box, "timer")

    def _build_settings_page(self) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_size_request(280, -1)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title = Gtk.Label(label="Settings")
        title.set_xalign(0.0)
        done_btn = Gtk.Button(label="Done")
        done_btn.connect("clicked", lambda *_: self._show_timer_page())
        header.pack_start(title, True, True, 0)
        header.pack_end(done_btn, False, False, 0)
        box.pack_start(header, False, False, 0)
        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        self.work_spin = self._make_spin_row(
            box, "Work cycle (min)", PomodoroTimer.MIN_MINUTES, PomodoroTimer.MAX_MINUTES, self._on_work_spin
        )
        self.break_spin = self._make_spin_row(
            box, "Break cycle (min)", PomodoroTimer.MIN_MINUTES, PomodoroTimer.MAX_MINUTES, self._on_break_spin
        )
        self.cycles_spin = self._make_spin_row(
            box, "Cycles", PomodoroTimer.MIN_CYCLES, PomodoroTimer.MAX_CYCLES, self._on_cycles_spin
        )

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        sound_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sound_label = Gtk.Label(label="Alarm sound")
        sound_label.set_xalign(0.0)
        self.sound_combo = Gtk.ComboBoxText()
        for sound in AlarmPlayer.AVAILABLE_SOUNDS:
            self.sound_combo.append(sound, sound)
        self.sound_combo.connect("changed", self._on_sound_changed)
        sound_row.pack_start(sound_label, True, True, 0)
        sound_row.pack_end(self.sound_combo, False, False, 0)
        box.pack_start(sound_row, False, False, 0)

        self.mute_check = Gtk.CheckButton(label="Mute alarm sound")
        self.mute_check.connect("toggled", self._on_mute_check_toggled)
        box.pack_start(self.mute_check, False, False, 0)

        self.autostart_check = Gtk.CheckButton(label="Autostart at login")
        self.autostart_check.connect("toggled", self._on_autostart_toggled)
        box.pack_start(self.autostart_check, False, False, 0)

        self.autonext_check = Gtk.CheckButton(label="Auto-start next after Acknowledge")
        self.autonext_check.connect("toggled", self._on_autonext_toggled)
        box.pack_start(self.autonext_check, False, False, 0)

        self.heatmap_check = Gtk.CheckButton(label="Show activity heatmap")
        self.heatmap_check.connect("toggled", self._on_heatmap_toggled)
        box.pack_start(self.heatmap_check, False, False, 0)

        box.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)

        actions_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        actions_row.set_homogeneous(True)
        self.reset_cycle_btn = Gtk.Button(label="Reset Cycle")
        self.reset_cycle_btn.connect("clicked", lambda *_: self._on_reset_cycle_progress())
        reset_today_btn = Gtk.Button(label="Reset Today")
        reset_today_btn.connect("clicked", lambda *_: self._on_reset_worked_today())
        self.defaults_btn = Gtk.Button(label="Defaults")
        self.defaults_btn.connect("clicked", lambda *_: self._on_reset_defaults())
        actions_row.pack_start(self.reset_cycle_btn, True, True, 0)
        actions_row.pack_start(reset_today_btn, True, True, 0)
        actions_row.pack_start(self.defaults_btn, True, True, 0)
        box.pack_start(actions_row, False, False, 0)

        settings_quit_btn = Gtk.Button(label="Quit MyPomodoro")
        settings_quit_btn.connect("clicked", lambda *_: self._quit())
        box.pack_start(settings_quit_btn, False, False, 0)

        self.stack.add_named(box, "settings")

    @staticmethod
    def _make_spin_row(parent: Gtk.Box, label: str, min_v: int, max_v: int, callback) -> Gtk.SpinButton:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl = Gtk.Label(label=label)
        lbl.set_xalign(0.0)
        adj = Gtk.Adjustment(value=min_v, lower=min_v, upper=max_v, step_increment=1, page_increment=5)
        spin = Gtk.SpinButton(adjustment=adj, climb_rate=1, digits=0)
        spin.connect("value-changed", callback)
        row.pack_start(lbl, True, True, 0)
        row.pack_end(spin, False, False, 0)
        parent.pack_start(row, False, False, 0)
        return spin

    def _setup_tray(self) -> None:
        self.xapp_icon = None
        self.indicator = None
        self.gtk_status_icon = None

        if HAS_XAPP and XApp is not None:
            self.xapp_icon = XApp.StatusIcon()
            self.xapp_icon.set_name("mypomodoro")
            self.xapp_icon.set_icon_name("alarm-symbolic")
            self.xapp_icon.connect("activate", lambda *_: self._toggle_window())
            menu = self._build_tray_menu()
            self.xapp_icon.set_secondary_menu(menu)
        elif HAS_INDICATOR and AppIndicator3 is not None:
            self.indicator = AppIndicator3.Indicator.new(
                "mypomodoro",
                "alarm-symbolic",
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.indicator.set_menu(self._build_tray_menu())
        else:
            self.gtk_status_icon = Gtk.StatusIcon()
            self.gtk_status_icon.set_from_icon_name("alarm-symbolic")
            self.gtk_status_icon.connect("activate", lambda *_: self._toggle_window())

    def _build_tray_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()
        open_item = Gtk.MenuItem(label="Open MyPomodoro")
        open_item.connect("activate", lambda *_: self._open_window())
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda *_: self._quit())
        menu.append(open_item)
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(quit_item)
        menu.show_all()
        return menu

    def _sync_tick_timer(self) -> None:
        if self.timer.status == PomodoroStatus.RUNNING:
            if self._tick_source_id is None:
                self._last_displayed_second = self.timer.remaining_seconds
                self._tick_source_id = GLib.timeout_add_seconds(1, self._on_tick)
        else:
            if self._tick_source_id is not None:
                GLib.source_remove(self._tick_source_id)
                self._tick_source_id = None

    def _on_tick(self) -> bool:
        just_finished = self.timer.tick()
        worked_min = self.timer.worked_minutes_today
        if worked_min != self._last_saved_worked_minute:
            self._last_saved_worked_minute = worked_min
            self._save_daily_worked()

        if just_finished:
            self._save_daily_worked()
            self._sync_tick_timer()
            self._ring_pulse_on = True
            if not self.settings.is_muted:
                self.alarm.start(self.settings.sound_name)
            self._open_window()
            return False

        if self.timer.remaining_seconds != self._last_displayed_second:
            self._last_displayed_second = self.timer.remaining_seconds
            self._update_tray()
            if self.window.get_visible():
                self._update_countdown_only()

        return self.timer.status == PomodoroStatus.RUNNING

    def _on_alarm_pulse(self) -> None:
        self._ring_pulse_on = not self._ring_pulse_on
        self._update_tray()

    def _on_alarm_timeout(self) -> None:
        self._ring_pulse_on = True
        self._update_tray()

    def _on_start_pause(self) -> None:
        self.timer.toggle_start_pause()
        self._save_daily_worked()
        self._sync_tick_timer()
        self._refresh_ui()

    def _on_reset(self) -> None:
        self.alarm.stop()
        self.timer.reset()
        self._save_daily_worked()
        self._sync_tick_timer()
        self._refresh_ui()

    def _on_acknowledge(self, auto_start_next: bool) -> None:
        self.alarm.stop()
        self._ring_pulse_on = False
        self.timer.acknowledge(auto_start_next=auto_start_next)
        self._save_daily_worked()
        self._sync_tick_timer()
        self._refresh_ui()

    def _on_skip_phase(self) -> None:
        self.alarm.stop()
        self._ring_pulse_on = False
        self.timer.skip_current_phase()
        self._save_daily_worked()
        self._sync_tick_timer()
        self._refresh_ui()

    def _on_extend(self, minutes: int) -> None:
        self.alarm.stop()
        self._ring_pulse_on = False
        self.timer.extend_current_cycle(minutes)
        self._sync_tick_timer()
        self._refresh_ui()

    def _on_work_spin(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_ui:
            return
        self.timer.set_work_minutes(spin.get_value_as_int())
        self._save_settings()
        self._refresh_ui()

    def _on_break_spin(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_ui:
            return
        self.timer.set_break_minutes(spin.get_value_as_int())
        self._save_settings()
        self._refresh_ui()

    def _on_cycles_spin(self, spin: Gtk.SpinButton) -> None:
        if self._syncing_ui:
            return
        self.timer.set_target_cycles(spin.get_value_as_int())
        self._save_settings()
        self._refresh_ui()

    def _on_sound_changed(self, combo: Gtk.ComboBoxText) -> None:
        if self._syncing_ui:
            return
        sound = combo.get_active_id()
        if not sound:
            return
        self.settings.sound_name = sound
        self._save_all()
        if not self.settings.is_muted:
            if self.alarm.is_ringing:
                self.alarm.start(sound)
            else:
                self.alarm.play_once(sound)

    def _on_toggle_mute(self) -> None:
        self.settings.is_muted = not self.settings.is_muted
        self._apply_mute_change()

    def _on_mute_check_toggled(self, check: Gtk.CheckButton) -> None:
        if self._syncing_ui:
            return
        self.settings.is_muted = check.get_active()
        self._apply_mute_change()

    def _apply_mute_change(self) -> None:
        self._save_all()
        if self.settings.is_muted:
            self.alarm.stop()
        elif self.timer.status == PomodoroStatus.RINGING:
            self.alarm.start(self.settings.sound_name)
        self._refresh_ui()

    def _on_autostart_toggled(self, check: Gtk.CheckButton) -> None:
        if self._syncing_ui:
            return
        self.autostart.set_enabled(check.get_active())
        self._refresh_ui()

    def _on_autonext_toggled(self, check: Gtk.CheckButton) -> None:
        if self._syncing_ui:
            return
        self.settings.auto_start_next = check.get_active()
        self._save_all()
        self._refresh_ui()

    def _on_heatmap_toggled(self, check: Gtk.CheckButton) -> None:
        if self._syncing_ui:
            return
        self.settings.show_heatmap = check.get_active()
        self._save_all()
        self._refresh_ui()

    def _on_reset_cycle_progress(self) -> None:
        self.alarm.stop()
        self.timer.reset_cycle_progress()
        self._save_daily_worked()
        self._sync_tick_timer()
        self._refresh_ui()

    def _on_reset_worked_today(self) -> None:
        self.timer.reset_worked_today()
        self._last_saved_worked_minute = self.timer.worked_minutes_today
        self._save_daily_worked()
        self._refresh_ui()

    def _on_reset_defaults(self) -> None:
        self.timer.reset_durations_to_default()
        self._save_settings()
        self._refresh_ui()

    def _save_settings(self) -> None:
        self.settings.work_minutes = self.timer.work_minutes
        self.settings.break_minutes = self.timer.break_minutes
        self.settings.target_cycles = self.timer.target_cycles
        self._save_all()

    def _save_daily_worked(self) -> None:
        self.settings.daily_worked_seconds = dict(self.timer.daily_worked_seconds)
        self._save_all()

    def _save_all(self) -> None:
        self.store.save(self.settings)

    def _refresh_ui(self) -> None:
        self._update_tray()
        self._update_window_controls()

    def _update_countdown_only(self) -> None:
        self.countdown_label.set_text(self.timer.formatted_remaining_time)
        worked_text = f"Today: {self.timer.worked_minutes_today} min"
        if self.worked_today_label.get_text() != worked_text:
            self.worked_today_label.set_text(worked_text)
            if self.settings.show_heatmap:
                self.heatmap_view.update_grid(self.timer.heatmap_grid(HeatmapDrawingArea.WEEKS_COUNT))

    def _update_window_controls(self) -> None:
        self._syncing_ui = True
        try:
            cycle_text = f"Cycle {self.timer.current_cycle_number}/{self.timer.target_cycles}"
            self.countdown_label.set_text(self.timer.formatted_remaining_time)
            self.worked_today_label.set_text(f"Today: {self.timer.worked_minutes_today} min")

            # Settings sync
            self.work_spin.set_value(self.timer.work_minutes)
            self.break_spin.set_value(self.timer.break_minutes)
            self.cycles_spin.set_value(self.timer.target_cycles)
            self.sound_combo.set_active_id(self.settings.sound_name)
            self.mute_check.set_active(self.settings.is_muted)
            self.autostart_check.set_active(self.autostart.is_enabled)
            self.autonext_check.set_active(self.settings.auto_start_next)
            self.heatmap_check.set_active(self.settings.show_heatmap)

            # Mute button icon
            mute_icon = "audio-volume-muted-symbolic" if self.settings.is_muted else "audio-volume-high-symbolic"
            self.mute_btn.set_image(Gtk.Image.new_from_icon_name(mute_icon, Gtk.IconSize.BUTTON))
            self.mute_btn.set_tooltip_text(
                "Sound muted — click to unmute" if self.settings.is_muted else "Mute alarm sound"
            )

            # Heatmap visibility
            if self.settings.show_heatmap:
                self.heatmap_view.update_grid(self.timer.heatmap_grid(HeatmapDrawingArea.WEEKS_COUNT))
                self.heatmap_box.show_all()
            else:
                self.heatmap_box.hide()

            # Phase & status styling
            for cls in ("phase-work", "phase-break", "phase-paused", "phase-ringing"):
                self.phase_label.get_style_context().remove_class(cls)
            for cls in ("muted-label", "status-ringing", "status-paused"):
                self.status_label.get_style_context().remove_class(cls)
            for cls in ("countdown-label", "countdown-ringing"):
                self.countdown_label.get_style_context().remove_class(cls)

            st = self.timer.status
            if st == PomodoroStatus.IDLE:
                self.phase_label.set_text(f"{self.timer.phase.display_name.upper()} • {cycle_text}")
                self.phase_label.get_style_context().add_class(
                    "phase-work" if self.timer.phase == PomodoroPhase.WORK else "phase-break"
                )
                self.countdown_label.get_style_context().add_class("countdown-label")
                self.status_label.set_text("Ready (Muted)" if self.settings.is_muted else "Ready")
                self.status_label.get_style_context().add_class("muted-label")
                self.start_pause_btn.set_label("Start")
                self.reset_btn.set_sensitive(
                    self.timer.remaining_seconds != self.timer.configured_minutes_for_current_phase * 60
                )
                self.normal_controls.show()
                self.ringing_controls.hide()
            elif st == PomodoroStatus.RUNNING:
                self.phase_label.set_text(f"{self.timer.phase.display_name.upper()} • {cycle_text}")
                self.phase_label.get_style_context().add_class(
                    "phase-work" if self.timer.phase == PomodoroPhase.WORK else "phase-break"
                )
                self.countdown_label.get_style_context().add_class("countdown-label")
                self.status_label.set_text("Running (Muted)" if self.settings.is_muted else "Running")
                self.status_label.get_style_context().add_class("muted-label")
                self.start_pause_btn.set_label("Pause")
                self.reset_btn.set_sensitive(True)
                self.normal_controls.show()
                self.ringing_controls.hide()
            elif st == PomodoroStatus.PAUSED:
                self.phase_label.set_text(f"{self.timer.phase.display_name.upper()} • {cycle_text}")
                self.phase_label.get_style_context().add_class("phase-paused")
                self.countdown_label.get_style_context().add_class("countdown-label")
                self.status_label.set_text("Paused")
                self.status_label.get_style_context().add_class("status-paused")
                self.start_pause_btn.set_label("Resume")
                self.reset_btn.set_sensitive(True)
                self.normal_controls.show()
                self.ringing_controls.hide()
            else:
                self.phase_label.set_text(f"{self.timer.phase.display_name.upper()} DONE • {cycle_text}")
                self.phase_label.get_style_context().add_class("phase-ringing")
                self.countdown_label.get_style_context().add_class("countdown-ringing")
                self.status_label.set_text(
                    "Time's up (Muted) — acknowledge"
                    if self.settings.is_muted
                    else "Time's up — acknowledge to silence"
                )
                self.status_label.get_style_context().add_class("status-ringing")
                if self.settings.auto_start_next:
                    self.ack_btn.set_label(f"Acknowledge & Start {self.timer.phase.next.display_name}")
                    self.ack_alt_btn.set_label("Acknowledge Only")
                else:
                    self.ack_btn.set_label("Acknowledge")
                    self.ack_alt_btn.set_label(f"Acknowledge & Start {self.timer.phase.next.display_name}")
                self.normal_controls.hide()
                self.ringing_controls.show_all()

            is_ringing = st == PomodoroStatus.RINGING
            self.skip_btn.set_label(f"Skip {self.timer.phase.display_name}")
            self.extend_1_btn.set_sensitive(True)
            self.extend_5_btn.set_sensitive(True)
            self.work_spin.set_sensitive(not is_ringing)
            self.break_spin.set_sensitive(not is_ringing)
            self.defaults_btn.set_sensitive(not is_ringing)
            self.reset_cycle_btn.set_sensitive(not is_ringing)

            if self.window.get_visible():
                self.window.resize(1, 1)
        finally:
            self._syncing_ui = False

    def _update_tray(self) -> None:
        st = self.timer.status
        if st == PomodoroStatus.IDLE:
            icon_name = "alarm-symbolic"
            label = ""
        elif st == PomodoroStatus.RUNNING:
            icon_name = "alarm-symbolic"
            label = f" {self.timer.formatted_remaining_time}"
        elif st == PomodoroStatus.PAUSED:
            icon_name = "media-playback-pause-symbolic"
            label = f" {self.timer.formatted_remaining_time}"
        else:
            icon_name = "preferences-system-notifications-symbolic" if self._ring_pulse_on else "alarm-symbolic"
            label = " 00:00"

        if self.xapp_icon is not None:
            if self._last_tray_icon != icon_name:
                self.xapp_icon.set_icon_name(icon_name)
                self._last_tray_icon = icon_name
            if self._last_tray_label != label:
                self.xapp_icon.set_label(label)
                self._last_tray_label = label
        elif self.indicator is not None:
            if self._last_tray_icon != icon_name:
                self.indicator.set_icon_full(icon_name, "MyPomodoro")
                self._last_tray_icon = icon_name
            if self._last_tray_label != label:
                self.indicator.set_label(label, " 00:00")
                self._last_tray_label = label
        elif self.gtk_status_icon is not None:
            if self._last_tray_icon != icon_name:
                self.gtk_status_icon.set_from_icon_name(icon_name)
                self._last_tray_icon = icon_name
            if self._last_tray_label != label:
                self.gtk_status_icon.set_tooltip_text(f"MyPomodoro{label}")
                self._last_tray_label = label

    def _show_timer_page(self) -> None:
        self._showing_settings = False
        self.stack.set_visible_child_name("timer")
        self.window.resize(1, 1)

    def _show_settings_page(self) -> None:
        self._showing_settings = True
        self.stack.set_visible_child_name("settings")
        self.window.resize(1, 1)

    def _toggle_window(self) -> None:
        if self.window.get_visible():
            self._hide_window()
        else:
            self._open_window()

    def _open_window(self) -> None:
        if self.timer.sync_daily_date_if_needed():
            self._last_saved_worked_minute = self.timer.worked_minutes_today
            self._save_daily_worked()
        self._show_timer_page()
        self._refresh_ui()
        self.window.set_position(Gtk.WindowPosition.MOUSE)
        self.window.show_all()
        if not self.settings.show_heatmap:
            self.heatmap_box.hide()
        if self.timer.status != PomodoroStatus.RINGING:
            self.ringing_controls.hide()
        self.window.resize(1, 1)
        self.window.present()

    def _hide_window(self) -> None:
        self.window.hide()

    def _on_window_key_press(self, _widget, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self._hide_window()
            return True
        return False

    def _on_window_focus_out(self, _widget, _event) -> bool:
        self._hide_window()
        return False

    def _quit(self, *_args) -> bool:
        if self._tick_source_id is not None:
            GLib.source_remove(self._tick_source_id)
            self._tick_source_id = None
        self.alarm.stop()
        if self.timer.status == PomodoroStatus.RUNNING:
            self.timer.pause()
        self._save_daily_worked()
        Gtk.main_quit()
        return False


def main() -> None:
    app = MyPomodoroMintApp()
    app.run()
