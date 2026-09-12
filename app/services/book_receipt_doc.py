# -*- coding: utf-8 -*-
"""
book_receipt_doc.py - แบบรับหนังสือเรียน (ลงชื่อรับรายคน) แยกตามห้อง -> ไฟล์ Word

รูปแบบตามแบบฟอร์มที่โรงเรียนใช้จริง (แนวตั้ง 1 ห้อง = 1 หน้า):
    หัวเรื่อง -> รายวิชา/รหัสวิชา/ครูผู้สอน -> ชื่อหนังสือ -> ครูที่ปรึกษา
    ตาราง: เลขที่ | เลขประจำตัว | ชื่อ - นามสกุล | ลายมือชื่อ | วันที่รับ | หมายเหตุ
    ท้ายหน้า: ลงชื่อครูประจำวิชา
ช่องรายวิชา/ชื่อหนังสือเว้นจุดไข่ปลาไว้ให้ครูเขียนเอง (1 แผ่นใช้กับหนังสือ 1 เล่ม)
"""
from docx import Document
from docx.shared import Cm
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_TABLE_ALIGNMENT

from app.services.doc_page import set_a4

from app.database import get_data_dir
from app.services.build_templates import (
    _font, _p, _set_cell, _repeat_header_row, _no_split_row, _fixed_cols,
)

# พื้นที่พิมพ์แนวตั้ง 16.5 ซม. (A4 ขอบซ้าย 3.0 ขวา 1.5)
_COLS = ["เลขที่", "เลขประจำตัว", "ชื่อ - นามสกุล", "ลายมือชื่อ", "วันที่รับ", "หมายเหตุ"]
_W = [Cm(1.2), Cm(2.2), Cm(5.3), Cm(3.2), Cm(2.4), Cm(2.2)]
_MIN_ROWS = 20          # อย่างน้อย 20 บรรทัด ถ้านักเรียนน้อยกว่านี้ (ไว้เขียนเพิ่ม)
_DOT = "." * 60


def _safe(text: str) -> str:
    bad = '<>:"/|?*' + chr(92) + chr(10) + chr(13) + chr(9)
    for ch in bad:
        text = text.replace(ch, "_")
    return text.strip()[:80]


def _class_name(level: str, room: str) -> str:
    lv = (level or "").strip()
    rm = (room or "").strip()
    if not lv:
        return "................."
    return f"{lv}/{rm}" if rm else lv


def is_kindergarten(level: str) -> bool:
    """ก่อนประถมศึกษา (อนุบาล) -> ให้ครูประจำชั้นลงลายมือชื่อรับแทนนักเรียน"""
    lv = (level or "").strip()
    return lv.startswith("อ.") or lv.startswith("อนุบาล")


def add_book_list_page(doc, year, level, room, books):
    """ใบรายการหนังสือเรียนของห้องนั้น (แยกออกมาจากแบบรับ เพราะ 1 ห้องมีหลายเล่ม)
    books = [{"name":..., "qty":..., "unit":..., "price":...}, ...]"""
    _p(doc, f"รายการหนังสือเรียน ชั้น{_class_name(level, room)} ปีการศึกษา {year}",
       align="center", bold=True, size=17, after=6)
    headers = ["ที่", "รายการหนังสือ", "จำนวน", "หน่วย", "ราคา/หน่วย", "รวมเงิน"]
    widths = [Cm(1.1), Cm(7.4), Cm(1.9), Cm(1.8), Cm(2.1), Cm(2.2)]
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    total = 0.0
    for i, b in enumerate(books or [], start=1):
        qty = float(b.get("qty") or 0)
        price = float(b.get("price") or 0)
        amount = qty * price
        total += amount
        vals = [str(i), b.get("name") or "", f"{qty:g}", b.get("unit") or "เล่ม",
                f"{price:,.2f}" if price else "-", f"{amount:,.2f}" if price else "-"]
        r = t.add_row(); _no_split_row(r)
        for c, v, w, al in zip(r.cells, vals, widths,
                               ["center", "left", "center", "center", "right", "right"]):
            _set_cell(c, v, align=al, size=14)
            c.width = w
    if not books:
        r = t.add_row(); _no_split_row(r)
        _set_cell(r.cells[1], "- ไม่มีรายการ -", align="center", size=14)
    _p(doc, f"รวม {len(books or [])} รายการ" + (f"  เป็นเงิน {total:,.2f} บาท" if total else ""),
       align="center", bold=True, before=4, after=0)
    return doc


def add_receipt_page(doc, year, level, room, advisor, students, *, books=None,
                     title_prefix="แบบรับหนังสือเรียน"):
    """เขียน 1 แผ่นใบรับหนังสือเรียนลงในเอกสารที่ส่งมา (ไม่ขึ้นหน้าใหม่ให้ - ผู้เรียกจัดการเอง)
    books = จำนวนรายการหนังสือ (int) หรือ list -> แสดงแค่จำนวน รายละเอียดอยู่ในใบรายการหนังสือ
    อนุบาล: ไม่มีช่องลายมือชื่อรายคน แต่ครูประจำชั้นเซ็นรับแทนทั้งห้อง"""
    kg = is_kindergarten(level)
    _p(doc, f"{title_prefix} ชั้น{_class_name(level, room)} ปีการศึกษา {year}",
       align="center", bold=True, size=17, after=4)
    n_books = books if isinstance(books, int) else (len(books) if books else 0)
    if n_books:
        _p(doc, f"หนังสือเรียนทั้งหมด {n_books} รายการ (รายละเอียดตามใบรายการหนังสือที่แนบ)",
           align="center", size=14, after=2)
    else:
        _p(doc, "รายวิชา............................................รหัสวิชา................................"
                "ครูผู้สอน............................................", align="center", size=14, after=2)
        _p(doc, "ชื่อหนังสือ...................................................................................."
                "....................................", align="center", size=14, after=2)
    _p(doc, f"ครูที่ปรึกษา  {advisor if advisor else _DOT}", align="center", size=14, after=6)

    cols = [c for c in _COLS if not (kg and c == "ลายมือชื่อ")]
    widths = list(_W) if not kg else [Cm(1.2), Cm(2.4), Cm(6.9), Cm(3.0), Cm(3.0)]
    t = doc.add_table(rows=1, cols=len(cols))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0]
    _repeat_header_row(hdr); _no_split_row(hdr)
    for c, h, w in zip(hdr.cells, cols, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w

    rows = list(students or [])
    n_rows = len(rows) if kg and rows else max(len(rows), _MIN_ROWS)
    for idx in range(n_rows):
        r = t.add_row(); _no_split_row(r)
        r.height = Cm(0.75); r.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        st = rows[idx] if idx < len(rows) else None
        base = [str(idx + 1) if st else "",
                (st.student_no or "") if st else "",
                (st.name or "") if st else ""]
        vals = base + (["", ""] if kg else ["", "", ""])
        aligns = ["center", "center", "left"] + (["center"] * (len(cols) - 3))
        for c, v, w, al in zip(r.cells, vals, widths, aligns):
            _set_cell(c, v, align=al, size=14)
            c.width = w

    _p(doc, "", after=6)
    if kg:
        _p(doc, f"ข้าพเจ้า........................................................... "
                f"ครูประจำชั้น{_class_name(level, room)} ได้รับหนังสือเรียนตามรายการข้างต้น "
                f"แทนนักเรียนจำนวน {len(rows) if rows else '.......'} คน "
                "เนื่องจากนักเรียนอยู่ในระดับก่อนประถมศึกษา", align="justify", indent=1.25, after=10)
        _p(doc, "ลงชื่อ........................................................ครูประจำชั้นผู้รับแทน",
           align="right", size=14, after=0)
    else:
        _p(doc, "ลงชื่อ........................................................ครูที่ปรึกษา",
           align="right", size=14, after=0)
    _p(doc, "(...............................................................)",
       align="right", size=14, after=0)
    return doc


def render_book_receipt(year, groups, school) -> str:
    """groups = [(level, room, advisor, [students], [books]), ...] เรียงตามชั้น/ห้อง
    books = [{"name","qty","unit","price"}] (ไม่มีก็ได้ -> เว้นช่องชื่อหนังสือให้เขียนเอง)
    รองรับรูปแบบเดิม 4 ค่า และ 3 ค่า (level, books, students) ด้วย"""
    doc = Document(); set_a4(doc)          # แนวตั้ง ตามแบบฟอร์มจริง
    _font(doc)
    first = True
    for g in groups:
        if len(g) == 5:
            level, room, advisor, students, books = g
        elif len(g) == 4:
            level, room, advisor, students = g
            books = []
        else:                               # รูปแบบเดิม (level, books, students)
            level, _books, students = g
            room, advisor, books = "", "", []
        if not first:
            doc.add_page_break()
        first = False
        if books:                           # มีรายการหนังสือของห้องนี้ -> แยกใบให้
            add_book_list_page(doc, year, level, room, books)
            doc.add_page_break()
        add_receipt_page(doc, year, level, room, advisor, students, books=len(books))

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / (_safe(f"แบบรับหนังสือเรียน_ปีการศึกษา{year}") + ".docx")
    doc.save(str(path))
    return str(path)
