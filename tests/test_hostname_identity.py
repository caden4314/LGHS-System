#!/usr/bin/env python3
"""Regression tests: student hostnames may change without changing Fleet identity."""
import importlib.machinery
import importlib.util
import socket
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    'student/lghs-agent',
    'student/lghs-telemetry-push',
    'student/lghs-command-executor',
    'student/lghs-lifecycle-notify',
)

def load_script(relative):
    name = 'test_hostname_' + relative.rsplit('/', 1)[-1].replace('-', '_')
    loader = importlib.machinery.SourceFileLoader(name, str(ROOT / relative))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

class StableIdentityTests(unittest.TestCase):
    def test_all_agents_keep_enrolled_device_id_after_hostname_change(self):
        real_read_text = Path.read_text
        def read_text(path, *args, **kwargs):
            if str(path) == '/etc/lghs/device.conf':
                return 'DEVICE_ID=CS-03\nROLE=student\nHOSTNAME=CS-03\n'
            return real_read_text(path, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', read_text), mock.patch.object(socket, 'gethostname', return_value='cs2-hr2-03'):
            for path in MODULES:
                with self.subTest(path=path):
                    mod = load_script(path)
                    self.assertEqual(mod.stable_device_id(), 'CS-03')

    def test_public_id_works_when_protected_config_is_unreadable(self):
        real_read_text = Path.read_text
        def read_text(path, *args, **kwargs):
            if str(path) == '/etc/lghs-device-id':
                return 'CS-999\n'
            if str(path) == '/etc/lghs/device.conf':
                raise PermissionError('protected LGHS directory')
            return real_read_text(path, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', read_text), mock.patch.object(socket, 'gethostname', return_value='cs0-hr0-999'):
            for path in MODULES:
                with self.subTest(path=path):
                    mod = load_script(path)
                    self.assertEqual(mod.stable_device_id(), 'CS-999')

    def test_agents_fallback_when_device_conf_absent(self):
        real_read_text = Path.read_text
        def read_text(path, *args, **kwargs):
            if str(path) == '/etc/lghs/device.conf':
                raise FileNotFoundError('/etc/lghs/device.conf')
            return real_read_text(path, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', read_text), mock.patch.object(socket, 'gethostname', return_value='cs-03'):
            for path in MODULES:
                with self.subTest(path=path):
                    mod = load_script(path)
                    self.assertEqual(mod.stable_device_id(), 'CS-03')

if __name__ == '__main__':
    unittest.main()
