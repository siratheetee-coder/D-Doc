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
    create_engine, event, Column, Integer, String, Boolean, DateTime, Date, ForeignKey,
    Float, LargeBinary, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

from app.database import get_data_dir
from app.modules import ALL_MODULES_CSV, MODULE_KEYS, modules_csv, modules_from_label, parse_modules

AccBase = declarative_base()
_engine = None
_Session = None


class Tenant(AccBase):
    """โรงเรียนผู้ใช้บริการ (1 โรงเรียน = 1 ฐานข้อมูลแยก ที่ data/schools/<id>/)"""
    __tablename__ = "tenant"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    slug = Column(String, unique=True)
    teacher_code = Column(String, nullable=True)   # รหัสต่อท้ายไอดีครู (owner ตั้งเอง) เช่น 104 -> teacher1.104 · unique ทั้งระบบ
    active = Column(Boolean, default=True)         # ระงับการใช้งานได้
    expiry_date = Column(Date, nullable=True)      # วันหมดอายุ (None = ไม่จำกัด)
    trial_expiry_date = Column(Date, nullable=True)  # วันสิ้นสุดทดลองเดิม ไม่เปลี่ยนเมื่อซื้อ/ต่ออายุ
    max_users = Column(Integer, default=3)         # จำนวนผู้ใช้สูงสุดต่อโรงเรียน
    plan = Column(String, default="member")        # trial = ทดลองใช้, member = สมาชิก(จ่ายแล้ว)
    docs_used = Column(Integer, default=0)         # จำนวนเอกสารที่ออกไปแล้ว (ใช้กับโควตาทดลอง)
    docs_limit = Column(Integer, default=0)        # โควตาเอกสารทดลองใช้ (0 = ไม่จำกัด/ซื้อครบแล้ว)
    # งานที่ "ซื้อแล้ว" (CSV) - ไม่ใช่ "งานที่เข้าได้" · ว่าง = ยังไม่ซื้อ ใช้สิทธิ์ทดลองอยู่
    # สิทธิ์เข้าใช้จริง = ซื้อแล้ว OR โควตาทดลองยังเหลือ (ดู can_use_module)
    modules = Column(String, default="")
    created_at = Column(DateTime, default=datetime.now)
    # ---- นโยบายลบข้อมูลเมื่อไม่มีการใช้งาน (ดู app/services/retention.py) ----
    policy_accepted_at = Column(DateTime, nullable=True)   # ยอมรับนโยบายความเป็นส่วนตัวเมื่อไหร่
    policy_version = Column(String, default="")            # ฉบับที่ยอมรับ (วันที่ปรับปรุงนโยบาย)
    policy_accept_ip = Column(String, default="")          # ยอมรับจากไอพีไหน
    last_active_at = Column(DateTime, nullable=True)   # ล็อกอินล่าสุดของคนใดคนหนึ่งในโรงเรียน
    inactive_stage = Column(Integer, default=0)        # เตือนไปแล้วกี่ครั้ง (0-3) · ใช้งานอีกครั้ง = รีเซ็ต
    inactive_notified_at = Column(DateTime, nullable=True)  # เตือนครั้งล่าสุดเมื่อไหร่

    accounts = relationship("Account", back_populates="tenant",
                            cascade="all, delete-orphan")


class Account(AccBase):
    """ผู้ใช้ล็อกอิน - role=user ผูกกับโรงเรียน, role=superadmin คือผู้ขาย (ไม่มี tenant)"""
    __tablename__ = "account"
    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenant.id"), nullable=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    display_name = Column(String, default="")
    role = Column(String, default="user")          # user / superadmin
    active = Column(Boolean, default=True)
    is_owner = Column(Boolean, default=False)       # ไอดีหลักของโรงเรียน: เห็นทุกงาน + จัดการผู้ใช้ได้
    is_director = Column(Boolean, default=False)    # ผอ./รองผอ.: อนุมัติแผนการสอน/ลา/ไปราชการ (ลงนามขั้นสุดท้าย)
    modules = Column(String, default="")            # งานที่ไอดีย่อยเข้าได้ (CSV) · owner ไม่ใช้ (เห็นทุกงาน)
    person_id = Column(Integer, nullable=True)      # บัญชีครู: ผูกกับ Person.id ใน DB โรงเรียน -> สิทธิ์เฉพาะวิชา/ห้องตัวเอง
    welcomed = Column(Boolean, default=False)       # เห็นการ์ดต้อนรับ/แนะนำจัดการผู้ใช้ตอนล็อกอินครั้งแรกแล้ว
    seen_modules = Column(String, default="")       # งานที่ไอดีหลักรับรู้แล้ว (เทียบกับที่ซื้อ -> แจ้งเตือนงานที่ซื้อเพิ่ม)
    must_change_password = Column(Boolean, default=False)   # บังคับเปลี่ยนรหัสครั้งแรก
    verified = Column(Boolean, default=True)        # ยืนยันอีเมลแล้วหรือยัง (สมัครใหม่ = False ถ้าเปิด SMTP)
    avatar = Column(LargeBinary, nullable=True)     # รูปโปรไฟล์ (JPEG ย่อ 256px) - ว่าง = ใช้อักษรย่อแทน
    last_seen_at = Column(DateTime, nullable=True)  # ใช้งานล่าสุด (ดูว่าใครออนไลน์ก่อนรีสตาร์ท)
    last_path = Column(String, default="")          # หน้าล่าสุดที่เปิด (บอกว่ากำลังทำงานอะไร)
    # ---- ยืนยันตัวตน 2 ชั้น (TOTP) · สมัครใจ ไม่บังคับ ----
    totp_secret = Column(String, default="")        # คีย์ลับ (มีตั้งแต่ตอนเริ่มตั้งค่า แต่ยังไม่เปิดใช้)
    totp_enabled = Column(Boolean, default=False)   # เปิดใช้จริงแล้ว (ยืนยันรหัสจากแอปสำเร็จ)
    totp_last_step = Column(Integer, default=0)     # step ล่าสุดที่ใช้ - กันใช้รหัสเดิมซ้ำ
    totp_recovery = Column(String, default="")      # รหัสสำรอง (เก็บเป็น sha256 ไม่ใช่ตัวรหัส)
    verify_token = Column(String, default="")       # โทเคนยืนยันอีเมล (ล้างเมื่อยืนยันแล้ว)
    reset_token = Column(String, default="")        # โทเคนรีเซ็ตรหัสผ่าน (ล้างเมื่อใช้แล้ว)
    reset_expires = Column(DateTime, nullable=True)  # วันหมดอายุของลิงก์รีเซ็ต
    created_at = Column(DateTime, default=datetime.now)

    tenant = relationship("Tenant", back_populates="accounts")


class Lead(AccBase):
    """คำขอจากหน้าเว็บสาธารณะ (landing): quote=ขอใบเสนอราคา, order=สั่งซื้อ/แจ้งชำระเงิน
    เก็บในฐานข้อมูลกลาง (ยังไม่ผูกโรงเรียน) - ผู้ขายดูได้ในคอนโซลผู้ดูแลระบบ"""
    __tablename__ = "lead"
    id = Column(Integer, primary_key=True)
    kind = Column(String, default="quote")        # quote / order
    school_name = Column(String, default="")
    address = Column(Text, default="")
    tax_id = Column(String, default="")
    contact_name = Column(String, default="")
    email = Column(String, default="")
    phone = Column(String, default="")
    packages = Column(String, default="")         # งานที่เลือก (ข้อความ - ใช้แสดงผล/ใบเสนอราคา)
    modules = Column(String, default="")          # งานที่เลือก (CSV - ค่าที่ระบบใช้จริงตอนอนุมัติ)
    amount = Column(Float, default=0.0)
    slip_file = Column(String, default="")        # ชื่อไฟล์สลิป (เฉพาะ order)
    note = Column(Text, default="")
    status = Column(String, default="ใหม่")        # ใหม่ / ตอบแล้ว / ปิด / อนุมัติแล้ว / ทดลองใช้
    tenant_id = Column(Integer, nullable=True)     # โรงเรียนที่สร้างจากคำขอนี้ (หลังอนุมัติ)
    login_user = Column(String, default="")        # ชื่อผู้ใช้ที่สร้างให้ลูกค้า
    created_at = Column(DateTime, default=datetime.now)


class SaleDoc(AccBase):
    """เลขที่เอกสารขาย: quotation=ใบเสนอราคา (QT), receipt=ใบเสร็จ (RC) - 1 lead/kind มีเลขเดียว (กันออกซ้ำ)"""
    __tablename__ = "sale_doc"
    id = Column(Integer, primary_key=True)
    lead_id = Column(Integer, nullable=True)
    kind = Column(String)                          # quotation / receipt
    year = Column(Integer)                         # พ.ศ.
    seq = Column(Integer)
    doc_no = Column(String)
    created_at = Column(DateTime, default=datetime.now)


class LoginFail(AccBase):
    """นับล็อกอินผิดต่อ IP - เก็บใน DB เพื่อให้ใช้ร่วมกันได้ทุก worker
    (ถ้าเก็บในหน่วยความจำ พอรันหลายโปรเซส ผู้โจมตีจะได้โควตาคูณจำนวน worker)"""
    __tablename__ = "login_fail"
    ip = Column(String, primary_key=True)
    count = Column(Integer, default=0)
    first_at = Column(Float, default=0.0)          # epoch seconds ของครั้งแรกในหน้าต่างเวลานี้


class AuditLog(AccBase):
    """บันทึกเหตุการณ์สำคัญ - ตอบให้ได้ว่า "ใคร ทำอะไร เมื่อไหร่ จากที่ไหน"

    เก็บใน accounts.db (ไม่ใช่ DB โรงเรียน) เพื่อให้
    - ครอบคลุมเหตุการณ์ที่ยังไม่รู้ว่าโรงเรียนไหน (ล็อกอินผิด) และเหตุการณ์ของผู้ดูแลระบบ
    - ไม่ถูกเขียนทับตอนโรงเรียนกู้คืนฐานข้อมูลตัวเอง (หลักฐานต้องไม่หายไปพร้อมข้อมูล)

    ตั้งใจบันทึกเฉพาะ "เหตุการณ์สำคัญ" ไม่ใช่ทุกการเปิดหน้า
    เพราะ log ที่มีแต่ noise = อ่านไม่ออก และตัวมันเองก็เป็นข้อมูลส่วนบุคคล
    """
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    at = Column(DateTime, default=datetime.now, index=True)
    tenant_id = Column(Integer, nullable=True, index=True)   # None = เหตุการณ์ระดับระบบ
    uid = Column(Integer, nullable=True)
    username = Column(String, default="")       # เก็บชื่อไว้ด้วย เผื่อบัญชีถูกลบทีหลัง
    action = Column(String, default="", index=True)
    target = Column(String, default="")         # สิ่งที่ถูกกระทำ (ชื่อผู้ใช้/ไฟล์/โรงเรียน)
    detail = Column(String, default="")
    ip = Column(String, default="")


# ===================== engine / session =====================
def _ensure_engine():
    global _engine, _Session
    if _engine is None:
        path = get_data_dir() / "accounts.db"
        _engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})

        # accounts.db ถูกอ่านทุก request (ตรวจสิทธิ์) และถูกเขียนบ่อย (ล็อกอิน/หักโควตาเอกสาร)
        # WAL = คนอ่านไม่ถูกบล็อกตอนมีคนเขียน · busy_timeout = รอแทนที่จะ error ทันที
        # จำเป็นมากถ้ารันหลาย worker (หลายโปรเซสใช้ไฟล์เดียวกัน)
        @event.listens_for(_engine, "connect")
        def _acc_pragma(dbapi_con, _):
            cur = dbapi_con.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

        AccBase.metadata.create_all(bind=_engine)
        # เพิ่มคอลัมน์ใหม่บน accounts.db เก่า (ปลอดภัย: ข้ามถ้ามีแล้ว)
        for sql in ("ALTER TABLE account ADD COLUMN must_change_password BOOLEAN DEFAULT 0",
                    "ALTER TABLE lead ADD COLUMN tenant_id INTEGER",
                    "ALTER TABLE lead ADD COLUMN login_user VARCHAR DEFAULT ''",
                    "ALTER TABLE tenant ADD COLUMN plan VARCHAR DEFAULT 'member'",
                    "ALTER TABLE tenant ADD COLUMN docs_used INTEGER DEFAULT 0",
                    "ALTER TABLE tenant ADD COLUMN docs_limit INTEGER DEFAULT 0",
                    "ALTER TABLE tenant ADD COLUMN trial_expiry_date DATE",
                    "UPDATE tenant SET trial_expiry_date=COALESCE(expiry_date, DATE(created_at, '+30 days')) "
                    "WHERE plan='trial' AND trial_expiry_date IS NULL",
                    "UPDATE tenant SET trial_expiry_date=DATE(created_at, '+30 days') "
                    "WHERE plan='member' AND trial_expiry_date IS NULL AND EXISTS "
                    "(SELECT 1 FROM lead WHERE lead.tenant_id=tenant.id AND lead.kind='trial' "
                    "AND lead.created_at >= tenant.created_at)",
                    "ALTER TABLE account ADD COLUMN verified BOOLEAN DEFAULT 1",
                    "ALTER TABLE account ADD COLUMN verify_token VARCHAR DEFAULT ''",
                    "ALTER TABLE account ADD COLUMN reset_token VARCHAR DEFAULT ''",
                    "ALTER TABLE account ADD COLUMN reset_expires DATETIME",
                    "ALTER TABLE tenant ADD COLUMN modules VARCHAR DEFAULT ''",
                    "ALTER TABLE lead ADD COLUMN modules VARCHAR DEFAULT ''",
                    # ระบบสิทธิ์รายบัญชี: ไอดีหลัก (เห็นทุกงาน+จัดการผู้ใช้) + งานที่ไอดีย่อยเข้าได้
                    "ALTER TABLE account ADD COLUMN is_owner BOOLEAN DEFAULT 0",
                    "ALTER TABLE account ADD COLUMN modules VARCHAR DEFAULT ''",
                    "ALTER TABLE account ADD COLUMN welcomed BOOLEAN DEFAULT 0",
                    "ALTER TABLE account ADD COLUMN seen_modules VARCHAR DEFAULT ''",
                    "ALTER TABLE account ADD COLUMN person_id INTEGER",   # บัญชีครู -> ผูก Person.id
                    "ALTER TABLE account ADD COLUMN is_director BOOLEAN DEFAULT 0",   # ผอ./รองผอ. อนุมัติเอกสาร
                    "ALTER TABLE tenant ADD COLUMN teacher_code VARCHAR",  # รหัสต่อท้ายไอดีครู (owner ตั้ง)
                    "ALTER TABLE account ADD COLUMN avatar BLOB",          # รูปโปรไฟล์
                    "ALTER TABLE account ADD COLUMN last_seen_at DATETIME",
                    "ALTER TABLE account ADD COLUMN last_path VARCHAR DEFAULT ''",
                    "ALTER TABLE account ADD COLUMN totp_secret VARCHAR DEFAULT ''",
                    "ALTER TABLE account ADD COLUMN totp_enabled BOOLEAN DEFAULT 0",
                    "ALTER TABLE account ADD COLUMN totp_last_step INTEGER DEFAULT 0",
                    "ALTER TABLE account ADD COLUMN totp_recovery VARCHAR DEFAULT ''",
                    "ALTER TABLE tenant ADD COLUMN policy_accepted_at DATETIME",
                    "ALTER TABLE tenant ADD COLUMN policy_version VARCHAR DEFAULT ''",
                    "ALTER TABLE tenant ADD COLUMN policy_accept_ip VARCHAR DEFAULT ''",
                    "ALTER TABLE tenant ADD COLUMN last_active_at DATETIME",
                    "ALTER TABLE tenant ADD COLUMN inactive_stage INTEGER DEFAULT 0",
                    "ALTER TABLE tenant ADD COLUMN inactive_notified_at DATETIME",
                    # โรงเรียนเดิมยังไม่มีค่า -> ถือว่าใช้งานล่าสุด ณ วันที่สร้างบัญชี
                    # (ไม่ใช่ NULL ไม่งั้นจะถูกนับว่าไม่ใช้งานมานานทันทีตั้งแต่วันอัปเดต)
                    "UPDATE tenant SET last_active_at = created_at WHERE last_active_at IS NULL",
                    # backfill: บัญชีแรก (id น้อยสุด) ของแต่ละโรงเรียน = ไอดีหลัก · รันซ้ำได้ (ตั้งค่าแถวเดิม)
                    "UPDATE account SET is_owner=1 WHERE tenant_id IS NOT NULL "
                    "AND id IN (SELECT MIN(id) FROM account WHERE tenant_id IS NOT NULL GROUP BY tenant_id)",
                    # โรงเรียนที่จ่ายเงินแล้วก่อนมีระบบสิทธิ์รายงาน -> ให้ครบทุกงาน (ไม่มีใครใช้งานสะดุด)
                    # ยิงเฉพาะแถวที่ยังว่าง จึงรันซ้ำได้ และไม่แตะโรงเรียนที่ยังทดลองอยู่ (ต้องเป็น '' ต่อไป
                    # ไม่งั้นจะกลายเป็น "ซื้อครบ" = ใช้ฟรีไม่จำกัด)
                    f"UPDATE tenant SET modules='{ALL_MODULES_CSV}' "
                    f"WHERE plan='member' AND (modules IS NULL OR modules='')"):
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


# ---- เกณฑ์ความแข็งแรงของรหัสผ่าน (ใช้ร่วมกันทุกจุดที่ตั้ง/เปลี่ยนรหัส) ----
PW_MIN_LEN = 8

# รหัสที่คนไทยตั้งบ่อยและเดาง่าย (เทียบแบบตัดตัวเลขท้ายออกด้วย)
_PW_COMMON = {
    # รหัสยอดฮิตทั่วไป
    "password", "passw0rd", "12345678", "123456789", "1234567890", "11111111",
    "qwerty", "qwertyui", "abc", "abcd", "abcde", "abcdef", "iloveyou", "sunshine",
    "letmein", "monkey", "dragon", "football", "baseball", "computer", "internet",
    # คำฐานที่มักตั้งแล้วต่อท้ายด้วยปี/ตัวเลข (เทียบหลังตัดตัวเลขท้ายออก)
    "admin", "administrator", "welcome", "login", "user", "test", "changeme",
    "school", "teacher", "student", "kru", "kroo", "ekkasan", "easyekkasan",
    "thailand", "bangkok",
}


def password_problem(pw: str, username: str = "") -> str | None:
    """ตรวจความแข็งแรงของรหัสผ่าน · คืนข้อความปัญหา (ภาษาไทย) หรือ None ถ้าผ่าน

    เกณฑ์: ยาว >= 8 · มีทั้งตัวอักษรและตัวเลข · ไม่ใช่รหัสยอดฮิต · ไม่ซ้ำกับอีเมล/ชื่อผู้ใช้
    (เน้นความยาว + ไม่เดาง่าย ตามแนวทาง NIST มากกว่าบังคับอักขระพิเศษจนจำไม่ได้)
    """
    pw = pw or ""
    if len(pw) < PW_MIN_LEN:
        return f"รหัสผ่านต้องยาวอย่างน้อย {PW_MIN_LEN} ตัวอักษร"
    if pw.strip() != pw:
        return "รหัสผ่านต้องไม่ขึ้นต้นหรือลงท้ายด้วยช่องว่าง"
    has_alpha = any(c.isalpha() for c in pw)
    has_digit = any(c.isdigit() for c in pw)
    if not (has_alpha and has_digit):
        return "รหัสผ่านต้องมีทั้งตัวอักษรและตัวเลข"
    low = pw.lower()
    if low in _PW_COMMON or low.rstrip("0123456789") in _PW_COMMON:
        return "รหัสผ่านนี้เดาง่ายเกินไป กรุณาตั้งรหัสอื่น"
    if len(set(pw)) <= 3:
        return "รหัสผ่านซ้ำตัวเดิมมากเกินไป กรุณาตั้งรหัสอื่น"
    local = (username or "").strip().lower().split("@")[0]
    if local and len(local) >= 4 and local in low:
        return "รหัสผ่านต้องไม่มีชื่อผู้ใช้/อีเมลของคุณอยู่ในนั้น"
    return None


def login_fail_count(ip: str, window: int) -> int:
    """จำนวนครั้งที่ล็อกอินผิดของ IP นี้ในหน้าต่างเวลา (นับข้าม worker ได้)"""
    import time as _t
    db = acc_session()
    try:
        r = db.get(LoginFail, ip)
        if not r or (_t.time() - (r.first_at or 0)) > window:
            return 0
        return r.count or 0
    finally:
        db.close()


def login_fail_record(ip: str, window: int) -> int:
    """บันทึกล็อกอินผิด 1 ครั้ง (รีเซ็ตถ้าเลยหน้าต่างเวลาแล้ว) คืนจำนวนสะสม"""
    import time as _t
    now = _t.time()
    db = acc_session()
    try:
        r = db.get(LoginFail, ip)
        if not r:
            r = LoginFail(ip=ip, count=0, first_at=now)
            db.add(r)
        if (now - (r.first_at or 0)) > window:
            r.count, r.first_at = 0, now
        r.count = (r.count or 0) + 1
        db.commit()
        return r.count
    finally:
        db.close()


def login_fail_clear(ip: str) -> None:
    """ล็อกอินสำเร็จ -> ล้างประวัติผิดของ IP นั้น"""
    db = acc_session()
    try:
        r = db.get(LoginFail, ip)
        if r:
            db.delete(r)
            db.commit()
    finally:
        db.close()


def change_password(uid: int, current_pw: str, new_pw: str) -> tuple[bool, str]:
    """เปลี่ยนรหัสผ่านของผู้ใช้เอง (ตรวจรหัสเดิมก่อน) คืน (สำเร็จ, ข้อความ)"""
    _bad = password_problem(new_pw)
    if _bad:
        return False, _bad
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
                    "verified": bool(getattr(u, "verified", True)),
                    "is_owner": bool(getattr(u, "is_owner", False)),
                    "is_director": bool(getattr(u, "is_director", False)),
                    "modules": getattr(u, "modules", "") or "",
                    "person_id": getattr(u, "person_id", None),
                    "welcomed": bool(getattr(u, "welcomed", False))}
        return None
    finally:
        db.close()


def touch_tenant_active(tenant_id) -> None:
    """บันทึกว่าโรงเรียนนี้มีการใช้งาน (เรียกตอนล็อกอินสำเร็จ)
    เขียนแค่วันละครั้งพอ - ล็อกอินวันละหลายรอบไม่ต้องเขียน DB ทุกครั้ง"""
    if not tenant_id:
        return
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return
        now = datetime.now()
        if t.last_active_at and (now - t.last_active_at).total_seconds() < 43200                 and not t.inactive_stage:
            return                      # ใช้งานอยู่แล้วภายใน 12 ชม. และไม่ได้ค้างสถานะเตือน
        t.last_active_at = now
        t.inactive_stage = 0            # กลับมาใช้งาน = ล้างสถานะเตือนทิ้ง
        t.inactive_notified_at = None
        db.commit()
    except Exception:
        pass
    finally:
        db.close()


def purge_tenant(tenant_id) -> dict:
    """ลบโรงเรียนออกจากระบบถาวร: บัญชีผู้ใช้ + ข้อมูลกลาง + ไฟล์ฐานข้อมูลของโรงเรียน
    ใช้ร่วมกันระหว่างคอนโซลผู้ดูแลระบบและงานลบอัตโนมัติเมื่อไม่มีการใช้งาน"""
    import shutil
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return {"error": "ไม่พบโรงเรียน"}
        name = t.name
        n = db.query(Account).filter_by(tenant_id=tenant_id).delete()
        db.delete(t)
        db.commit()
    finally:
        db.close()
    try:
        from app.tenancy import dispose_engine
        dispose_engine(tenant_id)
        folder = get_data_dir() / "schools" / str(tenant_id)
        if folder.exists():
            shutil.rmtree(folder, ignore_errors=True)
    except Exception:
        pass
    return {"name": name, "users": n}


# ---------------- ใครกำลังใช้งานอยู่ (ดูในคอนโซลก่อนรีสตาร์ทเซิร์ฟเวอร์) ----------------
_SEEN_EVERY = 60        # เขียน DB ไม่เกินนาทีละครั้งต่อคน (ไม่งั้นทุกคลิกจะเขียน accounts.db)
_seen_cache: dict = {}  # uid -> เวลาที่เขียนล่าสุด (ต่อโปรเซส)


def touch_last_seen(uid, path: str = "") -> None:
    """บันทึกว่าบัญชีนี้เพิ่งใช้งาน · เรียกจากมิดเดิลแวร์ทุก request แต่เขียนจริงนาทีละครั้ง"""
    import time as _t
    if not uid:
        return
    now = _t.time()
    if now - _seen_cache.get(uid, 0) < _SEEN_EVERY:
        return
    _seen_cache[uid] = now
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if a:
            a.last_seen_at = datetime.now()
            a.last_path = (path or "")[:120]
            db.commit()
    except Exception:
        pass
    finally:
        db.close()


def online_accounts(minutes: int = 5) -> list:
    """บัญชีโรงเรียนที่ใช้งานภายใน N นาทีล่าสุด (ไม่รวมผู้ดูแลระบบ) - ใหม่สุดก่อน"""
    from datetime import timedelta
    db = acc_session()
    try:
        cut = datetime.now() - timedelta(minutes=minutes)
        rows = (db.query(Account, Tenant)
                .outerjoin(Tenant, Account.tenant_id == Tenant.id)
                .filter(Account.last_seen_at >= cut, Account.role != "superadmin")
                .order_by(Account.last_seen_at.desc()).all())
        now = datetime.now()
        return [{"username": a.username, "name": a.display_name or a.username,
                 "school": t.name if t else "-",
                 "ago": max(0, int((now - a.last_seen_at).total_seconds() // 60)),
                 "path": a.last_path or ""} for a, t in rows]
    finally:
        db.close()


def account_for_login(uid) -> dict | None:
    """ข้อมูลผู้ใช้รูปแบบเดียวกับ authenticate() แต่ค้นด้วย uid
    ใช้ตอนผ่านขั้นยืนยัน 2 ชั้นแล้ว (ตรวจรหัสผ่านไปก่อนหน้าแล้ว)"""
    db = acc_session()
    try:
        u = db.query(Account).filter_by(id=uid, active=True).first()
        if not u:
            return None
        return {"uid": u.id, "username": u.username, "role": u.role,
                "tenant_id": u.tenant_id, "display_name": u.display_name,
                "must_change": bool(u.must_change_password),
                "verified": bool(getattr(u, "verified", True)),
                "is_owner": bool(getattr(u, "is_owner", False)),
                "is_director": bool(getattr(u, "is_director", False)),
                "modules": getattr(u, "modules", "") or "",
                "person_id": getattr(u, "person_id", None),
                "welcomed": bool(getattr(u, "welcomed", False))}
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


def members_since(start) -> int:
    """นับจำนวนโรงเรียนที่เป็นสมาชิก (จ่ายแล้ว) ตั้งแต่วันที่ start เป็นต้นมา
    ใช้คิด 'สิทธิ์ที่เหลือ' ของโปรโมชั่นเปิดตัวจากยอดจริง"""
    from datetime import datetime as _dt
    if isinstance(start, str):
        try:
            start = date.fromisoformat(start.strip())
        except (ValueError, TypeError):
            return 0
    db = acc_session()
    try:
        start_dt = _dt.combine(start, _dt.min.time())
        return (db.query(Tenant)
                  .filter(Tenant.plan == "member", Tenant.created_at >= start_dt)
                  .count())
    finally:
        db.close()


def tenant_status(tenant_id) -> dict | None:
    """สถานะแพ็กเกจสำหรับแสดงในแอป - คืน "ทั้งสองด้าน" พร้อมกันเสมอ เพราะโรงเรียนหนึ่ง
    อาจเป็นสมาชิกของบางงาน และยังใช้สิทธิ์ทดลองกับงานที่เหลืออยู่ในเวลาเดียวกัน

    {plan, modules, modules_count,            # ด้านสมาชิก (งานที่ซื้อแล้ว)
     days_left, expiry_date, unlimited,       # ด้านสมาชิก (อายุ)
     docs_limit, docs_used, docs_left}        # ด้านทดลอง (None ถ้าไม่มีโควตาแล้ว)
    """
    if not tenant_id:
        return None
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return None
        mods = parse_modules(t.modules)
        limit = t.docs_limit or 0
        used = t.docs_used or 0
        out = {
            "plan": t.plan or "member",
            "modules": [k for k in MODULE_KEYS if k in mods],
            "modules_count": len(mods),
            "docs_limit": limit or None,
            "docs_used": used,
            "docs_left": max(0, limit - used) if limit else None,
            "days_left": None, "expiry_date": None, "unlimited": True,
            "trial_expiry_date": t.trial_expiry_date,
            "trial_days_left": ((t.trial_expiry_date - date.today()).days if t.trial_expiry_date else None),
        }
        if t.expiry_date:
            out.update({"days_left": (t.expiry_date - date.today()).days,
                        "expiry_date": t.expiry_date, "unlimited": False})
        return out
    finally:
        db.close()


def tenant_modules(tenant_id) -> set:
    """งานที่โรงเรียนนี้ "ซื้อแล้ว" · fail-open: อ่านไม่ได้ให้ถือว่าครบทุกงาน
    (นี่คือการกั้นรายได้ ไม่ใช่การกั้นความปลอดภัย - DB สะดุดต้องไม่ล็อกคนที่จ่ายเงินแล้วออกจากระบบ)"""
    if not tenant_id:
        return set(MODULE_KEYS)
    try:
        db = acc_session()
        try:
            t = db.get(Tenant, tenant_id)
            return parse_modules(t.modules) if t else set(MODULE_KEYS)
        finally:
            db.close()
    except Exception:
        return set(MODULE_KEYS)


def can_use_module(tenant_id, module) -> bool:
    """สิทธิ์เข้าใช้งานหนึ่ง ๆ = **ซื้อแล้ว** หรือ **โควตาทดลองยังเหลือ**

    รวมกติกาไว้ที่เดียว (middleware/เทมเพลตเรียกอันนี้) จะได้ไม่มีใครลืมเงื่อนไขทดลอง
    เฟส 2 (ไอดีย่อยรายงาน) ค่อยเพิ่มพารามิเตอร์ account_id แล้ว intersect เพิ่มอีกชั้นตรงนี้จุดเดียว
    """
    if not module:
        return True
    if not tenant_id:
        return True
    try:
        db = acc_session()
        try:
            t = db.get(Tenant, tenant_id)
            if not t:
                return True
            mods = parse_modules(t.modules)
            if module in mods:                           # ซื้องานนี้แล้ว
                return True
            if (t.plan or "member") == "trial":
                # ทดลองใช้ -> เข้าดูได้ทุกงาน (คุมที่ "การออกเอกสาร" ไม่ใช่การเข้าหน้า)
                return True
            if t.trial_expiry_date and date.today() <= t.trial_expiry_date:
                return True
            if not mods:                                 # กันเคสข้อมูลผิดปกติ (สมาชิกแต่ modules ว่าง)
                return True
            return False                                 # สมาชิกที่ไม่ได้ซื้องานนี้
        finally:
            db.close()
    except Exception:
        return True


def ai_key_for(tenant_id) -> str:
    """คืน AI key กลาง (หลังบ้าน) เฉพาะโรงเรียนที่เป็นสมาชิก (จ่ายแล้ว ไม่ใช่ trial)
    มิฉะนั้นคืน '' (ปิด AI) - key ไม่เคยผูก per-tenant/ไม่ส่งถึง client"""
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


TRIAL_DAYS = 30   # ทดลองใช้: เต็มระบบ 30 วัน (นับจากวันสมัคร)


def _trial_ok(t) -> bool:
    """ทดลองใช้ยังไม่หมดอายุ (ภายใน TRIAL_DAYS วัน) · ถ้าไม่ใช่ trial คืน True (ไปเช็คที่อื่น)"""
    from datetime import timedelta
    if (getattr(t, "plan", "member") or "member") != "trial":
        return True
    exp = t.trial_expiry_date or t.expiry_date or (((t.created_at.date() if t.created_at else date.today()))
                            + timedelta(days=TRIAL_DAYS))
    return date.today() <= exp


def consume_doc_quota(tenant_id, module=None) -> tuple:
    """เรียกก่อนออกเอกสาร - ทดลองใช้ = เต็มระบบ 30 วัน (ไม่จำกัดจำนวนเอกสาร)

    - งานที่ซื้อแล้ว -> ผ่านฟรี
    - ทดลองใช้ยังไม่หมดอายุ -> ผ่านฟรี (ออกเอกสารไม่จำกัด) · หมดอายุ -> (False, info)
    - สมาชิก -> ผ่าน (อายุคุมที่ล็อกอิน/มิดเดิลแวร์)
    """
    if not tenant_id:
        return True, None
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if not t:
            return True, None
        if module and module in parse_modules(t.modules):   # ซื้องานนี้แล้ว
            return True, None
        if (t.plan or "member") == "trial":                 # ทดลองใช้ -> คุมด้วยเวลา 30 วัน
            return (True, None) if _trial_ok(t) else (False, {"expired": True, "trial": True})
        if module and parse_modules(t.modules):
            if t.trial_expiry_date and date.today() <= t.trial_expiry_date:
                return True, None
            return False, {"expired": True, "trial": True}
        return True, None                                   # สมาชิก
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


def delete_lead(lead_id: int) -> bool:
    """ลบคำขอ 1 รายการ (ผู้ขายกดลบในคอนโซล) คืน True ถ้าลบจริง"""
    db = acc_session()
    try:
        l = db.get(Lead, lead_id)
        if not l:
            return False
        db.delete(l); db.commit()
        return True
    finally:
        db.close()


def delete_leads(kind: str | None = None, status: str | None = None) -> int:
    """ลบคำขอเป็นชุด (เช่น ล้างที่ปิดแล้ว) คืนจำนวนที่ลบ
    ต้องระบุอย่างน้อย 1 เงื่อนไข กันเผลอลบทั้งตาราง"""
    if not kind and not status:
        return 0
    db = acc_session()
    try:
        q = db.query(Lead)
        if kind:
            q = q.filter_by(kind=kind)
        if status:
            q = q.filter_by(status=status)
        n = q.delete(synchronize_session=False)
        db.commit()
        return n
    finally:
        db.close()


def lead_counts() -> dict:
    """จำนวนคำขอแยกตามประเภท + รวม + ที่ยังใหม่ (ไว้โชว์ตัวเลขบนแท็บ/ลิงก์คอนโซล)"""
    from sqlalchemy import func as _func
    db = acc_session()
    try:
        out = {"all": db.query(Lead).count(),
               "new": db.query(Lead).filter_by(status="ใหม่").count(),
               "closed": db.query(Lead).filter_by(status="ปิด").count()}
        for k, n in db.query(Lead.kind, _func.count(Lead.id)).group_by(Lead.kind).all():
            out[k or "quote"] = n
        return out
    finally:
        db.close()


def purchase_account(uid) -> dict | None:
    """Read the verified school account for public purchase routes (fresh from DB)."""
    if not uid:
        return None
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a or not a.active or not a.verified or a.role == "superadmin" or a.must_change_password:
            return None
        t = db.get(Tenant, a.tenant_id) if a.tenant_id else None
        if not t or not t.active:
            return None
        return {"uid": a.id, "username": a.username, "tenant_id": t.id, "school_name": t.name}
    finally:
        db.close()


def bind_payment_account(lead_id: int, uid) -> bool:
    """Explicit bearer-link confirmation; never transfer an already bound quote."""
    account = purchase_account(uid)
    if not account:
        return False
    db = acc_session()
    try:
        lead = db.get(Lead, lead_id)
        if not lead:
            return False
        if lead.tenant_id:
            return lead.tenant_id == account["tenant_id"]
        if lead.slip_file or lead.status == "ต่ออายุแล้ว":
            return False
        changed = db.query(Lead).filter(Lead.id == lead_id, Lead.tenant_id.is_(None)).update(
            {"tenant_id": account["tenant_id"], "login_user": account["username"]}, synchronize_session=False)
        db.commit()
        return changed == 1
    finally:
        db.close()


def attach_lead_slip(lead_id: int, slip_file: str, tenant_id=None) -> dict | None:
    """ลูกค้าอัปสลิปผ่านลิงก์ชำระเงิน -> แนบสลิป + เปลี่ยนเป็นออเดอร์รอตรวจ (เข้าแท็บสั่งซื้อในคอนโซล)
    คืน dict ข้อมูล lead (ไว้ส่งแจ้งเตือนผู้ขาย) หรือ None"""
    db = acc_session()
    try:
        l = db.get(Lead, lead_id)
        if not l:
            return None
        if tenant_id is not None:
            if l.tenant_id != tenant_id or l.slip_file or l.status == "ต่ออายุแล้ว":
                return None
            changed = db.query(Lead).filter(
                Lead.id == lead_id, Lead.tenant_id == tenant_id,
                (Lead.slip_file == "") | Lead.slip_file.is_(None),
                Lead.status != "ต่ออายุแล้ว").update(
                    {"slip_file": slip_file, "kind": "order", "status": "ใหม่"}, synchronize_session=False)
            if not changed:
                return None
            db.commit()
            db.refresh(l)
            return {c.name: getattr(l, c.name) for c in Lead.__table__.columns}
        l.slip_file = slip_file
        l.kind = "order"
        l.status = "ใหม่"
        db.commit()
        return {"id": l.id, "school_name": l.school_name, "contact_name": l.contact_name,
                "email": l.email, "phone": l.phone, "packages": l.packages,
                "amount": l.amount, "note": l.note}
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
                     plan: str = "member", docs_limit: int = 0,
                     modules: str | None = None) -> int:
    """สร้างโรงเรียนใหม่ + ผู้ใช้แรก + สร้างไฟล์ฐานข้อมูลของโรงเรียน คืน tenant_id

    modules = งานที่ "ซื้อแล้ว" · ไม่ระบุ -> สมาชิก = ครบทุกงาน, ทดลองใช้ = ว่าง
    (ทดลองใช้ต้องเป็นค่าว่าง ไม่งั้นจะกลายเป็น "ซื้อครบ" = ใช้ฟรีไม่จำกัด - สิทธิ์ทดลองมาจากโควตาเอกสารแทน)
    """
    from app.tenancy import ensure_school_db
    if modules is None:
        modules = "" if plan == "trial" else ALL_MODULES_CSV
    db = acc_session()
    try:
        t = Tenant(name=name.strip(), slug=slug.strip(), expiry_date=expiry_date,
                   trial_expiry_date=expiry_date if plan == 'trial' else None,
                   max_users=max_users, plan=plan, docs_limit=docs_limit,
                   modules=modules_csv(parse_modules(modules)))
        db.add(t); db.flush()
        db.add(Account(tenant_id=t.id, username=admin_user.strip(),
                       password_hash=hash_password(admin_pw), role="user",
                       display_name=name.strip(), must_change_password=must_change,
                       is_owner=True))   # บัญชีแรกของโรงเรียน = ไอดีหลัก (เห็นทุกงาน + จัดการผู้ใช้)
        db.commit()
        tid = t.id
    finally:
        db.close()
    ensure_school_db(tid)   # สร้างไฟล์ DB + ตารางของโรงเรียน
    return tid


# ===================== จัดการผู้ใช้ในโรงเรียน (ไอดีหลักทำเอง) =====================
def list_tenant_users(tenant_id) -> list:
    """รายชื่อบัญชีของโรงเรียนนี้ (ไอดีหลักก่อน) - ตัด ORM คืน dict"""
    db = acc_session()
    try:
        us = (db.query(Account).filter_by(tenant_id=tenant_id)
              .order_by(Account.is_owner.desc(), Account.id).all())
        return [{"id": u.id, "username": u.username, "display_name": u.display_name or "",
                 "is_owner": bool(u.is_owner), "active": bool(u.active),
                 "is_director": bool(getattr(u, "is_director", False)),
                 "modules": u.modules or "", "person_id": u.person_id,
                 "totp": bool(getattr(u, "totp_enabled", False))} for u in us]
    finally:
        db.close()


def director_person_ids(tenant_id) -> list:
    """person_id ของบัญชี ผอ./รองผอ. ในโรงเรียนนี้ (ที่ผูก Person) - ไว้แจ้งเตือน/แปะลายเซ็น"""
    if not tenant_id:
        return []
    db = acc_session()
    try:
        us = (db.query(Account)
              .filter(Account.tenant_id == tenant_id, Account.is_director == True,  # noqa: E712
                      Account.person_id.isnot(None)).all())
        return [u.person_id for u in us]
    finally:
        db.close()


def get_account_access(uid) -> dict | None:
    """สิทธิ์บัญชีสด ๆ จาก DB (ใช้ใน middleware กัน session ค้าง)
    คืน {is_owner, modules, active} หรือ None ถ้าไม่พบบัญชี"""
    db = acc_session()
    try:
        u = db.query(Account).filter_by(id=uid).first()
        if not u:
            return None
        return {"is_owner": bool(u.is_owner), "modules": u.modules or "", "active": bool(u.active),
                "is_director": bool(getattr(u, "is_director", False)),
                "welcomed": bool(u.welcomed), "person_id": u.person_id}
    finally:
        db.close()


def mark_welcomed(uid) -> None:
    """บันทึกว่าผู้ใช้เห็นการ์ดต้อนรับแล้ว (ไม่ต้องเด้งอีก)"""
    db = acc_session()
    try:
        u = db.query(Account).filter_by(id=uid).first()
        if u and not u.welcomed:
            u.welcomed = True; db.commit()
    finally:
        db.close()


def sync_seen_modules(uid) -> None:
    """ตั้ง 'งานที่รับรู้แล้ว' = งานที่โรงเรียนซื้อตอนนี้ (กดรับรู้แบนเนอร์ซื้อเพิ่ม/ปิดการ์ดต้อนรับ)"""
    db = acc_session()
    try:
        u = db.query(Account).filter_by(id=uid).first()
        if not u:
            return
        t = db.query(Tenant).filter_by(id=u.tenant_id).first()
        u.seen_modules = (t.modules if t else "") or ""; db.commit()
    finally:
        db.close()


def owner_new_modules(uid) -> list:
    """งานที่โรงเรียนซื้อแล้วแต่ไอดีหลักยังไม่รับรู้ (ใช้แจ้งเตือน 'ซื้อเพิ่ม -> ไปเปิดสิทธิ์')
    คืน [] ถ้าไม่ใช่ไอดีหลัก หรือยังไม่ผ่านการ์ดต้อนรับ (ครั้งแรกให้การ์ดต้อนรับจัดการแทน)"""
    from app.modules import parse_modules, MODULE_KEYS
    db = acc_session()
    try:
        u = db.query(Account).filter_by(id=uid).first()
        if not u or not u.is_owner or not u.welcomed:
            return []
        t = db.query(Tenant).filter_by(id=u.tenant_id).first()
        if not t:
            return []
        owned, seen = parse_modules(t.modules), parse_modules(u.seen_modules)
        return [k for k in MODULE_KEYS if k in owned and k not in seen]
    finally:
        db.close()


def tenant_billing(tenant_id) -> dict | None:
    """สถานะการเรียกเก็บเงินของโรงเรียน (ใช้หน้า checkout ตัดสินว่าซื้อเพิ่ม prorate ได้ไหม)
    คืน {plan, expiry_date, days_left, modules(csv), active}"""
    from datetime import date
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return None
        days = (t.expiry_date - date.today()).days if t.expiry_date else None
        return {"plan": t.plan, "expiry_date": t.expiry_date, "days_left": days,
                "modules": t.modules or "", "active": bool(t.active)}
    finally:
        db.close()


def tenant_max_users(tenant_id) -> int:
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        return (t.max_users or 3) if t else 3
    finally:
        db.close()


def _own_user(db, tenant_id, uid):
    """คืน Account ที่อยู่ในโรงเรียนนี้เท่านั้น (กันแก้/ลบข้ามโรงเรียน)"""
    return db.query(Account).filter_by(id=uid, tenant_id=tenant_id).first()


AVATAR_PX = 256          # รูปโปรไฟล์ใช้แค่วงกลมเล็ก ๆ ย่อให้เล็กเพื่อไม่ให้ accounts.db บวม


def set_avatar(uid, data: bytes) -> dict:
    """ตั้งรูปโปรไฟล์ (ย่อ+ครอบเป็นสี่เหลี่ยมจัตุรัสกลางภาพเป็น JPEG) · คืน {"ok"} หรือ {"error"}"""
    import io as _io
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(_io.BytesIO(data))).convert("RGB")
    except Exception:
        return {"error": "ไฟล์นี้ไม่ใช่รูปภาพ (รองรับ JPG · PNG · HEIC จากมือถือ)"}
    # ครอบกลางภาพให้เป็นจัตุรัสก่อน วงกลมจะได้ไม่บีบเบี้ยว
    side = min(img.width, img.height)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    img = img.crop((left, top, left + side, top + side)).resize(
        (AVATAR_PX, AVATAR_PX), Image.LANCZOS)
    buf = _io.BytesIO()
    img.save(buf, "JPEG", quality=85, optimize=True)
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a:
            return {"error": "ไม่พบบัญชีผู้ใช้"}
        a.avatar = buf.getvalue()
        db.commit()
        return {"ok": True}
    finally:
        db.close()


def clear_avatar(uid):
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if a:
            a.avatar = None
            db.commit()
    finally:
        db.close()


def get_avatar(uid):
    """คืน bytes รูปโปรไฟล์ หรือ None (ใช้ตอนส่งรูปให้เบราว์เซอร์)"""
    db = acc_session()
    try:
        a = db.get(Account, uid)
        return a.avatar if a else None
    finally:
        db.close()


def has_avatar(uid) -> bool:
    db = acc_session()
    try:
        a = db.get(Account, uid)
        return bool(a and a.avatar)
    finally:
        db.close()


def totp_status(uid) -> dict:
    """สถานะ 2FA ของบัญชี -> {enabled, has_secret, recovery_left}"""
    from app.services import totp as _t
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a:
            return {"enabled": False, "has_secret": False, "recovery_left": 0}
        return {"enabled": bool(a.totp_enabled), "has_secret": bool(a.totp_secret),
                "recovery_left": _t.recovery_left(a.totp_recovery or "")}
    finally:
        db.close()


def totp_begin(uid) -> str | None:
    """เริ่มตั้งค่า 2FA - สร้างคีย์ใหม่ (ยังไม่เปิดใช้จนกว่าจะยืนยันรหัสสำเร็จ)
    ถ้าเปิดใช้อยู่แล้วจะไม่สร้างทับ (กันเผลอทำให้แอปเดิมใช้ไม่ได้)"""
    from app.services import totp as _t
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a or a.totp_enabled:
            return None
        a.totp_secret = _t.new_secret()
        db.commit()
        return a.totp_secret
    finally:
        db.close()


def totp_confirm(uid, code) -> dict:
    """ยืนยันรหัสจากแอปเพื่อเปิดใช้จริง · สำเร็จ -> คืนรหัสสำรอง (โชว์ครั้งเดียว)"""
    from app.services import totp as _t
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a or not a.totp_secret:
            return {"error": "ยังไม่ได้เริ่มตั้งค่า กรุณากดเริ่มใหม่อีกครั้ง"}
        if a.totp_enabled:
            return {"error": "เปิดใช้อยู่แล้ว"}
        st, step = _t.verify(a.totp_secret, code, last_step=a.totp_last_step or 0)
        if st == "used":
            return {"error": "รหัสนี้ถูกใช้ไปแล้ว รอให้แอปเปลี่ยนรหัสใหม่แล้วลองอีกครั้ง"}
        if st != "ok":
            return {"error": "รหัสไม่ถูกต้อง ลองใหม่อีกครั้ง (รหัสเปลี่ยนทุก 30 วินาที)"}
        codes = _t.new_recovery_codes()
        a.totp_enabled = True
        a.totp_last_step = step
        a.totp_recovery = _t.hash_recovery(codes)
        db.commit()
        return {"codes": codes}
    finally:
        db.close()


def totp_disable(uid, password) -> dict:
    """ปิด 2FA - ต้องกรอกรหัสผ่านซ้ำ (กันคนที่แอบใช้เครื่องที่ล็อกอินค้างไว้ปิดทิ้ง)"""
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a:
            return {"error": "ไม่พบบัญชีผู้ใช้"}
        if not verify_password(password or "", a.password_hash):
            return {"error": "รหัสผ่านไม่ถูกต้อง"}
        a.totp_enabled = False
        a.totp_secret = ""
        a.totp_recovery = ""
        a.totp_last_step = 0
        db.commit()
        return {"ok": True}
    finally:
        db.close()


def totp_reset_for(uid, tenant_id=None) -> dict:
    """ปิด 2FA ให้ผู้ใช้คนอื่น - ใช้ตอนเจ้าตัวทำมือถือหายและรหัสสำรองหมด

    ต่างจาก totp_disable() ตรงที่ไม่ต้องใช้รหัสผ่านของเจ้าตัว
    จึงต้องเรียกจาก route ที่ตรวจสิทธิ์ผู้ดูแลมาแล้วเท่านั้น
    tenant_id: ถ้าส่งมา จะยอมปลดเฉพาะบัญชีในโรงเรียนนั้น (กันไอดีหลักข้ามโรงเรียน)
    """
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a:
            return {"error": "ไม่พบบัญชีผู้ใช้"}
        if tenant_id is not None and a.tenant_id != tenant_id:
            return {"error": "บัญชีนี้ไม่ได้อยู่ในโรงเรียนของท่าน"}
        if not a.totp_enabled and not a.totp_secret:
            return {"error": "บัญชีนี้ไม่ได้เปิดยืนยัน 2 ชั้นไว้"}
        a.totp_enabled = False
        a.totp_secret = ""
        a.totp_recovery = ""
        a.totp_last_step = 0
        db.commit()
        return {"username": a.username}
    finally:
        db.close()


def totp_reset_tenant(tenant_id) -> int:
    """ปิด 2FA ของทุกบัญชีในโรงเรียน (ผู้ดูแลระบบใช้ช่วยโรงเรียนที่ล็อกตัวเองออก)"""
    db = acc_session()
    try:
        rows = (db.query(Account).filter_by(tenant_id=tenant_id)
                .filter(Account.totp_enabled == True).all())      # noqa: E712
        for a in rows:
            a.totp_enabled = False
            a.totp_secret = ""
            a.totp_recovery = ""
            a.totp_last_step = 0
        db.commit()
        return len(rows)
    finally:
        db.close()


def totp_check(uid, code) -> dict:
    """ตรวจรหัสตอนล็อกอิน · รับได้ทั้งรหัส 6 หลักจากแอป และรหัสสำรอง
    คืน {ok: True, recovery: bool, left: int} หรือ {error}"""
    from app.services import totp as _t
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a or not a.totp_enabled:
            return {"error": "บัญชีนี้ไม่ได้เปิดยืนยัน 2 ชั้น"}
        st, step = _t.verify(a.totp_secret, code, last_step=a.totp_last_step or 0)
        if st == "ok":
            a.totp_last_step = step
            db.commit()
            return {"ok": True, "recovery": False}
        if st == "used":
            return {"error": "รหัสนี้ถูกใช้ไปแล้ว รอให้แอปเปลี่ยนรหัสใหม่ (ประมาณ 30 วินาที)"}
        used, left = _t.use_recovery(a.totp_recovery or "", code)
        if used:
            a.totp_recovery = left
            db.commit()
            return {"ok": True, "recovery": True, "left": _t.recovery_left(left)}
        return {"error": "รหัสไม่ถูกต้อง"}
    finally:
        db.close()


def totp_required(uid) -> bool:
    db = acc_session()
    try:
        a = db.get(Account, uid)
        return bool(a and a.totp_enabled and a.totp_secret)
    finally:
        db.close()


AUDIT_KEEP_DAYS = 365      # เก็บ log ย้อนหลังกี่วัน (เกินนั้นลบ - ไม่เก็บนานเกินจำเป็นตาม PDPA)

# คำอธิบายภาษาไทยของแต่ละเหตุการณ์ (ใช้ทั้งหน้าแสดงผลและกันพิมพ์ action มั่ว)
AUDIT_LABELS = {
    "login.ok": "เข้าสู่ระบบสำเร็จ",
    "login.fail": "เข้าสู่ระบบไม่สำเร็จ",
    "login.blocked": "ถูกบล็อกชั่วคราว (ลองเข้าระบบถี่เกินไป)",
    "logout": "ออกจากระบบ",
    "password.change": "เปลี่ยนรหัสผ่านตัวเอง",
    "password.forgot": "ขอลิงก์ตั้งรหัสผ่านใหม่",
    "password.reset": "ตั้งรหัสผ่านใหม่ผ่านลิงก์อีเมล",
    "user.add": "เพิ่มผู้ใช้",
    "user.delete": "ลบผู้ใช้",
    "user.reset_password": "รีเซ็ตรหัสผ่านให้ผู้ใช้",
    "user.modules": "แก้สิทธิ์การเข้าถึงงาน",
    "user.active": "เปิด/ปิดการใช้งานบัญชี",
    "user.director": "ตั้ง/ยกเลิกสิทธิ์ผู้อำนวยการ",
    "teacher.add": "สร้างบัญชีครู",
    "teacher.code": "ตั้งรหัสต่อท้ายไอดีครู",
    "data.download": "ดาวน์โหลดไฟล์สำรองข้อมูล",
    "data.restore": "กู้คืนข้อมูลจากไฟล์สำรอง",
    "data.import": "นำเข้าข้อมูลจากไฟล์",
    "admin.tenant_delete": "ผู้ดูแลระบบลบโรงเรียน",
    "2fa.enable": "เปิดยืนยันตัวตน 2 ชั้น",
    "2fa.disable": "ปิดยืนยันตัวตน 2 ชั้น",
    "2fa.fail": "ใส่รหัสยืนยัน 2 ชั้นผิด",
    "2fa.recovery": "เข้าระบบด้วยรหัสสำรอง",
    "2fa.reset": "ปลดล็อกยืนยัน 2 ชั้นให้ผู้ใช้",
    "retention.warn": "แจ้งเตือนบัญชีไม่มีการใช้งาน",
    "retention.delete": "ลบข้อมูลอัตโนมัติ (ไม่มีการใช้งานนาน)",
    "admin.tenant_edit": "ผู้ดูแลระบบแก้ข้อมูลโรงเรียน",
}


def client_ip(request) -> str:
    """IP ผู้ใช้ (หลัง nginx ต้องเปิด --proxy-headers ไม่งั้นจะได้ 127.0.0.1 หมด)"""
    try:
        return request.client.host if request and request.client else ""
    except Exception:
        return ""


def audit(action, *, request=None, tenant_id=None, uid=None, username="",
          target="", detail="", ip="") -> None:
    """บันทึกเหตุการณ์ · ห้าม raise เด็ดขาด - log พังต้องไม่ทำให้ผู้ใช้ทำงานไม่ได้"""
    try:
        sess = getattr(request, "session", {}) if request is not None else {}
        row = AuditLog(
            tenant_id=tenant_id if tenant_id is not None else sess.get("tid"),
            uid=uid if uid is not None else sess.get("uid"),
            username=(username or sess.get("username") or "")[:120],
            action=str(action)[:60],
            target=str(target)[:200],
            detail=str(detail)[:400],
            ip=(ip or client_ip(request))[:60],
        )
        db = acc_session()
        try:
            db.add(row)
            db.commit()
        finally:
            db.close()
    except Exception:
        pass


def audit_list(tenant_id=None, *, limit=200, offset=0, action="", q=""):
    """อ่านรายการเหตุการณ์ · tenant_id=None = ทุกโรงเรียน (เฉพาะผู้ดูแลระบบ)"""
    db = acc_session()
    try:
        qs = db.query(AuditLog)
        if tenant_id is not None:
            qs = qs.filter(AuditLog.tenant_id == tenant_id)
        if action:
            qs = qs.filter(AuditLog.action == action)
        if q:
            like = f"%{q.strip()}%"
            qs = qs.filter((AuditLog.username.like(like)) | (AuditLog.target.like(like))
                           | (AuditLog.detail.like(like)) | (AuditLog.ip.like(like)))
        total = qs.count()
        rows = (qs.order_by(AuditLog.at.desc(), AuditLog.id.desc())
                .offset(offset).limit(limit).all())
        return [{"at": r.at, "username": r.username, "action": r.action,
                 "label": AUDIT_LABELS.get(r.action, r.action), "target": r.target,
                 "detail": r.detail, "ip": r.ip, "tenant_id": r.tenant_id} for r in rows], total
    finally:
        db.close()


def audit_prune(days: int = AUDIT_KEEP_DAYS) -> int:
    """ลบ log ที่เก่ากว่ากำหนด · คืนจำนวนแถวที่ลบ"""
    from datetime import timedelta
    db = acc_session()
    try:
        cut = datetime.now() - timedelta(days=days)
        n = db.query(AuditLog).filter(AuditLog.at < cut).delete(synchronize_session=False)
        db.commit()
        return n
    except Exception:
        return 0
    finally:
        db.close()


def set_display_name(uid, name: str) -> dict:
    """ผู้ใช้แก้ "ชื่อที่แสดง" ของบัญชีตัวเอง (ไม่ใช่ชื่อโรงเรียนบนเอกสาร - อันนั้นอยู่หน้าตั้งค่าโรงเรียน)"""
    name = (name or "").strip()
    if not name:
        return {"error": "กรุณากรอกชื่อที่ต้องการแสดง"}
    if len(name) > 80:
        return {"error": "ชื่อยาวเกินไป (ไม่เกิน 80 ตัวอักษร)"}
    db = acc_session()
    try:
        a = db.get(Account, uid)
        if not a:
            return {"error": "ไม่พบบัญชีผู้ใช้"}
        a.display_name = name
        db.commit()
        return {"name": name}
    finally:
        db.close()


def add_tenant_user(tenant_id, username, password, modules="", display_name="") -> dict:
    """ไอดีหลักเพิ่มไอดีย่อย (จำกัดตาม max_users) + กำหนดสิทธิ์งาน (CSV)"""
    from app.modules import modules_csv, parse_modules
    username = (username or "").strip()
    if not username:
        return {"error": "กรอกชื่อผู้ใช้"}
    _bad = password_problem(password, username)
    if _bad:
        return {"error": _bad}
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return {"error": "ไม่พบโรงเรียน"}
        # บัญชีครู (งานวิชาการ · ผูก Person) ไม่นับในโควตา -> นับเฉพาะไอดีเจ้าหน้าที่
        billable = (db.query(Account)
                    .filter(Account.tenant_id == tenant_id, Account.person_id.is_(None)).count())
        if billable >= (t.max_users or 3):
            return {"error": f"เกินจำนวนผู้ใช้สูงสุดของโรงเรียน ({t.max_users or 3} คน)"}
        if db.query(Account).filter_by(username=username).first():
            return {"error": "ชื่อผู้ใช้นี้ถูกใช้แล้ว เลือกชื่ออื่น"}
        db.add(Account(tenant_id=tenant_id, username=username,
                       password_hash=hash_password(password), role="user",
                       display_name=(display_name or "").strip(), is_owner=False,
                       modules=modules_csv(parse_modules(modules)), verified=True))
        db.commit()
        return {"ok": True}
    finally:
        db.close()


import re as _re


def _tenant_code(tenant) -> str:
    """รหัสต่อท้ายไอดีครูของโรงเรียน: ใช้ที่ owner ตั้งไว้ (teacher_code) ก่อน ไม่งั้น fallback เป็น slug"""
    if tenant is None:
        return ""
    return ((tenant.teacher_code or tenant.slug or f"t{getattr(tenant, 'id', '')}") or "").strip()


def teacher_username(base, tenant) -> str:
    """ไอดีเข้าระบบของครู = ชื่อที่ตั้ง + รหัสต่อท้ายของโรงเรียน กันซ้ำข้ามโรงเรียน
    เช่น 'teacher1' + รหัส '104' -> 'teacher1.104'"""
    base = (base or "").strip().replace(" ", "")
    code = _tenant_code(tenant)
    return f"{base}.{code}" if base else ""


def normalize_teacher_code(code) -> str:
    """รหัสต่อท้าย: ตัวอักษร/ตัวเลข/ขีดกลางเท่านั้น ตัดช่องว่าง (ห้ามมีจุด = ตัวคั่น)"""
    return (code or "").strip().replace(" ", "")


def get_teacher_code(tenant_id):
    """รหัสต่อท้ายปัจจุบันของโรงเรียน (ที่ตั้งเอง) + fallback slug ถ้ายังไม่ตั้ง · คืน (code, is_custom)"""
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return ("", False)
        return (_tenant_code(t), bool(t.teacher_code))
    finally:
        db.close()


def set_teacher_code(tenant_id, code) -> dict:
    """owner ตั้ง/แก้รหัสต่อท้ายไอดีครู - บังคับไม่ซ้ำกับโรงเรียนอื่น
    หมายเหตุ: ไอดีครูที่สร้างไปแล้วจะไม่เปลี่ยนตาม (คงใช้ของเดิมได้)"""
    code = normalize_teacher_code(code)
    if not code:
        return {"error": "กรอกรหัสต่อท้าย"}
    if not _re.fullmatch(r"[A-Za-z0-9-]{1,20}", code):
        return {"error": "รหัสต่อท้ายใช้ได้เฉพาะ ตัวอักษร/ตัวเลข/ขีดกลาง (ไม่เกิน 20 ตัว ห้ามเว้นวรรค)"}
    db = acc_session()
    try:
        # กันซ้ำกับโรงเรียนอื่น (ทั้ง teacher_code ที่ตั้งเอง และ slug ที่บางโรงเรียนใช้เป็น fallback)
        dup = (db.query(Tenant)
               .filter(Tenant.id != tenant_id,
                       (Tenant.teacher_code == code) | (Tenant.slug == code)).first())
        if dup:
            return {"error": "รหัสต่อท้ายนี้มีโรงเรียนอื่นใช้แล้ว กรุณาตั้งรหัสอื่น"}
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return {"error": "ไม่พบโรงเรียน"}
        t.teacher_code = code
        db.commit()
        return {"ok": True, "code": code}
    finally:
        db.close()


def add_teacher_account(tenant_id, person_id, username, password, display_name="") -> dict:
    """สร้างบัญชีครู (ผูกกับ Person.id ในโรงเรียน) - เข้าได้เฉพาะงานวิชาการ + สิทธิ์เฉพาะวิชา/ห้องตัวเอง
    ไอดีเข้าระบบจะเติมรหัสโรงเรียนต่อท้ายให้อัตโนมัติ กันซ้ำกับครูโรงเรียนอื่น (เช่น teacher1.rongrian-1)"""
    base = (username or "").strip().replace(" ", "")
    if not base:
        return {"error": "กรอกชื่อผู้ใช้"}
    _bad = password_problem(password, base)
    if _bad:
        return {"error": _bad}
    if not person_id:
        return {"error": "เลือกครูที่จะผูกกับบัญชีนี้"}
    db = acc_session()
    try:
        t = db.query(Tenant).filter_by(id=tenant_id).first()
        if not t:
            return {"error": "ไม่พบโรงเรียน"}
        # บัญชีครู (งานวิชาการ) ไม่จำกัดจำนวน - ยกเว้นจากโควตา max_users ของโรงเรียน
        if db.query(Account).filter_by(tenant_id=tenant_id, person_id=person_id).first():
            return {"error": "ครูคนนี้มีบัญชีอยู่แล้ว"}
        # ไอดี = ชื่อที่ตั้ง + รหัสโรงเรียน · เติมเลขต่อท้ายถ้าซ้ำภายในโรงเรียน (ครู 2 คนตั้งชื่อเดียวกัน)
        final = teacher_username(base, t)
        uname, n = final, 1
        while db.query(Account).filter_by(username=uname).first():
            n += 1
            uname = f"{final}-{n}"
        db.add(Account(tenant_id=tenant_id, username=uname,
                       password_hash=hash_password(password), role="user",
                       display_name=(display_name or "").strip(), is_owner=False,
                       modules="academic", person_id=int(person_id), verified=True))
        db.commit()
        return {"ok": True, "username": uname}
    finally:
        db.close()


def list_teacher_accounts(tenant_id) -> list:
    """บัญชีครู (person_id ไม่ว่าง) ของโรงเรียน -> [{id, username, display_name, person_id, active}]"""
    db = acc_session()
    try:
        us = (db.query(Account)
              .filter(Account.tenant_id == tenant_id, Account.person_id.isnot(None))
              .order_by(Account.id).all())
        return [{"id": u.id, "username": u.username, "display_name": u.display_name or "",
                 "person_id": u.person_id, "active": bool(u.active)} for u in us]
    finally:
        db.close()


def set_user_modules(tenant_id, uid, modules) -> dict:
    """กำหนดงานที่ไอดีย่อยเข้าได้ (owner เห็นทุกงานอยู่แล้ว ไม่ต้องตั้ง)"""
    from app.modules import modules_csv, parse_modules
    db = acc_session()
    try:
        u = _own_user(db, tenant_id, uid)
        if not u:
            return {"error": "ไม่พบผู้ใช้"}
        if u.is_owner:
            return {"error": "ไอดีหลักเห็นทุกงานอยู่แล้ว"}
        u.modules = modules_csv(parse_modules(modules)); db.commit()
        return {"ok": True}
    finally:
        db.close()


def reset_user_password(tenant_id, uid, new_password) -> dict:
    db = acc_session()
    try:
        u = _own_user(db, tenant_id, uid)
        if not u:
            return {"error": "ไม่พบผู้ใช้"}
        _bad = password_problem(new_password, getattr(u, "username", ""))
        if _bad:
            return {"error": _bad}
        u.password_hash = hash_password(new_password); u.must_change_password = False
        db.commit()
        return {"ok": True}
    finally:
        db.close()


def toggle_user_active(tenant_id, uid) -> dict:
    db = acc_session()
    try:
        u = _own_user(db, tenant_id, uid)
        if not u:
            return {"error": "ไม่พบผู้ใช้"}
        if u.is_owner:
            return {"error": "ปิดใช้งานไอดีหลักไม่ได้"}
        u.active = not u.active; db.commit()
        return {"ok": True, "active": bool(u.active)}
    finally:
        db.close()


def toggle_user_director(tenant_id, uid) -> dict:
    """สลับสิทธิ์ ผอ./รองผอ. (อนุมัติแผนการสอน/ลา/ไปราชการ ขั้นสุดท้าย)"""
    db = acc_session()
    try:
        u = _own_user(db, tenant_id, uid)
        if not u:
            return {"error": "ไม่พบผู้ใช้"}
        u.is_director = not bool(getattr(u, "is_director", False)); db.commit()
        return {"ok": True, "is_director": bool(u.is_director)}
    finally:
        db.close()


def delete_tenant_user(tenant_id, uid) -> dict:
    db = acc_session()
    try:
        u = _own_user(db, tenant_id, uid)
        if not u:
            return {"error": "ไม่พบผู้ใช้"}
        if u.is_owner:
            return {"error": "ลบไอดีหลักไม่ได้"}
        db.delete(u); db.commit()
        return {"ok": True}
    finally:
        db.close()


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


def _registration_existing(account):
    if not account.verified and account.active and account.role != 'superadmin':
        return {'error': 'บัญชีนี้สมัครแล้วและกำลังรอยืนยันอีเมล', 'exists': True, 'pending_verify': True}
    return {'error': 'อีเมลนี้มีบัญชีอยู่แล้ว กรุณาเข้าสู่ระบบ หรือกดลืมรหัสผ่าน', 'exists': True}


POLICY_VERSION = "2569-09-01"      # ต้องตรงกับวันที่ปรับปรุงในหน้า /privacy


def record_policy_accept(tenant_id, ip: str = "") -> None:
    """บันทึกว่าโรงเรียนนี้ยอมรับนโยบายฉบับไหน เมื่อไหร่ จากไอพีใด
    (PDPA: ต้องพิสูจน์ได้ว่ามีการให้ความยินยอมจริง แค่มีป๊อปอัปให้กดไม่พอ)"""
    if not tenant_id:
        return
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        if t:
            t.policy_accepted_at = datetime.now()
            t.policy_version = POLICY_VERSION
            t.policy_accept_ip = (ip or "")[:60]
            db.commit()
    except Exception:
        pass
    finally:
        db.close()


def register_account(email: str, password: str, school_name: str,
                     contact_name: str = "", phone: str = "", trial_days: int = TRIAL_DAYS) -> dict:
    """ลงทะเบียน: อีเมล = ชื่อผู้ใช้, ตั้งรหัสเอง -> ทดลองใช้ TRIAL_DAYS วัน ไม่จำกัดจำนวนเอกสาร + auto-login
    อีเมลเดิมใช้เป็น username ตลอด (ต่ออายุก็อีเมลนี้) · คืน {uid, tenant_id, username, display_name} หรือ {error}"""
    from datetime import date, timedelta
    email = (email or "").strip().lower()
    school_name = (school_name or "").strip()
    if not _EMAIL_RE.match(email):
        return {"error": "อีเมลไม่ถูกต้อง"}
    _bad = password_problem(password, email)
    if _bad:
        return {"error": _bad}
    if not school_name:
        return {"error": "กรุณากรอกชื่อโรงเรียน"}
    db = acc_session()
    try:
        existing = db.query(Account).filter_by(username=email).first()
        if existing:
            return _registration_existing(existing)
        slug = _uniq_slug(db, _slugify_acc(email.split("@")[0]))
    finally:
        db.close()
    # ทดลองใช้: เต็มระบบ 30 วัน (นับจากวันสมัคร) · ไม่จำกัดจำนวนเอกสาร
    from sqlalchemy.exc import IntegrityError
    try:
        tid = provision_tenant(school_name, slug, email, password,
                               expiry_date=date.today() + timedelta(days=TRIAL_DAYS),
                               max_users=3, must_change=False, plan="trial", docs_limit=0)
    except IntegrityError:
        # Another request may have created the account after our initial check.
        db = acc_session()
        try:
            existing = db.query(Account).filter_by(username=email).first()
            if existing:
                return _registration_existing(existing)
        finally:
            db.close()
        raise
    import secrets
    # บังคับยืนยันอีเมลเสมอ (fail-closed): บัญชีใหม่ต้องยืนยันอีเมลก่อนเข้าใช้งาน
    token = secrets.token_urlsafe(24)
    db = acc_session()
    try:
        acc = db.query(Account).filter_by(username=email).first()
        acc.verified = False
        acc.verify_token = token
        db.add(Lead(kind="trial", school_name=school_name, contact_name=contact_name.strip(),
                    email=email, phone=phone.strip(), tenant_id=tid,
                    login_user=email, status="ทดลองใช้"))
        db.commit()
        return {"uid": acc.id, "tenant_id": tid, "username": email, "display_name": school_name,
                "needs_verify": True, "verify_token": token, "email": email}
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


def create_reset_token(email: str) -> str | None:
    """ออกโทเคนรีเซ็ตรหัสผ่าน (อายุ 1 ชม.) คืนโทเคน หรือ None ถ้าไม่พบอีเมล/บัญชีถูกระงับ"""
    import secrets
    from datetime import timedelta
    db = acc_session()
    try:
        a = db.query(Account).filter_by(username=(email or "").strip().lower()).first()
        if not a or not a.active:
            return None
        a.reset_token = secrets.token_urlsafe(24)
        a.reset_expires = datetime.now() + timedelta(hours=1)
        db.commit()
        return a.reset_token
    finally:
        db.close()


def account_by_reset_token(token: str):
    """ตรวจโทเคนรีเซ็ต -> คืน {uid, username} ถ้ายังไม่หมดอายุ หรือ None"""
    token = (token or "").strip()
    if not token:
        return None
    db = acc_session()
    try:
        a = db.query(Account).filter_by(reset_token=token).first()
        if not a or not a.reset_expires or a.reset_expires < datetime.now():
            return None
        return {"uid": a.id, "username": a.username}
    finally:
        db.close()


def reset_password_with_token(token: str, new_password: str) -> dict:
    """ตั้งรหัสผ่านใหม่จากโทเคนรีเซ็ต -> {ok, username} หรือ {error}
    ผู้ที่รีเซ็ตได้ = เข้าถึงอีเมลจริง จึงถือว่ายืนยันอีเมลแล้วด้วย"""
    token = (token or "").strip()
    _bad = password_problem(new_password)
    if _bad:
        return {"error": _bad}
    db = acc_session()
    try:
        a = db.query(Account).filter_by(reset_token=token).first()
        if not a or not a.reset_expires or a.reset_expires < datetime.now():
            return {"error": "ลิงก์รีเซ็ตหมดอายุหรือไม่ถูกต้อง กรุณาขอลิงก์ใหม่"}
        a.password_hash = hash_password(new_password)
        a.reset_token = ""
        a.reset_expires = None
        a.must_change_password = False
        a.verified = True
        db.commit()
        return {"ok": True, "username": a.username}
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
            return {"error": "คำสั่งซื้อนี้ไม่ได้ผูกกับบัญชี - ลูกค้าต้องลงทะเบียน/เข้าสู่ระบบก่อนสั่งซื้อ"}
        t = db.get(Tenant, tid)
        if not t:
            return {"error": "ไม่พบบัญชีโรงเรียน"}
        # สิทธิ์งานที่ซื้อ (lead เก่าที่ยังไม่มีคอลัมน์ modules -> แกะจากข้อความ packages)
        bought = parse_modules(lead.modules) or modules_from_label(lead.packages)
        owned = parse_modules(t.modules)
        if t.plan == 'trial' and not t.trial_expiry_date:
            t.trial_expiry_date = t.expiry_date or (t.created_at.date() + timedelta(days=TRIAL_DAYS))
        # Model B: "ซื้อเพิ่มกลางรอบ" (co-term) = สมาชิกที่ยังไม่หมดอายุ + งานที่ซื้อเป็นงานใหม่ล้วน
        #   -> เพิ่มงานให้หมดอายุพร้อมของเดิม ไม่ขยับวันหมดอายุ
        # อื่น ๆ (ทดลอง/หมดอายุ/ต่ออายุงานเดิม) = ต่ออายุ +days ตามปกติ
        is_addon = (t.plan == "member" and t.expiry_date and t.expiry_date >= date.today()
                    and bought and bought.isdisjoint(owned))
        if not is_addon:
            base = t.expiry_date if (t.expiry_date and t.expiry_date >= date.today()) else date.today()
            t.expiry_date = base + timedelta(days=days)
        t.active = True
        t.plan = "member"          # อัปเกรดจากทดลองใช้ -> สมาชิก
        if bought:
            t.modules = modules_csv(owned | bought)

        # โควตาทดลอง: ล้างเฉพาะเมื่อซื้อครบทุกงานแล้ว
        # ถ้าซื้อบางงาน ต้องคงโควตาที่เหลือไว้ให้ใช้กับงานที่ยังไม่ได้ซื้อ -
        # การซื้องานแรกต้องเป็นการอัปเกรดล้วน ๆ ห้ามริบสิทธิ์ทดลองของงานที่เหลือ
        if parse_modules(t.modules) == set(MODULE_KEYS):
            t.docs_limit = 0       # ซื้อครบ: ออกเอกสารไม่จำกัดทุกงาน
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
            print("[Easy Ekkasan] กู้คืนจากคลาวด์ตอนเปิดไม่สำเร็จ:", e)
    _ensure_engine()
    db = acc_session()
    try:
        # 1) superadmin เริ่มต้น (ผู้ขาย) - เปลี่ยนรหัสได้ภายหลัง
        if not db.query(Account).filter_by(role="superadmin").first():
            su = os.environ.get("DDOC_SUPERADMIN", "admin")
            sp = os.environ.get("DDOC_SUPERADMIN_PW", "admin123")
            db.add(Account(username=su, password_hash=hash_password(sp),
                           role="superadmin", display_name="ผู้ดูแลระบบ",
                           must_change_password=True))
            db.commit()
            print(f"[Easy Ekkasan] สร้าง superadmin เริ่มต้น: {su} / {sp}  (โปรดเปลี่ยนรหัสผ่าน)")

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
        print(f"[Easy Ekkasan] ย้ายข้อมูลเดิมเป็นโรงเรียน '{name}' (id={tid})")
    ensure_school_db(tid)
    print(f"[Easy Ekkasan] โรงเรียนแรก: ผู้ใช้ school / school123  (โปรดเปลี่ยนรหัสผ่าน)")
