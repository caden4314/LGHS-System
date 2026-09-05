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
        token = b"device-specific-bootstrap-token-for-test"
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
        token = b"one-time-bootstrap-token"
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
        self.assertIn('btmgmt_command("find", "-b")', src)
        self.assertIn('["script", "-q", "-e", "-c", shlex.join(base), "/dev/null"]', src)
        self.assertIn('base = ["btmgmt", "-i", BT_INDEX, *args]', src)
        self.assertIn("select.select", src)
        self.assertNotIn("SCAN_INTERVAL", src)

    def test_zero_touch_link_layer_keeps_application_authentication(self):
        student = (ROOT / "student" / "lghs-bt-bootstrap").read_text(encoding="utf-8")
        controller = (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8")
        prepare = (ROOT / "bluetooth" / "lghs-bt-prepare").read_text(encoding="utf-8")
        prepare_unit = (ROOT / "systemd" / "lghs-bt-prepare.service").read_text(encoding="utf-8")

        self.assertIn('local cmd=(/usr/bin/btmgmt -i "$BT_INDEX" "$@")', prepare)
        self.assertIn('retry_btmgmt "NoInputNoOutput IO capability" io-cap 3', prepare)
        self.assertIn('retry_btmgmt "pairable mode" pairable on', prepare)
        self.assertIn('/usr/bin/script -q -e -c "$quoted" /dev/null', prepare)
        self.assertIn("Before=lghs-bt-provision.service lghs-bt-bootstrap.service", prepare_unit)

        for src in (student, controller):
            self.assertIn("set_app_authenticated_security", src)
        self.assertIn('verify_proof(token, "student"', controller)
        self.assertIn('verify_proof(token, "controller"', student)
        self.assertIn("decrypt_payload", student)
        self.assertIn("encrypt_payload", controller)

    def test_controller_authenticates_against_one_time_bootstrap_registry(self):
        controller = (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8")
        student = (ROOT / "student" / "lghs-bt-bootstrap").read_text(encoding="utf-8")
        enroll = (ROOT / "controller" / "lghs-bootstrap-enroll").read_text(encoding="utf-8")
        self.assertIn("bootstrap-tokens.json", controller)
        self.assertIn("bootstrap_token_for(device_id)", controller)
        self.assertIn('verify_proof(token, "student"', controller)
        self.assertIn("/etc/lghs/secrets/bootstrap-token", student)
        self.assertIn("expires_at", enroll)
        self.assertIn("24 * 60 * 60", enroll)

    def test_stock_password_bootstrap_is_prearmed_and_requires_no_per_device_handoff(self):
        controller_setup = (ROOT / "controller" / "lghs-stock-bootstrap-secret").read_text(encoding="utf-8")
        stock = (ROOT / "bootstrap" / "install-stock.sh").read_text(encoding="utf-8")
        for marker in ("LGHS-stock-bootstrap-v1", "LGHS-STOCK-BT-v1\\0", "hashlib.scrypt", "hashlib.sha512"):
            self.assertIn(marker, controller_setup)
            self.assertIn(marker, stock)
        self.assertIn("range(1, 15)", controller_setup)
        self.assertIn("stock-password-derived", controller_setup)
        self.assertIn("Password cannot be empty.", controller_setup)
        self.assertIn("Password cannot be empty.", stock)
        self.assertNotIn("Use at least 12 characters", controller_setup)
        self.assertNotIn("Use at least 12 characters", stock)
        self.assertNotIn("lghs-bootstrap-enroll", stock)
        self.assertNotIn("Remove-Variable bt", stock)
        self.assertNotIn("$bt =", stock)
        self.assertIn("No per-device token copy or Windows command is required.", stock)

    def test_cloudflare_is_verified_before_fleet_token_is_minted(self):
        controller = (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8")
        student = (ROOT / "student" / "lghs-bt-bootstrap").read_text(encoding="utf-8")

        verify_call = controller.index("verify_cloudflare_ssh(device_id")
        mint_call = controller.index("fleet_token = mint_fleet_token(device_id)")
        self.assertLess(verify_call, mint_call)
        self.assertIn('status != "cloudflare-ready"', controller)
        self.assertIn('"type": "fleet_enrollment"', controller)
        self.assertIn('enrollment.get("type") != "fleet_enrollment"', student)
        self.assertIn('["bluetooth", "cloudflare", "cloudflare-verified", "fleet"]', student)

    def test_controller_publishes_rfcomm_sdp_service(self):
        src = (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8")
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("ensure_sdp_record", src)
        self.assertIn('"sdptool", "add"', src)
        self.assertIn("bluetoothd --compat", install)
        self.assertIn("50-lghs-sdp-compat.conf", install)

    def test_firstboot_prepares_identity_before_bt(self):
        script = (ROOT / "student" / "lghs-firstboot-provision").read_text(encoding="utf-8")
        firstboot_unit = (ROOT / "systemd" / "lghs-firstboot-provision.service").read_text(encoding="utf-8")
        bt_unit = (ROOT / "systemd" / "lghs-bt-bootstrap.service").read_text(encoding="utf-8")

        self.assertIn("ssh-keygen -A", script)
        self.assertLess(script.index("ssh-keygen -A"), script.index("sshd -t"))
        self.assertIn("/etc/cloudflared", script)
        self.assertIn("systemctl restart lghs-bt-bootstrap.service", script)
        self.assertIn("Before=graphical.target display-manager.service getty@tty1.service lghs-policy.service lghs-agent.service lghs-bt-bootstrap.service", firstboot_unit)
        self.assertIn("After=lghs-firstboot-provision.service", bt_unit)

    def test_bt_sandbox_permits_only_needed_tunnel_install_paths(self):
        unit = (ROOT / "systemd" / "lghs-bt-bootstrap.service").read_text(encoding="utf-8")
        self.assertIn("ProtectSystem=strict", unit)
        write_line = next(line for line in unit.splitlines() if line.startswith("ReadWritePaths="))
        for path in (
            "/var/lib/lghs",
            "/var/lib/lghs-agent",
            "/etc/NetworkManager/system-connections",
            "/etc/cloudflared",
            "/etc/systemd/system",
            "/usr/local/bin",
            "/run",
            "/etc/lghs",
            "/etc/ssh/authorized_keys",
        ):
            self.assertIn(path, write_line)

    def test_cloudflared_download_is_pinned_and_verified(self):
        src = (ROOT / "student" / "lghs-cloudflare-install").read_text(encoding="utf-8")
        self.assertIn('CLOUDFLARED_VERSION="${LGHS_CLOUDFLARED_VERSION:-2026.8.1}"', src)
        self.assertIn("sha256sum", src)
        self.assertIn("6d517efc10dfce17440177bd7011909166eab44bae0f6998182183df717c7dba", src)
        self.assertNotIn("releases/latest/download", src)
        self.assertIn("--token-file /etc/cloudflared/token", src)

    def test_legacy_cleanup_survives_stock_identity_filter(self):
        src = (ROOT / "student" / "lghs-legacy-identity-cleanup").read_text(encoding="utf-8")
        install = (ROOT / "install.sh").read_text(encoding="utf-8")
        check = (ROOT / "student" / "lghs-check").read_text(encoding="utf-8")
        self.assertIn("LEGACY_ADMIN = 'cs' + '_admin'", src)
        self.assertIn("LEGACY_STUDENT = 'lg' + '_cs' + '_cont'", src)
        self.assertNotIn("LEGACY_ADMIN = 'cs_admin'", src)
        self.assertNotIn("LEGACY_STUDENT = 'lg_cs_cont'", src)
        self.assertIn("lghs-legacy-identity-cleanup --remove-safe", install)
        self.assertIn('LEGACY_ADMIN="cs""_admin"', check)
        self.assertIn('LEGACY_STUDENT="lg""_cs""_cont"', check)

    def test_update_validation_cannot_be_masked_by_later_success(self):
        updater = (ROOT / "updater" / "lghs-update").read_text(encoding="utf-8")
        self.assertIn('/bin/bash ./install.sh "$ROLE" || return 1', updater)
        self.assertIn('/usr/local/sbin/lghs-check || return 1', updater)
        self.assertIn('validate_student_05 || return 1', updater)
        self.assertIn('validate_controller || return 1', updater)

    def test_legacy_cleanup_archives_home_before_account_removal(self):
        src = (ROOT / "student" / "lghs-legacy-identity-cleanup").read_text(encoding="utf-8")
        self.assertIn("Path('/home/.lghs-legacy')", src)
        self.assertIn("os.replace(home, archive)", src)
        self.assertIn("run(['/usr/sbin/userdel', name])", src)
        self.assertNotIn("run(['/usr/sbin/userdel', '-r', name])", src)

    def test_remote_controller_runtime_is_read_only_and_fixed_scope(self):
        ctl = (ROOT / "controller" / "lghsctl").read_text(encoding="utf-8")
        shell = (ROOT / "controller" / "lghs-remote-shell").read_text(encoding="utf-8")
        self.assertIn('def controller_runtime():', ctl)
        self.assertIn("'lghs-fleet-api.service'", ctl)
        self.assertIn("'InvocationID'", ctl)
        self.assertIn("'NRestarts'", ctl)
        self.assertIn("'controller-runtime'", shell)
        self.assertNotIn("controller-runtime DEVICE", shell)

    def test_stock_docs_match_password_derived_zero_touch_flow(self):
        stock = (ROOT / "bootstrap" / "STOCK-SETUP.md").read_text(encoding="utf-8")
        hardware = (ROOT / "bluetooth" / "HARDWARE-TESTING.md").read_text(encoding="utf-8")
        self.assertIn("lghs-stock-bootstrap-secret", stock)
        self.assertIn("30 days", stock)
        self.assertIn("No token copy", stock)
        self.assertNotIn("TOKEN_PRINTED", stock)
        self.assertNotIn("Register the one-time token", stock)
        self.assertIn("controller-verified Cloudflare SSH", hardware)
        self.assertIn("Only after that proof", hardware)
        self.assertNotIn("installs the per-device Fleet API token", hardware)

    def test_planned_shutdown_reporting_is_installed_and_nonfatal(self):
        install=(ROOT/'install.sh').read_text(encoding='utf-8');check=(ROOT/'student'/'lghs-check').read_text(encoding='utf-8')
        unit=(ROOT/'systemd'/'lghs-lifecycle.service').read_text(encoding='utf-8');notify=(ROOT/'student'/'lghs-lifecycle-notify').read_text(encoding='utf-8')
        api=(ROOT/'controller'/'lghs-fleet-api').read_text(encoding='utf-8');fleet_notify=(ROOT/'controller'/'lghs-fleet-notify').read_text(encoding='utf-8')
        self.assertIn('lghs-lifecycle.service',install);self.assertIn('planned shutdown reporting',check)
        self.assertIn('ExecStop=/usr/local/sbin/lghs-lifecycle-notify --system-stop',unit);self.assertIn("state': 'planned_shutdown'",notify)
        self.assertIn('/v1/lifecycle/',api);self.assertIn('planned_shutdown_reporting',api);self.assertIn('Planned shutdown',fleet_notify)

    def test_no_static_wifi_secret_in_repository_protocol(self):
        combined = "\n".join([
            (ROOT / "controller" / "lghs-bt-provision").read_text(encoding="utf-8"),
            (ROOT / "student" / "lghs-bt-bootstrap").read_text(encoding="utf-8"),
        ])
        self.assertNotIn("LGHS_WIFI_PASSWORD=", combined)
        self.assertNotIn("DEFAULT_PSK", combined)


if __name__ == "__main__":
    unittest.main()
