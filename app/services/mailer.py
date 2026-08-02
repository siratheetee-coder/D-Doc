# -*- coding: utf-8 -*-
"""
mailer.py - ส่งอีเมล (ยืนยันอีเมล ฯลฯ) ผ่าน SMTP ที่ตั้งค่าใน seller_local.py
ถ้าไม่ได้ตั้งค่า SMTP -> ระบบข้ามการยืนยันอีเมล (auto-verify) เพื่อให้ใช้งาน local ได้
"""


def smtp_configured() -> bool:
    from app.seller_config import SELLER
    return bool((SELLER.get("smtp_host") or "").strip() and (SELLER.get("smtp_user") or "").strip())


def send_email(to: str, subject: str, html: str) -> bool:
    """ส่งอีเมล HTML ผ่าน SMTP (คืน True ถ้าสำเร็จ) - ต้องตั้ง smtp_* ใน seller_local.py"""
    from app.seller_config import SELLER
    import smtplib
    import ssl
    from email.message import EmailMessage

    host = (SELLER.get("smtp_host") or "").strip()
    user = (SELLER.get("smtp_user") or "").strip()
    pw = SELLER.get("smtp_pass") or ""
    frm = (SELLER.get("smtp_from") or user).strip()
    try:
        port = int(SELLER.get("smtp_port") or 587)
    except (TypeError, ValueError):
        port = 587
    if not (host and user):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = frm
    msg["To"] = to
    msg.set_content("กรุณาเปิดด้วยอีเมลที่รองรับ HTML")
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception as e:   # noqa: BLE001
        print("[mailer] ส่งอีเมลไม่สำเร็จ:", e)
        return False


def send_verify_email(to: str, link: str) -> bool:
    from app.seller_config import SELLER
    brand = SELLER.get("name") or "Easy Ekkasan"
    html = f"""
    <div style="font-family:sans-serif; max-width:520px; margin:0 auto;">
      <h2 style="color:#2563eb;">ยืนยันอีเมลเพื่อเริ่มใช้งาน Easy Ekkasan</h2>
      <p>ขอบคุณที่ลงทะเบียน กรุณากดปุ่มด้านล่างเพื่อยืนยันอีเมลและเปิดใช้งานบัญชี (ทดลองใช้ฟรี)</p>
      <p style="text-align:center; margin:26px 0;">
        <a href="{link}" style="background:#2563eb; color:#fff; text-decoration:none;
           padding:12px 28px; border-radius:10px; font-weight:700;">ยืนยันอีเมล</a>
      </p>
      <p style="color:#64748b; font-size:13px;">ถ้ากดปุ่มไม่ได้ คัดลอกลิงก์นี้ไปเปิด:<br>{link}</p>
      <p style="color:#94a3b8; font-size:12px;">อีเมลนี้ส่งจากระบบ {brand} - หากคุณไม่ได้ลงทะเบียน โปรดละเว้น</p>
    </div>"""
    return send_email(to, "ยืนยันอีเมล - Easy Ekkasan", html)


def send_reset_email(to: str, link: str) -> bool:
    from app.seller_config import SELLER
    brand = SELLER.get("name") or "Easy Ekkasan"
    html = f"""
    <div style="font-family:sans-serif; max-width:520px; margin:0 auto;">
      <h2 style="color:#2563eb;">รีเซ็ตรหัสผ่าน Easy Ekkasan</h2>
      <p>เราได้รับคำขอรีเซ็ตรหัสผ่านสำหรับบัญชีนี้ กดปุ่มด้านล่างเพื่อตั้งรหัสผ่านใหม่ (ลิงก์มีอายุ 1 ชั่วโมง)</p>
      <p style="text-align:center; margin:26px 0;">
        <a href="{link}" style="background:#2563eb; color:#fff; text-decoration:none;
           padding:12px 28px; border-radius:10px; font-weight:700;">ตั้งรหัสผ่านใหม่</a>
      </p>
      <p style="color:#64748b; font-size:13px;">ถ้ากดปุ่มไม่ได้ คัดลอกลิงก์นี้ไปเปิด:<br>{link}</p>
      <p style="color:#94a3b8; font-size:12px;">หากคุณไม่ได้ขอรีเซ็ตรหัสผ่าน โปรดละเว้นอีเมลนี้ รหัสผ่านเดิมยังใช้งานได้ตามปกติ - {brand}</p>
    </div>"""
    return send_email(to, "รีเซ็ตรหัสผ่าน - Easy Ekkasan", html)


def send_order_notice(kind: str, *, school: str, contact: str = "", email: str = "",
                      phone: str = "", packages: str = "", amount: float = 0.0,
                      ref="", note: str = "", has_slip: bool = False) -> bool:
    """แจ้งผู้ขายทันทีเมื่อมีคำสั่งซื้อ/ขอใบเสนอราคาใหม่ (ส่งเข้าอีเมลผู้ขายใน seller_local)
    ไม่ตั้งอีเมลผู้ขาย -> ข้าม (คืน False) โดยไม่ทำให้ flow ซื้อล้ม"""
    from app.seller_config import SELLER
    # แจ้งเตือนไปที่ notify_email ก่อน (ถ้าตั้งไว้) แยกจาก email ที่โชว์บนเอกสารให้ลูกค้า
    to = (SELLER.get("notify_email") or SELLER.get("email") or "").strip()
    if not to:
        return False
    from urllib.parse import quote
    base = (SELLER.get("base_url") or "").rstrip("/")
    target = "/admin-console/leads?kind=" + kind
    # ผ่าน /login?next= เพื่อพาเข้าคอนโซล leads อัตโนมัติ (ถ้ายังไม่ล็อกอิน/ล็อกอินผิดบัญชี ก็ให้ล็อกอินแล้วเด้งต่อ)
    link = (base + "/login?next=" + quote(target, safe="")) if base else target
    label = {"order": "คำสั่งซื้อ (แจ้งชำระเงิน)", "quote": "ขอใบเสนอราคา",
             "trial": "ทดลองใช้"}.get(kind, kind)
    rows = [("โรงเรียน", school), ("ผู้ติดต่อ", contact), ("อีเมล", email),
            ("โทร", phone), ("งานที่เลือก", packages),
            ("ยอดเงิน", f"{amount:,.0f} บาท" if amount else "-"),
            ("แนบสลิป", "มี" if has_slip else "-"), ("หมายเหตุ", note)]
    tr = "".join(
        f'<tr><td style="padding:4px 10px;color:#64748b;white-space:nowrap;vertical-align:top;">{k}</td>'
        f'<td style="padding:4px 10px;font-weight:600;">{(v or "-")}</td></tr>'
        for k, v in rows)
    html = f"""
    <div style="font-family:sans-serif; max-width:560px; margin:0 auto;">
      <h2 style="color:#2563eb;">มี{label}ใหม่</h2>
      <table style="border-collapse:collapse; font-size:15px; width:100%;">{tr}</table>
      <p style="text-align:center; margin:24px 0;">
        <a href="{link}" style="background:#2563eb; color:#fff; text-decoration:none;
           padding:11px 26px; border-radius:10px; font-weight:700;">เปิดคอนโซลเพื่ออนุมัติ</a>
      </p>
      <p style="color:#94a3b8; font-size:12px;">อ้างอิงคำขอ #{ref} · อีเมลอัตโนมัติจากระบบ Easy Ekkasan</p>
    </div>"""
    return send_email(to, f"[Easy Ekkasan] {label}ใหม่ - {school or '-'}", html)
