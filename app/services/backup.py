# -*- coding: utf-8 -*-
"""
backup.py — สำรองข้อมูลทุกโรงเรียน + อัปขึ้นคลาวด์ (off-site) แบบ "ประหยัด bandwidth"

หลักการประหยัด egress (สำคัญบน Render ฟรีที่จำกัด bandwidth):
- สำรองเฉพาะ "ข้อมูลจริง": ฐานข้อมูล (.db) + ไฟล์แนบ (uploads) — ไม่รวม documents/ (เอกสารที่ generate ใหม่ได้)
- อัปขึ้นคลาวด์ "เฉพาะตอนข้อมูลเปลี่ยนจริง" (เทียบ fingerprint) ถ้าไม่เปลี่ยน -> ข้าม ไม่อัป
- อัปทับ latest.zip ทุกครั้งที่เปลี่ยน (ไว้กู้คืน) + เก็บ snapshot ลงวันที่ "วันละ 1 ครั้ง" (ไว้ดูย้อนหลัง)

ตั้งค่าผ่าน env (S3-compatible: Cloudflare R2 / B2 / S3 / Wasabi):
    BACKUP_S3_ENDPOINT, BACKUP_S3_BUCKET, BACKUP_S3_KEY_ID, BACKUP_S3_SECRET, BACKUP_S3_REGION
"""
import os
import hashlib
import zipfile
from pathlib import Path
from datetime import datetime

from app.database import get_data_dir

KEEP = 14                                   # เก็บ snapshot ย้อนหลังกี่ชุด
_EXCLUDE_TOP = {"backups", "documents"}     # ไม่สำรอง: โฟลเดอร์สำรองเอง + เอกสาร generate ใหม่ได้
_LATEST_KEY = "ddoc-backups/latest.zip"

_last_fp = None          # fingerprint ที่ซิงก์ขึ้นคลาวด์ล่าสุด (ในหน่วยความจำ)
_last_snap_date = None   # วันที่ทำ snapshot ลงวันที่ล่าสุด (กันอัป snapshot ซ้ำหลายครั้ง/วัน)


def _backups_dir() -> Path:
    d = get_data_dir() / "backups"
    d.mkdir(exist_ok=True)
    return d


def _included_files(data: Path):
    """ไฟล์ที่ต้องสำรอง: ทุกอย่างใน data/ ยกเว้น backups/, documents/ และไฟล์ชั่วคราว"""
    for p in data.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(data)
        if rel.parts and rel.parts[0] in _EXCLUDE_TOP:
            continue
        if str(rel) == "school.db":          # ไฟล์ DB เดิมก่อน multi-tenant (ย้ายไป schools/ แล้ว) ไม่ต้องสำรอง
            continue
        if p.suffix == ".shm" or p.name == "_restore.zip":
            continue
        yield p, rel


def _fingerprint(data: Path) -> str:
    """ลายนิ้วมือของข้อมูล (ชื่อ+ขนาด+เวลาแก้ไข ของไฟล์ที่สำรอง) ใช้ตรวจว่าเปลี่ยนไหม"""
    h = hashlib.sha256()
    for p, rel in sorted(_included_files(data), key=lambda x: str(x[1])):
        try:
            st = p.stat()
            h.update(f"{rel}|{st.st_size}|{int(st.st_mtime)}".encode())
        except OSError:
            pass
    return h.hexdigest()


def _make_zip() -> Path:
    """สร้าง zip ของข้อมูลที่สำรอง (flush WAL ก่อน) คืนที่อยู่ไฟล์"""
    data = get_data_dir()
    try:
        from app.tenancy import checkpoint_all
        checkpoint_all()
    except Exception:
        pass
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = _backups_dir() / f"ddoc-backup-{ts}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in _included_files(data):
            z.write(p, rel)
            n += 1
    print(f"[backup {ts}] {n} ไฟล์ -> {out.name} ({out.stat().st_size // 1024} KB)")
    return out


def _s3():
    bucket = os.environ.get("BACKUP_S3_BUCKET")
    if not bucket:
        return None, None, "ไม่ได้ตั้งค่า S3 (สำรองเฉพาะในเครื่อง)"
    try:
        import boto3  # type: ignore
    except ImportError:
        return None, None, "ยังไม่ได้ติดตั้ง boto3 (pip install boto3)"
    client = boto3.client(
        "s3",
        endpoint_url=os.environ.get("BACKUP_S3_ENDPOINT"),
        aws_access_key_id=os.environ.get("BACKUP_S3_KEY_ID"),
        aws_secret_access_key=os.environ.get("BACKUP_S3_SECRET"),
        region_name=os.environ.get("BACKUP_S3_REGION", "auto"),
    )
    return client, bucket, None


def _prune_cloud(client, bucket):
    """ตัด snapshot เก่าบนคลาวด์ให้เหลือ KEEP ล่าสุด (best-effort)"""
    try:
        objs = client.list_objects_v2(Bucket=bucket, Prefix="ddoc-backups/ddoc-backup-").get("Contents", [])
        for old in sorted((o["Key"] for o in objs), reverse=True)[KEEP:]:
            client.delete_object(Bucket=bucket, Key=old)
            print("    ลบ snapshot เก่าบนคลาวด์:", old)
    except Exception as e:
        print("    (ข้าม) ตัด snapshot เก่าไม่สำเร็จ:", e)


def _upload(client, bucket, zip_path: Path, *, snapshot: bool):
    """อัป latest.zip เสมอ + (ถ้า snapshot) อัปไฟล์ลงวันที่ด้วย"""
    client.upload_file(str(zip_path), bucket, _LATEST_KEY)
    msg = "อัป latest.zip"
    if snapshot:
        client.upload_file(str(zip_path), bucket, f"ddoc-backups/{zip_path.name}")
        _prune_cloud(client, bucket)
        msg += f" + snapshot {zip_path.name}"
    print(f"    อัปขึ้นคลาวด์: {msg}")


def mark_synced():
    """ตั้งค่า baseline = ข้อมูลปัจจุบัน (เรียกหลังกู้คืน เพื่อไม่ให้อัปซ้ำทันที)"""
    global _last_fp
    _last_fp = _fingerprint(get_data_dir())


def run_backup(force: bool = False) -> Path | None:
    """สำรอง 1 รอบ — อัปขึ้นคลาวด์เฉพาะเมื่อข้อมูลเปลี่ยน (หรือ force=True)"""
    global _last_fp, _last_snap_date
    data = get_data_dir()
    if not data.exists():
        return None
    fp = _fingerprint(data)
    if not force and fp == _last_fp:
        return None     # ไม่มีการเปลี่ยนแปลง -> ไม่ต้องทำอะไร (ประหยัด bandwidth)

    zip_path = _make_zip()
    client, bucket, reason = _s3()
    if client:
        today = datetime.now().strftime("%Y%m%d")
        try:
            _upload(client, bucket, zip_path, snapshot=(_last_snap_date != today))
            if _last_snap_date != today:
                _last_snap_date = today
        except Exception as e:
            print("    (ผิดพลาด) อัปขึ้นคลาวด์ไม่สำเร็จ:", e)
    else:
        print("   ", reason)

    # ตัดสำรองในเครื่องให้เหลือไม่กี่ชุด (ดิสก์ฟรีพื้นที่จำกัด)
    for old in sorted(_backups_dir().glob("ddoc-backup-*.zip"), reverse=True)[3:]:
        old.unlink(missing_ok=True)
    _last_fp = _fingerprint(data)   # baseline ใหม่ (หลัง checkpoint แล้ว)
    return zip_path


def manual_backup() -> str:
    """สำรองทันที (บังคับอัป) + รายงานผลแบบอ่านได้ — ใช้กับปุ่มทดสอบในคอนโซล"""
    client, bucket, reason = _s3()
    try:
        zip_path = _make_zip()
    except Exception as e:
        return f"สร้างไฟล์สำรองไม่สำเร็จ: {e}"
    if not client:
        return f"สำรองในเครื่องแล้ว ({zip_path.name}) แต่ {reason}"
    try:
        _upload(client, bucket, zip_path, snapshot=True)
        mark_synced()
        return f"สำเร็จ! อัปขึ้นคลาวด์แล้ว: {zip_path.name} ({zip_path.stat().st_size // 1024} KB)"
    except Exception as e:
        return f"สำรองในเครื่องได้ แต่อัปขึ้น R2 ไม่สำเร็จ: {e}"


def restore_latest_from_s3() -> bool:
    """ดึงไฟล์สำรองล่าสุดจาก S3/R2 มากู้คืนลง data/ (ตอนเปิดเครื่องใหม่บนฟรีทีเออร์)"""
    client, bucket, reason = _s3()
    if not client:
        print("    [restore]", reason)
        return False
    data_dir = get_data_dir()
    tmp = data_dir / "_restore.zip"
    src = None
    try:
        client.download_file(bucket, _LATEST_KEY, str(tmp))
        src = _LATEST_KEY
    except Exception as e1:
        try:
            objs = client.list_objects_v2(Bucket=bucket, Prefix="ddoc-backups/").get("Contents", [])
            keys = sorted((o["Key"] for o in objs if o["Key"].endswith(".zip")), reverse=True)
            if not keys:
                print("    [restore] ยังไม่มีไฟล์สำรองบนคลาวด์ (เริ่มใหม่)")
                return False
            client.download_file(bucket, keys[0], str(tmp))
            src = keys[0]
        except Exception as e2:
            print(f"    [restore] ดึงไฟล์สำรองไม่สำเร็จ (latest: {e1}) (list: {e2})")
            return False
    try:
        with zipfile.ZipFile(tmp, "r") as z:
            for member in z.namelist():
                dest = (data_dir / member).resolve()
                if str(dest).startswith(str(data_dir.resolve())):
                    z.extract(member, data_dir)
        print(f"    [restore] กู้คืนข้อมูลจากคลาวด์: {src}")
        return True
    except Exception as e:
        print("    [restore] แตกไฟล์สำรองไม่สำเร็จ:", e)
        return False
    finally:
        tmp.unlink(missing_ok=True)
