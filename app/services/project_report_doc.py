# -*- coding: utf-8 -*-
"""
project_report_doc.py - รายงานผลการดำเนินงานโครงการ/กิจกรรม (Word พร้อมพิมพ์)

รูปแบบหัวข้อตายตัวตามที่โรงเรียนใช้กันทั่วไป (แนว PDCA + สนองมาตรฐานการศึกษา)
หัวข้อไหนครูไม่ได้กรอก จะไม่ขึ้นในเอกสาร (ไม่เหลือหัวข้อว่างให้ต้องลบเอง)

โครงสร้าง: ปกหน้า -> ส่วนที่ 1 ข้อมูลทั่วไป -> เนื้อหา 8 หัวข้อ -> ลงนาม -> ภาคผนวกภาพกิจกรรม
"""
import io
import os
import tempfile

from docx import Document
from docx.shared import Cm, Pt
from docx.enum.table import WD_ROW_HEIGHT_RULE

from app.services.doc_page import set_a4
from app.services.build_templates import (
    _font, _p, _sign_table, _set_cell, _no_borders, _csize, THAI_FONT,
)
from app.services.lunch_doc import _save, _money
from app.thai_utils import thai_date

# ---- หัวข้อเนื้อหา: (แอตทริบิวต์ในโมเดล, หัวข้อที่พิมพ์) เรียงตามลำดับในเอกสาร ----
BODY_SECTIONS = [
    ("principles",   "หลักการและเหตุผล"),
    ("objectives",   "วัตถุประสงค์"),
    ("target_qty",   "เป้าหมายเชิงปริมาณ"),
    ("target_qual",  "เป้าหมายเชิงคุณภาพ"),
    ("methods",      "วิธีดำเนินการ"),
    ("results",      "ผลการดำเนินงาน"),
    ("satisfaction", "ผลการประเมิน / ความพึงพอใจ"),
    ("problems",     "ปัญหาและอุปสรรค"),
    ("suggestions",  "ข้อเสนอแนะ"),
]


def _txt(v) -> str:
    return (str(v).strip() if v is not None else "")


def _period(rep) -> str:
    """ระยะเวลาดำเนินการเป็นข้อความไทย · วันเดียวไม่ต้องขึ้น 'ถึง'"""
    a, b = rep.date_start, rep.date_end
    if a and b:
        return thai_date(a) if a.date() == b.date() else f"{thai_date(a)} ถึง {thai_date(b)}"
    return thai_date(a or b) if (a or b) else ""


def _para_block(doc, text: str):
    """ข้อความหลายบรรทัด -> ย่อหน้าละบรรทัด (ย่อหน้าแรกเว้นหน้า 1.25 ซม. ตามแบบราชการ)
    บรรทัดที่ขึ้นต้นด้วยลำดับ (1. / - / •) ไม่ต้องเว้นหน้า เพราะเป็นรายการย่อย"""
    for line in _txt(text).splitlines():
        line = line.rstrip()
        if not line:
            continue
        listy = line.lstrip()[:2].rstrip(".)") .isdigit() or line.lstrip()[:1] in "-•*"
        _p(doc, line.lstrip() if listy else line,
           align="justify", indent=(0 if listy else 1.25), after=3)


def _kv_table(doc, rows):
    """ตารางไร้เส้น 2 คอลัมน์ (หัวข้อ : ค่า) สำหรับส่วนข้อมูลทั่วไป"""
    rows = [(k, v) for k, v in rows if _txt(v)]
    if not rows:
        return
    t = doc.add_table(rows=0, cols=2)
    _no_borders(t)
    for k, v in rows:
        c = t.add_row().cells
        c[0].width, c[1].width = Cm(5.0), Cm(11.0)
        _set_cell(c[0], f"{k}", size=16, align="left")
        _set_cell(c[1], f": {v}", size=16, align="left")
    _p(doc, "", size=8, after=0)


def _logo_path(school):
    """คืน path ชั่วคราวของโลโก้โรงเรียน (python-docx รับเฉพาะไฟล์/สตรีม) หรือ None"""
    data = getattr(school, "logo", None)
    if not data:
        return None
    ext = (getattr(school, "logo_ext", "") or "png").lstrip(".")
    fd, path = tempfile.mkstemp(suffix=f".{ext}")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _cover(doc, rep, school, year_label: str):
    """ปกหน้ารายงาน"""
    prj = rep.project
    _p(doc, "", after=0)
    logo = _logo_path(school)
    if logo:
        try:
            p = doc.add_paragraph(); p.alignment = 1          # center
            p.paragraph_format.space_after = Pt(6)
            p.add_run().add_picture(logo, height=Cm(3.0))
        except Exception:
            pass
        finally:
            try:
                os.unlink(logo)
            except OSError:
                pass
    else:
        _p(doc, "", size=28, after=0)

    _p(doc, "รายงานผลการดำเนินงาน", align="center", bold=True, size=26, before=12, after=4)
    _p(doc, _txt(rep.title) or _txt(prj.name), align="center", bold=True, size=22, after=2)
    if _txt(rep.title) and _txt(prj.name) and _txt(rep.title) != _txt(prj.name):
        _p(doc, f"ภายใต้โครงการ {prj.name}", align="center", size=18, after=2)
    if prj.plan_year:
        _p(doc, f"{year_label} {prj.plan_year}", align="center", size=18, after=2)

    _p(doc, "", size=20, after=0)
    if _txt(rep.responsible):
        _p(doc, "ผู้รับผิดชอบ", align="center", size=17, after=2)
        _p(doc, rep.responsible, align="center", bold=True, size=18, after=1)
        if _txt(rep.responsible_pos):
            _p(doc, rep.responsible_pos, align="center", size=16, after=2)

    _p(doc, "", size=20, after=0)
    if _txt(school.name):
        _p(doc, school.name, align="center", bold=True, size=18, after=2)
    for line in [_txt(getattr(school, "area_office", ""))]:
        if line:
            _p(doc, line, align="center", size=16, after=1)


def render_project_report(rep, school, doc=None) -> str:
    """สร้างไฟล์รายงานผลการดำเนินงาน 1 ฉบับ · คืน path ไฟล์ .docx"""
    from app.services.budget import plan_year_label
    own = doc is None
    if own:
        doc = Document(); set_a4(doc); _font(doc)
    elif doc.paragraphs or doc.tables:
        doc.add_page_break()

    prj = rep.project
    year_label = plan_year_label(school)
    _cover(doc, rep, school, year_label)
    doc.add_page_break()

    # ---------------- ส่วนที่ 1 ข้อมูลทั่วไป ----------------
    _p(doc, "รายงานผลการดำเนินงาน", align="center", bold=True, size=20, after=2)
    _p(doc, _txt(rep.title) or _txt(prj.name), align="center", bold=True, size=18, after=8)

    _p(doc, "๑. ข้อมูลทั่วไป", bold=True, size=17, before=4, after=4)
    _kv_table(doc, [
        ("ชื่อโครงการ", prj.name),
        ("ชื่อกิจกรรม", rep.title if _txt(rep.title) != _txt(prj.name) else ""),
        (year_label, prj.plan_year or ""),
        ("ฝ่าย/งานที่รับผิดชอบ", prj.responsible),
        ("ผู้รับผิดชอบ", " ".join(x for x in [_txt(rep.responsible), _txt(rep.responsible_pos)] if x)),
        ("ระยะเวลาดำเนินการ", _period(rep)),
        ("สถานที่ดำเนินการ", rep.location),
        ("สนองมาตรฐาน/กลยุทธ์", rep.std_ref),
    ])

    # ---------------- งบประมาณ ----------------
    planned = float(rep.budget_planned or 0)
    used = float(rep.budget_used or 0)
    if planned or used or _txt(rep.budget_note):
        _p(doc, "๒. งบประมาณ", bold=True, size=17, before=6, after=4)
        t = doc.add_table(rows=1, cols=3)
        t.style = "Table Grid"
        for cell, head in zip(t.rows[0].cells, ["งบประมาณที่ตั้งไว้", "ใช้จริง", "คงเหลือ"]):
            _set_cell(cell, head, size=16, align="center", bold=True)
            cell.width = Cm(5.3)
        c = t.add_row().cells
        for cell, val in zip(c, [planned, used, planned - used]):
            _set_cell(cell, f"{_money(val)} บาท", size=16, align="center")
            cell.width = Cm(5.3)
        _p(doc, "", size=8, after=0)
        if _txt(rep.budget_note):
            _p(doc, f"หมายเหตุ : {rep.budget_note}", size=16, indent=1.25, after=3)

    # ---------------- เนื้อหา ----------------
    n = 3 if (planned or used or _txt(rep.budget_note)) else 2
    thai_num = ["", "๑", "๒", "๓", "๔", "๕", "๖", "๗", "๘", "๙", "๑๐", "๑๑", "๑๒", "๑๓"]
    for attr, head in BODY_SECTIONS:
        body = _txt(getattr(rep, attr, ""))
        if not body:
            continue
        _p(doc, f"{thai_num[n] if n < len(thai_num) else n}. {head}",
           bold=True, size=17, before=6, after=4)
        _para_block(doc, body)
        n += 1

    # ---------------- ลงนาม ----------------
    _p(doc, "", size=12, after=0)
    signer = _txt(rep.responsible) or "..............................................."
    _sign_table(doc, [[
        ("", "center"),
        ("ลงชื่อ ...............................................", "center"),
        (f"( {signer} )", "center"),
        (_txt(rep.responsible_pos) or "ผู้รายงาน", "center"),
    ]], after=4)

    _p(doc, "ความเห็นของผู้อำนวยการโรงเรียน", bold=True, size=17, before=8, after=4)
    _p(doc, "........................................................................................"
            "..............................................................................", size=16, after=3)
    _p(doc, "........................................................................................"
            "..............................................................................", size=16, after=8)
    _sign_table(doc, [[
        ("ลงชื่อ ...............................................", "center"),
        (f"( {_txt(school.director_name) or '.............................................'} )", "center"),
        (_txt(getattr(school, "director_position", "")) or "ผู้อำนวยการโรงเรียน", "center"),
    ]], after=2)

    # ---------------- ภาคผนวก: ภาพกิจกรรม ----------------
    photos = [ph for ph in (rep.photos or []) if ph.image]
    if photos:
        doc.add_page_break()
        _p(doc, "ภาคผนวก", align="center", bold=True, size=20, after=2)
        _p(doc, "ภาพกิจกรรม", align="center", bold=True, size=18, after=10)
        _photo_grid(doc, photos)

    name = f"รายงานผลการดำเนินงาน_{_txt(rep.title) or _txt(prj.name)}"
    return _save(doc, name) if own else doc


def _photo_grid(doc, photos):
    """ตารางภาพ 2 คอลัมน์ · แต่ละภาพมีคำบรรยายใต้ภาพ (ภาพเสียข้ามไป ไม่ทำเอกสารพัง)"""
    t = doc.add_table(rows=0, cols=2)
    _no_borders(t)
    for i in range(0, len(photos), 2):
        pair = photos[i:i + 2]
        row = t.add_row()
        row.height = Cm(6.4)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for j, cell in enumerate(row.cells):
            cell.width = Cm(8.0)
            cell.text = ""
            if j >= len(pair):
                continue
            ph = pair[j]
            p = cell.paragraphs[0]
            p.alignment = 1
            p.paragraph_format.space_after = Pt(2)
            try:
                p.add_run().add_picture(io.BytesIO(ph.image), width=Cm(7.4))
            except Exception:
                continue
            cap = _txt(ph.caption)
            if cap:
                cp = cell.add_paragraph()
                cp.alignment = 1
                cp.paragraph_format.space_after = Pt(10)
                r = cp.add_run(cap)
                _csize(r, 14)
                r.font.name = THAI_FONT
