# -*- coding: utf-8 -*-
"""ปลายทางของปุ่ม "ย้อนกลับ" เมื่อไม่มีหน้าก่อนในงานเดียวกัน

เดิมปุ่มตัด URL ขึ้นหนึ่งระดับตรง ๆ เช่น /me/letters -> /me ซึ่งไม่มีหน้านั้น ขึ้น 404
(เจ้าของเจอในไอดีครู) ที่นี่ไล่ขึ้นทีละระดับจนเจอหน้า GET ที่มีจริง ไม่เจอเลย = None
ให้ปุ่มไปหน้าหลักของงานแทน
"""
import re

_FILE = re.compile(r"(\.(docx|pdf|png|jpg|xlsx|csv|zip)$)|/(file|download|preview|avatar|qr\.png)$")
_PATTERNS = None


def _patterns():
    global _PATTERNS
    if _PATTERNS is None:
        from starlette.routing import Route
        from app.main import app
        out = []
        for r in app.routes:
            if isinstance(r, Route) and "GET" in (r.methods or set()) and not _FILE.search(r.path):
                out.append(re.compile("^" + re.sub(r"\{[^}]+\}", "[^/]+", r.path.rstrip("/") or "/") + "$"))
        _PATTERNS = out
    return _PATTERNS


def up_url(path: str):
    p = (path or "/").rstrip("/")
    try:
        pats = _patterns()
    except Exception:
        return None
    while "/" in p:
        p = p[:p.rfind("/")]
        if not p:
            return None
        if any(x.match(p) for x in pats):
            return p
    return None
