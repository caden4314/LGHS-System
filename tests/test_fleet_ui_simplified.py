#!/usr/bin/env python3
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "controller" / "lghs-console-day6").read_text(encoding="utf-8")
INSTALL = (ROOT / "install.sh").read_text(encoding="utf-8")
UPDATER = (ROOT / "updater" / "lghs-0.5-install").read_text(encoding="utf-8")


class FleetUISimplifiedTests(unittest.TestCase):
    def test_source_is_valid_python(self):
        ast.parse(SRC)

    def test_primary_navigation_is_five_sections(self):
        for row in (
            '("Overview", "main")', '("Fleet", "fleet")', '("Work", "updates")',
            '("Requests", "sudo")', '("Events", "activity")',
        ):
            self.assertIn(row, SRC)
        self.assertIn('PRIMARY_NAV = [', SRC)

    def test_escape_is_a_real_back_key(self):
        self.assertIn('return key in (27, curses.KEY_BACKSPACE, 127, 8, ord("b"), ord("B"))', SRC)
        self.assertNotIn('Bare Esc is deliberately ignored', SRC)

    def test_command_palette_and_event_unification_are_wired(self):
        self.assertIn('def command_palette(', SRC)
        self.assertIn('key == ord(":")', SRC)
        self.assertIn('def events_screen(', SRC)
        self.assertIn('ui.activity_screen = events_screen', SRC)

    def test_device_detail_replaces_second_level_menu(self):
        self.assertIn('def device_detail_screen(', SRC)
        self.assertIn('["Summary", "Health", "Update", "Telemetry", "Diagnostics"]', SRC)
        self.assertIn('ui.device_menu = device_detail_screen', SRC)

    def test_core_operator_flows_exist(self):
        for marker in ('def overview_screen(', 'def fleet_screen(', 'def work_screen(', 'def events_screen('):
            self.assertIn(marker, SRC)
        self.assertIn('ui.main_menu = overview_screen', SRC)
        self.assertIn('ui.fleet_screen = fleet_screen', SRC)
        self.assertIn('ui.updates_screen = work_screen', SRC)

    def test_day6_is_active_and_day5_is_fallback_core(self):
        self.assertIn('BASE = "/usr/local/libexec/lghs-console-day5-core"', SRC)
        for text in (INSTALL, UPDATER):
            self.assertIn('lghs-console-day5-core', text)
            self.assertIn('controller/lghs-console-day6', text)
            self.assertIn('/usr/local/sbin/lghs-console', text)

    def test_layer_does_not_add_new_shell_execution_paths(self):
        self.assertNotIn('shell=True', SRC)
        self.assertNotIn('eval(', SRC)
        self.assertNotIn('os.system(', SRC)


if __name__ == '__main__':
    unittest.main()
