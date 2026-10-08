# -*- coding: utf-8 -*-
"""
member_notice.py - อีเมลเตือนสมาชิกที่จ่ายเงินแล้วว่าใกล้หมดอายุ/หมดแล้ว

เดิมมีเฉพาะอีเมลเตือนช่วงทดลองใช้ (trial_notice.py) สมาชิกที่จ่ายเงินแล้วไม่เคยได้รับ
อะไรเลย ครบปีแล้วเปิดระบบมาเจอหน้า "บัญชีหมดอายุ" ทันที (มิดเดิลแวร์ใน main.py บล็อกทุกหน้า)
ซึ่งทั้งเสียความรู้สึกลูกค้าและเสียรายได้จากคนที่แค่ลืมต่อ

ส่ง 4 ขั้น (ไปที่ไอดีหลักของโรงเรียน ชื่อผู้ใช้ = อีเมลตอนสมัคร):
    1 = เหลือไม่เกิน 30 วัน  (โรงเรียนต้องทำเรื่องขออนุมัติงบ ต้องรู้ล่วงหน้า)
    2 = เหลือไม่เกิน 7 วัน
    3 = วันสุดท้ายหรือก่อนวันสุดท้าย 1 วัน
    4 = หมดแล้ว (ข้อมูลยังอยู่ครบ ต่ออายุแล้วใช้ต่อได้ทันที)

รันจาก cron วันละครั้ง 8 โมงเช้า:
    /opt/ddoc/.venv/bin/python -m app.services.member_notice
ดูก่อนว่าจะส่งหาใครโดยไม่ส่งจริง:
    /opt/ddoc/.venv/bin/python -m app.services.member_notice --dry-run

กติกา (ยกโครงจาก trial_notice.py ที่ใช้งานมาแล้ว)
  - ส่งเฉพาะ plan='member' ที่ยังไม่ถูกระงับ และมีวันหมดอายุ (ไม่จำกัดเวลา = ไม่ต้องเตือน)
  - จำขั้นที่ส่งแล้วใน tenant.member_notice_stage -> รันซ้ำกี่รอบก็ไม่ส่งซ้ำ
  - ข้ามขั้นได้ ส่งเฉพาะขั้นล่าสุดขั้นเดียว (ไม่ไล่ส่งย้อนหลังทีละขั้น)
  - หมดมานานเกิน EXPIRED_WINDOW วันแล้วไม่ส่ง · กันอีเมลย้อนหลังถล่มตอนเปิดใช้ครั้งแรก
    (โรงเรียนที่หมดอายุไปนานแล้วจะไม่ได้รับอีเมลจากรอบแรกที่เปิดใช้ฟีเจอร์นี้)
  - ต่ออายุแล้ว (เหลือเกิน 30 วัน) -> รีเซ็ตขั้น ให้เตือนใหม่ได้ในปีถัดไป
  - ส่งไม่สำเร็จ (SMTP ล่ม) -> ไม่บันทึกขั้น รอบหน้าลองใหม่
"""
import sys
from datetime import date, datetime

AHEAD_DAYS = 30        # ขั้น 1: เหลือไม่เกินกี่วัน (เผื่อเวลาทำเรื่องขออนุมัติงบ)
WARN_DAYS = 7          # ขั้น 2
LAST_DAYS = 1          # ขั้น 3
EXPIRED_WINDOW = 7     # ขั้น 4: ส่งเฉพาะที่หมดไม่เกินกี่วัน


def stage_for(days_left: int) -> int:
    """ขั้นที่ควรได้รับแล้ว ณ วันนี้ · days_left = วันหมดอายุ - วันนี้ (ติดลบ = หมดแล้ว)"""
    if days_left < 0:
        return 4 if days_left >= -EXPIRED_WINDOW else 0
    if days_left <= LAST_DAYS:
        return 3
    if days_left <= WARN_DAYS:
        return 2
    if days_left <= AHEAD_DAYS:
        return 1
    return 0


def _thai(d: date) -> str:
    from app.thai_utils import thai_date
    return thai_date(datetime(d.year, d.month, d.day))


def build_email(school: str, stage: int, end: date, days_left: int, base_url: str) -> tuple:
    from html import escape
    school_h = escape(school or "โรงเรียนของท่าน")
    end_th = _thai(end)
    renew = f"{base_url}/checkout"
    quote = f"{base_url}/quote"
    keep = ("<p><b>ข้อมูลและเอกสารทั้งหมดยังเก็บไว้ครบ</b> ไม่มีอะไรหายไป "
            "ต่ออายุด้วยอีเมลเดิมแล้วใช้งานต่อจากเดิมได้ทันที</p>")
    if stage == 1:
        head = f"อีก {days_left} วัน ระบบจะหมดอายุ"
        body = (f"<p>การใช้งาน Easy Ekkasan ของ <b>{school_h}</b> จะหมดอายุ"
                f"<b>วันที่ {end_th}</b></p>"
                "<p>แจ้งล่วงหน้าเพื่อให้มีเวลาทำเรื่องขออนุมัติงบประมาณ "
                f'หากต้องการใบเสนอราคาไปประกอบการขออนุมัติ <a href="{quote}">ขอได้ที่นี่</a> '
                "ทีมงานส่งให้ทางอีเมลภายใน 1 วันทำการ</p>")
    elif stage == 2:
        head = f"เหลืออีก {days_left} วัน ก่อนระบบหมดอายุ"
        body = (f"<p>การใช้งานของ <b>{school_h}</b> จะหมดอายุ<b>วันที่ {end_th}</b></p>"
                "<p>ต่ออายุก่อนวันดังกล่าวเพื่อใช้งานต่อได้โดยไม่สะดุด</p>")
    elif stage == 3:
        head = ("พรุ่งนี้เป็นวันสุดท้ายของการใช้งาน" if days_left == 1
                else "วันนี้เป็นวันสุดท้ายของการใช้งาน")
        body = (f"<p>การใช้งานของ <b>{school_h}</b> ใช้ได้ถึง<b>วันที่ {end_th}</b> เท่านั้น</p>"
                "<p>หลังจากนั้นจะเข้าใช้งานไม่ได้จนกว่าจะต่ออายุ</p>" + keep)
    else:
        head = "ระบบหมดอายุแล้ว"
        body = (f"<p>การใช้งานของ <b>{school_h}</b> หมดอายุเมื่อวันที่ {end_th}</p>" + keep)
    html = f"""
    <div style="font-family:'Prompt','Sarabun','Leelawadee UI','Segoe UI',Tahoma,sans-serif; max-width:520px; margin:0 auto;">
      <h2 style="color:#2563eb;">{head}</h2>
      {body}
      <p style="text-align:center; margin:26px 0;">
        <a href="{renew}" style="background:#2563eb; color:#fff; text-decoration:none;
           padding:12px 28px; border-radius:10px; font-weight:700;">ต่ออายุการใช้งาน</a>
      </p>
      <p style="color:#64748b; font-size:13px;">ถ้ากดปุ่มไม่ได้ คัดลอกลิงก์นี้ไปเปิด:<br>{renew}</p>
      <p style="color:#94a3b8; font-size:12px;">อีเมลนี้ส่งอัตโนมัติจากระบบ Easy Ekkasan
        ถึงผู้ดูแลบัญชีของโรงเรียน</p>
    </div>"""
    return f"[Easy Ekkasan] {head}", html


def run(dry_run: bool = False, verbose: bool = True, today: date | None = None) -> dict:
    from app.accounts import acc_session, Tenant, audit
    from app.services.mailer import send_email, smtp_configured
    from app.services.retention import _owner_emails, _base_url

    def say(*a):
        if verbose:
            print(*a)

    today = today or date.today()
    base = _base_url()
    sent, reset, failed = [], [], []
    if not dry_run and not smtp_configured():
        say("[member_notice] ยังไม่ได้ตั้งค่า SMTP - ไม่ส่งอีเมล")
        return {"sent": sent, "reset": reset, "failed": failed, "dry_run": dry_run, "smtp": False}

    db = acc_session()
    try:
        tenants = (db.query(Tenant)
                   .filter(Tenant.plan == "member", Tenant.active == True,      # noqa: E712
                           Tenant.expiry_date.isnot(None))
                   .all())
        say(f"[member_notice] ตรวจ {len(tenants)} บัญชีสมาชิก"
            + (" (โหมดดูอย่างเดียว ไม่ส่งจริง)" if dry_run else ""))
        for t in tenants:
            end = t.expiry_date
            left = (end - today).days
            done = t.member_notice_stage or 0
            want = stage_for(left)
            if left > AHEAD_DAYS and done:          # ต่ออายุแล้ว -> เตือนใหม่ได้ปีหน้า
                if not dry_run:
                    t.member_notice_stage = 0
                    db.commit()
                reset.append(t.name)
                continue
            if want == 0 or want <= done:
                continue
            mails = _owner_emails(t.id)
            say(f"  ! ขั้น {want}: {t.name} (หมด {end}, เหลือ {left} วัน) -> {', '.join(mails) or 'ไม่พบอีเมล'}")
            if not mails:
                continue
            if dry_run:
                sent.append((t.name, want))
                continue
            subject, html = build_email(t.name, want, end, left, base)
            ok = False
            for to in mails:
                ok = send_email(to, subject, html) or ok
            if not ok:
                failed.append(t.name)
                continue
            t.member_notice_stage = want
            db.commit()
            audit("member.notice", tenant_id=t.id, target=t.name,
                  detail=f"อีเมลเตือนต่ออายุขั้น {want} · หมด {end} · เหลือ {left} วัน")
            sent.append((t.name, want))
    finally:
        db.close()
    say(f"[member_notice] ส่ง {len(sent)} · ส่งไม่สำเร็จ {len(failed)} · รีเซ็ต {len(reset)}")
    return {"sent": sent, "reset": reset, "failed": failed, "dry_run": dry_run, "smtp": True}


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv or "-n" in sys.argv)
