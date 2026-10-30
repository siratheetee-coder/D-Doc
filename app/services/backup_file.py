# -*- coding: utf-8 -*-
"""
backup_file.py - ไฟล์สำรองของโรงเรียน (.zip): สร้าง เซ็น อ่านก่อนกู้คืน และกติกาว่ากู้คืนได้ไหม

ไฟล์สำรองมี meta.json ที่เซ็นด้วยคีย์ของเซิร์ฟเวอร์ (HMAC) ผูกกับเลขโรงเรียนต้นทางและ hash ของ school.db
แก้ meta หรือสลับ school.db แล้วลายเซ็นไม่ตรง = ไฟล์ไม่ได้เซ็น

กติกา (เจ้าของเลือก 2026-10-30): กันสมัครบัญชีใหม่แล้วกู้คืนไฟล์ของโรงเรียนอื่นเพื่อใช้ทดลองต่อไปเรื่อย ๆ
  - บัญชีทดลอง/ระบบตัวอย่าง (plan ไม่ใช่ member) กู้คืนได้เฉพาะไฟล์ที่เซ็นแล้วและสำรองจากบัญชีตัวเอง
  - สมาชิกที่จ่ายแล้ว กู้คืนได้ทุกไฟล์ (เช่น ย้ายบัญชี) รวมไฟล์รุ่นเก่าที่ยังไม่มีลายเซ็น
"""
import hashlib
import hmac
import io
import json
import os
import secrets
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime

FORMAT = "easy-ekkasan-school-backup"
VERSION = 2
SQLITE_MAGIC = b"SQLite format 3\x00"
PENDING_TTL = 3600            # ไฟล์ที่อัปโหลดรอยืนยัน เก็บไว้ 1 ชั่วโมง

# ตารางที่นับให้ดูก่อนกู้คืน (ชื่อที่แสดง, ชื่อตาราง)
COUNT_TABLES = [("เรื่องจัดซื้อจัดจ้าง", "procurement"), ("ครุภัณฑ์", "asset"), ("รายการรับ-จ่ายเงิน", "finance_txn"),
                ("บุคลากร", "person"), ("นักเรียน", "student"), ("หนังสือรับ-ส่ง", "document"),
                ("โครงการ", "project"), ("โครงการอาหารกลางวัน", "lunch_program")]


def _key() -> bytes:
    from app.accounts import get_secret_key
    return ("backup-sign:" + get_secret_key()).encode("utf-8")


def _sign(meta: dict) -> str:
    body = json.dumps({k: v for k, v in meta.items() if k != "sig"}, ensure_ascii=False, sort_keys=True)
    return hmac.new(_key(), body.encode("utf-8"), hashlib.sha256).hexdigest()


def build(tenant_id, school_name: str, db_path, users: list) -> bytes:
    """สร้างไฟล์สำรอง .zip (ข้อมูลทุกงาน + บัญชีผู้ใช้) พร้อม meta ที่เซ็นแล้ว"""
    db_bytes = open(db_path, "rb").read()
    meta = {"format": FORMAT, "version": VERSION, "created_at": datetime.now().isoformat(timespec="seconds"),
            "school_name": school_name or "", "tenant_id": tenant_id, "accounts": len(users),
            "db_sha256": hashlib.sha256(db_bytes).hexdigest()}
    meta["sig"] = _sign(meta)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
        z.writestr("school.db", db_bytes)
        z.writestr("users.json", json.dumps(users, ensure_ascii=False))
    return buf.getvalue()


def _counts(db_bytes: bytes) -> list:
    """นับข้อมูลหลักในไฟล์ (เปิดแบบอ่านอย่างเดียวจากสำเนาชั่วคราว)"""
    out = []
    fd, path = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(db_bytes)
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for label, table in COUNT_TABLES:
                try:
                    n = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                except sqlite3.Error:
                    continue
                if n:
                    out.append((label, int(n)))
            try:
                row = con.execute("SELECT name FROM school LIMIT 1").fetchone()
                out.insert(0, ("ชื่อโรงเรียนในไฟล์", (row[0] or "").strip() if row else ""))
            except sqlite3.Error:
                pass
        finally:
            con.close()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return out


def read(data: bytes) -> dict:
    """อ่านไฟล์สำรองที่อัปโหลด -> {ok, error, db_bytes, users, meta, signed, origin, counts, legacy}"""
    info = {"ok": False, "error": "", "db_bytes": None, "users": None, "meta": {}, "signed": False,
            "origin": None, "counts": [], "legacy": False}
    if data[:16] == SQLITE_MAGIC:                   # ไฟล์ .db รุ่นแรก: ข้อมูลอย่างเดียว ไม่มีลายเซ็น
        info.update(ok=True, db_bytes=data, legacy=True)
    elif data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = set(z.namelist())
                if "school.db" not in names:
                    info["error"] = "ไม่ใช่ไฟล์สำรองของระบบ (ไม่มีข้อมูลโรงเรียนในไฟล์)"
                    return info
                db_bytes = z.read("school.db")
                if db_bytes[:16] != SQLITE_MAGIC:
                    info["error"] = "ไฟล์ข้อมูลในไฟล์สำรองเสีย"
                    return info
                info.update(ok=True, db_bytes=db_bytes)
                if "users.json" in names:
                    try:
                        v = json.loads(z.read("users.json").decode("utf-8"))
                        info["users"] = v if isinstance(v, list) else None
                    except Exception:
                        info["users"] = None
                if "meta.json" in names:
                    try:
                        meta = json.loads(z.read("meta.json").decode("utf-8"))
                        info["meta"] = meta if isinstance(meta, dict) else {}
                    except Exception:
                        info["meta"] = {}
        except zipfile.BadZipFile:
            info["error"] = "ไฟล์ .zip เสีย เปิดไม่ได้"
            return info
    else:
        info["error"] = "ไฟล์ที่อัปโหลดไม่ใช่ไฟล์สำรองของระบบ (.zip หรือ .db)"
        return info
    meta = info["meta"]
    sig = meta.get("sig") if meta else None
    if sig and hmac.compare_digest(str(sig), _sign(meta)) \
            and meta.get("db_sha256") == hashlib.sha256(info["db_bytes"]).hexdigest():
        info["signed"] = True
        info["origin"] = meta.get("tenant_id")
    else:
        info["legacy"] = True
    try:
        info["counts"] = _counts(info["db_bytes"])
    except Exception:
        info["counts"] = []
    return info


def decide(info: dict, tenant_id, plan: str) -> tuple:
    """กู้คืนไฟล์นี้เข้าโรงเรียนนี้ได้ไหม -> (ได้/ไม่ได้, เหตุผล)"""
    if not info.get("ok"):
        return False, info.get("error") or "อ่านไฟล์ไม่ได้"
    if (plan or "member") == "member":
        return True, ""
    if info.get("signed") and str(info.get("origin")) == str(tenant_id):
        return True, ""
    if not info.get("signed"):
        return False, ("บัญชีทดลองใช้กู้คืนได้เฉพาะไฟล์สำรองที่ดาวน์โหลดจากบัญชีนี้ "
                       "ไฟล์นี้เป็นไฟล์รุ่นเก่าหรือไม่ได้มาจากระบบ หากจำเป็นต้องใช้ กรุณาติดต่อเจ้าหน้าที่")
    return False, ("ไฟล์นี้สำรองมาจากบัญชีโรงเรียนอื่น บัญชีทดลองใช้กู้คืนได้เฉพาะไฟล์ของบัญชีนี้ "
                   "หากต้องการย้ายข้อมูลมาบัญชีใหม่ กรุณาติดต่อเจ้าหน้าที่")


# ---------------- ไฟล์ที่อัปโหลดรอยืนยัน (กู้คืน / นำเข้า Excel) ----------------
def _pending_dir():
    from app.accounts import get_data_dir
    d = get_data_dir() / "pending_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _clean(d) -> None:
    now = time.time()
    for p in d.iterdir():
        try:
            if now - p.stat().st_mtime > PENDING_TTL:
                p.unlink()
        except OSError:
            pass


def stash(tenant_id, kind: str, data: bytes) -> str:
    """เก็บไฟล์ไว้รอกดยืนยัน คืนโทเคน (ผูกกับโรงเรียน ใช้ข้ามโรงเรียนไม่ได้)"""
    d = _pending_dir()
    _clean(d)
    token = secrets.token_urlsafe(16)
    (d / f"{kind}_{int(tenant_id or 0)}_{token}.bin").write_bytes(data)
    return token


def _path(tenant_id, kind: str, token: str):
    if not token or not all(c.isalnum() or c in "-_" for c in token):
        return None
    p = _pending_dir() / f"{kind}_{int(tenant_id or 0)}_{token}.bin"
    if not p.exists() or time.time() - p.stat().st_mtime > PENDING_TTL:
        return None
    return p


def load(tenant_id, kind: str, token: str):
    p = _path(tenant_id, kind, token)
    return p.read_bytes() if p else None


def drop(tenant_id, kind: str, token: str) -> None:
    p = _path(tenant_id, kind, token)
    if p:
        try:
            p.unlink()
        except OSError:
            pass
