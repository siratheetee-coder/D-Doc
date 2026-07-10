# -*- coding: utf-8 -*-
"""
accounts.py
-----------
ฐานข้อมูลกลาง (data/accounts.db) สำหรับระบบคลาวด์หลายโรงเรียน (SaaS):
- Tenant  : โรงเรียนผู้ใช้บริการ (เปิด/ปิด, วันหมดอายุ)
- Account : ผู้ใช้ล็อกอิน (ผูกกับโรงเรียน) + ผู้ดูแลระบบ (superadmin = ผู้ขาย)

รหัสผ่านเก็บเป็น hash (pbkdf2_hmac, stdlib) ไม่เก็บ plaintext
"""
import os
import hashlib
import secrets
import shutil
from datetime import datetime, date

from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime, Date, ForeignKey, Float, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from app.database import get_data_dir

AccBase = declarative_base()
_engine = None
_Session = None


class Tenant(AccBase):
    """โรงเรียนผู้ใช้บริการ (1 โรงเรียน = 1 ฐานข้อมูลแยก ที่ data/schools/<id>/)"""
    __tablename__ = "tenant"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True)
    active = Column(Boolean, default=True)         # ระงับการใช้งานได้
    expiry_date = Column(Date, nullable=True)      # วันหมดอายุ (None = ไม่จำกัด)
    max_users = Column(Integer, default=3)         # จำนวนผู้ใช้สูงสุดต่อโรงเรียน
    plan = Column(String, default="member")        # trial = ทดลองใช้, member = สมาชิก(จ่ายแล้ว)
    docs_used = Column(Integer, default=0)         # จำนวนเอกสารที่ออกไปแล้ว (ใช้กับ trial)
    docs_limit = Column(Integer, default=0)        # โควตาเอกสารทดลองใช้ (0 = ไม่จำกัด/สมาชิก)
    created_at = Column(DateTime, default=datetime.now)

    accounts = relationship("Account", back_populates="tenant",
                            cascade="all, delete-orphan")


class Account(AccBase):
    """ผู้ใช้ล็อกอิน — role=user ผูกกับโรงเรียน, role=superadmin คือผู้ขาย (ไม่มี tenant)"""
    __tablename__ = "account"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, default="")
    role = Column(String, default="user")          # user / superadmin
    active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)   # บังคับเปลี่ยนรหัสครั้งแรก
    verified = Column(Boolean, default=True)        # ยืนยันอีเมลแล้วหรือยัง (สมัครใหม่ = False ถ้าเปิด SMTP)
    verify_token = Column(String, default="")       # โทเคนยืนยันอีเมล (ล้างเมื่อยืนยันแล้ว)
    created_at = Column(DateTime, default=datetime.now)

    tenant = relationship("Tenant", back_populates="accounts")


class Lead(AccBase):
    """คำขอจากหน้าเว็บสาธารณะ (landing): quote=ขอใบเสนอราคา, order=สั่งซื้อ/แจ้งชำระเงิน
    เก็บในฐานข้อมูลกลาง (ยังไม่ผูกโรงเรียน) — ผู้ขายดูได้ในคอนโซลผู้ดูแลระบบ"""
    __tablename__ = "lead"
    id = Column(Integer, primary_key=True)
    kind = Column(String, default="quote")        # quote / order
    school_name = Column(String, default="")
    address = Column(Text, default="")
    tax_id = Column(String, default="")
    contact_name = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    packages = Column(String, default="")         # งานที่เลือก (ข้อความ)
    amount = Column(Float, default=0.0)
    slip_file = Column(String, default="")        # ชื่อไฟล์สลิป (เฉพาะ order)
    note = Column(Text, default="")
    status = Column(String, default="ใหม่")        # ใหม่ / ตอบแล้ว / ปิด / อนุมัติแล้ว / ทดลองใช้
    tenant_id = Column(Integer, nullable=True)     # โรงเรียนที่สร้างจากคำขอนี้ (หลังอนุมัติ)
    login_user = Column(String, default="")        # ชื่อผู้ใช้ที่สร้างให้ลูกค้า
    created_at = Column(DateTime, default=datetime.now)


class SaleDoc(AccBase):
    """เลขที่เอกสารขาย: quotation=ใบเสนอราคา (QT), receipt=ใบเสร็จ (RC) — 1 lead/kind มีเลขเดียว (กันออกซ้ำ)"""
    __tablename__ = "sale_doc"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, nullable=True)
    kind = Column(String)                          # quotation / receipt
    year = Column(Integer)                         # พ.ศ.
    seq = Column(Integer)
    doc_no = Column(String)
    created_at = Column(DateTime, default=datetime.now)


# ===================== engine / session =====================
def _ensure_engine():
    global _engine, _Session
    if _engine is None:
        path = get_data_dir() / "accounts.db"
        _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        AccBase.metadata.create_all(bind=_engine)
        # เพิ่มคอลัมน์ใหม่บน accounts.db เก่า (ปลอดภัย: ข้ามถ้ามีแล้ว)
        for sql in ("ALTER TABLE account ADD COLUMN must_change_password BOOLEAN DEFAULT 0",
                    "ALTER TABLE lead ADD COLUMN tenant_id INTEGER",
                    "ALTER TABLE lead ADD COLUMN login_user VARCHAR DEFAULT ''",
                    "ALTER TABLE tenant ADD COLUMN plan VARCHAR DEFAULT 'member'",
                    "ALTER TABLE tenant ADD COLUMN docs_used INTEGER DEFAULT 0",
                    "ALTER TABLE tenant ADD COLUMN docs_limit INTEGER DEFAULT 0",
                    "ALTER TABLE account ADD COLUMN verified BOOLEAN DEFAULT 1",
                    "ALTER TABLE account ADD COLUMN verify_token VARCHAR DEFAULT ''"):
            try:
                conn = _engine.raw_connection(); cur = conn.cursor()
                cur.execute(sql); conn.commit(); conn.close()
            except Exception:
                pass
        _Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
    return _engine


def acc_session():
    _ensure_engine()
    return _Session()


# ===================== รหัสผ่าน =====================
def hash_password(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${h}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt, h = (stored or "").split("$", 1)
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 200_000).hex()
        return secrets.compare_digest(calc, h)
    except Exception:
        return False


def change_password(uid: int, current_pw: str, new_pw: str) -> tuple[bool, str]:
    """เปลี่ยนรหัสผ่านของผู้ใช้เอง (ตรวจรหัสเดิมก่อน) คืน (สำเร็จ, ข้อความ)"""
    if len(new_pw or "") < 6:
        return False, "รหัสผ่านใหม่ต้องยาวอย่างน้อย 6 ตัวอักษร"
    db = acc_session()
    try:
        u = db.get(Account, uid)
        if not u:
            return False, "ไม่พบบัญชีผู้ใช้"
        if not verify_password(current_pw, u.password_hash):
            return False, "รหัสผ่านเดิมไม่ถูกต้อง"
        u.password_hash = hash_password(new_pw)
        u.must_change_password = False
        db.commit()
        return True, "เปลี่ยนรหัสผ่านเรียบร้อยแล้ว"
    finally:
        db.close()


def authenticate(username: str, password: str) -> dict | None:
    """ตรวจ user/password คืน dict ข้อมูลผู้ใช้ (ตัดการผูก ORM) หรือ None"""
    db = acc_session()
    try:
        u = (db.query(Account)
             .filter_by(username=(username or "").strip(), active=True).first())
        if u and verify_password(password, u.password_hash):
            return {"uid": u.id, "username": u.username, "role": u.role,
                    "tenant_id": u.tenant_id, "display_name": u.display_name,
                    "must_change": bool(u.must_change_password),
                    "verified": bool(getattr(u, "verified", True))}
        return None
    finally:
        db.close()


# ===================== สถานะโรงเรียน (ใช้ใน middleware) =====================
def tenant_state(tenant_id) -> dict | None:
    """คืนสถานะโรงเรียน {name, active, expired} หรือ None ถ้าไม่พบ"""
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return None
        expired = bool(t.expiry_date and t.expiry_date < date.today())
        return {"name": t.name, "active": bool(t.active), "expired": expired,
                "expiry_date": t.expiry_date}
    finally:
        db.close()


def tenant_status(tenant_id) -> dict | None:
    """สถานะแพ็กเกจสำหรับแสดงในแอป:
    trial -> {plan:'trial', docs_left, docs_limit, docs_used}
    member -> {plan:'member', days_left, expiry_date, unlimited}"""
    if not tenant_id:
        return None
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return None
        plan = t.plan or "member"
        if plan == "trial" and (t.docs_limit or 0) > 0:
            used = t.docs_used or 0
            return {"plan": "trial", "docs_limit": t.docs_limit,
                    "docs_used": used, "docs_left": max(0, t.docs_limit - used)}
        if not t.expiry_date:
            return {"plan": "member", "days_left": None, "expiry_date": None, "unlimited": True}
        return {"plan": "member", "days_left": (t.expiry_date - date.today()).days,
                "expiry_date": t.expiry_date, "unlimited": False}
    finally:
        db.close()


def ai_key_for(tenant_id) -> str:
    """คืน AI key กลาง (หลังบ้าน) เฉพาะโรงเรียนที่เป็นสมาชิก (จ่ายแล้ว ไม่ใช่ trial)
    มิฉะนั้นคืน '' (ปิด AI) — key ไม่เคยผูก per-tenant/ไม่ส่งถึง client"""
    from app.seller_config import SELLER
    key = (SELLER.get("ai_api_key") or "").strip()
    if not key or not tenant_id:
        return ""
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t or (t.plan or "member") == "trial":
            return ""
        return key
    finally:
        db.close()


def consume_doc_quota(tenant_id) -> tuple:
    """เรียกก่อนออกเอกสาร: ถ้าเป็น trial ยังไม่ครบโควตา -> +1 คืน (True, info)
    ถ้าครบโควตา -> (False, info) · สมาชิก/ไม่มี tenant -> (True, None)"""
    if not tenant_id:
        return True, None
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t or (t.plan or "member") != "trial" or not (t.docs_limit or 0):
            return True, None
        used = t.docs_used or 0
        if used >= t.docs_limit:
            return False, {"used": used, "limit": t.docs_limit}
        t.docs_used = used + 1
        db.commit()
        return True, {"used": t.docs_used, "limit": t.docs_limit}
    finally:
        db.close()


# ===================== คำขอจากหน้าเว็บ (leads) =====================
def add_lead(**fields) -> int:
    """บันทึกคำขอ (ขอใบเสนอราคา/สั่งซื้อ) จากหน้าเว็บสาธารณะ คืน id"""
    db = acc_session()
    try:
        lead = Lead(**{k: v for k, v in fields.items() if hasattr(Lead, k)})
        db.add(lead); db.commit()
        return lead.id
    finally:
        db.close()


def list_leads(kind: str | None = None) -> list[dict]:
    """รายการคำขอทั้งหมด (ใหม่ก่อน) แบบ dict (ตัดการผูก ORM)"""
    db = acc_session()
    try:
        q = db.query(Lead).order_by(Lead.id.desc())
        if kind:
            q = q.filter_by(kind=kind)
        return [{c.name: getattr(l, c.name) for c in Lead.__table__.columns} for l in q.all()]
    finally:
        db.close()


def set_lead_status(lead_id: int, status: str) -> None:
    db = acc_session()
    try:
        l = db.get(Lead, lead_id)
        if l:
            l.status = status; db.commit()
    finally:
        db.close()


def count_new_leads() -> int:
    db = acc_session()
    try:
        return db.query(Lead).filter_by(status="ใหม่").count()
    finally:
        db.close()


def get_lead(lead_id: int) -> dict | None:
    db = acc_session()
    try:
        l = db.get(Lead, lead_id)
        if not l:
            return None
        return {c.name: getattr(l, c.name) for c in Lead.__table__.columns}
    finally:
        db.close()


def issue_sale_doc(kind: str, lead_id: int, year: int) -> dict:
    """คืนเลขที่เอกสารของ lead+kind นี้ (ถ้ามีแล้วใช้ซ้ำ ไม่มีก็สร้างเลขถัดไปของปีนั้น)
    kind: quotation -> QT-<ปีพ.ศ.>-0001, receipt -> RC-<ปีพ.ศ.>-0001"""
    db = acc_session()
    try:
        exist = (db.query(SaleDoc).filter_by(kind=kind, lead_id=lead_id)
                 .order_by(SaleDoc.id.desc()).first())
        if exist:
            return {"doc_no": exist.doc_no, "seq": exist.seq, "created_at": exist.created_at}
        last = (db.query(SaleDoc).filter_by(kind=kind, year=year)
                .order_by(SaleDoc.seq.desc()).first())
        seq = (last.seq if last else 0) + 1
        prefix = "QT" if kind == "quotation" else "RC"
        doc_no = f"{prefix}-{year}-{seq:04d}"
        d = SaleDoc(lead_id=lead_id, kind=kind, year=year, seq=seq, doc_no=doc_no)
        db.add(d); db.commit()
        return {"doc_no": doc_no, "seq": seq, "created_at": d.created_at}
    finally:
        db.close()


# ===================== จัดการโรงเรียน/ผู้ใช้ (super-admin) =====================
def provision_tenant(name: str, slug: str, admin_user: str, admin_pw: str,
                     expiry_date=None, max_users: int = 3, must_change: bool = True,
                     plan: str = "member", docs_limit: int = 0) -> int:
    """สร้างโรงเรียนใหม่ + ผู้ใช้แรก + สร้างไฟล์ฐานข้อมูลของโรงเรียน คืน tenant_id"""
    from app.tenancy import ensure_school_db
    db = acc_session()
    try:
        t = Tenant(name=name.strip(), slug=slug.strip(), expiry_date=expiry_date,
                   max_users=max_users, plan=plan, docs_limit=docs_limit)
        db.add(t); db.flush()
        db.add(Account(tenant_id=t.id, username=admin_user.strip(),
                       password_hash=hash_password(admin_pw), role="user",
                       display_name=name.strip(), must_change_password=must_change))
        db.commit()
        tid = t.id
    finally:
        db.close()
    ensure_school_db(tid)   # สร้างไฟล์ DB + ตารางของโรงเรียน
    return tid


# ===================== สร้างบัญชีจากคำขอ (B) + ทดลองใช้ฟรี (A) =====================
def _slugify_acc(s: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "school"


def _uniq_username(db, base: str) -> str:
    base = (base or "school")[:20]
    u, n = base, 1
    while db.query(Account).filter_by(username=u).first():
        n += 1; u = f"{base}{n}"
    return u


def _uniq_slug(db, base: str) -> str:
    base = base or "school"
    s, n = base, 1
    while db.query(Tenant).filter_by(slug=s).first():
        n += 1; s = f"{base}-{n}"
    return s


def _gen_password(length: int = 8) -> str:
    import secrets, string
    alpha = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alpha) for _ in range(length))


def username_available(username: str) -> bool:
    db = acc_session()
    try:
        return not db.query(Account).filter_by(username=(username or "").strip()).first()
    finally:
        db.close()


import re as _re
_EMAIL_RE = _re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def account_by_email(email: str):
    """คืน dict บัญชี {uid, username, tenant_id, ...} จากอีเมล (username) หรือ None"""
    db = acc_session()
    try:
        a = db.query(Account).filter_by(username=(email or "").strip().lower()).first()
        if not a:
            return None
        return {"uid": a.id, "username": a.username, "tenant_id": a.tenant_id,
                "display_name": a.display_name, "must_change": bool(a.must_change_password)}
    finally:
        db.close()


TRIAL_DOC_LIMIT = 50   # ทดลองใช้: ออกเอกสารฟรีได้กี่ฉบับ (นับรวมทุกงาน)


def register_account(email: str, password: str, school_name: str,
                     contact_name: str = "", phone: str = "", trial_days: int = 14) -> dict:
    """ลงทะเบียน: อีเมล = ชื่อผู้ใช้, ตั้งรหัสเอง -> ทดลองใช้ (ออกเอกสารฟรี TRIAL_DOC_LIMIT ฉบับ ไม่จำกัดเวลา) + auto-login
    อีเมลเดิมใช้เป็น username ตลอด (ต่ออายุก็อีเมลนี้) · คืน {uid, tenant_id, username, display_name} หรือ {error}"""
    from datetime import date, timedelta
    email = (email or "").strip().lower()
    school_name = (school_name or "").strip()
    if not _EMAIL_RE.match(email):
        return {"error": "อีเมลไม่ถูกต้อง"}
    if len(password or "") < 6:
        return {"error": "รหัสผ่านต้องยาวอย่างน้อย 6 ตัวอักษร"}
    if not school_name:
        return {"error": "กรุณากรอกชื่อโรงเรียน"}
    db = acc_session()
    try:
        if db.query(Account).filter_by(username=email).first():
            return {"error": "อีเมลนี้ลงทะเบียนแล้ว กรุณาเข้าสู่ระบบ", "exists": True}
        slug = _uniq_slug(db, _slugify_acc(email.split("@")[0]))
    finally:
        db.close()
    # ทดลองใช้: ไม่จำกัดเวลา (expiry=None) แต่จำกัดจำนวนเอกสารที่ออก
    tid = provision_tenant(school_name, slug, email, password, expiry_date=None,
                           max_users=3, must_change=False, plan="trial",
                           docs_limit=TRIAL_DOC_LIMIT)
    import secrets
    from app.services.mailer import smtp_configured
    need_verify = smtp_configured()
    token = secrets.token_urlsafe(24) if need_verify else ""
    db = acc_session()
    try:
        acc = db.query(Account).filter_by(username=email).first()
        if need_verify:
            acc.verified = False
            acc.verify_token = token
        db.add(Lead(kind="trial", school_name=school_name, contact_name=contact_name.strip(),
                    email=email, phone=phone.strip(), tenant_id=tid,
                    login_user=email, status="ทดลองใช้"))
        db.commit()
        return {"uid": acc.id, "tenant_id": tid, "username": email, "display_name": school_name,
                "needs_verify": need_verify, "verify_token": token, "email": email}
    finally:
        db.close()


def verify_email(token: str) -> dict | None:
    """ยืนยันอีเมลจากโทเคน -> เปิดใช้งานบัญชี คืนข้อมูลบัญชี (สำหรับ auto-login) หรือ None"""
    token = (token or "").strip()
    if not token:
        return None
    db = acc_session()
    try:
        a = db.query(Account).filter_by(verify_token=token).first()
        if not a:
            return None
        a.verified = True
        a.verify_token = ""
        db.commit()
        return {"uid": a.id, "username": a.username, "role": a.role,
                "tenant_id": a.tenant_id, "display_name": a.display_name}
    finally:
        db.close()


def new_verify_token(email: str) -> str | None:
    """ออกโทเคนยืนยันใหม่ (สำหรับส่งอีเมลซ้ำ) คืนโทเคน หรือ None ถ้าไม่พบ/ยืนยันแล้ว"""
    import secrets
    db = acc_session()
    try:
        a = db.query(Account).filter_by(username=(email or "").strip().lower()).first()
        if not a or a.verified:
            return None
        a.verify_token = secrets.token_urlsafe(24)
        db.commit()
        return a.verify_token
    finally:
        db.close()


def renew_lead(lead_id: int, days: int = 365) -> dict | None:
    """(B) อนุมัติคำสั่งซื้อ -> ต่ออายุบัญชีเดิมของลูกค้า +days (ไม่สร้างบัญชีใหม่ ใช้อีเมลเดิม)
    หา tenant จาก lead.tenant_id ก่อน ถ้าไม่มีลองจับคู่จากอีเมล · คืน {username, tenant_id, expiry} หรือ {error}"""
    from datetime import date, timedelta
    db = acc_session()
    try:
        lead = db.get(Lead, lead_id)
        if not lead:
            return None
        tid = lead.tenant_id
        email = (lead.email or "").strip().lower()
        if not tid and email:
            a = db.query(Account).filter_by(username=email).first()
            tid = a.tenant_id if a else None
        if not tid:
            return {"error": "คำสั่งซื้อนี้ไม่ได้ผูกกับบัญชี — ลูกค้าต้องลงทะเบียน/เข้าสู่ระบบก่อนสั่งซื้อ"}
        t = db.get(Tenant, tid)
        if not t:
            return {"error": "ไม่พบบัญชีโรงเรียน"}
        base = t.expiry_date if (t.expiry_date and t.expiry_date >= date.today()) else date.today()
        t.expiry_date = base + timedelta(days=days)
        t.active = True
        t.plan = "member"          # อัปเกรดจากทดลองใช้ -> สมาชิก
        t.docs_limit = 0           # สมาชิก: ออกเอกสารไม่จำกัด
        acc = db.query(Account).filter_by(tenant_id=tid).first()
        lead.tenant_id = tid
        lead.login_user = acc.username if acc else email
        lead.status = "ต่ออายุแล้ว"
        db.commit()
        return {"tenant_id": tid, "username": lead.login_user, "expiry": t.expiry_date.isoformat()}
    finally:
        db.close()


# ===================== bootstrap ตอนเริ่มระบบ =====================
def get_secret_key() -> str:
    """คีย์เซ็นคุกกี้ session (เก็บไฟล์ data/secret.key สร้างครั้งเดียว)"""
    p = get_data_dir() / "secret.key"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    p.write_text(key, encoding="utf-8")
    return key


def bootstrap():
    """เริ่มระบบ: สร้าง accounts.db, superadmin เริ่มต้น, และย้ายข้อมูลเดิม (ถ้ามี) เป็นโรงเรียนแรก"""
    # ฟรีทีเออร์ (ดิสก์ชั่วคราว): ถ้าดิสก์ว่าง แต่มีสำรองบนคลาวด์ -> กู้คืนก่อน กันข้อมูลหายตอน deploy ใหม่
    if not (get_data_dir() / "accounts.db").exists():
        try:
            from app.services.backup import restore_latest_from_s3
            restore_latest_from_s3()
        except Exception as e:
            print("[D-Doc] กู้คืนจากคลาวด์ตอนเปิดไม่สำเร็จ:", e)
    _ensure_engine()
    db = acc_session()
    try:
        # 1) superadmin เริ่มต้น (ผู้ขาย) — เปลี่ยนรหัสได้ภายหลัง
        if not db.query(Account).filter_by(role="superadmin").first():
            su = os.environ.get("DDOC_SUPERADMIN", "admin")
            sp = os.environ.get("DDOC_SUPERADMIN_PW", "admin123")
            db.add(Account(username=su, password_hash=hash_password(sp),
                           role="superadmin", display_name="ผู้ดูแลระบบ",
                           must_change_password=True))
            db.commit()
            print(f"[D-Doc] สร้าง superadmin เริ่มต้น: {su} / {sp}  (โปรดเปลี่ยนรหัสผ่าน)")

        has_tenant = db.query(Tenant).first() is not None
    finally:
        db.close()

    # 2) ย้ายฐานข้อมูลเดิม (data/school.db) เป็นโรงเรียนแรก (ครั้งเดียว)
    if not has_tenant:
        _migrate_legacy_db()

    # 3) ตั้ง baseline ของระบบสำรอง = สถานะตอนเปิดเครื่อง
    #    -> ตัวจับเวลาจะอัปขึ้นคลาวด์ "เฉพาะเมื่อข้อมูลเปลี่ยนหลังจากนี้" (ประหยัด bandwidth)
    try:
        from app.services.backup import mark_synced
        mark_synced()
    except Exception:
        pass


def _migrate_legacy_db():
    """ถ้ามี data/school.db เดิม -> สร้างโรงเรียนแรกแล้วย้ายไฟล์เข้า data/schools/<id>/
    ถ้าไม่มีข้อมูลเดิม (deploy ใหม่บนคลาวด์) -> ไม่สร้างอะไร ให้ superadmin สร้างโรงเรียนเองผ่านคอนโซล"""
    from app.tenancy import school_db_path, ensure_school_db
    legacy = get_data_dir() / "school.db"
    if not legacy.exists():
        return
    name = "โรงเรียนของฉัน"
    if legacy.exists():
        # อ่านชื่อโรงเรียนจาก DB เดิม (ถ้าอ่านได้)
        try:
            eng = create_engine(f"sqlite:///{legacy}", connect_args={"check_same_thread": False})
            with eng.connect() as c:
                row = c.exec_driver_sql("SELECT name FROM school LIMIT 1").fetchone()
                if row and row[0]:
                    name = row[0]
            eng.dispose()
        except Exception:
            pass

    db = acc_session()
    try:
        t = Tenant(name=name, slug="rongrian-1", max_users=3)
        db.add(t); db.flush()
        db.add(Account(tenant_id=t.id, username="school", password_hash=hash_password("school123"),
                       role="user", display_name=name, must_change_password=True))
        db.commit()
        tid = t.id
    finally:
        db.close()

    dest = school_db_path(tid)
    if legacy.exists() and not dest.exists():
        shutil.copy2(legacy, dest)              # คัดลอกข้อมูลเดิมเข้าโรงเรียนแรก
        print(f"[D-Doc] ย้ายข้อมูลเดิมเป็นโรงเรียน '{name}' (id={tid})")
    ensure_school_db(tid)
    print(f"[D-Doc] โรงเรียนแรก: ผู้ใช้ school / school123  (โปรดเปลี่ยนรหัสผ่าน)")
