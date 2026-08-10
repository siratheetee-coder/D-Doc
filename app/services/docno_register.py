# -*- coding: utf-8 -*-
"""
docno_register.py - ออกไฟล์ "ทะเบียนหนังสือราชการ" (บันทึกข้อความ/คำสั่ง/หนังสือส่ง ฯลฯ)
เป็นเอกสาร Word แนวนอน (A4 landscape) แยกตารางตามประเภทเอกสาร
"""
from pathlib import Path

from docx import Document
from docx.shared import Cm

from app.services.doc_page import set_a4
from app.services.build_templates import _font, _p, _set_cell
from app.thai_utils import thai_date
from app.database import get_data_dir


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def render_docno_register(groups: dict, type_labels: dict, fiscal_year: int, school) -> str:
    """groups = {doc_type: [IssuedDocNo,...]} เรียงแล้ว · คืน path ไฟล์ .docx (แนวนอน)"""
    sname = (getattr(school, "name", "") or "").strip() or "โรงเรียน"
    doc = Document()
    _font(doc)                       # _font ตั้งขนาดเป็นแนวตั้ง ต้องเรียกก่อน
    set_a4(doc, landscape=True)      # แล้วค่อยสลับเป็นแนวนอน (ไม่งั้นถูก _font ทับ)
    _p(doc, f"ทะเบียนหนังสือราชการ  โรงเรียน{sname}", align="center", bold=True, size=18, after=0)
    _p(doc, f"ประจำปีงบประมาณ {fiscal_year}", align="center", after=8)

    widths = [Cm(3.6), Cm(4.2), Cm(14.9), Cm(4.5)]   # รวม ~27.2 = พื้นที่พิมพ์ A4 แนวนอน
    header = ["เลขที่", "ลงวันที่", "เรื่อง", "งาน"]
    src_label = {"procurement": "พัสดุ", "admin": "ธุรการ", "finance": "การเงิน"}

    if not groups:
        _p(doc, "ยังไม่มีเลขที่ถูกใช้ในปีงบประมาณนี้", align="center", after=0)

    for dt, rows in groups.items():
        _p(doc, type_labels.get(dt, dt) + f"  ({len(rows)} เลข)", bold=True, size=16, before=8, after=2)
        t = doc.add_table(rows=1, cols=4)
        t.style = "Table Grid"
        for c, v, w in zip(t.rows[0].cells, header, widths):
            _set_cell(c, v, size=15, align="center"); c.width = w
        for r in rows:
            cells = t.add_row().cells
            vals = [r.full_no or "", thai_date(r.date) if r.date else "",
                    r.subject or "", src_label.get(r.source, r.source or "-")]
            aligns = ["center", "center", "left", "center"]
            for c, v, w, a in zip(cells, vals, widths, aligns):
                _set_cell(c, v, size=14, align=a); c.width = w

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / _safe(f"ทะเบียนหนังสือราชการ_ปีงบ{fiscal_year}.docx")
    doc.save(str(out_path))
    return str(out_path)
