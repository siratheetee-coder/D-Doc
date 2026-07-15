# -*- coding: utf-8 -*-
"""
hr_doc.py — เอกสารงานบุคคล (Word)
- render_leave_form  : ใบลา (ป่วย/กิจ/พักผ่อน ฯลฯ)
- render_certificate : หนังสือรับรอง (การเป็นบุคลากร / เงินเดือน)
"""
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn

from app.database import get_data_dir
from app.thai_utils import thai_date

THAI_FONT = "TH Sarabun New"
_BLANK = "................................"


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _p(doc, text="", *, align="left", bold=False, size=15, after=6, indent=0.0):
    p = doc.add_paragraph()
    p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}[align]
    p.paragraph_format.space_after = Pt(after)
    if indent:
        p.paragraph_format.first_line_indent = Cm(indent)
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    r.font.name = THAI_FONT
    r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    return p


def _doc():
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(2.5)
    sec.top_margin = Cm(2.0); sec.bottom_margin = Cm(1.5)
    base = doc.styles["Normal"]; base.font.name = THAI_FONT; base.font.size = Pt(15)
    base._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    return doc


def _director_pos(school):
    return ("ผู้อำนวยการ" + school.name) if (school.name or "").startswith("โรงเรียน") \
        else (getattr(school, "director_position", "") or "ผู้อำนวยการโรงเรียน")


def _dt(d):
    return thai_date(d) if d else _BLANK


# ---------------- ใบลา ----------------
def render_leave_form(school, person, record, type_label) -> str:
    doc = _doc()
    _p(doc, "ใบลา" + type_label.replace("ลา", "", 1), align="center", bold=True, size=20, after=10)

    _p(doc, f"เขียนที่ {school.name or ''}", align="right", after=0)
    _p(doc, f"วันที่ {_dt(record.created_at)}", align="right", after=8)

    _p(doc, f"เรื่อง  ขอ{type_label}", after=2)
    _p(doc, f"เรียน  {_director_pos(school)}", after=6)

    name = person.name or _BLANK
    pos = person.position or "ครู"
    _p(doc, f"ข้าพเจ้า {name} ตำแหน่ง {pos} "
            f"ขอ{type_label}ตั้งแต่วันที่ {_dt(record.start_date)} ถึงวันที่ {_dt(record.end_date)} "
            f"มีกำหนด {record.days:g} วัน "
            + (f"เนื่องจาก {record.reason} " if (record.reason or '').strip() else "")
            + "ในระหว่างลาข้าพเจ้าจะติดต่อได้ที่ "
            + ((record.contact or '').strip() or _BLANK),
       align="justify", size=15, after=6, indent=1.25)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณาอนุญาต", align="justify", after=20, indent=1.25)

    _p(doc, "ขอแสดงความนับถือ", align="center", after=2)
    _p(doc, "(ลงชื่อ)...................................ผู้ลา", align="center", after=0)
    _p(doc, f"( {name} )", align="center", after=14)

    # ความเห็น/คำสั่งผู้บังคับบัญชา
    _p(doc, "คำสั่ง", bold=True, after=2)
    _p(doc, "☐ อนุญาต            ☐ ไม่อนุญาต", indent=1.25, after=14)
    _p(doc, "(ลงชื่อ)...................................", align="center", after=0)
    _p(doc, f"( {(getattr(school, 'director_name', '') or '').strip() or _BLANK} )", align="center", after=0)
    _p(doc, _director_pos(school), align="center", after=2)

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"ใบลา_{name}_{record.id}") + ".docx")
    doc.save(str(out))
    return str(out)


# ---------------- หนังสือรับรอง ----------------
def render_certificate(school, person, kind="status") -> str:
    doc = _doc()
    _p(doc, (school.name or ""), align="center", bold=True, size=16, after=0)
    if getattr(school, "address", ""):
        _p(doc, school.address, align="center", size=13, after=8)
    else:
        _p(doc, "", after=6)

    _p(doc, "หนังสือรับรอง", align="center", bold=True, size=18, after=10)

    name = person.name or _BLANK
    pos = person.position or "ครู"
    rank = (person.rank or "").strip()
    idc = (person.id_card or "").strip()
    detail_pos = (f"{pos} {rank}".strip())

    lead = (f"หนังสือฉบับนี้ให้ไว้เพื่อรับรองว่า {name} "
            + (f"เลขประจำตัวประชาชน {idc} " if idc else "")
            + f"ตำแหน่ง {detail_pos} ")

    if kind == "salary":
        body = (lead + f"เป็นบุคลากรของ{school.name or 'โรงเรียน'} "
                + (f"ปฏิบัติงานตั้งแต่วันที่ {thai_date(person.start_date)} " if person.start_date else "")
                + f"ปัจจุบันได้รับเงินเดือน เดือนละ {(person.salary or 0):,.2f} บาท "
                + f"({_baht(person.salary or 0)}) จริง")
        title_note = "รับรองเงินเดือน"
    else:
        body = (lead + f"เป็นบุคลากรของ{school.name or 'โรงเรียน'} "
                + (f"ปฏิบัติหน้าที่ตั้งแต่วันที่ {thai_date(person.start_date)} " if person.start_date else "")
                + "จนถึงปัจจุบันจริง")
        title_note = "รับรองการเป็นบุคลากร"

    _p(doc, body, align="justify", size=15, after=6, indent=1.25)
    _p(doc, f"ให้ไว้ ณ วันที่ {thai_date(__import__('datetime').datetime.now())}",
       align="justify", after=24, indent=1.25)

    _p(doc, "(ลงชื่อ)...................................", align="center", after=0)
    _p(doc, f"( {(getattr(school, 'director_name', '') or '').strip() or _BLANK} )", align="center", after=0)
    _p(doc, _director_pos(school), align="center", after=2)

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"หนังสือรับรอง_{title_note}_{name}") + ".docx")
    doc.save(str(out))
    return str(out)


# ---------------- คำสั่งไปราชการ ----------------
def render_travel_order(school, person, record) -> str:
    doc = _doc()
    _p(doc, "คำสั่ง" + (school.name or "โรงเรียน"), align="center", bold=True, size=17, after=0)
    _p(doc, f"ที่  {record.doc_no or '............/............'}", align="center", size=14, after=0)
    _p(doc, "เรื่อง  ให้ข้าราชการครูและบุคลากรทางการศึกษาไปราชการ", align="center", bold=True, size=15, after=8)
    _p(doc, "───────────────────", align="center", after=8)

    name = person.name or _BLANK
    pos = person.position or "ครู"
    subject = (record.subject or "").strip() or "ปฏิบัติราชการ"
    place = (record.place or "").strip() or _BLANK
    _p(doc, f"ด้วย {school.name or 'โรงเรียน'} มีความจำเป็นต้องให้บุคลากรไปราชการเพื่อ {subject} "
            f"จึงอาศัยอำนาจตามความในมาตราที่เกี่ยวข้อง แต่งตั้งให้บุคคลดังต่อไปนี้ไปราชการ",
       align="justify", size=15, after=6, indent=1.25)
    _p(doc, f"{name} ตำแหน่ง {pos} "
            f"ไปราชการ ณ {place} "
            f"ตั้งแต่วันที่ {_dt(record.start_date)} ถึงวันที่ {_dt(record.end_date)} "
            f"รวม {record.days:g} วัน"
            + (f" โดยเบิกค่าใช้จ่ายในการเดินทางไปราชการ จำนวน {record.budget:,.2f} บาท" if (record.budget or 0) else ""),
       align="justify", size=15, after=6, indent=1.25)
    _p(doc, "ทั้งนี้ ให้ผู้ได้รับแต่งตั้งปฏิบัติหน้าที่ที่ได้รับมอบหมายด้วยความเรียบร้อย เกิดผลดีแก่ทางราชการ",
       align="justify", size=15, after=8, indent=1.25)
    _p(doc, f"สั่ง ณ วันที่ {_dt(record.doc_date)}", align="center", after=24)

    _p(doc, "(ลงชื่อ)...................................", align="center", after=0)
    _p(doc, f"( {(getattr(school, 'director_name', '') or '').strip() or _BLANK} )", align="center", after=0)
    _p(doc, _director_pos(school), align="center", after=2)

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"คำสั่งไปราชการ_{name}_{record.id}") + ".docx")
    doc.save(str(out))
    return str(out)


def _baht(v):
    try:
        from app.thai_utils import bahttext
        return bahttext(v)
    except Exception:
        return ""
