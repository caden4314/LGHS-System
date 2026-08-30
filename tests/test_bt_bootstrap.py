#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bluetooth"))

from lghs_bt_protocol import (decrypt_payload, derive_key, encrypt_payload,
                              new_ephemeral, proof, transcript, verify_proof)


class BluetoothProtocolTests(unittest.TestCase):
    def test_mutual_auth_and_encrypted_round_trip(self):
        token = b"device-specific-fleet-token-for-test"
        server_private, server_pub = new_ephemeral()
        client_private, client_pub = new_ephemeral()
        tx = transcript("LGCSCONT", "CS-999", "server-nonce", "client-nonce", server_pub, client_pub)

        student = proof(token, "student", tx)
        controller = proof(token, "controller", tx)
        self.assertTrue(verify_proof(token, "student", tx, student))
        self.assertTrue(verify_proof(token, "controller", tx, controller))
        self.assertFalse(verify_proof(b"wrong-token", "student", tx, student))

        server_key = derive_key(server_private, client_pub, token, tx)
        client_key = derive_key(client_private, server_pub, token, tx)
        self.assertEqual(server_key, client_key)

        payload = {"type": "wifi_profile", "wifi": {"ssid": "LGHS-Guest", "key_mgmt": "wpa-psk", "psk": "not-plaintext-on-wire"}}
        envelope = encrypt_payload(server_key, tx, payload)
        self.assertNotIn("ssid", envelope)
        self.assertNotIn("psk", envelope)
        self.assertEqual(decrypt_payload(client_key, tx, envelope), payload)

    def test_transcript_change_breaks_authentication(self):
        token = b"fleet-token"
        _, server_pub = new_ephemeral()
        _, client_pub = new_ephemeral()
        tx = transcript("LGCSCONT", "CS-999", "a", "b", server_pub, client_pub)
        signed = proof(token, "student", tx)
        changed = dict(tx)
        changed["device_id"] = "CS-998"
        self.assertFalse(verify_proof(token, "student", changed, signed))


class BluetoothSourceInvariants(unittest.TestCase):
    def test_student_is_opt_in_one_shot_and_event_driven(self):
        src = (ROOT / "student" / "lghs-bt-bootstrap").read_text(encoding="utf-8")
        self.assertIn("/etc/lghs/bluetooth-bootstrap-enabled", src)
        self.assertIn("wifi-provisioned.json", src)
        self.assertIn('["btmgmt", "find", "-b"]', src)
        self.assertIn("select.select", src)
        self.assertNotIn("SCAN_INTERVAL", src)

    def test_zero_touch_link_layer_keeps_application_authentication(self):
        student = (ROOT / "student" / "lghs-bt-bootstrap").read_text(encoding="utf-8")
        controller = (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8")
        for src in (student, controller):
            self.assertIn('["btmgmt", "io-cap", "3"]', src)
            self.assertIn("set_app_authenticated_security", src)
        self.assertIn('verify_proof(token, "student"', controller)
        self.assertIn('verify_proof(token, "controller"', student)
        self.assertIn("decrypt_payload", student)
        self.assertIn("encrypt_payload", controller)

    def test_controller_authenticates_against_device_token_registry(self):
        src = (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8")
        self.assertIn("fleet-api-tokens.json", src)
        self.assertIn('verify_proof(token, "student"', src)
        self.assertIn("encrypt_payload", src)

    def test_controller_publishes_rfcomm_sdp_service(self):
        src = (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8")
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("ensure_sdp_record", src)
        self.assertIn('"sdptool", "add"', src)
        self.assertIn("bluetoothd --compat", install)
        self.assertIn("50-lghs-sdp-compat.conf", install)

    def test_no_static_wifi_secret_in_repository_protocol(self):
        combined = "\n".join([
            (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8"),
            (ROOT / "student" / "lghs-bt-bootstrap").read_text(encoding="utf-8"),
        ])
        self.assertNotIn("LGHS_WIFI_PASSWORD=", combined)
        self.assertNotIn("DEFAULT_PSK", combined)


if __name__ == "__main__":
    unittest.main()
