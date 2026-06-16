# -*- coding: utf-8 -*-
"""
backup.py — สำรองข้อมูลทุกโรงเรียน (zip ทั้งโฟลเดอร์ data/) + อัปขึ้นคลาวด์ (off-site, ทางเลือก)

ใช้ได้ 2 ทาง:
- เรียกจากในแอป (ตัวจับเวลาเบื้องหลัง) — เหมาะกับ Render ที่ผูกดิสก์ได้ service เดียว
- รันจาก cron ผ่าน tools/backup_all.py — เหมาะกับ VPS

ตั้งค่าอัปขึ้นคลาวด์ผ่าน env (S3-compatible: Cloudflare R2 / Backblaze B2 / S3 / Wasabi):
    BACKUP_S3_ENDPOINT, BACKUP_S3_BUCKET, BACKUP_S3_KEY_ID, BACKUP_S3_SECRET, BACKUP_S3_REGION
ถ้าไม่ตั้ง -> สำรองแค่ในเครื่อง (ไม่ error)
"""
import os
import zipfile
from pathlib import Path
from datetime import datetime

from app.database import get_data_dir

KEEP = 14   # เก็บย้อนหลังกี่ชุด (ทั้งในเครื่องและบนคลาวด์)


def _backups_dir() -> Path:
    d = get_data_dir() / "backups"
    d.mkdir(exist_ok=True)
    return d


def _make_zip() -> Path:
    data = get_data_dir()
    backups = _backups_dir()
    # flush WAL ของทุกโรงเรียนลงไฟล์หลักก่อน กันข้อมูลล่าสุดตกหล่น
    try:
        from app.tenancy import checkpoint_all
        checkpoint_all()
    except Exception:
        pass
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = backups / f"ddoc-backup-{ts}.zip"
    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in data.rglob("*"):
            if backups in p.parents or p == backups:          # ข้ามโฟลเดอร์สำรองเอง
                continue
            if p.is_file() and p.suffix != ".shm":             # เก็บ .db + .wal (เผื่อยังไม่ checkpoint) ข้ามแค่ .shm
                z.write(p, p.relative_to(data))
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


def _upload_and_prune(client, bucket, zip_path: Path):
    key = f"ddoc-backups/{zip_path.name}"
    client.upload_file(str(zip_path), bucket, key)
    print(f"    อัปขึ้นคลาวด์: s3://{bucket}/{key}")
    try:
        objs = client.list_objects_v2(Bucket=bucket, Prefix="ddoc-backups/").get("Contents", [])
        for old in sorted((o["Key"] for o in objs), reverse=True)[KEEP:]:
            client.delete_object(Bucket=bucket, Key=old)
            print("    ลบสำรองเก่าบนคลาวด์:", old)
    except Exception as e:
        print("    (เตือน) ตัดสำรองเก่าบนคลาวด์ไม่สำเร็จ:", e)


def manual_backup() -> str:
    """สำรองทันที + รายงานผลแบบอ่านได้ (ใช้กับปุ่มทดสอบในคอนโซล) — เผยข้อผิดพลาด R2 ตรง ๆ"""
    try:
        zip_path = _make_zip()
    except Exception as e:
        return f"สร้างไฟล์สำรองไม่สำเร็จ: {e}"
    client, bucket, reason = _s3()
    if not client:
        return f"สำรองในเครื่องแล้ว ({zip_path.name}) แต่ {reason}"
    try:
        _upload_and_prune(client, bucket, zip_path)
        return f"สำเร็จ! อัปขึ้นคลาวด์แล้ว: {zip_path.name}"
    except Exception as e:
        return f"สำรองในเครื่องได้ แต่อัปขึ้น R2 ไม่สำเร็จ: {e}"


def restore_latest_from_s3() -> bool:
    """ดึงไฟล์สำรองล่าสุดจาก S3/R2 มากู้คืนลง data/ (ใช้ตอนเปิดเครื่องใหม่บนฟรีทีเออร์)
    คืน True ถ้ากู้คืนสำเร็จ"""
    client, bucket, reason = _s3()
    if not client:
        print("    [restore]", reason)
        return False
    try:
        objs = client.list_objects_v2(Bucket=bucket, Prefix="ddoc-backups/").get("Contents", [])
        keys = sorted((o["Key"] for o in objs if o["Key"].endswith(".zip")), reverse=True)
        if not keys:
            print("    [restore] ยังไม่มีไฟล์สำรองบนคลาวด์ (เริ่มใหม่)")
            return False
        latest = keys[0]
        data_dir = get_data_dir()
        tmp = data_dir / "_restore.zip"
        client.download_file(bucket, latest, str(tmp))
        with zipfile.ZipFile(tmp, "r") as z:
            for member in z.namelist():
                # กัน path traversal
                dest = (data_dir / member).resolve()
                if str(dest).startswith(str(data_dir.resolve())):
                    z.extract(member, data_dir)
        tmp.unlink(missing_ok=True)
        print(f"    [restore] กู้คืนข้อมูลจากคลาวด์: {latest}")
        return True
    except Exception as e:
        print("    [restore] กู้คืนไม่สำเร็จ:", e)
        return False


def run_backup() -> Path | None:
    """สำรอง 1 รอบ: zip + (ถ้าตั้งค่า) อัปขึ้นคลาวด์ + ตัดของเก่า คืนที่อยู่ไฟล์ zip"""
    if not get_data_dir().exists():
        return None
    zip_path = _make_zip()
    client, bucket, reason = _s3()
    if client:
        try:
            _upload_and_prune(client, bucket, zip_path)
        except Exception as e:
            print("    (ผิดพลาด) อัปขึ้นคลาวด์ไม่สำเร็จ:", e)
    else:
        print("   ", reason)
    for old in sorted(_backups_dir().glob("ddoc-backup-*.zip"), reverse=True)[KEEP:]:
        old.unlink(missing_ok=True)
        print("ลบสำรองเก่าในเครื่อง:", old.name)
    return zip_path
