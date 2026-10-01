# -*- coding: utf-8 -*-
"""
notice_mail.py - อีเมลแจ้งปิดปรับปรุงระบบ ส่งถึงไอดีหลักของแต่ละโรงเรียน

หน้าตาอีเมลคุมให้ตรงกับการ์ดบนเว็บ (สีอำพันไล่เฉด · วันเวลาเด่น · รายการที่จะปรับปรุง)
ส่งทีละฉบับ ไม่ใส่ที่อยู่คนอื่นในช่อง To/Cc เพื่อไม่ให้อีเมลโรงเรียนอื่นรั่วถึงกัน
"""
from app.services.mailer import send_email
from app.thai_utils import thai_date


def _esc(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def when_text(notice) -> str:
    """ข้อความวันเวลาแบบอ่านง่าย (ข้ามวันก็บอกวันจบให้ด้วย)"""
    s, e = notice.start_at, notice.end_at
    out = f"{thai_date(s)} เวลา {s:%H:%M} – {e:%H:%M} น."
    if e.date() != s.date():
        out = f"{thai_date(s)} เวลา {s:%H:%M} น. ถึง {thai_date(e)} เวลา {e:%H:%M} น."
    return out


def build_html(notice, school: str = "") -> str:
    items = "".join(f"<li style='margin:4px 0'>{_esc(x)}</li>" for x in notice.lines())
    items_html = (f"<b>สิ่งที่จะปรับปรุง</b><ul style='padding-left:18px;margin:8px 0'>{items}</ul>"
                  if items else "")
    hello = f"เรียน ผู้ดูแลระบบ{(' ' + school) if school else ''}"
    note = (f"<p style='margin:14px 0 0'>{_esc(notice.note)}</p>" if notice.note else "")
    return f"""<div style="font-family:'Segoe UI',Tahoma,sans-serif;max-width:640px;margin:0 auto;
     border:1px solid #eceef3;border-radius:12px;overflow:hidden">
  <div style="background:linear-gradient(120deg,#b45309,#f59e0b);color:#fff;padding:18px 22px">
    <div style="font-size:13.5px;opacity:.92">Easy Ekkasan · แจ้งปิดปรับปรุงระบบ</div>
    <h2 style="margin:4px 0 0;font-size:20px">ขออภัยในความไม่สะดวก</h2>
  </div>
  <div style="padding:20px 22px;color:#334155;font-size:15px;line-height:1.6">
    {_esc(hello)}<br>
    ระบบจะมีการปรับปรุงในช่วงเวลาต่อไปนี้ ช่วงดังกล่าวอาจเข้าใช้งานไม่ได้ชั่วคราว
    <div style="background:#fff8ec;border-left:3px solid #f0a020;border-radius:3px 10px 10px 3px;
         padding:10px 14px;margin:14px 0;font-weight:700;color:#7a4f06">{_esc(when_text(notice))}</div>
    {items_html}{note}
  </div>
  <div style="border-top:1px solid #eceef3;padding:14px 22px;color:#7b8190;font-size:13px">
    อีเมลนี้ส่งอัตโนมัติจากระบบ Easy Ekkasan · หากมีข้อสงสัยติดต่อผู้ดูแลระบบ
  </div>
</div>"""


def send_maintenance_mail(notice, targets) -> tuple:
    """ส่งอีเมลแจ้งทีละโรงเรียน · คืน (ส่งสำเร็จ, ส่งไม่สำเร็จ)

    targets = [{"email": ..., "school": ...}, ...] จาก accounts.owner_emails()
    """
    subject = f"[Easy Ekkasan] {notice.title} · {when_text(notice)}"
    sent = failed = 0
    for t in targets:
        try:
            ok = send_email(t["email"], subject, build_html(notice, t.get("school", "")))
        except Exception:
            ok = False
        if ok:
            sent += 1
        else:
            failed += 1
    return sent, failed
