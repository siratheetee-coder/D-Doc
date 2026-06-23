# -*- coding: utf-8 -*-
"""
file_upload.py
--------------
ฟังก์ชันกลางสำหรับรับไฟล์แนบ (PDF/Word) — ใช้ร่วมทั้งงานธุรการและพัสดุ
เซฟลง data/uploads/<uuid>.<ext> + ดึงจาก URL + ตรวจชนิดไฟล์
"""
import re
import uuid
import urllib.request
from urllib.parse import urlparse
from pathlib import Path

from app.database import get_data_dir

# ชื่อไฟล์ปลอดภัย (กัน path traversal) — uuid 32 ตัว + นามสกุลที่อนุญาต
SAFE_FILE_NAME = re.compile(r"^[0-9a-fA-F]{32}\.(pdf|docx|png|jpg|webp)$")


def uploads_dir() -> Path:
    d = get_data_dir() / "uploads"
    d.mkdir(exist_ok=True)
    return d


def detect_ext(data: bytes, filename: str = "") -> str:
    """เดานามสกุลจากเนื้อไฟล์/ชื่อไฟล์: 'pdf'/'docx'/'png'/'jpg'/'webp' / '' (ไม่รองรับ)"""
    if data[:5].startswith(b"%PDF"):
        return "pdf"
    if data[:2] == b"PK" and filename.lower().endswith(".docx"):
        return "docx"
    if data[:3] == b"\xff\xd8\xff":                       # JPEG
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":                  # PNG
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":     # WEBP
        return "webp"
    fn = filename.lower()
    if fn.endswith(".pdf"):
        return "pdf"
    if fn.endswith((".jpg", ".jpeg")):
        return "jpg"
    if fn.endswith(".png"):
        return "png"
    if fn.endswith(".webp"):
        return "webp"
    return ""


def save_upload(data: bytes, ext: str) -> str:
    """เซฟไฟล์ลงโฟลเดอร์ uploads ด้วยชื่อสุ่ม คืนชื่อไฟล์ (uuid.pdf / uuid.docx)"""
    name = uuid.uuid4().hex + "." + ext
    (uploads_dir() / name).write_bytes(data)
    return name


def fetch_file(url: str):
    """ดึงไฟล์ PDF/DOCX จาก URL (ฝั่งเซิร์ฟเวอร์) คืน (bytes, ext, None) หรือ (None, None, 'error')"""
    url = (url or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return None, None, "url"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read(25 * 1024 * 1024)   # จำกัด ~25MB
    except Exception:
        return None, None, "fetch"
    ext = detect_ext(data, p.path)
    if not ext:
        return None, None, "notpdf"   # ไม่ใช่ PDF/Word (อาจเป็นหน้า login/HTML)
    return data, ext, None
