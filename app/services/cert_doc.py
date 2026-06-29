# -*- coding: utf-8 -*-
"""
cert_doc.py
-----------
ออกเกียรติบัตรจากรูปพื้นหลังที่ผู้ใช้อัปโหลด + พิมพ์ชื่อ (และข้อความเสริม) ทับตามตำแหน่งที่เลือก
ทำทีละชื่อ -> รวมเป็น PDF หลายหน้า (1 คน/หน้า) ด้วย Pillow

ฟอนต์ไทย: ใช้ Prompt (.ttf) ที่ฝังในรีโป (app/static/fonts) ใช้ได้ทั้ง Windows/Linux
"""
from pathlib import Path

from app.database import get_data_dir
from app.services.file_upload import uploads_dir

_FONT_DIR = Path(__file__).resolve().parent.parent / "static" / "fonts"


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*\n\r\t':
        text = text.replace(ch, "_")
    return text.strip()[:60]


def _font(px: int, bold: bool = True):
    from PIL import ImageFont
    name = "Prompt-SemiBold.ttf" if bold else "Prompt-Regular.ttf"
    return ImageFont.truetype(str(_FONT_DIR / name), max(8, int(px)))


def render_certificates(batch, names: list, school) -> str:
    """วาดชื่อทับรูปพื้นหลังทีละคน -> คืน path ไฟล์ PDF หลายหน้า"""
    from PIL import Image, ImageDraw, ImageOps
    bg_path = uploads_dir() / (batch.bg_image or "")
    if not bg_path.exists():
        raise FileNotFoundError("ไม่พบรูปพื้นหลังเกียรติบัตร")
    base = ImageOps.exif_transpose(Image.open(bg_path)).convert("RGB")
    W, H = base.size

    name_px = max(10, int(W * float(batch.name_size or 48) / 1000))   # ขนาดชื่อ ~ %width
    sub_px = max(8, int(name_px * 0.5))
    color = batch.name_color or "#1a1a1a"
    nx = W * float(batch.name_x or 50) / 100.0
    ny = H * float(batch.name_y or 45) / 100.0
    name_font = _font(name_px, bold=True)
    sub_font = _font(sub_px, bold=False)
    sub_text = (batch.sub_text or "").strip()

    pages = []
    for nm in names:
        nm = (nm or "").strip()
        if not nm:
            continue
        img = base.copy()
        d = ImageDraw.Draw(img)
        d.text((nx, ny), nm, font=name_font, fill=color, anchor="mm")
        if sub_text:
            d.text((nx, ny + name_px * 0.95), sub_text, font=sub_font, fill=color, anchor="mm")
        pages.append(img)

    if not pages:
        raise ValueError("ไม่มีรายชื่อสำหรับออกเกียรติบัตร")

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / (_safe(f"เกียรติบัตร_{batch.title or batch.id}") + ".pdf")
    pages[0].save(str(out_path), "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return str(out_path)
