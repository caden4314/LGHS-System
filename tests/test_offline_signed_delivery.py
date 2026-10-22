"""Controller-to-student update contract and wake-up-after-offline regression tests."""
import base64
import importlib.machinery
import importlib.util
import json
import tempfile
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from controller.lghs import release
from controller.lghs.command_delivery import prepare_delivery
from controller.lghs.database import FleetDB
from controller.lghs.rollout import dispatch_phase, freeze_deployment

ROOT = Path(__file__).resolve().parents[1]


def student_executor():
    loader = importlib.machinery.SourceFileLoader(
        "offline_test_student_executor", str(ROOT / "student/lghs-command-executor")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class OfflineSignedDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        paths = {
            "KEY_FILE": self.path / "secrets/key",
            "STATE_ROOT": self.path / "state",
            "SEQUENCE_FILE": self.path / "state/release-sequence",
            "CURRENT_FILE": self.path / "state/current.json",
            "LOCK_FILE": self.path / "state/lock",
            "VERSION_FILE": self.path / "version",
            "UPDATE_ENV": self.path / "update.env",
        }
        for field, value in paths.items():
            self.stack.enter_context(mock.patch.object(release, field, value))
        (self.path / "version").write_text("0.6.0\n", encoding="utf-8")
        (self.path / "update.env").write_text("LGHS_UPDATE_BRANCH=main\n", encoding="utf-8")
        release.generate_key()
        self.store = FleetDB(self.path / "fleet.db")
        self.store.initialize()
        self.commit = "a" * 40
        self.store.update_device_inventory(
            "CS-999", hostname="CS-999", role="student",
            current_commit="b" * 40, current_version="0.6.0",
        )

    def test_offline_pi_gets_fresh_signed_exact_sha_after_three_weeks(self):
        created_at = time.time() - 21 * 86400
        deployment = freeze_deployment(
            self.store, name="Canary", target_commit=self.commit,
            selector={"device_id": "CS-999"}, now=created_at,
        )
        cid = dispatch_phase(self.store, deployment["deployment_id"], 0, now=created_at)[0]
        command = self.store.get_command(cid)
        self.assertGreater(command["deadline_at"], time.time())
        self.assertEqual(command["state"], "queued")
        rows = self.store.commands_for_delivery("CS-999", now=time.time())
        self.assertEqual(len(rows), 1)
        prepared = prepare_delivery(rows)[0]
        payload = prepared["payload"]
        self.assertEqual(set(payload), {"target_commit", "target_channel",
                                        "release_manifest_b64", "release_signature_b64"})
        self.assertEqual(payload["target_commit"], self.commit)
        raw = base64.b64decode(payload["release_manifest_b64"])
        signature = base64.b64decode(payload["release_signature_b64"])
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(release.public_key_b64()))
        pub.verify(signature, raw)
        manifest = json.loads(raw)
        self.assertEqual(manifest["commit"], self.commit)
        self.assertEqual(manifest["channel"], payload["target_channel"])
        self.assertGreater(manifest["expires_at"], time.time() + 3600)
        command_args = student_executor().action_command("lghs-update", payload, cid)
        self.assertIn("--commit", command_args)
        self.assertIn("--release-manifest-b64", command_args)
        self.assertIn("--idempotency-key", command_args)
        self.assertNotIn("--deployment-id", command_args)

    def test_legacy_deployment_metadata_stripped_before_executor(self):
        payload = {"target_commit": self.commit, "deployment_id": "old-dep", "phase": 0}
        out = prepare_delivery([{"id": "abc", "action": "lghs-update", "payload": payload}])
        student_executor().action_command("lghs-update", out[0]["payload"], "abc")
        self.assertNotIn("deployment_id", out[0]["payload"])
        self.assertNotIn("phase", out[0]["payload"])

    def test_unsigned_pinned_update_is_not_sent_without_signing_key(self):
        self.stack.enter_context(mock.patch.object(release, "KEY_FILE", self.path / "missing"))
        with self.assertRaisesRegex(RuntimeError, "signing key unavailable"):
            prepare_delivery([{"id": "abc", "action": "lghs-update",
                               "payload": {"target_commit": self.commit}}])

    def test_unexpected_update_fields_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected fields"):
            prepare_delivery([{"id": "abc", "action": "lghs-update",
                               "payload": {"target_commit": self.commit, "shell": "echo no"}}])


if __name__ == "__main__":
    unittest.main()
