# -*- coding: utf-8 -*-
"""
notice_mail.py - อีเมลประกาศถึงไอดีหลักของแต่ละโรงเรียน

ใช้ได้ทุกประเภทประกาศ (ปิดปรับปรุง / ของใหม่ / ทั่วไป) ถ้อยคำกับสีดึงจาก
accounts.NOTICE_KINDS ที่เดียวกับการ์ดบนเว็บ อีเมลกับการ์ดจึงพูดตรงกันเสมอ
ส่งทีละฉบับ ไม่ใส่ที่อยู่คนอื่นในช่อง To/Cc เพื่อไม่ให้อีเมลโรงเรียนอื่นรั่วถึงกัน
"""
from app.services.mailer import send_email, send_bulk
from app.thai_utils import thai_date


def _esc(text: str) -> str:
    return (str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def kind_of(notice) -> dict:
    from app.accounts import notice_kind
    return notice_kind(getattr(notice, "kind", "") or "")


def when_text(notice) -> str:
    """ข้อความวันเวลาแบบอ่านง่าย (ตัวจริงอยู่ที่ accounts.notice_when ใช้ร่วมกับการ์ด)"""
    from app.accounts import notice_when
    return notice_when(notice)


_BOX = {      # สีกล่องวันเวลาในอีเมล ให้เข้าชุดกับหัวอีเมลแต่ละประเภท
    "maint": ("#fff8ec", "#f0a020", "#7a4f06"),
    "news": ("#eff5ff", "#3b82f6", "#1e40af"),
    "info": ("#ecfdf5", "#10b981", "#065f46"),
}


def build_html(notice, school: str = "") -> str:
    k = kind_of(notice)
    bg, line, ink = _BOX.get(k["css"], _BOX["maint"])
    items = "".join(f"<li style='margin:4px 0'>{_esc(x)}</li>" for x in notice.lines())
    items_html = (f"<b>{_esc(k['items_label'])}</b>"
                  f"<ul style='padding-left:18px;margin:8px 0'>{items}</ul>" if items else "")
    hello = f"เรียน ผู้ดูแลระบบ{(' ' + school) if school else ''}"
    note = (f"<p style='margin:14px 0 0'>{_esc(notice.note)}</p>" if notice.note else "")
    return f"""<div style="font-family:'Segoe UI',Tahoma,sans-serif;max-width:640px;margin:0 auto;
     border:1px solid #eceef3;border-radius:12px;overflow:hidden">
  <div style="background:{k['grad']};color:#fff;padding:18px 22px">
    <div style="font-size:13.5px;opacity:.92">Easy Ekkasan · {_esc(k['label'])}</div>
    <h2 style="margin:4px 0 0;font-size:20px">{_esc(notice.title)}</h2>
  </div>
  <div style="padding:20px 22px;color:#334155;font-size:15px;line-height:1.6">
    {_esc(hello)}<br>
    {_esc(k['lead'])}
    <div style="background:{bg};border-left:3px solid {line};border-radius:3px 10px 10px 3px;
         padding:10px 14px;margin:14px 0;font-weight:700;color:{ink}">{_esc(k['when_label'])}
         {_esc(when_text(notice))}</div>
    {items_html}{note}
  </div>
  <div style="border-top:1px solid #eceef3;padding:14px 22px;color:#7b8190;font-size:13px">
    อีเมลนี้ส่งอัตโนมัติจากระบบ Easy Ekkasan · หากมีข้อสงสัยติดต่อผู้ดูแลระบบ
  </div>
</div>"""


def send_maintenance_mail(notice, targets, on_progress=None) -> tuple:
    """ส่งอีเมลแจ้งทีละโรงเรียน · คืน (ส่งสำเร็จ, ส่งไม่สำเร็จ)

    ส่งแยกฉบับ (ไม่ใส่ที่อยู่โรงเรียนอื่นใน To/Cc) แต่ใช้การเชื่อมต่อ SMTP เดียว
    ไม่งั้น 56 โรงเรียนกินเวลาเป็นนาทีจนโดนตัด 504
    targets = [{"email": ..., "school": ...}, ...] จาก accounts.owner_emails()
    """
    subject = f"[Easy Ekkasan] {notice.title} · {when_text(notice)}"
    msgs = [(t["email"], subject, build_html(notice, t.get("school", ""))) for t in targets]
    return send_bulk(msgs, on_progress=on_progress)


def send_in_background(notice_id: int) -> None:
    """ยิงอีเมลในเธรดแยก แล้วอัปเดตความคืบหน้าลงฐานข้อมูลให้คอนโซลดูได้

    หน้าเว็บตอบกลับทันที ไม่ต้องรอส่งจบ (เดิมรอจนโดน 504)
    """
    import threading

    def run():
        from datetime import datetime
        from app.accounts import acc_session, MaintenanceNotice, owner_emails
        targets = owner_emails()
        db = acc_session()
        try:
            n = db.get(MaintenanceNotice, notice_id)
            if not n:
                return
            n.email_started_at = datetime.now()
            n.email_total = len(targets)
            n.email_count = 0
            n.emailed_at = None
            db.commit()

            def progress(done, _total):
                n.email_count = done
                db.commit()

            sent, failed = send_maintenance_mail(n, targets, on_progress=progress)
            n.email_count = sent
            n.emailed_at = datetime.now()
            db.commit()
            print(f"[notice] ส่งอีเมลประกาศ {notice_id}: สำเร็จ {sent} ไม่สำเร็จ {failed}")
        except Exception as e:      # noqa: BLE001
            print("[notice] ส่งอีเมลเบื้องหลังล้มเหลว:", e)
        finally:
            db.close()

    threading.Thread(target=run, name=f"notice-mail-{notice_id}", daemon=True).start()
