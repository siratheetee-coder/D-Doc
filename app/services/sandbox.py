# -*- coding: utf-8 -*-
"""
sandbox.py - "ทดลองใช้ระบบตัวอย่าง" จากหน้า landing โดยไม่ต้องสมัคร

  - กดปุ่มแล้วได้โรงเรียนสมมติของตัวเอง 1 โรงเรียน (ข้อมูลครบ 6 งาน จาก demo_seed)
    คนละฐานข้อมูลกับคนอื่น ใครกรอกอะไรก็ไม่มีใครเห็น
  - ลบทิ้งเองเมื่อครบ 24 ชั่วโมง (ล้างตอนมีคนกดใหม่ และตอนเปิดเซิร์ฟเวอร์)
  - ปิดส่วนที่ไม่ควรเปิดให้คนทั่วไป: ส่งอีเมล, AI, บัญชีผู้ใช้/รหัสผ่าน, กู้คืนข้อมูล, แชทกับทีมงาน
  - ฐานข้อมูลต้นแบบสร้างวันละครั้ง (วันที่ในข้อมูลสมมติเลื่อนตามวันจริง) แล้วคัดลอกให้แต่ละคน
"""
import os
import re
import secrets
import shutil
import threading
import time
from datetime import date, datetime, timedelta

PLAN = "sandbox"
HOURS = 24
SCHOOL_NAME = "โรงเรียนบ้านตัวอย่างวิทยา (ระบบตัวอย่าง)"
USER_PREFIX = "sandbox-"

try:
    MAX_ACTIVE = max(1, int(os.environ.get("DDOC_SANDBOX_MAX", "200")))
except ValueError:
    MAX_ACTIVE = 200
PER_IP_PER_HOUR = 10

# ส่วนที่ปิดในระบบตัวอย่าง (เฉพาะการบันทึก · เปิดดูหน้าได้ปกติ)
_BLOCK_WRITE = ("/account", "/users", "/restore", "/support", "/academic/teacher-accounts")

_lock = threading.Lock()
_ip_hits: dict = {}
_cache: dict = {}            # tenant_id -> (is_sandbox, เวลาที่อ่าน)


def is_sandbox(tenant_id) -> bool:
    """โรงเรียนนี้เป็นระบบตัวอย่างไหม (แคช 5 นาที เรียกได้บ่อย)"""
    if not tenant_id:
        return False
    hit = _cache.get(tenant_id)
    if hit and time.time() - hit[1] < 300:
        return hit[0]
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        t = db.get(Tenant, tenant_id)
        val = bool(t and (t.plan or "") == PLAN)
    finally:
        db.close()
    _cache[tenant_id] = (val, time.time())
    return val


def blocked(path: str, method: str) -> bool:
    if method not in ("POST", "PUT", "PATCH", "DELETE"):
        return False
    return any(path == p or path.startswith(p + "/") for p in _BLOCK_WRITE)


def clean_ref(v) -> str:
    """ชื่อลิงก์ที่มา: ตัวอักษร/ตัวเลข/ภาษาไทย/ - _ . ไม่เกิน 40 ตัว"""
    v = re.sub(r"[^0-9A-Za-z฀-๿._-]", "", (v or "").strip())
    return v[:40]


# ------------------------------------------------------------------ ต้นแบบ
def _dir():
    from app.database import get_data_dir
    d = get_data_dir() / "sandbox"
    d.mkdir(parents=True, exist_ok=True)
    return d


def template_path(today: date | None = None):
    today = today or date.today()
    return _dir() / f"template-{today:%Y%m%d}.db"


def ensure_template(today: date | None = None):
    """ฐานข้อมูลต้นแบบของวันนี้ (สร้างครั้งแรกของวัน ใช้เวลาไม่กี่วินาที)"""
    today = today or date.today()
    path = template_path(today)
    if path.exists():
        return path
    with _lock:
        if path.exists():
            return path
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.database import init_school_db
        from app.services.demo_seed import seed_school
        tmp = _dir() / f"build-{os.getpid()}-{secrets.token_hex(4)}.db"
        engine = create_engine(f"sqlite:///{tmp}", connect_args={"check_same_thread": False})
        try:
            init_school_db(engine)
            db = sessionmaker(bind=engine)()
            try:
                seed_school(db, today=today)
            finally:
                db.close()
        finally:
            engine.dispose()
        os.replace(tmp, path)
        for old in _dir().glob("*.db"):
            if old != path:
                try:
                    old.unlink()
                except OSError:
                    pass
    return path


# ------------------------------------------------------------------ สร้าง / ล้าง
def _rate_ok(ip: str) -> bool:
    now = time.time()
    with _lock:
        hits = [t for t in _ip_hits.get(ip, []) if now - t < 3600]
        if len(hits) >= PER_IP_PER_HOUR:
            _ip_hits[ip] = hits
            return False
        hits.append(now)
        _ip_hits[ip] = hits
        return True


def cleanup(now: datetime | None = None, limit: int = 50) -> int:
    """ลบระบบตัวอย่างที่ครบ 24 ชั่วโมงแล้ว"""
    from app.accounts import acc_session, Tenant, purge_tenant
    cut = (now or datetime.now()) - timedelta(hours=HOURS)
    db = acc_session()
    try:
        ids = [t.id for t in db.query(Tenant.id).filter(Tenant.plan == PLAN, Tenant.created_at < cut)
               .limit(limit)]
    finally:
        db.close()
    for tid in ids:
        purge_tenant(tid)
        _cache.pop(tid, None)
    return len(ids)


def active_count() -> int:
    from app.accounts import acc_session, Tenant
    db = acc_session()
    try:
        return db.query(Tenant).filter(Tenant.plan == PLAN).count()
    finally:
        db.close()


def create(ip: str = "", ref: str = "") -> dict:
    """สร้างระบบตัวอย่างใหม่ 1 ชุด คืน {uid, tid, username, name} หรือ {error}"""
    from app.accounts import acc_session, Tenant, Account, SandboxVisit, hash_password
    from app.modules import ALL_MODULES_CSV
    from app.tenancy import school_db_path, dispose_engine

    try:
        cleanup()
    except Exception as e:  # noqa: BLE001  ล้างไม่ได้ไม่ควรทำให้คนใหม่เข้าไม่ได้
        print("[sandbox] ล้างระบบตัวอย่างเก่าไม่สำเร็จ:", e)
    if ip and not _rate_ok(ip):
        return {"error": "เปิดระบบตัวอย่างถี่เกินไป กรุณาลองใหม่ในอีกสักครู่"}
    if active_count() >= MAX_ACTIVE:
        return {"error": "ตอนนี้มีผู้ทดลองใช้ระบบตัวอย่างเต็มแล้ว กรุณาลองใหม่ในอีกสักครู่ หรือสมัครทดลองใช้ฟรีได้เลย"}
    tpl = ensure_template()

    token = secrets.token_hex(6)
    username = USER_PREFIX + token
    now = datetime.now()
    db = acc_session()
    try:
        t = Tenant(name=SCHOOL_NAME, slug=username, active=True, plan=PLAN, modules=ALL_MODULES_CSV,
                   docs_limit=0, max_users=1, expiry_date=date.today() + timedelta(days=2),
                   policy_version=PLAN, last_active_at=now, signup_ref=clean_ref(ref))
        db.add(t); db.flush()
        a = Account(tenant_id=t.id, username=username, password_hash=hash_password(secrets.token_urlsafe(24)),
                    display_name="ผู้ทดลองใช้ระบบตัวอย่าง", role="user", is_owner=True, active=True,
                    welcomed=True, verified=True, must_change_password=False)
        db.add(a)
        db.add(SandboxVisit(ref=clean_ref(ref)))
        db.commit()
        tid, uid = t.id, a.id
    finally:
        db.close()
    dispose_engine(tid)
    dest = school_db_path(tid)
    for extra in (dest.with_name(dest.name + "-wal"), dest.with_name(dest.name + "-shm")):
        if extra.exists():          # เลข id ซ้ำกับโรงเรียนที่ลบไปแล้ว ไฟล์ค้างต้องไม่ปนกับต้นแบบ
            extra.unlink()
    shutil.copyfile(tpl, dest)
    _cache[tid] = (True, time.time())
    return {"uid": uid, "tid": tid, "username": username, "name": SCHOOL_NAME}
