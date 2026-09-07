# -*- coding: utf-8 -*-
"""
tenancy.py
----------
จัดการ "ฐานข้อมูลแยกต่อโรงเรียน" (multi-tenant แบบ DB-per-tenant)

- current_school_id : contextvar เก็บ id โรงเรียนของคำขอปัจจุบัน (ตั้งโดย middleware)
- engine_for / session_for : engine/session ของโรงเรียนนั้น (สร้าง+แคชครั้งแรก)
- ไฟล์ DB อยู่ที่ data/schools/<id>/school.db พร้อมเปิด WAL ให้หลายผู้ใช้พร้อมกันได้
"""
import contextvars
import os
from collections import OrderedDict

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.database import get_data_dir, init_school_db

# id โรงเรียนของคำขอปัจจุบัน (None = ยังไม่ได้เลือก/ยังไม่ล็อกอิน)
current_school_id = contextvars.ContextVar("current_school_id", default=None)

# งาน (โมดูล) ของคำขอปัจจุบัน (None = ไม่ใช่ของงานไหน เช่น หน้าเลือกงาน/ตั้งค่า)
# ตั้งโดย middleware · ใช้ตอนออกเอกสารเพื่อรู้ว่าควรหักโควตาทดลองหรือไม่
current_module = contextvars.ContextVar("current_module", default=None)

# แคช engine/session ต่อโรงเรียน: {school_id: (engine, SessionLocal)}
# ใช้ LRU มีเพดาน: ถ้าโรงเรียนเยอะ (หลักร้อย-พัน) การเก็บ engine ไว้ทุกโรงเรียนตลอด
# จะกิน RAM + file descriptor ไม่จำกัด (ยิ่งคูณจำนวน worker) จึงคืนตัวที่ไม่ได้ใช้นานสุด
_engines: "OrderedDict[object, tuple]" = OrderedDict()

# ปรับได้ด้วย env · 0 = ไม่จำกัด (พฤติกรรมเดิม)
try:
    _MAX_ENGINES = max(0, int(os.environ.get("DDOC_MAX_DB_ENGINES", "120")))
except ValueError:
    _MAX_ENGINES = 120


def _evict_if_needed():
    """คืน engine ที่ไม่ได้ใช้นานสุดเมื่อเกินเพดาน (การเชื่อมต่อที่กำลังใช้งานอยู่ไม่ถูกตัด
    - SQLAlchemy จะปิดให้ตอนคืนเข้า pool)"""
    while _MAX_ENGINES and len(_engines) > _MAX_ENGINES:
        _sid, (eng, _sl) = _engines.popitem(last=False)
        try:
            eng.dispose()
        except Exception:
            pass


def school_db_path(school_id):
    d = get_data_dir() / "schools" / str(school_id)
    d.mkdir(parents=True, exist_ok=True)
    return d / "school.db"


def _build(school_id):
    engine = create_engine(
        f"sqlite:///{school_db_path(school_id)}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_con, _):
        cur = dbapi_con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")    # หลายผู้ใช้เขียนพร้อมกันปลอดภัยขึ้น
        cur.execute("PRAGMA busy_timeout=5000")   # รอ 5 วิ ถ้าไฟล์ถูกล็อกชั่วคราว
        cur.close()

    init_school_db(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    _engines[school_id] = (engine, SessionLocal)
    _evict_if_needed()
    return _engines[school_id]


def _get(school_id):
    if school_id is None:
        raise RuntimeError("ยังไม่ได้เลือกโรงเรียน (ต้องล็อกอินก่อน)")
    pair = _engines.get(school_id)
    if pair is None:
        return _build(school_id)
    _engines.move_to_end(school_id)        # ใช้ล่าสุด -> ท้ายคิว (โดนคืนทีหลังสุด)
    return pair


def engine_for(school_id):
    return _get(school_id)[0]


def session_for(school_id):
    return _get(school_id)[1]()


def ensure_school_db(school_id):
    """สร้างไฟล์ DB + ตารางของโรงเรียน (เรียกตอน provision โรงเรียนใหม่)"""
    engine_for(school_id)


def dispose_engine(school_id):
    """ปิดและลบ engine ที่แคชไว้ (ใช้ก่อนเขียนทับไฟล์ตอนกู้คืน)"""
    pair = _engines.pop(school_id, None)
    if pair:
        pair[0].dispose()


def checkpoint_all():
    """flush WAL ของทุกโรงเรียนลงไฟล์ .db หลัก (เรียกก่อนสำรองข้อมูล กันข้อมูลตกหล่นใน .wal)"""
    for engine, _SL in list(_engines.values()):
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
