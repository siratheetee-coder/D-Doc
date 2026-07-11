# -*- coding: utf-8 -*-
"""
signature.py — จัดการลายเซ็นบุคลากร
- process_signature(): รับรูปที่อัปโหลด -> ลบพื้นหลังขาวให้โปร่งใส + ตัดขอบ -> เซฟเป็น PNG
- signature_path_for(): หา path ลายเซ็นจากชื่อผู้ลงนาม (ตรงกับบุคลากรที่มีลายเซ็น)

เก็บไฟล์ที่ data/signatures/<uuid>.png (ชื่อสุ่ม กันเดา) โดยชื่อไฟล์ถูกอ้างอิงใน Person.signature
ของ DB แต่ละโรงเรียน (แยกกันตามผู้ลงนามของโรงเรียนนั้น ๆ)
"""
import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps

from app.database import get_data_dir

# เกณฑ์ความสว่างสำหรับตัดพื้นหลังขาว (ยิ่งพิกเซลสว่างยิ่งโปร่งใส)
_CLEAR = 240   # สว่าง >= ค่านี้ = พื้นหลัง -> โปร่งใสเต็ม
_KEEP = 205    # เข้ม <= ค่านี้ = เส้นลายเซ็น -> ทึบเต็ม (ระหว่างสองค่าไล่ระดับให้ขอบเนียน)
_MAX_W = 900   # ย่อความกว้างสูงสุด (กันไฟล์ใหญ่)


def signatures_dir() -> Path:
    d = get_data_dir() / "signatures"
    d.mkdir(exist_ok=True)
    return d


def process_signature(data: bytes, remove_white: bool = True) -> str | None:
    """แปลงรูปลายเซ็นที่อัปโหลด -> PNG โปร่งใส (ตัดพื้นหลังขาว + ตัดขอบ) คืนชื่อไฟล์ หรือ None ถ้าไม่ใช่รูป

    remove_white=False: เก็บภาพตามเดิม (เผื่อผู้ใช้อัป PNG โปร่งใสมาเอง) แค่แปลงเป็น RGBA + ตัดขอบ
    """
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGBA")
    except Exception:
        return None

    if remove_white:
        lum = img.convert("L")

        def _alpha(l):
            if l >= _CLEAR:
                return 0
            if l <= _KEEP:
                return 255
            return int((_CLEAR - l) / (_CLEAR - _KEEP) * 255)

        alpha = lum.point(_alpha)
        # ผสมกับ alpha เดิม (เผื่อภาพมีส่วนโปร่งใสอยู่แล้ว) — เลือกค่าที่โปร่งใสกว่า (min)
        img.putalpha(_min_channels(alpha, img.getchannel("A")))

    # ตัดขอบว่างรอบ ๆ (อิงพื้นที่ที่ไม่โปร่งใส)
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)

    # ย่อถ้ากว้างเกิน
    if img.width > _MAX_W:
        h = round(img.height * _MAX_W / img.width)
        img = img.resize((_MAX_W, h), Image.LANCZOS)

    name = uuid.uuid4().hex + ".png"
    img.save(signatures_dir() / name, "PNG")
    return name


def _min_channels(a, b):
    """คืนภาพ L ที่แต่ละพิกเซล = ค่าน้อยกว่าของ a,b (ใช้รวม alpha)"""
    from PIL import ImageChops
    return ImageChops.darker(a, b)


def signature_full_path(filename: str) -> Path | None:
    """คืน path เต็มของไฟล์ลายเซ็น หรือ None ถ้าไม่มี/ชื่อไม่ปลอดภัย"""
    fn = (filename or "").strip()
    if not fn or "/" in fn or "\\" in fn or ".." in fn:
        return None
    p = signatures_dir() / fn
    return p if p.exists() else None


def delete_signature(filename: str) -> None:
    p = signature_full_path(filename)
    if p:
        try:
            p.unlink()
        except OSError:
            pass


def _norm(s: str) -> str:
    return " ".join((s or "").split())


def signature_path_for(db, signer_name: str) -> str | None:
    """หา path ลายเซ็นจากชื่อผู้ลงนาม — จับคู่กับบุคลากรที่มีลายเซ็น คืน path (str) หรือ None"""
    from app.models import Person
    target = _norm(signer_name)
    if not target:
        return None
    for p in db.query(Person).filter(Person.signature != "").all():
        if _norm(p.name) == target:
            full = signature_full_path(p.signature)
            return str(full) if full else None
    return None


def signature_path_for_current(signer_name: str) -> str | None:
    """เหมือน signature_path_for แต่เปิดเซสชันของโรงเรียนที่ล็อกอินอยู่เอง
    (ใช้ตอนสร้างเอกสาร ซึ่งไม่มี db handle ส่งเข้ามา)"""
    from app.tenancy import current_school_id, session_for
    sid = current_school_id.get()
    if not sid:
        return None
    db = session_for(sid)
    try:
        return signature_path_for(db, signer_name)
    finally:
        db.close()
