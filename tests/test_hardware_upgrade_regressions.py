#!/usr/bin/env python3
import importlib.machinery
import importlib.util
import tempfile
import unittest
from pathlib import Path

from controller.lghs.database import FleetDB
from controller.lghs.rollout import freeze_deployment

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'd' * 40


def load_fleet_api():
    path = ROOT / 'controller' / 'lghs-fleet-api'
    loader = importlib.machinery.SourceFileLoader('test_hw_fleet_api', str(path))
    spec = importlib.util.spec_from_loader('test_hw_fleet_api', loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class HardwareUpgradeRegressionTests(unittest.TestCase):
    def test_command_success_does_not_mark_deployment_succeeded_before_convergence(self):
        mod = load_fleet_api()
        with tempfile.TemporaryDirectory() as td:
            store = FleetDB(Path(td) / 'fleet.db')
            store.initialize()
            store.upsert_device('CS-999', agent_version='0.5.1')
            result = freeze_deployment(
                store,
                name='hardware regression',
                target_commit=TARGET,
                selector={'device_id': 'CS-999'},
                strategy={'type': 'all-at-once'},
            )
            did = result['deployment_id']
            cid = store.create_command(
                'CS-999',
                'lghs-update',
                payload={'target_commit': TARGET, 'deployment_id': did, 'phase': 0},
                dedupe=False,
            )
            with store.transaction() as db:
                db.execute(
                    "UPDATE deployment_executions SET command_id=?,stage='Waiting for device' WHERE deployment_id=? AND device_id='CS-999'",
                    (cid, did),
                )
                db.execute("UPDATE deployments SET state='running' WHERE deployment_id=?", (did,))
            mod.DB = store
            for state in ('delivered', 'received', 'accepted', 'running', 'succeeded'):
                store.transition_command(cid, state, stage='LGHS is current' if state == 'succeeded' else state)
                mod.sync_deployment_execution(cid)
            execution = store.list_deployment_executions(did)[0]
            deployment = store.get_deployment(did)
            self.assertEqual(execution['state'], 'succeeded')
            self.assertEqual(deployment['state'], 'running')
            self.assertIsNone(store.get_device('CS-999')['current_commit'])

    def test_failed_terminal_command_can_still_fail_deployment(self):
        mod = load_fleet_api()
        with tempfile.TemporaryDirectory() as td:
            store = FleetDB(Path(td) / 'fleet.db')
            store.initialize()
            store.upsert_device('CS-999', agent_version='0.5.1')
            result = freeze_deployment(
                store,
                name='hardware failure regression',
                target_commit=TARGET,
                selector={'device_id': 'CS-999'},
            )
            did = result['deployment_id']
            cid = store.create_command('CS-999', 'lghs-update', payload={'target_commit': TARGET}, dedupe=False)
            with store.transaction() as db:
                db.execute("UPDATE deployment_executions SET command_id=? WHERE deployment_id=? AND device_id='CS-999'", (cid, did))
                db.execute("UPDATE deployments SET state='running' WHERE deployment_id=?", (did,))
            mod.DB = store
            store.transition_command(cid, 'failed', stage='Update failed', message='bridge failure')
            mod.sync_deployment_execution(cid)
            self.assertEqual(store.get_deployment(did)['state'], 'failed')
            execution = store.list_deployment_executions(did)[0]
            self.assertEqual(execution['state'], 'failed')
            self.assertEqual(execution['error_code'], 'FAILED')


if __name__ == '__main__':
    unittest.main()
