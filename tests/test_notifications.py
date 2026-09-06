from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import re
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from app.services import notifications, mailer
from app.routers import superadmin


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        p = patch.object(notifications, 'get_data_dir', return_value=Path(self.temp.name))
        p.start(); self.addCleanup(p.stop)

    def test_recipient_persists_and_invalid_update_preserves_it(self):
        notifications.save_notification_email('owner@example.test')
        self.assertEqual(notifications.notification_email(), 'owner@example.test')
        with self.assertRaises(ValueError): notifications.save_notification_email('bad\naddress')
        self.assertEqual(notifications.notification_email(), 'owner@example.test')

    def test_email_contains_only_authorized_details_and_direct_link(self):
        notifications.save_notification_email('owner@example.test')
        with patch.dict('app.seller_config.SELLER', {'base_url':'https://example.test'}), patch.object(mailer, 'send_email', return_value=True) as send:
            for kind in ['quote', 'order']:
                self.assertTrue(mailer.send_order_notice(kind, school='Private school',
                    contact='Private contact', email='customer@example.test', phone='0812345678',
                    packages='Private package', amount=12345, ref=13, note='Private note', has_slip=True))
                to, subject, html = send.call_args.args
                self.assertEqual(to, 'owner@example.test')
                for value in ['Private', 'customer@example.test', '0812345678', '12,345']:
                    self.assertNotIn(value, subject + html)
                link = re.search(r'href="([^"]+)"', html).group(1)
                target = parse_qs(urlparse(link).query)['next'][0]
                self.assertEqual(target, '/admin-console/leads?kind=' + kind + '#lead-13')
                self.assertIn('#13', subject)

    def test_settings_are_admin_only_and_save(self):
        app = FastAPI(); app.add_middleware(SessionMiddleware, secret_key='test')
        app.include_router(superadmin.router)
        @app.get('/session')
        def session(request: Request):
            request.session['role'] = 'superadmin'
            return {}
        with TestClient(app, follow_redirects=False) as client:
            self.assertEqual(client.get('/admin-console/notifications').status_code, 403)
            self.assertEqual(client.post('/admin-console/notifications', data={'email':'owner@example.test'}).status_code, 403)
            client.get('/session')
            self.assertEqual(client.post('/admin-console/notifications', data={'email':'bad'}).status_code, 400)
            self.assertEqual(client.post('/admin-console/notifications', data={'email':'owner@example.test'}).status_code, 303)
            page = client.get('/admin-console/notifications')
            self.assertEqual(page.context['email'], 'owner@example.test')


if __name__ == '__main__': unittest.main()
