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
    status = Column(String, default="ใหม่")        # ใหม่ / ตอบแล้ว / ปิด
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
        try:
            conn = _engine.raw_connection(); cur = conn.cursor()
            cur.execute("ALTER TABLE account ADD COLUMN must_change_password BOOLEAN DEFAULT 0")
            conn.commit(); conn.close()
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
                    "must_change": bool(u.must_change_password)}
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
                     expiry_date=None, max_users: int = 3) -> int:
    """สร้างโรงเรียนใหม่ + ผู้ใช้แรก + สร้างไฟล์ฐานข้อมูลของโรงเรียน คืน tenant_id"""
    from app.tenancy import ensure_school_db
    db = acc_session()
    try:
        t = Tenant(name=name.strip(), slug=slug.strip(), expiry_date=expiry_date,
                   max_users=max_users)
        db.add(t); db.flush()
        db.add(Account(tenant_id=t.id, username=admin_user.strip(),
                       password_hash=hash_password(admin_pw), role="user",
                       display_name=name.strip(), must_change_password=True))
        db.commit()
        tid = t.id
    finally:
        db.close()
    ensure_school_db(tid)   # สร้างไฟล์ DB + ตารางของโรงเรียน
    return tid


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
