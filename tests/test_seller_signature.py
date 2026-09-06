import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from app.routers import superadmin, sales
from app.services import seller_signature, sale_doc, mailer


class SellerSignatureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in [seller_signature, sale_doc]:
            p = patch.object(module, 'get_data_dir', return_value=self.root)
            p.start(); self.addCleanup(p.stop)
        app = FastAPI(); app.add_middleware(SessionMiddleware, secret_key='test')
        app.include_router(superadmin.router)
        app.include_router(sales.router)
        @app.get('/session/{role}')
        def session(request: Request, role: str):
            request.session.update(uid=99, role=role, must_change=False)
            return {}
        self.client = TestClient(app, follow_redirects=False); self.addCleanup(self.client.close)

    def sample(self):
        image = Image.new('RGB', (300, 100), 'white')
        ImageDraw.Draw(image).line([(15, 70), (150, 20), (285, 55)], fill='navy', width=5)
        b = io.BytesIO(); image.save(b, 'PNG'); return b.getvalue()

    def test_admin_can_save_preview_and_remove_signature(self):
        self.client.get('/session/superadmin')
        result = self.client.post('/admin-console/signature', data={'signer':'Test Seller'},
                                  files={'image':('sign.png', self.sample(), 'image/png')})
        self.assertEqual(result.status_code, 303)
        profile = seller_signature.seller_profile({})
        self.assertEqual(profile['signer'], 'Test Seller')
        self.assertEqual(self.client.get('/admin-console/signature/image').status_code, 200)
        self.client.post('/admin-console/signature', data={'signer':'Updated'})
        self.assertEqual(seller_signature.seller_profile({})['signature_path'], profile['signature_path'])
        self.client.post('/admin-console/signature', data={'signer':'Updated', 'remove':'true'})
        self.assertNotIn('signature_path', seller_signature.seller_profile({}))

    def test_nonadmin_cannot_read_or_change_signature(self):
        self.client.get('/session/user')
        for path in ['/admin-console/signature', '/admin-console/signature/image']:
            self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post('/admin-console/signature', data={'signer':'Other'}).status_code, 403)

    def test_invalid_image_keeps_old_profile(self):
        seller_signature.save_signature('Original', self.sample())
        before = seller_signature.seller_profile({})
        for data in [b'fake', b'x' * (5*1024*1024+1)]:
            with self.assertRaises(ValueError): seller_signature.save_signature('Bad', data)
        self.assertEqual(seller_signature.seller_profile({}), before)

    def test_email_only_attaches_document_without_signature_image(self):
        seller_signature.save_signature('Seller', self.sample())
        with patch.dict('app.seller_config.SELLER', {'smtp_host':'example.test','smtp_user':'test'}), patch('smtplib.SMTP') as smtp:
            self.assertTrue(mailer.send_email('recipient@example.test', 'Test', '<p>Body</p>',
                attachments=[('test.pdf', b'pdf', 'application/pdf')]))
            message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
            self.assertNotIn('cid:', message.get_body(preferencelist=('html',)).get_content())
            self.assertEqual(len([p for p in message.walk() if p.get_content_maintype() == 'image']), 0)
            self.assertEqual(len(list(message.iter_attachments())), 1)

    def test_cleanup_removes_pale_background_and_preserves_dark_ink(self):
        image = Image.new('RGB', (200, 100), (235, 235, 235))
        ImageDraw.Draw(image).line([(40, 60), (160, 30)], fill='navy', width=5)
        cleaned = seller_signature.clean_signature(image)
        self.assertLess(cleaned.width, 150)
        self.assertLess(cleaned.height, 60)
        self.assertEqual(cleaned.getchannel('A').getextrema(), (0, 255))

    def test_both_document_formats_include_signature(self):
        from docx import Document
        seller_signature.save_signature('Test Seller', self.sample())
        seller = seller_signature.seller_profile({'name':'Test Seller'})
        lead = {'school_name':'School', 'amount':890, 'packages':'งานพัสดุ'}
        for kind in ['quotation', 'receipt']:
            docx = getattr(sale_doc, 'render_' + kind)(lead, seller, 'TEST-1')
            self.assertGreaterEqual(len(Document(docx).inline_shapes), 2)
            pdf = getattr(sale_doc, 'render_' + kind + '_pdf')(lead, seller, 'TEST-1')
            self.assertTrue(Path(pdf).read_bytes().startswith(b'%PDF'))

    def test_admin_quote_links_offer_logout_instead_of_login_loop(self):
        self.client.get('/session/superadmin')
        with patch.object(sales, '_parse_pay_token', return_value=13), patch.object(sales, 'get_lead', return_value={'id':13,'amount':890}), patch('app.accounts.purchase_account', return_value=None):
            page = self.client.get('/pay/test-token')
        self.assertTrue(page.context['switch_account'])
        self.assertTrue(page.context['login_url'].startswith('/logout?'))
        self.assertIn('/admin-console/leads', page.text)
        self.assertNotIn('href="/register?', page.text)


if __name__ == '__main__': unittest.main()
