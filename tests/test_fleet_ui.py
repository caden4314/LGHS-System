import unittest

from controller.lghs.fleet_ui import build_create_args, deployment_matches, filter_deployments


class FleetUIFilterTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                'deployment_id': 'dep-room101',
                'name': 'Room 101 rollout',
                'state': 'paused',
                'target_commit': 'a' * 40,
                'target_version': '0.6.0-dev',
                'policy': {'auto_advance': True, 'respect_maintenance': True},
                'strategy': {'type': 'phased'},
                'target': {
                    'selector': {'group_id': 'room101'},
                    'resolved_devices': ['CS-001', 'CS-999'],
                },
            },
            {
                'deployment_id': 'dep-canary',
                'name': 'Canary test',
                'state': 'succeeded',
                'target_commit': 'b' * 40,
                'target_version': '0.5.1',
                'policy': {'auto_advance': False, 'respect_maintenance': False},
                'strategy': {'type': 'all-at-once'},
                'target': {
                    'selector': {'tag': 'ring:canary'},
                    'resolved_devices': ['CS-003'],
                },
            },
        ]

    def test_plain_and_quoted_search(self):
        self.assertTrue(deployment_matches(self.rows[0], 'room 101'))
        self.assertTrue(deployment_matches(self.rows[0], 'name:"Room 101"'))
        self.assertFalse(deployment_matches(self.rows[1], 'Room 101'))

    def test_keyed_filters_are_anded(self):
        result = filter_deployments(self.rows, 'state:paused device:CS-999 group:room101 auto:true maintenance:true')
        self.assertEqual([row['deployment_id'] for row in result], ['dep-room101'])
        self.assertEqual(filter_deployments(self.rows, 'state:paused auto:false'), [])

    def test_tag_target_and_commit_prefix(self):
        self.assertEqual([row['deployment_id'] for row in filter_deployments(self.rows, 'tag:ring:canary')], ['dep-canary'])
        self.assertEqual([row['deployment_id'] for row in filter_deployments(self.rows, 'target:bbbbbbbb')], ['dep-canary'])

    def test_unknown_key_does_not_match(self):
        self.assertFalse(deployment_matches(self.rows[0], 'wat:anything'))


class FleetUICreateArgsTests(unittest.TestCase):
    def test_all_at_once_plan_builds_exact_sha_command(self):
        args = build_create_args({
            'name': 'Single Pi plan',
            'target_type': 'device',
            'target_value': 'cs-999',
            'target_commit': 'A' * 40,
            'target_version': '0.6.0-dev',
            'health_max_age': 45,
        })
        self.assertEqual(args[:5], ['create', '--name', 'Single Pi plan', '--target-commit', 'a' * 40])
        self.assertIn('--device', args)
        self.assertEqual(args[args.index('--device') + 1], 'CS-999')
        self.assertNotIn('--dispatch', args)
        self.assertNotIn('--auto', args)

    def test_phased_auto_maintenance_builds_safe_argv(self):
        args = build_create_args({
            'name': 'Lab rollout',
            'target_type': 'group',
            'target_value': 'room101',
            'target_commit': 'b' * 40,
            'phased': True,
            'canary_count': 1,
            'canary_tag': 'ring:canary',
            'waves': '20,50,100',
            'soak_seconds': 300,
            'health_max_age': 60,
            'required_health_checks': ['service.lghs-agent', 'storage.root-writable'],
            'auto': True,
            'respect_maintenance': True,
        })
        for expected in ('--group', '--phased', '--canary-count', '--canary-tag', '--waves', '--soak-seconds', '--health-max-age', '--auto', '--respect-maintenance'):
            self.assertIn(expected, args)
        self.assertEqual(args.count('--required-health-check'), 2)
        self.assertNotIn('--dispatch', args)

    def test_dispatch_and_auto_are_not_both_emitted(self):
        args = build_create_args({
            'name': 'Automatic',
            'target_type': 'all',
            'target_commit': 'c' * 40,
            'auto': True,
            'dispatch': True,
        })
        self.assertIn('--auto', args)
        self.assertNotIn('--dispatch', args)

    def test_rejects_moving_or_short_target_reference(self):
        for value in ('main', 'abc123', 'release-0.6.0-fleet-operations'):
            with self.assertRaises(ValueError):
                build_create_args({
                    'name': 'Bad target',
                    'target_type': 'all',
                    'target_commit': value,
                })

    def test_rejects_invalid_target_and_health_age(self):
        with self.assertRaises(ValueError):
            build_create_args({'name': 'Bad', 'target_type': 'group', 'target_value': '', 'target_commit': 'd' * 40})
        with self.assertRaises(ValueError):
            build_create_args({'name': 'Bad age', 'target_type': 'all', 'target_commit': 'd' * 40, 'health_max_age': 5})


if __name__ == '__main__':
    unittest.main()
