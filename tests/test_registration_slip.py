import ast
import asyncio
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.slip_upload import read_slip, SlipError, MAX_SLIP_BYTES
from PIL import Image
from jinja2 import Environment, FileSystemLoader

# Exercise the actual pure route helpers without bootstrapping production databases.
tree = ast.parse((ROOT / 'app/routers/sales.py').read_text(encoding='utf-8'))
names = {'_registration_flow', '_registration_destination', '_verify_link'}
ns = {'get_secret_key': lambda: 'test-only-secret', 'Request': object,
      'SELLER': {'base_url': 'https://example.test'}}
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[]), 'sales_helpers', 'exec'), ns)

class Upload:
    def __init__(self, data): self.data = data
    async def read(self, size):
        assert size == MAX_SLIP_BYTES + 1
        return self.data[:size]

class FixTests(unittest.TestCase):
    def test_checkout_continuation(self):
        token = ns['_registration_flow']('USER@example.test', 'checkout', 'งานพัสดุ')
        dest = ns['_registration_destination'](token, 'user@example.test')
        self.assertEqual(parse_qs(urlparse(dest).query)['packages'], ['งานพัสดุ'])
        self.assertEqual(urlparse(dest).path, '/checkout')

    def test_trial_goes_to_app(self):
        token = ns['_registration_flow']('u@x.test', '', 'งานพัสดุ')
        self.assertEqual(ns['_registration_destination'](token, 'u@x.test'), '/')

    def test_flow_bound_to_account_and_signed(self):
        token = ns['_registration_flow']('u@x.test', 'checkout', 'งานพัสดุ')
        self.assertEqual(ns['_registration_destination'](token, 'other@x.test'), '/')
        self.assertEqual(ns['_registration_destination'](token + 'bad', 'u@x.test'), '/')

    def test_expired_flow(self):
        with patch('time.time', return_value=1000000):
            token = ns['_registration_flow']('u@x.test', 'checkout', 'งานพัสดุ')
        self.assertEqual(ns['_registration_destination'](token, 'u@x.test'), '/')

    def test_cannot_redirect_external(self):
        self.assertEqual(ns['_registration_flow']('u@x.test', 'https://evil.test', ''), '')

    def test_email_link_preserves_flow(self):
        flow = ns['_registration_flow']('u@x.test', 'checkout', 'งานพัสดุ')
        query = parse_qs(urlparse(ns['_verify_link'](object(), 'abc', flow)).query)
        self.assertEqual(query['flow'], [flow])
        self.assertEqual(query['token'], ['abc'])

    def test_image_formats(self):
        for fmt, ext in [('PNG','.png'), ('JPEG','.jpg'), ('WEBP','.webp')]:
            with self.subTest(fmt=fmt):
                buf = io.BytesIO(); Image.new('RGB', (8, 8)).save(buf, format=fmt)
                self.assertEqual(asyncio.run(read_slip(Upload(buf.getvalue())))[1], ext)

    def test_reject_fake_and_corrupt_files(self):
        for data in [b'<html>fake.png</html>', b'', b'%PDF-1.4 invalid', b'\x89PNG\r\n\x1a\ninvalid']:
            with self.subTest(data=data):
                with self.assertRaises(SlipError) as cm: asyncio.run(read_slip(Upload(data)))
                self.assertEqual(cm.exception.code, 'sliptype')

    def test_reject_large_upload(self):
        with self.assertRaises(SlipError) as cm:
            asyncio.run(read_slip(Upload(b'x' * (MAX_SLIP_BYTES + 1))))
        self.assertEqual(cm.exception.code, 'slipsize')

    def test_pdf(self):
        from reportlab.pdfgen.canvas import Canvas
        buf = io.BytesIO(); c = Canvas(buf); c.drawString(10, 10, 'sample'); c.save()
        self.assertEqual(asyncio.run(read_slip(Upload(buf.getvalue())))[1], '.pdf')

    def test_templates_parse_and_registration_renders(self):
        env = Environment(loader=FileSystemLoader(ROOT / 'app/templates'))
        for name in ['landing.html', 'register.html', 'register_sent.html', 'checkout.html', 'pay.html']:
            env.parse((ROOT / 'app/templates' / name).read_text(encoding='utf-8'))
        class Request:
            session = {}
        html = env.get_template('register.html').render(request=Request(), trial_days=30, form={}, next='', error=None)
        self.assertIn('ทดลองใช้ฟรี 30 วัน', html)
        self.assertNotIn('14 วัน', html)
        self.assertIn('ยืนยันในอีเมล', html)

    def test_trial_links_and_python_syntax(self):
        landing = (ROOT / 'app/templates/landing.html').read_text(encoding='utf-8')
        self.assertNotIn('/register?next=checkout', landing)
        for name in ['accounts.py', 'templating.py', 'routers/sales.py', 'services/slip_upload.py']:
            ast.parse((ROOT / 'app' / name).read_text(encoding='utf-8'))

if __name__ == '__main__': unittest.main(verbosity=2)

