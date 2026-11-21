"""อ่าน/เขียนไฟล์ฐานข้อมูลที่แอปเปิดอยู่ ให้ปลอดภัย (ใช้ backup API ของ SQLite เท่านั้น)

ห้าม open()/shutil.copy/zip.write ไฟล์ .db หรือ -wal ที่แอปเปิดอยู่ในโปรเซสแอปเด็ดขาด
เหตุผล (ต้นเหตุ -wal หาย 26 ต.ค. และ 14 พ.ย. 2569): บน Linux ล็อกของ SQLite เป็นแบบ POSIX
(fcntl) ซึ่งผูกกับ "โปรเซส" ไม่ใช่ไฟล์ที่เปิด พอโค้ด Python เปิดแล้วปิดไฟล์ .db เองแม้แค่อ่าน
ล็อกทุกตัวที่ SQLite ถือไว้บนไฟล์นั้นในโปรเซสนี้จะหลุดหมดเงียบ ๆ โปรเซสอื่น (cron, worker อื่น)
ที่ปิดการเชื่อมต่อสุดท้ายจึงเข้าใจว่าไม่มีใครใช้ฐานแล้ว เลย checkpoint แล้วลบไฟล์ -wal ทิ้ง
ขณะที่แอปยังเขียนลงไฟล์ -wal ที่ถูกลบอยู่ = ข้อมูลแตกสองชุด

การเปิดผ่าน sqlite3 ปลอดภัย เพราะ SQLite จำ inode ที่เปิดไว้ในโปรเซสเดียวกันและไม่ปลดล็อกกันเอง
"""
import os
import sqlite3
import tempfile
from pathlib import Path


def snapshot(src, dst) -> None:
    """คัดลอกฐาน src (รวมข้อมูลใน -wal) ไปเป็นไฟล์เดียว dst แบบสอดคล้อง ณ เวลาหนึ่ง"""
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    s = sqlite3.connect(str(src), timeout=30)
    d = sqlite3.connect(str(dst))
    try:
        s.backup(d)
        d.execute("PRAGMA journal_mode=DELETE")     # สำเนาเป็นไฟล์เดียว ไม่มี -wal ติดไป
    finally:
        d.close()
        s.close()


def snapshot_bytes(src) -> bytes:
    """สำเนาฐานเป็น bytes (เช่น ใส่ไฟล์ zip ให้ดาวน์โหลด)"""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        os.unlink(tmp)              # ให้ sqlite สร้างไฟล์ใหม่เอง
        snapshot(src, tmp)
        with open(tmp, "rb") as f:  # ไฟล์ชั่วคราวของเราเอง แอปไม่ได้เปิด อ่านตรงได้
            return f.read()
    finally:
        for p in (tmp, tmp + "-journal"):
            try:
                os.unlink(p)
            except OSError:
                pass


def restore_into(live_path, data: bytes) -> None:
    """เขียนทับฐานที่แอปเปิดอยู่ด้วยข้อมูลใหม่ ผ่าน backup API (ไม่ open() ไฟล์จริง ไม่แตะ -wal)
    worker/โปรเซสอื่นที่เปิดฐานนี้อยู่จะเห็นข้อมูลใหม่ทันทีอย่างถูกต้อง"""
    fd, tmp = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        s = sqlite3.connect(tmp)
        d = sqlite3.connect(str(live_path), timeout=30)
        try:
            s.backup(d)
        finally:
            d.close()
            s.close()
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
