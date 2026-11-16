from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from .timer import HeatmapDay  # noqa: E402


class HeatmapDrawingArea(Gtk.DrawingArea):
    WEEKS_COUNT = 19
    CELL_SIZE = 11
    CELL_SPACING = 2
    LABEL_WIDTH = 16
    HEADER_HEIGHT = 16
    HEADER_GAP = 5

    def __init__(self) -> None:
        super().__init__()
        self._grid: list[list[HeatmapDay | None]] = []
        grid_width = self.WEEKS_COUNT * self.CELL_SIZE + (self.WEEKS_COUNT - 1) * self.CELL_SPACING
        grid_height = 7 * self.CELL_SIZE + 6 * self.CELL_SPACING
        self.set_size_request(
            self.LABEL_WIDTH + grid_width,
            self.HEADER_HEIGHT + self.HEADER_GAP + grid_height,
        )
        self.set_has_tooltip(True)
        self.connect("draw", self._on_draw)
        self.connect("query-tooltip", self._on_query_tooltip)

    def update_grid(self, grid: list[list[HeatmapDay | None]]) -> None:
        if grid == self._grid:
            return
        self._grid = grid
        self.queue_draw()

    def _is_dark_theme(self) -> bool:
        ctx = self.get_style_context()
        bg = ctx.get_background_color(Gtk.StateFlags.NORMAL)
        luminance = 0.2126 * bg.red + 0.7152 * bg.green + 0.0722 * bg.blue
        return luminance < 0.5

    def _color_for_minutes(self, minutes: int, dark: bool) -> tuple[float, float, float, float]:
        if minutes <= 0:
            return (0.28, 0.28, 0.30, 0.45) if dark else (0.85, 0.87, 0.89, 0.9)
        if minutes < 30:
            return (0.055, 0.267, 0.161, 1.0) if dark else (0.608, 0.914, 0.659, 1.0)
        if minutes < 60:
            return (0.0, 0.427, 0.196, 1.0) if dark else (0.251, 0.769, 0.388, 1.0)
        if minutes < 120:
            return (0.149, 0.651, 0.255, 1.0) if dark else (0.188, 0.631, 0.306, 1.0)
        return (0.224, 0.827, 0.325, 1.0) if dark else (0.129, 0.431, 0.224, 1.0)

    @staticmethod
    def _rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def _on_draw(self, _widget, cr) -> bool:
        dark = self._is_dark_theme()
        alloc = self.get_allocation()

        # Header
        cr.select_font_face("Sans", 0, 0)
        cr.set_font_size(10)
        if dark:
            cr.set_source_rgba(0.75, 0.75, 0.78, 1.0)
        else:
            cr.set_source_rgba(0.35, 0.35, 0.38, 1.0)
        cr.move_to(0, 11)
        cr.show_text(f"Last {self.WEEKS_COUNT} weeks")

        # Legend
        cr.set_font_size(9)
        swatch_size = 8
        swatch_gap = 2
        more_w = cr.text_extents("More").width
        less_w = cr.text_extents("Less").width
        swatches_w = 5 * swatch_size + 4 * swatch_gap
        x = alloc.width - (less_w + 4 + swatches_w + 4 + more_w)

        cr.move_to(x, 11)
        cr.show_text("Less")
        x += less_w + 4

        for mins in (0, 15, 45, 90, 150):
            cr.set_source_rgba(*self._color_for_minutes(mins, dark))
            self._rounded_rect(cr, x, 3, swatch_size, swatch_size, 2)
            cr.fill()
            x += swatch_size + swatch_gap

        if dark:
            cr.set_source_rgba(0.75, 0.75, 0.78, 1.0)
        else:
            cr.set_source_rgba(0.35, 0.35, 0.38, 1.0)
        cr.move_to(x + 2, 11)
        cr.show_text("More")

        # Weekday labels
        top_y = self.HEADER_HEIGHT + self.HEADER_GAP
        for row_idx, label in ((1, "M"), (3, "W"), (5, "F")):
            y = top_y + row_idx * (self.CELL_SIZE + self.CELL_SPACING) + 9
            cr.move_to(0, y)
            cr.show_text(label)

        # Cells
        for week_idx, col in enumerate(self._grid):
            cell_x = self.LABEL_WIDTH + week_idx * (self.CELL_SIZE + self.CELL_SPACING)
            for day_idx, day in enumerate(col):
                if day is None:
                    continue
                cell_y = top_y + day_idx * (self.CELL_SIZE + self.CELL_SPACING)
                cr.set_source_rgba(*self._color_for_minutes(day.minutes, dark))
                self._rounded_rect(cr, cell_x, cell_y, self.CELL_SIZE, self.CELL_SIZE, 2)
                cr.fill()

        return False

    def _on_query_tooltip(self, _widget, x: int, y: int, _keyboard_mode: bool, tooltip) -> bool:
        top_y = self.HEADER_HEIGHT + self.HEADER_GAP
        rel_x = x - self.LABEL_WIDTH
        rel_y = y - top_y
        if rel_x < 0 or rel_y < 0:
            return False

        step = self.CELL_SIZE + self.CELL_SPACING
        week_idx = int(rel_x // step)
        day_idx = int(rel_y // step)
        if (rel_x % step) > self.CELL_SIZE or (rel_y % step) > self.CELL_SIZE:
            return False
        if week_idx < 0 or week_idx >= len(self._grid):
            return False
        col = self._grid[week_idx]
        if day_idx < 0 or day_idx >= len(col):
            return False
        day = col[day_idx]
        if day is None:
            return False

        tooltip.set_text(f"{day.day.strftime('%b %d, %Y')}: {day.minutes} min")
        return True
