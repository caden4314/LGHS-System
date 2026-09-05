#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_backup():
    path = ROOT / 'controller' / 'lghs-controller-backup'
    loader = importlib.machinery.SourceFileLoader('test_controller_backup_impl', str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class ControllerBackupTests(unittest.TestCase):
    def test_online_backup_is_verified_atomic_and_retained(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / 'fleet.db'
            writer = sqlite3.connect(source)
            try:
                self.assertEqual(writer.execute('PRAGMA journal_mode=WAL').fetchone()[0].lower(), 'wal')
                writer.execute('CREATE TABLE marker(value TEXT NOT NULL)')
                writer.execute('INSERT INTO marker(value) VALUES(?)', ('live-wal-value',))
                writer.commit()
                # Keep the writer open so the source remains a live WAL database.
                mod = load_backup()
                safe_config = root / 'fleet.json'
                safe_config.write_text('{"devices":{}}\n', encoding='utf-8')
                mod.SOURCE = source
                mod.ROOT = root / 'backups'
                mod.CONFIG_FILES = (safe_config,)
                result = mod.backup(datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc))
                daily = Path(result['daily'])
                self.assertTrue(daily.is_file())
                copy = sqlite3.connect(daily)
                try:
                    self.assertEqual(copy.execute('PRAGMA quick_check').fetchone()[0].lower(), 'ok')
                    self.assertEqual(copy.execute('SELECT value FROM marker').fetchone()[0], 'live-wal-value')
                finally:
                    copy.close()
                config_copy = Path(result['config'])
                self.assertTrue(config_copy.is_file())
                config_payload = json.loads(config_copy.read_text(encoding='utf-8'))
                self.assertEqual(config_payload['files'][str(safe_config)], '{"devices":{}}\n')
                self.assertTrue((mod.ROOT / 'weekly' / 'fleet-2026-W23.db').is_file())
                self.assertTrue((mod.ROOT / 'weekly' / 'fleet-2026-W23.config.json').is_file())
                self.assertTrue((mod.ROOT / 'monthly' / 'fleet-2026-06.db').is_file())
                self.assertTrue((mod.ROOT / 'monthly' / 'fleet-2026-06.config.json').is_file())
                for day in range(2, 11):
                    mod.backup(datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc))
                self.assertLessEqual(len(list((mod.ROOT / 'daily').glob('fleet-*.db'))), 7)
                self.assertLessEqual(len(list((mod.ROOT / 'weekly').glob('fleet-*.db'))), 4)
                self.assertLessEqual(len(list((mod.ROOT / 'monthly').glob('fleet-*.db'))), 3)
            finally:
                writer.close()

    def test_backup_source_never_copies_live_database_files(self):
        text = (ROOT / 'controller' / 'lghs-controller-backup').read_text(encoding='utf-8')
        self.assertIn('source.backup(destination', text)
        self.assertIn("PRAGMA quick_check", text)
        self.assertNotIn('shutil.copy2(SOURCE', text)
        self.assertNotIn("'-wal'", text)
        self.assertNotIn("'-shm'", text)
        self.assertNotIn("Path('/etc/lghs/secrets", text)
        self.assertNotIn("fleet-api-tokens", text)
        self.assertIn("Path('/var/lib/lghs/release/release-sequence')", text)
        self.assertIn("Path('/var/lib/lghs/release/current.json')", text)
        self.assertNotIn("release-signing-key", text)


if __name__ == '__main__':
    unittest.main()
