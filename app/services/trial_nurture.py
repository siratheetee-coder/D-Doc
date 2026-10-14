# -*- coding: utf-8 -*-
"""
trial_nurture.py - อีเมลตามผู้ทดลองใช้ ตามความคืบหน้าจริง (ไม่ใช่ส่งเหมือนกันทุกคน)

  ขั้น 1 (สมัครได้ 1-3 วัน)   ยังไม่ออกเอกสารเลย -> "เริ่มออกเอกสารฉบับแรกใน 3 ขั้น"
                              ออกเอกสารแล้ว      -> ไม่ต้องส่ง
  ขั้น 2 (สมัครได้ 5-8 วัน)   ยังไม่ออกเอกสารเลย -> "ติดตรงไหนบอกเราได้"
                              ออกเอกสารแล้ว      -> "ออกไปแล้ว N ฉบับ ลองงานอื่นด้วย" (บอกงานที่ยังไม่ได้ลอง)
  ขั้น 3 (สมัครได้ 12-18 วัน) ไม่ได้เข้าระบบ 5 วันขึ้นไป -> "ยังเหลือเวลาทดลองอีก X วัน"
                              ยังใช้งานอยู่ -> ไม่ต้องส่ง

  ส่วนอีเมลใกล้หมดเวลาทดลอง (เหลือ 7 วัน / วันสุดท้าย / หมดแล้ว) อยู่ที่ trial_notice.py

กติกา
  - ส่งเฉพาะไอดีหลักที่ยืนยันอีเมลแล้ว · plan = trial · ไม่ถูกระงับ · ยังไม่เข้าช่วงเตือนหมดเวลา
  - จำขั้นที่ผ่านแล้วใน tenant.nurture_stage -> ไม่ส่งซ้ำ · พ้นช่วงของขั้นไปแล้วข้ามเลย ไม่ส่งย้อนหลัง
  - ทุกฉบับมีลิงก์ "ไม่ต้องการรับอีเมลแนะนำ" (ตั้ง nurture_stage = STOPPED) อีเมลเตือนหมดเวลายังส่งตามปกติ
  - ส่งไม่สำเร็จ -> ไม่บันทึกขั้น รอบหน้าลองใหม่

รันพร้อม trial_notice ทุกวัน (cron เดิม ไม่ต้องตั้งเพิ่ม) · ดูก่อนไม่ส่งจริง:
    /opt/ddoc/.venv/bin/python -m app.services.trial_nurture --dry-run
"""
import hashlib
import hmac
import json
import sys
from datetime import date

WINDOWS = {1: (1, 3), 2: (5, 8), 3: (12, 18)}     # ขั้น: (สมัครมาแล้วกี่วัน ตั้งแต่ ถึง)
IDLE_DAYS = 5
STOPPED = 99


# ------------------------------------------------------------------ ลิงก์เลิกรับ
def stop_token(tenant_id) -> str:
    from app.accounts import get_secret_key
    sig = hmac.new(get_secret_key().encode(), f"nurture-stop:{tenant_id}".encode(), hashlib.sha256).hexdigest()[:24]
    return f"{tenant_id}.{sig}"


def stop_by_token(token: str) -> bool:
    from app.accounts import acc_session, Tenant
    tid, _, sig = (token or "").partition(".")
    if not tid.isdigit() or not hmac.compare_digest(stop_token(int(tid)), f"{tid}.{sig}"):
        return False
    db = acc_session()
    try:
        t = db.get(Tenant, int(tid))
        if not t:
            return False
        t.nurture_stage = STOPPED
        db.commit()
        return True
    finally:
        db.close()


# ------------------------------------------------------------------ ความคืบหน้า
def progress(db, tenant_id) -> dict:
    """ออกเอกสารไปกี่ฉบับ · ใช้งานไหนไปแล้วบ้าง"""
    from sqlalchemy import func
    from app.accounts import UsageDay, UsageLifetime
    docs = db.query(func.sum(UsageDay.docs)).filter(UsageDay.tenant_id == tenant_id).scalar() or 0
    life = db.get(UsageLifetime, tenant_id)
    docs += (life.docs or 0) if life else 0
    used = set()
    for (mods,) in db.query(UsageDay.modules).filter(UsageDay.tenant_id == tenant_id):
        try:
            used |= {k for k, v in json.loads(mods or "{}").items() if v}
        except ValueError:
            pass
    return {"docs": int(docs), "modules": used}


def decide(stage_done: int, age_days: int, prog: dict, idle_days: int) -> tuple:
    """(ขั้นที่ถึงแล้ว, แบบอีเมล หรือ None = ข้ามขั้นนี้) · ขั้นที่ถึง 0 = ยังไม่ถึงขั้นไหน"""
    due = 0
    for stage, (lo, _hi) in WINDOWS.items():
        if age_days >= lo:
            due = stage
    if due <= stage_done:
        return 0, None
    lo, hi = WINDOWS[due]
    if age_days > hi:                       # พ้นช่วงไปแล้ว: ไม่ส่งย้อนหลัง แค่จำว่าผ่านขั้นนี้
        return due, None
    started = prog["docs"] > 0
    if due == 1:
        return 1, (None if started else "first_doc")
    if due == 2:
        return 2, ("try_more" if started else "need_help")
    return 3, ("come_back" if idle_days >= IDLE_DAYS else None)


# ------------------------------------------------------------------ เนื้อหาอีเมล
def _btn(href, text):
    return (f'<p style="text-align:center; margin:24px 0;"><a href="{href}" style="background:#2563eb; color:#fff; '
            f'text-decoration:none; padding:12px 28px; border-radius:10px; font-weight:700;">{text}</a></p>')


def build_email(kind: str, school: str, base: str, *, docs: int = 0, unused: list | None = None,
                days_left: int = 0, end_th: str = "", stop_link: str = "", facebook: str = "") -> tuple:
    from html import escape
    s = escape(school or "โรงเรียนของท่าน")
    login = f"{base}/login"
    if kind == "first_doc":
        head = "เริ่มออกเอกสารฉบับแรกได้ใน 3 ขั้น"
        body = (f"<p>ขอบคุณที่ทดลองใช้ Easy Ekkasan ครับ ตอนนี้ <b>{s}</b> ยังไม่ได้ออกเอกสารฉบับแรก "
                "ลองทำตามนี้ ใช้เวลาไม่ถึง 10 นาที</p><ol style='line-height:1.9;'>"
                "<li><b>ตั้งค่าโรงเรียน</b>: ชื่อโรงเรียน ผู้อำนวยการ ที่อยู่ (ขึ้นบนเอกสารทุกฉบับ)</li>"
                "<li><b>เพิ่มบุคลากร</b>: ครูและเจ้าหน้าที่ที่ต้องลงนามในเอกสาร</li>"
                "<li><b>เลือกงานที่ทำบ่อย</b> เช่น งานพัสดุ: สร้างเรื่องจัดซื้อ แล้วกดออกเอกสารครบชุดได้ทันที</li></ol>"
                "<p>หน้าแรกของแต่ละงานมีรายการเริ่มต้นบอกขั้นถัดไปให้ทุกขั้น</p>")
        cta = _btn(login, "เข้าใช้งาน")
    elif kind == "need_help":
        head = "ติดตรงไหน บอกเราได้เลย"
        body = (f"<p><b>{s}</b> สมัครทดลองใช้มาหลายวันแล้ว แต่ยังไม่ได้ออกเอกสาร "
                "ถ้าไม่แน่ใจว่าจะเริ่มจากตรงไหน หรือเอกสารที่ต้องการยังไม่มี บอกเราได้ ทีมงานช่วยตั้งค่าให้</p>"
                "<ul style='line-height:1.9;'><li>กด <b>ติดต่อเจ้าหน้าที่</b> ในระบบ (เมนูด้านซ้าย)</li>"
                f"<li>ดู<a href='{base}/guide'>วิธีใช้งานทีละขั้น</a></li>"
                + (f"<li>ทักทาง <a href='{facebook}'>Facebook</a></li>" if facebook else "") + "</ul>")
        cta = _btn(login, "เข้าใช้งาน")
    elif kind == "try_more":
        head = f"ออกเอกสารไปแล้ว {docs:,} ฉบับ"
        more = ", ".join(unused or [])
        body = (f"<p>เยี่ยมมากครับ <b>{s}</b> ใช้ Easy Ekkasan ออกเอกสารไปแล้ว <b>{docs:,} ฉบับ</b></p>"
                + (f"<p>ช่วงทดลองใช้ลองได้ครบทุกงาน งานที่ยังไม่ได้ลอง: <b>{escape(more)}</b> "
                   "กรอกข้อมูลบุคลากรไว้แล้ว ใช้ร่วมกันได้ทุกงาน ไม่ต้องกรอกซ้ำ</p>" if more else
                   "<p>ท่านลองครบทุกงานแล้ว ถ้ามีเอกสารแบบไหนที่อยากให้ระบบทำเพิ่ม บอกเราได้เลย</p>"))
        cta = _btn(login, "เข้าใช้งานต่อ")
    else:   # come_back
        head = f"ยังเหลือเวลาทดลองใช้อีก {days_left} วัน"
        body = (f"<p>ช่วงทดลองใช้ของ <b>{s}</b> ใช้ได้ถึงวันที่ {end_th} "
                "ข้อมูลที่ทำไว้ยังอยู่ครบ เข้ามาทำต่อได้ทันที</p>"
                "<p>ถ้าติดปัญหาตรงไหน กด <b>ติดต่อเจ้าหน้าที่</b> ในระบบได้เลย</p>")
        cta = _btn(login, "เข้าใช้งานต่อ")
    html = f"""
    <div style="font-family:'Prompt','Sarabun','Leelawadee UI','Segoe UI',Tahoma,sans-serif; max-width:540px; margin:0 auto; color:#1e293b;">
      <h2 style="color:#2563eb;">{head}</h2>
      {body}
      {cta}
      <p style="color:#94a3b8; font-size:12px;">อีเมลนี้ส่งถึงผู้ดูแลบัญชีของโรงเรียนในช่วงทดลองใช้ Easy Ekkasan
        · <a href="{stop_link}" style="color:#94a3b8;">ไม่ต้องการรับอีเมลแนะนำการใช้งาน</a></p>
    </div>"""
    return f"[Easy Ekkasan] {head}", html


# ------------------------------------------------------------------ รัน
def run(dry_run: bool = False, verbose: bool = True, today: date | None = None) -> dict:
    from app.accounts import acc_session, Account, Tenant, audit
    from app.modules import MODULE_KEYS, MODULE_LABELS
    from app.seller_config import SELLER
    from app.services.mailer import send_email, smtp_configured
    from app.services.retention import _base_url
    from app.services.trial_notice import trial_end, WARN_DAYS, _thai

    def say(*a):
        if verbose:
            print(*a)

    today = today or date.today()
    sent, skipped, failed = [], [], []
    if not dry_run and not smtp_configured():
        say("[trial_nurture] ยังไม่ได้ตั้งค่า SMTP - ไม่ส่งอีเมล")
        return {"sent": sent, "skipped": skipped, "failed": failed}
    base = _base_url()
    db = acc_session()
    try:
        tenants = db.query(Tenant).filter(Tenant.plan == "trial", Tenant.active.is_(True)).all()
        for t in tenants:
            done = t.nurture_stage or 0
            if done >= STOPPED or not t.created_at:
                continue
            end = trial_end(t)
            left = (end - today).days
            if left <= WARN_DAYS:                       # ช่วงเตือนหมดเวลา: ให้ trial_notice ทำหน้าที่
                continue
            owners = [a.username for a in db.query(Account).filter_by(tenant_id=t.id, is_owner=True, active=True)
                      if a.verified and "@" in (a.username or "")]
            if not owners:
                continue
            age = (today - t.created_at.date()).days
            idle = (today - t.last_active_at.date()).days if t.last_active_at else age
            prog = progress(db, t.id)
            stage, kind = decide(done, age, prog, idle)
            if not stage:
                continue
            if kind is None:                            # ขั้นนี้ไม่ต้องส่ง (ใช้งานอยู่แล้ว / พ้นช่วง)
                if not dry_run:
                    t.nurture_stage = stage
                    db.commit()
                skipped.append((t.name, stage))
                continue
            say(f"  ! ขั้น {stage} ({kind}): {t.name} สมัครมา {age} วัน · เอกสาร {prog['docs']} -> {', '.join(owners)}")
            if dry_run:
                sent.append((t.name, stage, kind))
                continue
            unused = [MODULE_LABELS.get(k, k) for k in MODULE_KEYS if k not in prog["modules"]]
            subject, html = build_email(kind, t.name, base, docs=prog["docs"], unused=unused, days_left=left,
                                        end_th=_thai(end), facebook=SELLER.get("facebook") or "",
                                        stop_link=f"{base}/email/stop?t={stop_token(t.id)}")
            ok = False
            for to in owners:
                ok = send_email(to, subject, html) or ok
            if not ok:
                failed.append(t.name)
                continue
            t.nurture_stage = stage
            db.commit()
            audit("trial.nurture", tenant_id=t.id, target=t.name, detail=f"อีเมลแนะนำขั้น {stage} ({kind})")
            sent.append((t.name, stage, kind))
    finally:
        db.close()
    say(f"[trial_nurture] ส่ง {len(sent)} · ข้ามขั้น {len(skipped)} · ส่งไม่สำเร็จ {len(failed)}"
        + (" (ดูอย่างเดียว)" if dry_run else ""))
    return {"sent": sent, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    run(dry_run="--dry-run" in sys.argv or "-n" in sys.argv)
