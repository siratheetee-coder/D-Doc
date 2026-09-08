# -*- coding: utf-8 -*-
"""
totp.py - ยืนยันตัวตน 2 ชั้น (TOTP ตาม RFC 6238) ใช้กับแอป Google Authenticator / Microsoft
Authenticator / Authy

เขียนเองด้วยไลบรารีมาตรฐานของ Python (hmac/hashlib/base64) แทนการเพิ่มแพ็กเกจใหม่
เพราะการ deploy ของระบบนี้คือ "git pull + restart" ไม่มีขั้นตอน pip install
(ส่วน QR ใช้ qrcode ที่มีอยู่แล้วใน requirements.txt)
"""
import base64
import hashlib
import hmac
import os
import secrets
import struct
import time

DIGITS = 6
STEP = 30              # อายุรหัสละ 30 วินาที (มาตรฐานที่ทุกแอปใช้)
WINDOW = 1             # ยอมรับรหัสของช่วงก่อนหน้า/ถัดไป 1 ช่วง (เผื่อนาฬิกาเครื่องคลาดเคลื่อน)
_B32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def new_secret() -> str:
    """สร้างคีย์ลับใหม่ (base32 160 บิต ตามที่แอป authenticator รองรับ)"""
    return "".join(secrets.choice(_B32) for _ in range(32))


def _code_at(secret: str, step: int) -> str:
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    num = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(num % (10 ** DIGITS)).zfill(DIGITS)


def now_step(at: float | None = None) -> int:
    return int((at if at is not None else time.time()) // STEP)


def verify(secret: str, code: str, *, last_step: int = 0, at: float | None = None):
    """ตรวจรหัส 6 หลัก · คืน (สถานะ, step)

    สถานะ: "ok" ผ่าน · "used" รหัสถูกแต่ใช้ไปแล้ว · "bad" ไม่ถูกต้อง

    last_step = step ล่าสุดที่เคยใช้สำเร็จ - รหัสเดิมใช้ซ้ำไม่ได้
    (กันคนแอบเห็นรหัสบนจอ/ดักจับได้แล้วเอาไปใช้ภายใน 30 วินาที)
    แยก "used" ออกจาก "bad" เพื่อบอกผู้ใช้ได้ถูกว่าให้รอรหัสถัดไป ไม่ใช่บอกว่ารหัสผิด
    """
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != DIGITS or not secret:
        return "bad", 0
    cur = now_step(at)
    for step in range(cur - WINDOW, cur + WINDOW + 1):
        if hmac.compare_digest(_code_at(secret, step), code):
            return ("used", step) if step <= last_step else ("ok", step)
    return "bad", 0


def uri(secret: str, account: str, issuer: str = "Easy Ekkasan") -> str:
    """otpauth:// สำหรับสแกน QR (ชื่อที่โชว์ในแอป = issuer:account)"""
    from urllib.parse import quote
    label = quote(f"{issuer}:{account}", safe="")
    return (f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={DIGITS}&period={STEP}")


def qr_png(data: str) -> bytes | None:
    """รูป QR เป็น PNG · คืน None ถ้าสร้างไม่ได้ (หน้าเว็บจะโชว์คีย์ให้พิมพ์เองแทน)"""
    try:
        import io
        import qrcode
        img = qrcode.make(data)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


# ---------------- รหัสสำรอง (ใช้ตอนทำมือถือหาย) ----------------
RECOVERY_COUNT = 8
_RB32 = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"      # ตัด I O 0 1 ออก กันอ่านผิด


def new_recovery_codes(n: int = RECOVERY_COUNT) -> list[str]:
    """รหัสสำรองอ่านง่าย เช่น 'K7QP-3XM9' (40 บิต/รหัส)"""
    out = []
    for _ in range(n):
        raw = "".join(secrets.choice(_RB32) for _ in range(8))
        out.append(f"{raw[:4]}-{raw[4:]}")
    return out


def _norm(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch in _RB32)


def hash_recovery(codes) -> str:
    """เก็บเป็น sha256 ไม่เก็บตัวรหัสจริง · รหัสสุ่ม 40 บิตจึงไม่ต้องใช้ KDF ช้า ๆ"""
    return ",".join(hashlib.sha256(_norm(c).encode()).hexdigest() for c in codes)


def use_recovery(stored: str, code: str):
    """ตรวจรหัสสำรอง · คืน (ผ่านไหม, สตริงใหม่ที่ตัดรหัสที่ใช้ไปแล้วออก) - ใช้ได้ครั้งเดียว"""
    want = hashlib.sha256(_norm(code).encode()).hexdigest()
    left = [h for h in (stored or "").split(",") if h]
    ok = any(hmac.compare_digest(h, want) for h in left)
    if not ok:
        return False, stored
    return True, ",".join(h for h in left if not hmac.compare_digest(h, want))


def recovery_left(stored: str) -> int:
    return len([h for h in (stored or "").split(",") if h])
