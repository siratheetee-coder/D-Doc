# -*- coding: utf-8 -*-
"""
usage.py - สรุปการใช้งานรายวันของแต่ละบัญชี (สำหรับคอนโซลเจ้าของระบบ)

ตั้งใจเก็บแค่ "สรุปรายวัน" ไม่ใช่ log ทุกการเปิดหน้า เพราะ
  - log รายคลิกคือข้อมูลส่วนบุคคลเต็ม ๆ และโตเร็วมาก
  - สิ่งที่ต้องตอบจริง ๆ คือ "วันนี้ใครใช้ ใช้งานไหน ออกเอกสารกี่ฉบับ" เท่านั้น
เหตุการณ์สำคัญรายครั้ง (ล็อกอินผิด/รีเซ็ตรหัส/กู้คืนข้อมูล) ยังอยู่ที่ AuditLog เหมือนเดิม

เก็บอะไร (ต่อ 1 บัญชี 1 วัน)
  - จำนวนครั้งที่เรียกใช้ระบบ · จำนวนเอกสารที่ออก
  - งานที่ใช้ + จำนวนครั้งของแต่ละงาน (พัสดุ/การเงิน/วิชาการ ...)
  - เวลาเข้าใช้ครั้งแรกและครั้งสุดท้ายของวัน
ไม่เก็บ: URL ที่เปิด · ข้อมูลที่กรอก · IP (IP อยู่ใน AuditLog เฉพาะเหตุการณ์สำคัญ)

เก็บย้อนหลัง RETENTION_DAYS วัน เกินกว่านั้นลบทิ้งอัตโนมัติตอน flush
"""
import json
import threading
import time
from datetime import date, datetime, timedelta

RETENTION_DAYS = 90        # อายุข้อมูลสรุปการใช้งาน
_FLUSH_SECONDS = 30        # เขียนลงฐานข้อมูลทุก ๆ กี่วินาที (ระหว่างนั้นพักไว้ในหน่วยความจำ)
_FLUSH_MAX_KEYS = 200      # หรือเมื่อค้างเกินกี่รายการ

_DOC_TYPES = ("wordprocessingml", "spreadsheetml", "application/pdf",
              "presentationml", "application/zip")

_lock = threading.Lock()
_buf: dict = {}            # (tenant_id, uid, day) -> ข้อมูลสะสม
_last_flush = time.time()
_last_purge = ""           # วันที่ล้างข้อมูลเก่าครั้งล่าสุด (ลบวันละครั้งพอ)


def _is_doc(content_type: str) -> bool:
    ct = (content_type or "").lower()
    return any(t in ct for t in _DOC_TYPES)


def record(tenant_id, acc, module, method: str, content_type: str = "") -> None:
    """นับการใช้งาน 1 ครั้ง (เรียกจาก middleware หลังตอบกลับแล้ว)"""
    if not tenant_id or not acc:
        return
    uid = acc.get("uid")
    if not uid:
        return
    key = (int(tenant_id), int(uid), date.today().isoformat())
    now = datetime.now()
    with _lock:
        row = _buf.get(key)
        if row is None:
            row = _buf[key] = {
                "username": acc.get("username") or "",
                "display_name": acc.get("display_name") or "",
                "hits": 0, "writes": 0, "docs": 0, "modules": {},
                "first_at": now, "last_at": now,
            }
        row["hits"] += 1
        row["last_at"] = now
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            row["writes"] += 1
        if _is_doc(content_type):
            row["docs"] += 1
        if module:
            row["modules"][module] = row["modules"].get(module, 0) + 1
        need = len(_buf) >= _FLUSH_MAX_KEYS or (time.time() - _last_flush) >= _FLUSH_SECONDS
    if need:
        flush()


def flush() -> int:
    """เขียนที่ค้างในหน่วยความจำลงฐานข้อมูล (รวมยอดกับของเดิมของวันนั้น)"""
    global _last_flush, _last_purge
    with _lock:
        pending, _buf_clear = dict(_buf), _buf.clear()
        _last_flush = time.time()
    if not pending:
        return 0
    from app.accounts import acc_session, UsageDay
    db = acc_session()
    try:
        for (tid, uid, day), row in pending.items():
            rec = (db.query(UsageDay)
                   .filter_by(tenant_id=tid, uid=uid, day=day).first())
            if rec is None:
                rec = UsageDay(tenant_id=tid, uid=uid, day=day,
                               first_at=row["first_at"], modules="{}")
                db.add(rec)
            rec.username = row["username"] or rec.username
            rec.display_name = row["display_name"] or rec.display_name
            rec.hits = (rec.hits or 0) + row["hits"]
            rec.writes = (rec.writes or 0) + row["writes"]
            rec.docs = (rec.docs or 0) + row["docs"]
            rec.last_at = row["last_at"]
            try:
                mods = json.loads(rec.modules or "{}")
            except Exception:
                mods = {}
            for k, v in row["modules"].items():
                mods[k] = mods.get(k, 0) + v
            rec.modules = json.dumps(mods, ensure_ascii=False)
        today = date.today().isoformat()
        if _last_purge != today:
            cut = (date.today() - timedelta(days=RETENTION_DAYS)).isoformat()
            db.query(UsageDay).filter(UsageDay.day < cut).delete(synchronize_session=False)
            _last_purge = today
        db.commit()
        return len(pending)
    except Exception:
        db.rollback()
        return 0
    finally:
        db.close()


def days_with_data(db, limit: int = 60) -> list:
    """วันที่ที่มีข้อมูล (ใหม่ไปเก่า) ไว้ทำตัวเลือกวันในคอนโซล"""
    from app.accounts import UsageDay
    rows = (db.query(UsageDay.day).distinct()
            .order_by(UsageDay.day.desc()).limit(limit).all())
    return [r[0] for r in rows if r[0]]


def summary_for_day(db, day: str) -> list:
    """สรุปการใช้งานของวันนั้น เรียงตามโรงเรียนและจำนวนครั้ง"""
    from app.accounts import UsageDay, Tenant
    rows = db.query(UsageDay).filter_by(day=day).all()
    names = {t.id: (t.name or f"โรงเรียน #{t.id}") for t in db.query(Tenant).all()}
    out = []
    for r in rows:
        try:
            mods = json.loads(r.modules or "{}")
        except Exception:
            mods = {}
        out.append({
            "tenant_id": r.tenant_id,
            "tenant": names.get(r.tenant_id, f"#{r.tenant_id}"),
            "username": r.username, "display_name": r.display_name,
            "hits": r.hits or 0, "writes": r.writes or 0, "docs": r.docs or 0,
            "first_at": r.first_at, "last_at": r.last_at,
            "modules": sorted(mods.items(), key=lambda kv: -kv[1]),
        })
    out.sort(key=lambda x: (x["tenant"], -x["hits"]))
    return out
