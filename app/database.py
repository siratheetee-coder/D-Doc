"""
database.py
-----------
จุดเชื่อมต่อฐานข้อมูล SQLite ด้วย SQLAlchemy

โหมด multi-tenant: **1 โรงเรียน = 1 ไฟล์ฐานข้อมูล** (data/schools/<id>/school.db)
- ตัวเลือก engine/session ต่อโรงเรียนอยู่ใน app/tenancy.py
- get_db() เลือกฐานข้อมูลตามโรงเรียนที่ล็อกอิน (current_school_id)
- ฐานข้อมูลกลาง (บัญชีผู้ใช้/โรงเรียน) อยู่ใน app/accounts.py

โมเดลและ migration เดิมใช้ต่อได้ทั้งหมด เพราะภายในแต่ละ DB ยังเป็น "โรงเรียนเดียว"
"""
from pathlib import Path
import sys
import shutil
from datetime import datetime

from sqlalchemy.orm import declarative_base


def get_data_dir() -> Path:
    """โฟลเดอร์เก็บข้อมูล (data/) — รากโปรเจกต์ หรือข้าง ๆ .exe เมื่อแพ็กแล้ว"""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    data_dir = base / "data"
    data_dir.mkdir(exist_ok=True)
    return data_dir


# Base = คลาสแม่ของทุกตารางในไฟล์ models.py (ใช้ร่วมทุกโรงเรียน)
Base = declarative_base()


# รายการเพิ่มคอลัมน์ใหม่บน DB เก่า (ปลอดภัย: ข้ามถ้ามีอยู่แล้ว)
MIGRATIONS = [
    ("vendor",      "owner_name",       "VARCHAR DEFAULT ''"),
    ("procurement", "spec_memo_date",   "DATETIME"),
    ("procurement", "result_memo_date", "DATETIME"),
    ("procurement", "command_date",     "DATETIME"),
    ("procurement", "delivery_date",    "DATETIME"),
    ("project",     "budget",           "FLOAT DEFAULT 0"),
    ("project",     "budget_note",      "VARCHAR DEFAULT ''"),
    ("incoming_letter", "file_path",    "VARCHAR DEFAULT ''"),
    ("procurement",     "file_path",    "VARCHAR DEFAULT ''"),
    ("school",          "ai_api_key",   "VARCHAR DEFAULT ''"),
    ("finance_txn",     "item_id",      "INTEGER"),
    ("receipt",         "txn_id",       "INTEGER"),
    ("finance_account", "deposit_type", "VARCHAR DEFAULT 'bank'"),
    ("account_item",    "deposit_type", "VARCHAR DEFAULT 'bank'"),
    ("disburse_memo",   "vat",          "FLOAT DEFAULT 0"),
    ("disburse_memo",   "wht",          "FLOAT DEFAULT 0"),
    ("disburse_memo",   "fine",         "FLOAT DEFAULT 0"),
    ("disburse_memo",   "proc_kind",    "VARCHAR DEFAULT 'จัดซื้อ'"),
    ("school", "finance_officer_name",  "VARCHAR DEFAULT ''"),
    ("school", "finance_head_name",     "VARCHAR DEFAULT ''"),
    ("school", "admin_officer_name",    "VARCHAR DEFAULT ''"),
]


def run_migrations(engine) -> None:
    """เพิ่มคอลัมน์ใหม่บน DB ของโรงเรียนที่ระบุ"""
    conn = engine.raw_connection()
    cursor = conn.cursor()
    for table, col, coltype in MIGRATIONS:
        try:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        except Exception:
            pass
    conn.commit()
    conn.close()


def init_school_db(engine) -> None:
    """สร้างตารางทั้งหมด + เพิ่มคอลัมน์ใหม่ บน DB ของโรงเรียนที่ระบุ"""
    from app import models  # noqa: F401  (ลงทะเบียนตารางทั้งหมด)
    Base.metadata.create_all(bind=engine)
    run_migrations(engine)


def get_db():
    """ส่งเซสชันของ DB โรงเรียนที่ล็อกอินอยู่ (current_school_id) ให้แต่ละคำขอ"""
    from app.tenancy import current_school_id, session_for
    sid = current_school_id.get()
    db = session_for(sid)
    try:
        yield db
    finally:
        db.close()


# ===================== สำรอง / กู้คืน (ของโรงเรียนปัจจุบัน) =====================
def backups_dir() -> Path:
    d = get_data_dir() / "backups"
    d.mkdir(exist_ok=True)
    return d


def _current_engine_path():
    from app.tenancy import current_school_id, engine_for, school_db_path
    sid = current_school_id.get()
    return engine_for(sid), school_db_path(sid)


def _checkpoint() -> None:
    """บังคับเขียนข้อมูลค้าง (WAL) ลงไฟล์ก่อนสำรอง"""
    try:
        engine, _ = _current_engine_path()
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(FULL)")
    except Exception:
        pass


def make_backup_copy(label: str = "auto") -> Path:
    """ก๊อปไฟล์ DB ของโรงเรียนปัจจุบันเก็บใน data/backups/"""
    _checkpoint()
    _, db_path = _current_engine_path()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = backups_dir() / f"school-{label}-{ts}.db"
    shutil.copy2(db_path, dest)
    return dest


def restore_db(data: bytes) -> None:
    """กู้คืน DB ของโรงเรียนปัจจุบันจากไฟล์ที่อัปโหลด (สำรองไฟล์ปัจจุบันก่อนเสมอ)"""
    from app.tenancy import current_school_id, dispose_engine, school_db_path
    make_backup_copy("before-restore")
    sid = current_school_id.get()
    db_path = school_db_path(sid)
    dispose_engine(sid)          # ปิด+ลบ engine ที่แคชไว้ ก่อนเขียนทับ
    with open(db_path, "wb") as f:
        f.write(data)


def current_db_path() -> Path:
    """ที่อยู่ไฟล์ DB ของโรงเรียนปัจจุบัน (ใช้ดาวน์โหลดสำรอง)"""
    _, db_path = _current_engine_path()
    return db_path
