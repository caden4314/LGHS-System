#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB


ROOT = Path(__file__).resolve().parents[1]


class CommandEventReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = FleetDB(Path(self.tmp.name) / 'fleet.db')
        self.store.initialize()
        self.cid = self.store.create_command('CS-999', 'lghs-update', command_id='cmd-live', now=10)

    def tearDown(self):
        self.tmp.cleanup()

    def events(self):
        with self.store.connect() as db:
            return [dict(r) for r in db.execute(
                'SELECT state,stage,message,progress,created_at,detail_json FROM command_events WHERE command_id=? ORDER BY id',
                (self.cid,),
            ).fetchall()]

    def test_exact_event_replay_is_suppressed(self):
        self.store.transition_command(
            self.cid, 'running', stage='Reconciling current install',
            message='LGHS is already current', progress=85, now=20,
            detail={'update_state': 'validating'},
        )
        self.store.transition_command(
            self.cid, 'running', stage='Reconciling current install',
            message='LGHS is already current', progress=85, now=20,
            detail={'update_state': 'validating'},
        )
        running = [e for e in self.events() if e['state'] == 'running']
        self.assertEqual(len(running), 1)

    def test_same_state_meaningful_change_is_preserved(self):
        self.store.transition_command(
            self.cid, 'accepted', stage='Backfilled', message='', progress=0,
            now=20, detail={'backfilled': True},
        )
        self.store.transition_command(
            self.cid, 'accepted', stage='Accepted by executor', message='Queued locally', progress=0,
            now=20, detail={'update_state': None},
        )
        accepted = [e for e in self.events() if e['state'] == 'accepted']
        self.assertEqual(len(accepted), 2)


class LiveRegressionSourceTests(unittest.TestCase):
    def test_agent_does_not_reuse_terminal_commands_for_new_update_status(self):
        source = (ROOT / 'student' / 'lghs-agent').read_text(encoding='utf-8')
        self.assertIn('TERMINAL_COMMAND_STATES', source)
        self.assertIn("if str(row.get('state') or '').lower() in TERMINAL_COMMAND_STATES:", source)

    def test_legacy_downgrade_cleans_05_services(self):
        source = (ROOT / 'updater' / 'lghs-update').read_text(encoding='utf-8')
        self.assertIn('cleanup_legacy_student_services()', source)
        self.assertIn('systemctl disable --now lghs-command-executor.service', source)
        self.assertIn('systemctl enable --now lghs-telemetry-push.service', source)
        self.assertIn('systemctl is-active --quiet lghs-telemetry-push.service', source)

    def test_managed_sudo_uses_one_persistent_waiter(self):
        broker = (ROOT / 'student' / 'lghs-sudo-broker').read_text(encoding='utf-8')
        wrapper = (ROOT / 'student' / 'sudo').read_text(encoding='utf-8')
        self.assertIn("elif action == 'wait'", broker)
        self.assertIn('BROKER_WAIT_SECONDS = 600', wrapper)
        self.assertIn("waiter = broker_waiter(rid)", wrapper)
        self.assertIn("'/usr/local/sbin/lghs-sudo-broker', 'wait', rid, str(BROKER_WAIT_SECONDS)", wrapper)
        self.assertNotIn("request_status(rid, 2", wrapper)
        self.assertNotIn("request_status(rid, 15", wrapper)
        self.assertNotIn('POLL_SECONDS = 0.35', wrapper)


if __name__ == '__main__':
    unittest.main()
