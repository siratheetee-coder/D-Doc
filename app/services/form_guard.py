# -*- coding: utf-8 -*-
"""
form_guard.py - กันบอทกรอกฟอร์มสาธารณะ (สมัคร / ขอใบเสนอราคา / ส่งอีเมลยืนยันซ้ำ) แบบคนไม่เห็น

  ไม่ใช้ CAPTCHA (ครูไม่ต้องทำอะไรเพิ่ม) ใช้ 2 ชั้น:
  1) โทเคนเวลา: ตอนเปิดหน้า ระบบฝังเวลาที่เซ็นลายเซ็นไว้ในฟอร์ม
     - ไม่มีโทเคน / ปลอมลายเซ็น  -> บอทยิงตรงโดยไม่เปิดหน้า
     - ส่งเร็วกว่า MIN_SECONDS     -> คนกรอกไม่ทันขนาดนั้น
     - เก่ากว่า MAX_AGE            -> ใช้โทเคนเดิมซ้ำ ๆ
  2) ช่องล่อ (honeypot): ช่องที่คนมองไม่เห็น บอทมักกรอกทุกช่อง

  เจอบอท: ตอบเหมือนสำเร็จ (บอทจะได้ไม่ปรับตัว) แต่ไม่บันทึก ไม่ส่งอีเมลใด ๆ
"""
import hashlib
import hmac
import os
import time

from markupsafe import Markup

MIN_SECONDS = 3
MAX_AGE = 24 * 3600
TOKEN_FIELD = "ft"
TRAP_FIELD = "website"
ENABLED = os.environ.get("DDOC_FORM_GUARD", "1") != "0"


def _sign(ts: str) -> str:
    from app.accounts import get_secret_key
    return hmac.new(get_secret_key().encode(), ("form:" + ts).encode(), hashlib.sha256).hexdigest()[:32]


def token(now: float | None = None) -> str:
    ts = str(int(now if now is not None else time.time()))
    return f"{ts}.{_sign(ts)}"


def fields() -> Markup:
    """ใส่ในฟอร์ม: โทเคนเวลา + ช่องล่อที่ซ่อนจากคน (ทั้งตา, โปรแกรมอ่านหน้าจอ และปุ่ม Tab)"""
    return Markup(
        f'<input type="hidden" name="{TOKEN_FIELD}" value="{token()}">'
        f'<div style="position:absolute;left:-10000px;top:auto;width:1px;height:1px;overflow:hidden;" aria-hidden="true">'
        f'<label>เว็บไซต์ (เว้นว่างไว้)<input type="text" name="{TRAP_FIELD}" value="" tabindex="-1" autocomplete="off"></label>'
        f'</div>')


def is_bot(ft: str, trap: str, now: float | None = None) -> str:
    """คืนเหตุผลถ้าเป็นบอท ("" = ผ่าน)"""
    if not ENABLED:
        return ""
    if (trap or "").strip():
        return "trap"
    ts, _, sig = (ft or "").partition(".")
    if not ts.isdigit() or not sig or not hmac.compare_digest(sig, _sign(ts)):
        return "token"
    age = (now if now is not None else time.time()) - int(ts)
    if age < MIN_SECONDS:
        return "fast"
    if age > MAX_AGE:
        return "old"
    return ""


def log(kind: str, reason: str, request=None) -> None:
    """นับไว้ดูในคอนโซล (ไม่เก็บอีเมล/ข้อมูลที่บอทกรอก)"""
    try:
        from app.accounts import audit
        audit("bot.blocked", request=request, tenant_id=None, uid=None, username="",
              target=kind, detail=reason)
    except Exception:
        pass
