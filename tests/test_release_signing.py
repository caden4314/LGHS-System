#!/usr/bin/env python3
import base64
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    path = ROOT / relative
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class SignedReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.release = load('test_release_module', 'controller/lghs/release.py')
        self.release.KEY_FILE = self.root / 'secrets' / 'release-signing-key'
        self.release.STATE_ROOT = self.root / 'state'
        self.release.SEQUENCE_FILE = self.release.STATE_ROOT / 'release-sequence'
        self.release.CURRENT_FILE = self.release.STATE_ROOT / 'current.json'
        self.release.LOCK_FILE = self.release.STATE_ROOT / 'lock'
        self.release.VERSION_FILE = self.root / 'version'
        self.release.UPDATE_ENV = self.root / 'update.env'
        self.release.VERSION_FILE.write_text('0.6.1\n', encoding='utf-8')
        self.release.UPDATE_ENV.write_text('LGHS_UPDATE_BRANCH=main\n', encoding='utf-8')
        self.public = self.release.generate_key()

        self.verify = load('test_release_verify', 'student/lghs-release-verify')
        self.verify.PUBLIC_KEY = self.root / 'release-public-key'
        self.verify.SEQUENCE_FILE = self.root / 'accepted-sequence'
        self.verify.PUBLIC_KEY.write_text(self.public + '\n', encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_valid_manifest_and_reuse(self):
        commit = 'a' * 40
        first = self.release.issue_release(commit, channel='main', version='0.6.1', now=1000)
        second = self.release.issue_release(commit, channel='main', version='0.6.1', now=1100)
        self.assertEqual(first['manifest']['release_sequence'], 1)
        self.assertEqual(second['manifest']['release_sequence'], 1)
        seq = self.verify.verify(commit, 'main', first['manifest_b64'], first['signature_b64'], now=1200)
        self.assertEqual(seq, 1)
        self.assertEqual(first['public_key_fingerprint_sha256'], self.release.public_fingerprint())

    def test_tamper_expiry_and_channel_mismatch_are_rejected(self):
        commit = 'b' * 40
        bundle = self.release.issue_release(commit, channel='main', version='0.6.1', ttl_seconds=3600, now=1000)
        manifest = json.loads(base64.b64decode(bundle['manifest_b64']).decode())
        manifest['version'] = 'evil'
        tampered = base64.b64encode(json.dumps(manifest, sort_keys=True, separators=(',', ':')).encode()).decode()
        with self.assertRaisesRegex(ValueError, 'signature'):
            self.verify.verify(commit, 'main', tampered, bundle['signature_b64'], now=1200)
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.verify.verify(commit, 'main', bundle['manifest_b64'], bundle['signature_b64'], now=5000)
        with self.assertRaisesRegex(ValueError, 'channel'):
            self.verify.verify(commit, 'stable', bundle['manifest_b64'], bundle['signature_b64'], now=1200)

    def test_release_sequence_rollback_requires_local_root_override(self):
        commit = 'c' * 40
        bundle = self.release.issue_release(commit, channel='main', version='0.6.1', ttl_seconds=3600, now=1000)
        self.verify.SEQUENCE_FILE.write_text('2\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'rollback rejected'):
            self.verify.verify(commit, 'main', bundle['manifest_b64'], bundle['signature_b64'], now=1200)
        with mock.patch.dict(os.environ, {'LGHS_ALLOW_RELEASE_ROLLBACK': '1'}):
            self.assertEqual(self.verify.verify(commit, 'main', bundle['manifest_b64'], bundle['signature_b64'], now=1200), 1)

    def test_minimum_updater_is_enforced(self):
        commit = 'd' * 40
        bundle = self.release.issue_release(commit, channel='main', version='0.6.1', minimum_updater='9.0.0', now=1000)
        with self.assertRaisesRegex(ValueError, 'requires updater'):
            self.verify.verify(commit, 'main', bundle['manifest_b64'], bundle['signature_b64'], now=1200)

    def test_public_key_install_is_one_time_and_idempotent(self):
        installer = load('test_release_key_install', 'student/lghs-release-key-install')
        installer.TARGET = self.root / 'installed-public-key'
        installer.TARGET.write_text('', encoding='utf-8')
        fingerprint = installer.install(self.public)
        self.assertEqual(installer.install(self.public), fingerprint)
        other = load('test_release_other', 'controller/lghs/release.py')
        other.KEY_FILE = self.root / 'other-secrets' / 'release-signing-key'
        other.STATE_ROOT = self.root / 'other-state'
        other.SEQUENCE_FILE = other.STATE_ROOT / 'release-sequence'
        other.CURRENT_FILE = other.STATE_ROOT / 'current.json'
        other.LOCK_FILE = other.STATE_ROOT / 'lock'
        other_public = other.generate_key()
        with self.assertRaisesRegex(ValueError, 'already enrolled'):
            installer.install(other_public)

        missing = self.root / 'missing-slot'
        installer.TARGET = missing
        with self.assertRaisesRegex(ValueError, 'slot is missing'):
            installer.install(self.public)
        unit = (ROOT / 'systemd' / 'lghs-command-executor.service').read_text(encoding='utf-8')
        rw_line = next(line for line in unit.splitlines() if line.startswith('ReadWritePaths='))
        self.assertIn('/etc/lghs/release-public-key', rw_line)
        self.assertNotIn(' /etc/lghs ', rw_line + ' ')
        install = (ROOT / 'install.sh').read_text(encoding='utf-8')
        self.assertIn('[[ ! -e /etc/lghs/release-public-key ]]', install)

    def test_augment_update_payload_signs_only_after_key_exists(self):
        commit = 'e' * 40
        payload = self.release.augment_update_payload({'target_commit': commit, 'target_channel': 'main'})
        self.assertIn('release_manifest_b64', payload)
        self.assertIn('release_signature_b64', payload)
        verified = self.verify.verify(commit, 'main', payload['release_manifest_b64'], payload['release_signature_b64'], now=int(__import__('time').time()))
        self.assertGreaterEqual(verified, 1)


if __name__ == '__main__':
    unittest.main()
