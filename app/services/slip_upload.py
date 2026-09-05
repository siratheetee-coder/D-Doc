"""Bound and validate payment slips before persisting them."""
from io import BytesIO
import warnings

MAX_SLIP_BYTES = 10 * 1024 * 1024

class SlipError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)

async def read_slip(upload):
    data = await upload.read(MAX_SLIP_BYTES + 1)
    if len(data) > MAX_SLIP_BYTES:
        raise SlipError('slipsize')
    try:
        if data.startswith(b'%PDF-'):
            from pdfminer.pdfparser import PDFParser
            from pdfminer.pdfdocument import PDFDocument
            from pdfminer.pdfpage import PDFPage
            doc = PDFDocument(PDFParser(BytesIO(data)))
            if next(PDFPage.create_pages(doc), None) is None:
                raise ValueError('empty PDF')
            return data, '.pdf'
        from PIL import Image
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as img:
                ext = {'PNG': '.png', 'JPEG': '.jpg', 'WEBP': '.webp'}.get(img.format)
                if not ext or img.width * img.height > 20_000_000:
                    raise ValueError('unsupported image')
                img.verify()
        return data, ext
    except Exception as exc:
        raise SlipError('sliptype') from exc
