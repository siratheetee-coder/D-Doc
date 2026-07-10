# -*- coding: utf-8 -*-
"""
mailer.py — ส่งอีเมล (ยืนยันอีเมล ฯลฯ) ผ่าน SMTP ที่ตั้งค่าใน seller_local.py
ถ้าไม่ได้ตั้งค่า SMTP -> ระบบข้ามการยืนยันอีเมล (auto-verify) เพื่อให้ใช้งาน local ได้
"""


def smtp_configured() -> bool:
    from app.seller_config import SELLER
    return bool((SELLER.get("smtp_host") or "").strip() and (SELLER.get("smtp_user") or "").strip())


def send_email(to: str, subject: str, html: str) -> bool:
    """ส่งอีเมล HTML ผ่าน SMTP (คืน True ถ้าสำเร็จ) — ต้องตั้ง smtp_* ใน seller_local.py"""
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
    brand = SELLER.get("name") or "D-Doc"
    html = f"""
    <div style="font-family:sans-serif; max-width:520px; margin:0 auto;">
      <h2 style="color:#2563eb;">ยืนยันอีเมลเพื่อเริ่มใช้งาน D-Doc</h2>
      <p>ขอบคุณที่ลงทะเบียน กรุณากดปุ่มด้านล่างเพื่อยืนยันอีเมลและเปิดใช้งานบัญชี (ทดลองใช้ฟรี)</p>
      <p style="text-align:center; margin:26px 0;">
        <a href="{link}" style="background:#2563eb; color:#fff; text-decoration:none;
           padding:12px 28px; border-radius:10px; font-weight:700;">ยืนยันอีเมล</a>
      </p>
      <p style="color:#64748b; font-size:13px;">ถ้ากดปุ่มไม่ได้ คัดลอกลิงก์นี้ไปเปิด:<br>{link}</p>
      <p style="color:#94a3b8; font-size:12px;">อีเมลนี้ส่งจากระบบ {brand} — หากคุณไม่ได้ลงทะเบียน โปรดละเว้น</p>
    </div>"""
    return send_email(to, "ยืนยันอีเมล — D-Doc", html)
