#!/usr/bin/env python3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ArchitectureDocsTests(unittest.TestCase):
    def test_readme_describes_current_stock_exact_sha_architecture(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('stock Raspberry Pi OS plus zero-touch LGHS provisioning', readme)
        self.assertIn('exact Git SHA', readme)
        self.assertIn('Ed25519-signed release manifest', readme)
        self.assertIn('lghs-classroom-ready DEVICE', readme)
        self.assertIn('not guaranteed atomic across sudden power loss', readme)
        self.assertNotIn('V0209', readme)
        self.assertNotIn('uses cloud-init to establish', readme)

    def test_architecture_covers_required_trust_and_recovery_domains(self):
        doc = (ROOT / 'docs' / 'ARCHITECTURE.md').read_text(encoding='utf-8')
        for marker in (
            'Trust boundaries and identities', 'Zero-touch provisioning transaction',
            'Cloudflare and runtime transport', 'Fleet command delivery', 'Student sudo approval',
            'Software updates and signed releases', 'Lifecycle and reboot semantics',
            'SQLite durability and backups', 'Remote administration and recovery',
            'CLASSROOM READY gate', 'Optional/legacy image path',
        ):
            self.assertIn(marker, doc)
        self.assertLess(doc.index('CF_VERIFIED'), doc.index('FLEET_ENROLLED'))
        self.assertLess(doc.index('FLEET_ENROLLED'), doc.index('FIRST_TELEMETRY'))
        self.assertIn('/etc/lghs/secrets/release-signing-key', doc)
        self.assertIn('/etc/lghs/release-public-key', doc)

    def test_bluetooth_module_comment_matches_bootstrap_identity_model(self):
        src = (ROOT / 'bluetooth' / 'lghs_bt_protocol.py').read_text(encoding='utf-8')
        head = '\n'.join(src.splitlines()[:12])
        self.assertIn('per-device bootstrap', head)
        self.assertIn('Fleet API credentials are minted only after', head)
        self.assertNotIn('Fleet API tokens\nprovide mutual authentication', head)


if __name__ == '__main__':
    unittest.main()
