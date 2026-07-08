# -*- coding: utf-8 -*-
"""
book_receipt_doc.py — บัญชีรายชื่อนักเรียนรับหนังสือเรียน (ลงชื่อรับ) แยกตามชั้น -> ไฟล์ Word
คอลัมน์ = ชื่อหนังสือ (หัวตารางแนวตั้ง) · แถว = นักเรียน · ท้ายตารางมีช่องลงชื่อครูประจำชั้น
ดึงนักเรียนจากทะเบียนกลาง (Student) และหนังสือจากทะเบียนหนังสือเรียน (TextBook)
"""
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from app.database import get_data_dir
from app.services.build_templates import (
    _font, _p, _set_cell, _repeat_header_row, _no_split_row,
)

THAI_FONT = "TH Sarabun New"


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*\n\r\t':
        text = text.replace(ch, "_")
    return text.strip()[:80]


def _landscape(doc):
    s = doc.sections[0]
    s.orientation = WD_ORIENT.LANDSCAPE
    s.page_width, s.page_height = Cm(29.7), Cm(21.0)
    s.left_margin = s.right_margin = Cm(1.2)
    s.top_margin = s.bottom_margin = Cm(1.2)


def _vertical(cell):
    """ตั้งข้อความในเซลล์เป็นแนวตั้ง (ล่างขึ้นบน) สำหรับหัวคอลัมน์ชื่อหนังสือ"""
    tcPr = cell._tc.get_or_add_tcPr()
    td = OxmlElement("w:textDirection")
    td.set(qn("w:val"), "btLr")
    tcPr.append(td)
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER


def _set_cell_v(cell, text):
    _set_cell(cell, text, bold=True, align="center", size=13)
    _vertical(cell)


def render_book_receipt(year, groups, school) -> str:
    """groups = [(level, [books], [students]), ...] เรียงตามชั้น"""
    doc = Document()
    _font(doc)
    _landscape(doc)
    sname = (school.name or "โรงเรียน").strip()
    addr = " ".join(x for x in [(school.address or "").strip(),
                                ("อ." + school.district) if getattr(school, "district", "") else "",
                                ("จ." + school.province) if getattr(school, "province", "") else ""] if x)

    first = True
    for level, books, students in groups:
        if not first:
            doc.add_page_break()
        first = False
        _p(doc, f"บัญชีรายชื่อนักเรียนรับหนังสือเรียน ปีการศึกษา {year}", align="center", bold=True, size=17, after=0)
        _p(doc, f"{sname}" + (f"  {addr}" if addr else ""), align="center", size=14, after=0)
        _p(doc, f"ชั้น{level or '.................'}", align="center", bold=True, size=15, after=4)

        n_books = len(books)
        # คอลัมน์: ลำดับ + ชื่อ-สกุล + หนังสือ(n) + ลงชื่อ
        ncols = 2 + n_books + 1
        # กว้างคอลัมน์หนังสือ: ปรับตามจำนวนหนังสือให้พอดีหน้ากระดาษแนวนอน (พื้นที่หนังสือ ~ 16 ซม.)
        book_w = Cm(1.1) if n_books <= 12 else Cm(max(0.8, 16.0 / n_books))
        t = doc.add_table(rows=1, cols=ncols)
        t.style = "Table Grid"
        t.autofit = False
        t.alignment = WD_TABLE_ALIGNMENT.CENTER   # จัดตารางกึ่งกลางหน้า
        hdr = t.rows[0]
        _repeat_header_row(hdr)
        _no_split_row(hdr)
        # แถวหัวสูงพอสำหรับข้อความชื่อหนังสือแนวตั้ง (กันตัวอักษรถูกบีบ)
        hdr.height = Cm(4.0)
        hdr.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        _set_cell(hdr.cells[0], "ที่", bold=True, align="center", size=13); hdr.cells[0].width = Cm(1.0)
        _set_cell(hdr.cells[1], "ชื่อ - สกุล", bold=True, align="center", size=13); hdr.cells[1].width = Cm(6.0)
        for i, b in enumerate(books):
            _set_cell_v(hdr.cells[2 + i], b.title or "-")
            hdr.cells[2 + i].width = book_w
        _set_cell(hdr.cells[-1], "ลงชื่อผู้รับ", bold=True, align="center", size=13); hdr.cells[-1].width = Cm(3.2)

        rows_students = students if students else []
        # อย่างน้อย 10 แถวว่างถ้าไม่มีนักเรียน (ไว้เขียนมือ)
        count = max(len(rows_students), 12)
        for idx in range(count):
            r = t.add_row(); _no_split_row(r)
            r.cells[0].width = Cm(1.0); r.cells[1].width = Cm(6.0)
            if idx < len(rows_students):
                _set_cell(r.cells[0], str(idx + 1), align="center", size=13)
                _set_cell(r.cells[1], rows_students[idx].name, align="left", size=13)
            else:
                _set_cell(r.cells[0], "", align="center", size=13)
                _set_cell(r.cells[1], "", align="left", size=13)
            for i in range(n_books):
                _set_cell(r.cells[2 + i], "", align="center", size=13)
                r.cells[2 + i].width = book_w
            _set_cell(r.cells[-1], "", align="center", size=13); r.cells[-1].width = Cm(3.2)

        _p(doc, "", after=6)
        _p(doc, "ลงชื่อ ....................................................... ครูประจำชั้น",
           align="right", size=14, after=0)
        _p(doc, "(.......................................................)", align="right", size=14, after=0)
        _p(doc, "ตำแหน่ง .......................................................", align="right", size=14, after=0)

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / (_safe(f"บัญชีรับหนังสือเรียน_ปีการศึกษา{year}") + ".docx")
    doc.save(str(path))
    return str(path)
