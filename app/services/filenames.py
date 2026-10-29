# -*- coding: utf-8 -*-
"""ชื่อไฟล์ที่สร้างจากข้อความผู้ใช้ (ชื่อโครงการ ชื่อเรื่อง ฯลฯ)

Linux จำกัดชื่อไฟล์ 255 ไบต์ อักษรไทย 1 ตัว = 3 ไบต์ (UTF-8) ชื่อโครงการยาว ๆ จึงเกินได้
(OSError: File name too long -> error 500) ตัดให้สั้นตามจำนวนไบต์ โดยคงนามสกุลไฟล์ไว้
"""
import re

MAX_BYTES = 180   # เผื่อที่ให้นามสกุลและเลขต่อท้ายกันชื่อซ้ำ
_EXT = re.compile(r"\.(docx|xlsx|pdf|zip|csv|txt)$", re.I)


def fit_name(name: str, limit: int = MAX_BYTES) -> str:
    """ตัดชื่อไฟล์ให้ไม่เกิน limit ไบต์ ไม่ตัดกลางตัวอักษร คงนามสกุลไว้"""
    m = _EXT.search(name)
    ext = m.group(0) if m else ""
    stem = name[: len(name) - len(ext)] if ext else name
    room = limit - len(ext.encode("utf-8"))
    raw = stem.encode("utf-8")
    if len(raw) <= room:
        return name
    stem = raw[:room].decode("utf-8", errors="ignore").rstrip(" _-.")
    return stem + ext
