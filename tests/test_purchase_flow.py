"""Exercise purchase HTTP routes with isolated accounts and no outgoing email."""
import io
from datetime import date, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from app import accounts
from app.routers import sales, auth
from app.modules import MODULE_KEYS, MODULE_LABELS


class PurchaseFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        engine = create_engine('sqlite:///' + str(Path(self.temp.name) / 'accounts.db'),
                               connect_args={'check_same_thread': False})
        self.addCleanup(engine.dispose)
        accounts.AccBase.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        for target, value in [('app.accounts.acc_session', self.Session),
                              ('app.routers.sales.get_secret_key', lambda: 'test-secret'),
                              ('app.routers.sales._LEADS_DIR', Path(self.temp.name) / 'leads')]:
            p = patch(target, value); p.start(); self.addCleanup(p.stop)
        for name in ['send_order_notice', 'send_verify_email']:
            p = patch('app.services.mailer.' + name); p.start(); self.addCleanup(p.stop)
        with self.Session() as db:
            for i in (1, 2):
                db.add(accounts.Tenant(id=i, name='School ' + str(i), plan='trial'))
                db.add(accounts.Account(id=i, tenant_id=i, username=f'owner{i}@example.test',
                                        password_hash=accounts.hash_password('test-password'), is_owner=True))
            db.commit()
        app = FastAPI()
        app.add_middleware(SessionMiddleware, secret_key='test-session')
        app.include_router(sales.router)
        app.include_router(auth.router)
        @app.get('/test-session/{uid}')
        def session(uid: int, request: Request):
            request.session.clear()
            if uid:
                request.session.update(uid=uid, tid=uid, username=f'owner{uid}@example.test', role='user')
            return {}
        self.client = TestClient(app, follow_redirects=False)
        self.addCleanup(self.client.close)
        self.key = MODULE_KEYS[0]
        self.price = sales.price_for({self.key})['total']

    def login(self, uid=1):
        self.client.get(f'/test-session/{uid}')

    def quote(self):
        return accounts.add_lead(kind='quote', school_name='Quoted school',
                                 email='contact@example.test', packages=MODULE_LABELS[self.key],
                                 modules=self.key, amount=777.0)

    def png(self):
        stream = io.BytesIO(); Image.new('RGB', (8, 8)).save(stream, 'PNG')
        return ('receipt.png', stream.getvalue(), 'image/png')

    def order(self, **changes):
        data = dict(school_name='Receipt school', contact_name='Test contact', phone='0812345678',
                    addr_no='12', addr_tambon='Test tambon', addr_amphoe='Test amphoe',
                    addr_province='Test province', addr_zip='10100', note='Keep my note',
                    mod=self.key, quoted_total=str(self.price))
        data.update(changes)
        return data

    def test_guest_checkout_and_login_keep_package(self):
        result = self.client.get('/checkout', params={'packages': MODULE_LABELS[self.key]})
        register = self.client.get(result.headers['location'])
        target = register.context['next']
        self.assertEqual(parse_qs(urlparse(target).query)['packages'], [MODULE_LABELS[self.key]])
        result = self.client.post('/login', data={'username':'owner1@example.test',
                                  'password':'test-password', 'next':target})
        self.assertEqual(result.headers['location'], target)
        page = self.client.get(target)
        self.assertEqual(page.context['selected_mods'], [self.key])
        self.assertEqual(page.context['mode'], 'สั่งซื้อ')

    def test_quote_requires_explicit_binding_and_preserves_amount(self):
        lid = self.quote(); path = '/pay/' + sales.make_pay_token(lid)
        page = self.client.get(path)
        self.assertFalse(page.context['bound'])
        self.assertNotIn('/checkout/promptpay.png', page.text)
        self.login()
        self.assertFalse(self.client.get(path).context['bound'])
        self.client.post(path + '/slip', files={'slip':self.png()})
        self.assertFalse(accounts.get_lead(lid)['slip_file'])
        self.assertEqual(self.client.post(path + '/bind').status_code, 303)
        lead = accounts.get_lead(lid)
        self.assertEqual((lead['tenant_id'], lead['amount'], lead['email']), (1, 777, 'contact@example.test'))
        self.assertTrue(self.client.get(path).context['bound'])
        self.client.post(path + '/slip', files={'slip':self.png()})
        saved = accounts.get_lead(lid)['slip_file']
        self.assertTrue(saved)
        self.assertTrue(self.client.get(path).context['paid'])
        self.client.post(path + '/slip', files={'slip':self.png()})
        self.assertEqual(accounts.get_lead(lid)['slip_file'], saved)
        self.assertEqual(len(list(sales._LEADS_DIR.iterdir())), 1)

    def test_other_school_cannot_rebind_or_upload(self):
        lid = self.quote(); path = '/pay/' + sales.make_pay_token(lid)
        self.login(); self.client.post(path + '/bind')
        self.login(2)
        self.assertTrue(self.client.get(path).context['conflict'])
        self.assertEqual(self.client.post(path + '/bind').status_code, 403)
        self.client.post(path + '/slip', files={'slip':self.png()})
        self.assertFalse(accounts.get_lead(lid)['slip_file'])

    def test_disabled_or_unverified_accounts_cannot_bind(self):
        for field in ['active', 'verified']:
            with self.subTest(field=field):
                with self.Session() as db:
                    account = db.get(accounts.Account, 1)
                    account.active = account.verified = True
                    setattr(account, field, False); db.commit()
                self.assertFalse(accounts.bind_payment_account(self.quote(), 1))

    def test_fake_done_does_not_claim_payment_received(self):
        lid = self.quote(); self.login(); accounts.bind_payment_account(lid, 1)
        page = self.client.get('/pay/' + sales.make_pay_token(lid) + '?done=1')
        self.assertFalse(page.context['paid'])

    def test_invalid_slip_preserves_form_and_selection_without_order(self):
        self.login()
        page = self.client.post('/checkout', data=self.order(), files={'slip':('fake.png', b'fake', 'image/png')})
        self.assertEqual(page.status_code, 400)
        self.assertEqual(page.context['form']['note'], 'Keep my note')
        self.assertEqual(page.context['form']['addr_no'], '12')
        self.assertEqual(page.context['selected_mods'], [self.key])
        with self.Session() as db:
            self.assertEqual(db.query(accounts.Lead).count(), 0)
        self.assertFalse(sales._LEADS_DIR.exists())

    def test_missing_selection_fields_or_changed_price_do_not_save_slip(self):
        self.login()
        for change in [{'mod':''}, {'contact_name':''}, {'quoted_total':'1'}, {'quoted_total':'nan'}]:
            with self.subTest(change=change):
                result = self.client.post('/checkout', data=self.order(**change), files={'slip':self.png()})
                self.assertEqual(result.status_code, 400)
        self.assertFalse(sales._LEADS_DIR.exists())

    def test_checkout_uses_server_price_and_binds_account(self):
        self.login()
        result = self.client.post('/checkout', data=self.order(amount='1', packages='fake'), files={'slip':self.png()})
        self.assertEqual(result.status_code, 303)
        with self.Session() as db:
            lead = db.query(accounts.Lead).one()
            self.assertEqual((lead.tenant_id, lead.amount, lead.modules), (1, self.price, self.key))

    def test_quote_link_preserves_selection_and_request_ignores_tampered_price(self):
        self.login()
        page = self.client.get('/checkout', params={'packages':MODULE_LABELS[self.key]})
        quote = self.client.get(page.context['quote_url'])
        self.assertEqual(quote.context['prefill']['amount'], self.price)
        result = self.client.post('/quote', data=dict(school_name='School', contact_name='Contact',
                                  email='contact@example.test', packages=MODULE_LABELS[self.key], amount='1'))
        self.assertEqual(result.status_code, 303)
        with self.Session() as db:
            self.assertEqual(db.query(accounts.Lead).one().amount, self.price)

    def test_invalid_quote_is_not_created(self):
        self.assertEqual(self.client.post('/quote', data={'packages':'unknown'}).status_code, 400)
        with self.Session() as db:
            self.assertEqual(db.query(accounts.Lead).count(), 0)

    def test_addon_quote_matches_checkout_and_keeps_school(self):
        from app.seller_config import price_addon
        with self.Session() as db:
            tenant = db.get(accounts.Tenant, 1)
            tenant.plan = 'member'; tenant.modules = MODULE_KEYS[1]
            tenant.expiry_date = date.today() + timedelta(days=100)
            db.commit()
        self.login()
        checkout = self.client.get('/checkout', params={'packages': MODULE_LABELS[self.key]})
        quote = self.client.get(checkout.context['quote_url'])
        self.assertTrue(quote.context['addon'])
        self.assertEqual(quote.context['prefill']['amount'], checkout.context['amount'])
        self.client.post('/quote', data=dict(school_name='Receipt school', contact_name='Contact',
                        email='another@example.test', packages=MODULE_LABELS[self.key]))
        with self.Session() as db:
            lead = db.query(accounts.Lead).one()
            self.assertEqual(lead.tenant_id, 1)
            self.assertEqual(lead.amount, price_addon({self.key}, 100)['total'])

    def test_admin_approval_activates_bound_school_not_contact_email(self):
        lid = self.quote()
        self.assertTrue(accounts.bind_payment_account(lid, 2))
        accounts.attach_lead_slip(lid, 'test.png', tenant_id=2)
        result = accounts.renew_lead(lid)
        self.assertEqual(result['tenant_id'], 2)
        with self.Session() as db:
            self.assertEqual(db.get(accounts.Tenant, 2).plan, 'member')
            self.assertEqual(db.get(accounts.Tenant, 1).plan, 'trial')

    def test_invalid_qr_amounts_rejected(self):
        with patch.dict(sales.SELLER, {'promptpay_id':'0812345678'}):
            for amount in ['0', '-1', 'nan', 'inf', 'bad']:
                self.assertEqual(self.client.get('/checkout/promptpay.png', params={'amount':amount}).status_code, 400)

    def test_signed_registration_returns_to_quote_after_verification(self):
        target = '/pay/' + sales.make_pay_token(self.quote())
        flow = sales._registration_flow('owner1@example.test', target, '')
        with patch('app.accounts.verify_email', return_value=dict(uid=1, username='owner1@example.test',
                    tenant_id=1, display_name='School 1')):
            result = self.client.get('/verify', params={'token':'verify-test', 'flow':flow})
        self.assertEqual(result.headers['location'], target)
        self.assertFalse(self.client.get(target).context['bound'])


if __name__ == '__main__':
    unittest.main()
