# -*- coding: utf-8 -*-
"""
promptpay.py — สร้าง PromptPay QR แบบระบุยอดเงิน (Thai QR Payment / EMVCo)
ใช้ target = เบอร์มือถือ (10 หลัก) หรือ เลขบัตรประชาชน (13 หลัก) ของผู้รับเงิน
"""
import io


def _tlv(tag: str, val: str) -> str:
    return f"{tag}{len(val):02d}{val}"


def _crc16(data: str) -> str:
    crc = 0xFFFF
    for ch in data.encode("ascii"):
        crc ^= ch << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def promptpay_payload(target: str, amount=None) -> str:
    """คืนสตริง payload มาตรฐาน PromptPay (ใส่ใน QR)
    target: เบอร์มือถือ '0xxxxxxxxx' หรือเลขบัตร ปชช. 13 หลัก
    amount: จำนวนเงิน (ระบุ = QR แบบ dynamic ยอดขึ้นตามนี้), None = static"""
    t = "".join(c for c in str(target) if c.isdigit())
    if len(t) >= 13:
        acc = _tlv("02", t[:13])                       # เลขบัตรประชาชน
    else:
        acc = _tlv("01", "0066" + t.lstrip("0"))       # เบอร์มือถือ -> 0066xxxxxxxxx
    mai = _tlv("29", _tlv("00", "A000000677010111") + acc)
    poi = "010212" if amount else "010211"             # 12 = dynamic (มียอด), 11 = static
    body = _tlv("00", "01") + poi + mai + _tlv("53", "764") + _tlv("58", "TH")
    if amount:
        body += _tlv("54", f"{float(amount):.2f}")
    body += "6304"
    return body + _crc16(body)


def promptpay_png(target: str, amount=None) -> bytes:
    """สร้าง QR PromptPay เป็น PNG (bytes)"""
    import qrcode
    img = qrcode.make(promptpay_payload(target, amount))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
