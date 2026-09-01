from __future__ import annotations

import os
import unittest

os.environ.setdefault('LGHS_WEB_ALLOWED_HOSTS', 'testserver,localhost,127.0.0.1,fleet.scenicrouteservers.com')
os.environ.setdefault('LGHS_WEB_PUBLIC_ORIGIN', 'https://fleet.scenicrouteservers.com')
os.environ.setdefault('LGHS_WEB_DIST', '/tmp/lghs-web-ui-not-built')

from fastapi.testclient import TestClient

import app as gateway


class GatewaySecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(gateway.app)

    def test_health_response_has_browser_hardening_headers(self):
        response = self.client.get('/healthz')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get('x-content-type-options'), 'nosniff')
        self.assertEqual(response.headers.get('x-frame-options'), 'DENY')
        self.assertEqual(response.headers.get('cross-origin-opener-policy'), 'same-origin')
        self.assertEqual(response.headers.get('cross-origin-resource-policy'), 'same-origin')
        self.assertIn("frame-ancestors 'none'", response.headers.get('content-security-policy', ''))
        self.assertIn('max-age=31536000', response.headers.get('strict-transport-security', ''))

    def test_state_change_with_foreign_origin_is_clean_403(self):
        response = self.client.post('/api/v1/not-a-real-route', headers={'Origin': 'https://evil.example'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'detail': 'invalid request origin'})

    def test_state_change_without_csrf_is_clean_403(self):
        response = self.client.post('/api/v1/not-a-real-route', headers={'Origin': 'https://fleet.scenicrouteservers.com'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json(), {'detail': 'CSRF validation failed'})

    def test_session_without_access_identity_is_unauthorized_and_not_cached(self):
        response = self.client.get('/api/v1/session')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers.get('cache-control'), 'no-store, max-age=0')


if __name__ == '__main__':
    unittest.main()
