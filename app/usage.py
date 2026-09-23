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

from sqlalchemy import func

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


def days_with_data(db, limit: int = RETENTION_DAYS) -> list:
    """วันที่ที่มีข้อมูล (ใหม่ไปเก่า) ไว้ทำตัวเลือกวันในคอนโซล"""
    from app.accounts import UsageDay
    rows = (db.query(UsageDay.day).distinct()
            .order_by(UsageDay.day.desc()).limit(limit).all())
    return [r[0] for r in rows if r[0]]


# ---------------------------------------------------------------- สรุปหลายวัน
RANGES = [(1, "วันนี้"), (7, "7 วัน"), (30, "30 วัน"), (90, "90 วัน")]


def range_bounds(days: int, end_day: str = "") -> tuple:
    """ช่วงวันที่ (เริ่ม, สิ้นสุด) ย้อนหลัง days วันโดยนับวันสุดท้ายด้วย"""
    end = date.fromisoformat(end_day) if end_day else date.today()
    start = end - timedelta(days=max(1, days) - 1)
    return start.isoformat(), end.isoformat()


def _mods(text):
    try:
        return json.loads(text or "{}")
    except Exception:
        return {}


def _mod_label(key):
    """คีย์งาน -> ชื่อไทย (คีย์ที่ไม่รู้จักแสดงตามเดิม)"""
    from app.modules import MODULE_LABELS
    return MODULE_LABELS.get(key, key)


def summary_for_range(db, start: str, end: str) -> dict:
    """สรุปการใช้งานทั้งช่วง แยกรายโรงเรียน (มีรายบัญชีซ้อนอยู่ข้างใน)

    คืน  schools = รายโรงเรียนที่มีการใช้งาน (เรียงตามจำนวนครั้ง)
         daily   = ยอดรวมรายวันทุกวันในช่วง (ไว้วาดกราฟแท่ง วันที่ไม่มีข้อมูล = 0)
         idle    = โรงเรียนที่ไม่มีการใช้งานเลยในช่วงนี้ + ใช้ล่าสุดเมื่อไหร่
         totals  = ยอดรวมของทั้งช่วง
    """
    from app.accounts import UsageDay, Tenant
    rows = (db.query(UsageDay)
            .filter(UsageDay.day >= start, UsageDay.day <= end).all())
    tenants = {t.id: t for t in db.query(Tenant).all()}

    schools, daily = {}, {}
    d0, d1 = date.fromisoformat(start), date.fromisoformat(end)
    d = d0
    while d <= d1:
        daily[d.isoformat()] = {"day": d.isoformat(), "schools": set(), "users": 0,
                                "hits": 0, "writes": 0, "docs": 0}
        d += timedelta(days=1)

    for r in rows:
        t = tenants.get(r.tenant_id)
        sc = schools.get(r.tenant_id)
        if sc is None:
            sc = schools[r.tenant_id] = {
                "tenant_id": r.tenant_id,
                "tenant": (t.name if t else None) or f"โรงเรียน #{r.tenant_id}",
                "plan": (t.plan if t else ""), "expiry": (t.expiry_date if t else None),
                "active": (t.active if t else True),
                "users": {}, "days": set(), "hits": 0, "writes": 0, "docs": 0,
                "modules": {}, "last_at": None,
            }
        u = sc["users"].get(r.uid)
        if u is None:
            u = sc["users"][r.uid] = {"uid": r.uid, "username": r.username,
                                      "display_name": r.display_name, "days": set(),
                                      "hits": 0, "writes": 0, "docs": 0,
                                      "modules": {}, "last_at": None}
        for box in (sc, u):
            box["days"].add(r.day)
            box["hits"] += r.hits or 0
            box["writes"] += r.writes or 0
            box["docs"] += r.docs or 0
            if r.last_at and (box["last_at"] is None or r.last_at > box["last_at"]):
                box["last_at"] = r.last_at
            for k, v in _mods(r.modules).items():
                box["modules"][k] = box["modules"].get(k, 0) + v
        day = daily.get(r.day)
        if day:
            day["schools"].add(r.tenant_id)
            day["users"] += 1
            day["hits"] += r.hits or 0
            day["writes"] += r.writes or 0
            day["docs"] += r.docs or 0

    out_schools = []
    for sc in schools.values():
        users = sorted(sc["users"].values(), key=lambda x: -x["hits"])
        for u in users:
            u["days_active"] = len(u["days"])
            u["modules"] = [(_mod_label(k), v) for k, v in
                            sorted(u["modules"].items(), key=lambda kv: -kv[1])]
        sc["users"] = users
        sc["n_users"] = len(users)
        sc["days_active"] = len(sc["days"])
        sc["modules"] = [(_mod_label(k), v) for k, v in
                         sorted(sc["modules"].items(), key=lambda kv: -kv[1])]
        out_schools.append(sc)
    out_schools.sort(key=lambda x: (-x["hits"], x["tenant"]))

    # โรงเรียนที่ไม่ได้ใช้เลยในช่วงนี้ (เรียงจากที่เงียบนานสุด)
    last_seen = dict(db.query(UsageDay.tenant_id, func.max(UsageDay.day))
                     .group_by(UsageDay.tenant_id).all())
    idle = [{"tenant_id": t.id, "tenant": t.name or f"โรงเรียน #{t.id}",
             "plan": t.plan, "active": t.active, "last_day": last_seen.get(t.id)}
            for t in tenants.values() if t.id not in schools]
    idle.sort(key=lambda x: (x["last_day"] or ""))

    daily_rows = [dict(v, schools=len(v["schools"])) for v in
                  sorted(daily.values(), key=lambda x: x["day"])]
    return {
        "schools": out_schools, "idle": idle, "daily": daily_rows,
        "totals": {
            "schools": len(out_schools),
            "users": sum(s["n_users"] for s in out_schools),
            "hits": sum(s["hits"] for s in out_schools),
            "writes": sum(s["writes"] for s in out_schools),
            "docs": sum(s["docs"] for s in out_schools),
        },
    }
