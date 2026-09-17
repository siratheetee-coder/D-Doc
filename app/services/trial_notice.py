# -*- coding: utf-8 -*-
"""
trial_notice.py - อีเมลเตือนเจ้าของบัญชีเมื่อทดลองใช้ใกล้หมด/หมดแล้ว

ส่ง 3 ครั้ง (ไปที่ไอดีหลักของโรงเรียน ชื่อผู้ใช้ = อีเมลตอนสมัคร):
    1 = เหลือไม่เกิน 7 วัน
    2 = วันสุดท้ายหรือก่อนวันสุดท้าย 1 วัน
    3 = หมดแล้ว (ข้อมูลยังอยู่ครบ สมัครแล้วใช้ต่อได้)

รันจาก cron วันละครั้ง:
    /opt/ddoc/.venv/bin/python -m app.services.trial_notice
ดูก่อนว่าจะส่งหาใครโดยไม่ส่งจริง:
    /opt/ddoc/.venv/bin/python -m app.services.trial_notice --dry-run

กติกา:
  - ส่งเฉพาะ plan='trial' ที่ยังไม่ถูกระงับ · สมัครสมาชิกแล้ว (plan='member') ไม่ส่ง
  - จำขั้นที่ส่งแล้วใน tenant.trial_notice_stage -> รันซ้ำกี่รอบก็ไม่ส่งซ้ำ
  - ข้ามขั้นได้ (เช่น สมัครทีหลังจนเหลือ 1 วันเลย) ส่งเฉพาะขั้นล่าสุดขั้นเดียว
  - หมดมานานเกิน EXPIRED_WINDOW วันแล้วไม่ส่ง (กันอีเมลย้อนหลังถล่มตอนเปิดใช้ครั้งแรก)
  - ถูกขยายเวลาทดลองจนเหลือเกิน 7 วัน -> รีเซ็ตขั้น ให้เตือนใหม่ได้
  - ส่งไม่สำเร็จ (SMTP ล่ม) -> ไม่บันทึกขั้น รอบหน้าลองใหม่
"""
import sys
from datetime import date, datetime, timedelta

WARN_DAYS = 7          # ขั้น 1: เหลือไม่เกินกี่วัน
LAST_DAYS = 1          # ขั้น 2: เหลือไม่เกินกี่วัน
EXPIRED_WINDOW = 7     # ขั้น 3: ส่งเฉพาะที่หมดไม่เกินกี่วัน


def trial_end(t) -> date:
    """วันสุดท้ายที่ยังใช้ได้ (ตรงกับ accounts._trial_ok: ใช้ได้ถึง <= วันนี้)"""
    from app.accounts import TRIAL_DAYS
    if t.trial_expiry_date:
        return t.trial_expiry_date
    if t.expiry_date:
        return t.expiry_date
    base = t.created_at.date() if t.created_at else date.today()
    return base + timedelta(days=TRIAL_DAYS)


def stage_for(days_left: int) -> int:
    """ขั้นที่ควรได้รับแล้ว ณ วันนี้ · days_left = วันสุดท้าย - วันนี้ (ติดลบ = หมดแล้ว)"""
    if days_left < 0:
        return 3 if days_left >= -EXPIRED_WINDOW else 0
    if days_left <= LAST_DAYS:
        return 2
    if days_left <= WARN_DAYS:
        return 1
    return 0


def _thai(d: date) -> str:
    from app.thai_utils import thai_date
    return thai_date(datetime(d.year, d.month, d.day))


def build_email(school: str, stage: int, end: date, days_left: int, base_url: str) -> tuple:
    from html import escape
    school_h = escape(school or "โรงเรียนของท่าน")
    end_th = _thai(end)
    buy = f"{base_url}/checkout"
    if stage == 1:
        head = f"เหลือเวลาทดลองใช้อีก {days_left} วัน"
        body = (f"<p>ช่วงทดลองใช้ Easy Ekkasan ของ <b>{school_h}</b> จะสิ้นสุดใน<b>วันที่ {end_th}</b></p>"
                "<p>สมัครสมาชิกก่อนวันดังกล่าว เพื่อใช้งานต่อได้ทันทีโดยไม่สะดุด "
                "ข้อมูลและเอกสารที่ทำไว้ทั้งหมดยังอยู่ครบ</p>")
    elif stage == 2:
        head = "พรุ่งนี้เป็นวันสุดท้ายของการทดลองใช้" if days_left == 1 else "วันนี้เป็นวันสุดท้ายของการทดลองใช้"
        body = (f"<p>ช่วงทดลองใช้ของ <b>{school_h}</b> ใช้งานได้ถึง<b>วันที่ {end_th}</b> เท่านั้น</p>"
                "<p>หลังจากนั้นจะเข้าใช้งานไม่ได้จนกว่าจะสมัครสมาชิก "
                "ข้อมูลที่ทำไว้ยังเก็บอยู่ครบ ไม่หายไปไหน</p>")
    else:
        head = "ช่วงทดลองใช้สิ้นสุดแล้ว"
        body = (f"<p>ช่วงทดลองใช้ของ <b>{school_h}</b> สิ้นสุดเมื่อวันที่ {end_th}</p>"
                "<p><b>ข้อมูลและเอกสารทั้งหมดยังเก็บไว้ครบ</b> สมัครสมาชิกแล้วเข้าใช้งานต่อจากเดิมได้ทันที</p>")
    html = f"""
    <div style="font-family:sans-serif; max-width:520px; margin:0 auto;">
      <h2 style="color:#2563eb;">{head}</h2>
      {body}
      <p style="text-align:center; margin:26px 0;">
        <a href="{buy}" style="background:#2563eb; color:#fff; text-decoration:none;
           padding:12px 28px; border-radius:10px; font-weight:700;">สมัครสมาชิก</a>
      </p>
      <p style="color:#64748b; font-size:13px;">ถ้ากดปุ่มไม่ได้ คัดลอกลิงก์นี้ไปเปิด:<br>{buy}</p>
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
        say("[trial_notice] ยังไม่ได้ตั้งค่า SMTP - ไม่ส่งอีเมล")
        return {"sent": sent, "reset": reset, "failed": failed, "dry_run": dry_run, "smtp": False}

    db = acc_session()
    try:
        tenants = db.query(Tenant).filter(Tenant.plan == "trial", Tenant.active == True).all()  # noqa: E712
        say(f"[trial_notice] ตรวจ {len(tenants)} บัญชีทดลองใช้"
            + (" (โหมดดูอย่างเดียว ไม่ส่งจริง)" if dry_run else ""))
        for t in tenants:
            end = trial_end(t)
            left = (end - today).days
            done = t.trial_notice_stage or 0
            want = stage_for(left)
            if left > WARN_DAYS and done:           # ถูกขยายเวลาทดลอง -> เตือนใหม่ได้
                if not dry_run:
                    t.trial_notice_stage = 0
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
            t.trial_notice_stage = want
            db.commit()
            audit("trial.notice", tenant_id=t.id, target=t.name,
                  detail=f"อีเมลเตือนทดลองใช้ขั้น {want} · หมด {end} · เหลือ {left} วัน")
            sent.append((t.name, want))
    finally:
        db.close()
    say(f"[trial_notice] ส่ง {len(sent)} · ส่งไม่สำเร็จ {len(failed)} · รีเซ็ต {len(reset)}")
    return {"sent": sent, "reset": reset, "failed": failed, "dry_run": dry_run, "smtp": True}


if __name__ == "__main__":
    run(dry_run="--dry-run" in sys.argv or "-n" in sys.argv)
