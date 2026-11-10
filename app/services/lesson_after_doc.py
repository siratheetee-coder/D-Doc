# -*- coding: utf-8 -*-
"""
lesson_after_doc.py - บันทึกหลังการจัดการเรียนรู้ (ท้ายแผนแต่ละหน่วย)

ครูอัปโหลดเฉพาะ "ตัวแผน" ไม่ต้องทำหน้านี้และช่องลายเซ็นมาเอง ระบบออกให้หน่วยละหนึ่งหน้า
เพราะเป็นหน้าที่ระบบสร้างเอง การลงนามทุกหน่วยจึงเป็นคลิกเดียว ไม่ว่าจะมีกี่หน่วย
ซึ่งเป็นปัญหาตั้งต้นของงานนี้ (แผนชุดหนึ่งมีหลายหน่วย ผอ. ต้องเซ็นให้ครบทุกหน่วย)

รูปแบบหน้า ยกตามแบบที่โรงเรียนใช้จริง
    กรอบบน  ผลการจัดการเรียนรู้ แยกด้านความรู้ (K) ด้านกระบวนการ (P)
            ด้านคุณลักษณะอันพึงประสงค์และเจตคติ (A)
    กรอบกลาง ปัญหาและอุปสรรค
    กรอบล่าง ข้อเสนอแนะ / แนวทางแก้ไข
    ท้ายหน้า ลงชื่อครูผู้สอน และผู้อำนวยการ พร้อมวันที่
ช่องที่ยังไม่ได้กรอกจะพิมพ์เป็นเส้นบรรทัดว่างให้เขียนมือได้ตามเดิม
"""
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from app.services.build_templates import _bcs, _csize, _no_borders, _no_split_row, THAI_FONT
from app.services.doc_page import set_a4
from app.services.office_doc import _save_doc, _safe, _float_signature
from app.services.org_names import head_title_short
from app.thai_utils import thai_date

_SIG_CM = 1.2
# จำนวนเส้นบรรทัดว่างของแต่ละช่อง เมื่อครูยังไม่ได้พิมพ์ผลเข้ามา
_BLANK_LINES = {"k": 3, "p": 3, "a": 3, "problem": 3, "suggestion": 3}
# บรรทัดไข่ปลา: เจ้าของขอให้ข้อความที่ครูพิมพ์อยู่บนเส้นไข่ปลา ไม่ลบไข่ปลาออก
# ทำด้วยขีดเส้นใต้แบบจุด (w:u dotted) ทั้งตัวข้อความ แล้วต่อด้วย tab ที่ขีดเส้นใต้จนสุดบรรทัด
_LINE_TAB_CM = 15.6     # จุดสิ้นสุดเส้นไข่ปลาในกรอบ (กรอบกว้าง 16.5 ซม.)
_CHARS_PER_LINE = 88    # ประมาณตัวอักษรไทยต่อบรรทัด ไว้นับว่าข้อความกินไปกี่บรรทัด
_RULE = " " * 2      # ช่องว่างต้นบรรทัดของเส้นว่าง (เส้นมาจากขอบล่างของย่อหน้า)


def _p(container, text="", *, bold=False, size=14, align="left", after=2, before=0,
       indent=None, first=False):
    pg = container.paragraphs[0] if (first and container.paragraphs) else container.add_paragraph()
    pg.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "right": WD_ALIGN_PARAGRAPH.RIGHT,
                    "justify": WD_ALIGN_PARAGRAPH.THAI_JUSTIFY}[align]
    pg.paragraph_format.space_after = Pt(after)
    pg.paragraph_format.space_before = Pt(before)
    if indent is not None:
        pg.paragraph_format.left_indent = Cm(indent)
    r = pg.add_run(text)
    _csize(r, size)
    _bcs(r, bold)
    r.font.name = THAI_FONT
    r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    return pg


def _underline_rule(paragraph):
    """ขีดเส้นใต้เต็มความกว้างย่อหน้า (ใช้เป็นบรรทัดให้เขียนมือ)"""
    pPr = paragraph._p.get_or_add_pPr()
    bdr = pPr.makeelement(qn("w:pBdr"), {})
    bottom = pPr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single", qn("w:sz"): "6", qn("w:space"): "1", qn("w:color"): "000000"})
    bdr.append(bottom)
    pPr.append(bdr)


def _dotted_run(paragraph, text):
    r = paragraph.add_run(text)
    _csize(r, 14)
    r.font.name = THAI_FONT
    rpr = r._element.get_or_add_rPr()
    rpr.rFonts.set(qn("w:cs"), THAI_FONT)
    u = rpr.makeelement(qn("w:u"), {qn("w:val"): "dotted"})
    rpr.append(u)
    return r


def _dotted_line(cell, text="", *, indent=0.5):
    """บรรทัดไข่ปลาหนึ่งบรรทัด ข้อความ (ถ้ามี) วางบนเส้น ที่เหลือเป็นไข่ปลาจนสุดบรรทัด"""
    from docx.enum.text import WD_TAB_ALIGNMENT
    pg = cell.add_paragraph()
    pg.paragraph_format.left_indent = Cm(indent)
    pg.paragraph_format.space_after = Pt(2)
    pg.paragraph_format.space_before = Pt(0)
    pg.paragraph_format.tab_stops.add_tab_stop(Cm(_LINE_TAB_CM), WD_TAB_ALIGNMENT.RIGHT)
    if text:
        _dotted_run(pg, " " + text + " ")
    _dotted_run(pg, "\t")
    return pg


def _filled_or_blank(cell, text, blank_lines, *, indent=0.5):
    """เขียนข้อความที่ครูกรอกบนเส้นไข่ปลา แล้วเติมบรรทัดไข่ปลาเปล่าให้ครบอย่างน้อย blank_lines บรรทัด"""
    import math
    used = 0
    for line in (text or "").strip().splitlines():
        line = line.strip()
        if not line:
            continue
        _dotted_line(cell, line, indent=indent)
        used += max(1, math.ceil(len(line) / _CHARS_PER_LINE))
    for _ in range(max(0, blank_lines - used)):
        _dotted_line(cell, indent=indent)


def _box(doc, heading, rows, *, width_cm=16.5):
    """กรอบหนึ่งกล่องของแบบฟอร์ม (ตาราง 1 ช่อง มีขอบ) rows = [(หัวข้อย่อย, ข้อความ, บรรทัดว่าง)]"""
    table = doc.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    cell.width = Cm(width_cm)
    _no_split_row(table.rows[0])
    _p(cell, heading, bold=True, after=6, first=True)
    for sub, text, blanks in rows:
        if sub:
            _p(cell, sub, bold=True, after=4, indent=0.3)
        _filled_or_blank(cell, text, blanks)
    _p(doc, "", after=6)
    return table


def _sign_cell(cell, label, name, date_txt, *, sign_dy=-0.45):
    line = _p(cell, f"ลงชื่อ ............................................... {label}",
              align="center", after=0, first=True)
    line.paragraph_format.space_before = Pt(22)
    _p(cell, f"( {name or '...............................................'} )", align="center", after=0)
    _p(cell, f"วันที่ {date_txt or '...............................'}", align="center", after=0)
    if (name or "").strip():
        _float_signature(line, name, height_cm=_SIG_CM, dy_cm=sign_dy)


def _unit_title(plan, unit) -> str:
    """บอกให้ชัดว่าเป็นบันทึกของแผนไหน หน่วยไหน (พิมพ์รวมเล่มแล้วไม่ปนกัน)"""
    from app.services.lesson_set import row_title
    return row_title(plan, unit)


def _sub_title(plan, unit) -> str:
    bits = []
    if (getattr(plan, "title", "") or "").strip():
        bits.append(plan.title.strip())
    if getattr(plan, "term", None):
        bits.append(f"ภาคเรียนที่ {plan.term}")
    if getattr(plan, "year", None):
        bits.append(f"ปีการศึกษา {plan.year}")
    if getattr(unit, "taught_at", None):
        bits.append(f"สอนวันที่ {thai_date(unit.taught_at)}")
    return " ".join(bits)


def render_after_note(doc, plan, school, unit, *, teacher=None, director=None):
    """วางบันทึกหลังการจัดการเรียนรู้ของหน่วยหนึ่งลงในเอกสารที่ส่งเข้ามา"""
    teacher = teacher if teacher is not None else plan.teacher
    _p(doc, "บันทึกหลังการจัดการเรียนรู้", bold=True, size=16, align="center", after=2)
    _p(doc, _unit_title(plan, unit), align="center", size=14, after=0)
    _p(doc, _sub_title(plan, unit), align="center", size=14, after=8)

    _box(doc, "ผลการจัดการเรียนรู้", [
        ("ด้านความรู้ (Knowledge: K)", unit.k_text, _BLANK_LINES["k"]),
        ("ด้านกระบวนการ (Process: P)", unit.p_text, _BLANK_LINES["p"]),
        ("ด้านคุณลักษณะอันพึงประสงค์และเจตคติ (Attitude: A)", unit.a_text, _BLANK_LINES["a"]),
    ])
    _box(doc, "ปัญหาและอุปสรรค", [("", unit.problem, _BLANK_LINES["problem"])])
    _box(doc, "ข้อเสนอแนะ / แนวทางแก้ไข", [("", unit.suggestion, _BLANK_LINES["suggestion"])])

    sig = doc.add_table(rows=1, cols=2)
    _no_borders(sig)
    _no_split_row(sig.rows[0])
    for c in sig.rows[0].cells:
        c.width = Cm(8.2)
    # ลายเซ็นครูขึ้นเมื่อบันทึกผลแล้วเท่านั้น หน้าที่ยังว่างจึงไม่มีใครเซ็นค้างไว้
    recorded = bool(unit.taught_at or (unit.k_text or unit.p_text or unit.a_text
                                       or unit.problem or unit.suggestion or "").strip())
    _sign_cell(sig.rows[0].cells[0], "ครูผู้สอน",
               (getattr(teacher, "name", "") or "") if recorded else "",
               thai_date(unit.taught_at) if unit.taught_at else "")
    dir_name = (getattr(director, "name", "") or "").strip() or (school.director_name or "").strip()
    signed = plan.status == "approved" and plan.director_at
    _sign_cell(sig.rows[0].cells[1], head_title_short(school),
               dir_name if signed else "",
               thai_date(plan.director_at) if signed else "")
    return doc


def render_after_notes(plan, school, *, units=None, teacher=None, director=None) -> str:
    """รวมบันทึกหลังการจัดการเรียนรู้ของทุกหน่วยเป็นไฟล์เดียว หน่วยละหนึ่งหน้า"""
    from app.services.build_templates import _font
    units = list(units if units is not None else (plan.units_rows or []))
    doc = Document()
    set_a4(doc)
    _font(doc)
    for i, u in enumerate(units):
        if i:
            doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
        render_after_note(doc, plan, school, u, teacher=teacher, director=director)
    if not units:
        _p(doc, "ยังไม่มีหน่วยการเรียนรู้ในชุดแผนนี้", align="center")
    return _save_doc(doc, _safe(f"บันทึกหลังการจัดการเรียนรู้_{plan.id}") + ".docx")


def merge_with_plan(plan, school, unit, *, teacher=None, director=None) -> str | None:
    """ไฟล์แผนของหน่วยนั้น + บันทึกหลังการจัดการเรียนรู้ ต่อท้ายเป็นไฟล์เดียว

    ทำได้เฉพาะไฟล์ Word เพราะต่อท้ายเอกสารได้ตรง ๆ (docxcompose ที่ระบบใช้อยู่แล้ว)
    ไฟล์ PDF และรูปถ่ายต่อท้ายไม่ได้ถ้าไม่เพิ่มเครื่องมือแปลงเอกสารบนเซิร์ฟเวอร์
    คืน None เมื่อต่อไม่ได้ ให้ฝั่งเรียกใช้แจ้งผู้ใช้ว่าให้พิมพ์แนบเอง
    """
    import io
    from docxcompose.composer import Composer
    name = (unit.file_name or "").lower()
    if not unit.file_blob or not name.endswith(".docx"):
        return None
    try:
        master = Document(io.BytesIO(unit.file_blob))
    except Exception:
        return None       # ไฟล์ Word เสียหรือเป็น .doc รุ่นเก่าที่เปิดไม่ได้
    master.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    tail = Document()
    set_a4(tail)
    from app.services.build_templates import _font
    _font(tail)
    render_after_note(tail, plan, school, unit, teacher=teacher, director=director)
    buf = io.BytesIO()
    tail.save(buf)
    buf.seek(0)
    Composer(master).append(Document(buf))
    from app.services.lesson_set import is_plan_mode
    tag = f"แผนที่{unit.seq}" if is_plan_mode(plan) else f"หน่วยที่{unit.seq}"
    return _save_doc(master, _safe(f"แผนพร้อมบันทึกหลังสอน_{plan.id}_{tag}") + ".docx")
