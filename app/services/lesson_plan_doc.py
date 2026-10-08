# -*- coding: utf-8 -*-
"""
lesson_plan_doc.py - บันทึกข้อความขออนุมัติใช้แผนการจัดการเรียนรู้

ทำไมต้องมีเอกสารนี้
    ไฟล์แผนที่ครูอัปโหลดเป็นรูปแบบของแต่ละโรงเรียน ระบบแตะไม่ได้ (บางโรงเรียนส่ง Word
    บางโรงเรียนส่ง PDF หรือรูปถ่าย) ลายเซ็นผู้บริหารจึงต้องไปอยู่บน "หน้าที่ระบบออกเอง"
    คือบันทึกข้อความนำหน้าแผน ซึ่งเป็นรูปแบบเดียวกับที่ใช้เสนอ ผอ. อยู่แล้วตามระเบียบ
    สำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. 2526 ข้อ 26 (บันทึกเสนอผู้บังคับบัญชา)

โครงเอกสาร (1 หน้า)
    หัวบันทึกข้อความ (ครุฑ + ส่วนราชการ/ที่/วันที่/เรื่อง/เรียน) ตามแบบเดียวกับเอกสารอื่นในระบบ
    เนื้อความ 3 ตอน: เหตุ -> รายการหน่วยการเรียนรู้ (ตาราง) -> ข้อเสนอ
    ช่องลงนามครูผู้เสนอ -> ความเห็นหัวหน้ากลุ่มบริหารงานวิชาการ -> คำสั่งผู้อำนวยการ
    ลายเซ็นทั้งสามคนแปะอัตโนมัติจาก Person.signature แบบ "อยู่หน้าข้อความ" (จุดไข่ปลาไม่เลื่อน)

ผอ. ลงนามครั้งเดียวครอบคลุมทุกหน่วยที่ปรากฏในตาราง ตรงตามหลักการลงนามอนุมัติเอกสารทั้งฉบับ
ไม่ต้องเซ็นรายแผ่น
"""
import re

from docx import Document
from docx.shared import Cm, Pt

from app.services.doc_page import set_a4
from app.services.build_templates import (_font, _p, _p_runs, _sign_table, _set_cell,
                                          _krut_and_title, _repeat_header_row, _no_split_row)
from app.services.office_doc import _save_doc, _safe, _float_signature
from app.services.org_names import head_title, org_display
from app.thai_utils import thai_date

DOT = "................................"
_SIG_CM = 1.2          # ความสูงรูปลายเซ็นในบันทึกนี้
_DOTS = "." * 34       # เส้นไข่ปลาในช่องความเห็น (กว้างครึ่งหน้า)

# "(12 ชั่วโมง)" / "12 ชม." / "เวลา 12 ชั่วโมง" -> ดึงจำนวนชั่วโมงออกมา
_HOURS = re.compile(r"(\d+(?:\.\d+)?)\s*(?:ชั่วโมง|ชม\.?)")
# คำนำหน้าลำดับที่ครูมักพิมพ์มาเอง ("หน่วยที่ 1", "หน่วย 1", "1.", "1)", "- ")
_LEAD = re.compile(r"^\s*(?:หน่วย(?:การเรียนรู้)?\s*(?:ที่)?\s*)?(\d+)?\s*[.)\-:]*\s*")


def _v(text, dots=DOT) -> str:
    text = (str(text) if text is not None else "").strip()
    return text or dots


def _hours_text(h) -> str:
    """ชั่วโมงแบบไม่มีทศนิยมเกินจำเป็น (12.0 -> 12, 1.5 -> 1.5)"""
    if h is None:
        return ""
    return str(int(h)) if float(h).is_integer() else f"{float(h):g}"


def parse_units(text: str) -> list[dict]:
    """แปลงข้อความที่ครูพิมพ์ (บรรทัดละหน่วย) เป็นรายการหน่วยการเรียนรู้

    รับได้ทุกแบบที่ครูพิมพ์กันจริง เพราะกรอกเป็นข้อความอิสระ
        หน่วยที่ 1 จำนวนนับ (12 ชั่วโมง)
        2. การบวกลบ 15 ชม.
        - การวัด
    คืน [{"no": ลำดับ, "name": ชื่อหน่วย, "hours": ชั่วโมงหรือ None}]
    ลำดับใช้ของที่ครูพิมพ์มาถ้ามี ไม่มีก็ไล่ให้ตามบรรทัด (กันเลขซ้ำ/ข้ามแล้วเอกสารดูผิด)
    """
    out: list[dict] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _HOURS.search(line)
        hours = float(m.group(1)) if m else None
        if m:
            # ตัดส่วนที่บอกชั่วโมงออกจากชื่อ รวมวงเล็บและคำว่า "เวลา" ที่ครอบอยู่
            line = (line[:m.start()] + line[m.end():]).strip()
            line = re.sub(r"(?:เวลา)?\s*[(\[]?\s*[)\]]?\s*$", "", line).strip()
            line = line.strip("()[]-:,. ").strip()
        lead = _LEAD.match(line)
        no = int(lead.group(1)) if (lead and lead.group(1)) else None
        name = line[lead.end():].strip() if lead else line
        if not name and no is not None:
            # บรรทัดมีแต่เลข เช่น "3" ถือว่าไม่ใช่ชื่อหน่วย ปล่อยไว้เป็นชื่อตามที่พิมพ์
            name = line.strip()
            no = None
        out.append({"no": no or (len(out) + 1), "name": name, "hours": hours})
    return out


def total_hours(units: list[dict]) -> float:
    return sum(u["hours"] for u in units if u.get("hours"))


def _teacher_pos(teacher) -> str:
    return (getattr(teacher, "position", "") or "").strip() or "ครู"


def _memo_head(doc, school, subject, date_txt):
    """หัวบันทึกข้อความตามแบบที่ระบบใช้อยู่ (ครุฑ + หัวข้อตัวหนา + tab วันที่ที่ 8 ซม.)"""
    office = (f"{org_display(school)}  " + (school.address or "").strip()).strip()
    _krut_and_title(doc)
    _p_runs(doc, [("ส่วนราชการ  ", True), (_v(office), False)], after=0)
    _p_runs(doc, [("ที่  ", True), (DOT, False), ("\t", False),
                  ("วันที่  ", True), (_v(date_txt), False)], tab_cm=8, after=0)
    _p_runs(doc, [("เรื่อง  ", True), (subject, False)], after=0)
    _p_runs(doc, [("เรียน  ", True), (head_title(school), False)], after=6)


def _units_table(doc, units):
    """ตารางรายการหน่วยการเรียนรู้ (ที่ / ชื่อหน่วย / เวลา) ปิดท้ายด้วยแถวรวมเวลา"""
    table = doc.add_table(rows=1, cols=3)
    table.style = "Table Grid"
    widths = (Cm(1.6), Cm(11.4), Cm(2.6))
    hdr = table.rows[0]
    _repeat_header_row(hdr)
    for cell, text, w in zip(hdr.cells, ("ที่", "ชื่อหน่วยการเรียนรู้", "เวลา (ชั่วโมง)"), widths):
        _set_cell(cell, text, bold=True, align="center")
        cell.width = w
    for u in units:
        row = table.add_row()
        _no_split_row(row)
        for cell, text, align, w in zip(
                row.cells,
                (str(u["no"]), _v(u["name"]), _hours_text(u.get("hours")) or "-"),
                ("center", "left", "center"), widths):
            _set_cell(cell, text, align=align)
            cell.width = w
    th = total_hours(units)
    if th:
        row = table.add_row()
        _no_split_row(row)
        _set_cell(row.cells[0], "", align="center")
        _set_cell(row.cells[1], "รวมเวลาเรียน", bold=True, align="right")
        _set_cell(row.cells[2], _hours_text(th), bold=True, align="center")
        for cell, w in zip(row.cells, widths):
            cell.width = w
    return table


def _cell_p(cell, text, *, bold=False, align="left", size=14, first=False, after=2, indent=None):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn as _qn
    from app.services.build_templates import _csize, _bcs, THAI_FONT
    pg = cell.paragraphs[0] if first else cell.add_paragraph()
    pg.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                    "justify": WD_ALIGN_PARAGRAPH.THAI_JUSTIFY}[align]
    pg.paragraph_format.space_after = Pt(after)
    pg.paragraph_format.space_before = Pt(0)
    if indent is not None:
        pg.paragraph_format.first_line_indent = Cm(indent)
    r = pg.add_run(text)
    _csize(r, size)
    _bcs(r, bold)
    r.font.name = THAI_FONT
    r._element.rPr.rFonts.set(_qn("w:cs"), THAI_FONT)
    return pg


def _opinion_text(cell, heading, lines):
    _cell_p(cell, heading, bold=True, first=True)
    for text in lines:
        _cell_p(cell, text, align="justify", indent=1.0)


def _opinion_sign(cell, name, position, date_txt):
    sig = _cell_p(cell, "ลงชื่อ ..............................................",
                  align="center", after=0, first=True)
    sig.paragraph_format.space_before = Pt(10)   # เว้นที่เซ็นจริงเหนือบรรทัดลงชื่อ
    _cell_p(cell, f"( {_v(name)} )", align="center", after=0)
    _cell_p(cell, _v(position), align="center", after=0)
    _cell_p(cell, _v(date_txt, DOT), align="center", after=0)
    if (name or "").strip():
        _float_signature(sig, name, height_cm=_SIG_CM, dy_cm=-0.45)


def _opinion_pair(doc, left, right):
    """ความเห็นวิชาการ | คำสั่ง ผอ. วางเคียงกันแบบแบบฟอร์มราชการ (เช่นใบลา)

    ใช้ตารางไร้เส้นขอบ 2 คอลัมน์ 2 แถว แถวบนเป็นข้อความ แถวล่างเป็นช่องลงนาม
    แยกแถวเพื่อให้ "ลงชื่อ" ของทั้งสองฝั่งอยู่ระดับเดียวกันเสมอ
    ต่อให้ความเห็นสองฝั่งยาวไม่เท่ากัน
    """
    from app.services.build_templates import _no_borders
    table = doc.add_table(rows=2, cols=2)
    _no_borders(table)
    for row in table.rows:
        _no_split_row(row)
    for i, block in enumerate((left, right)):
        heading, lines, name, position, date_txt = block
        table.rows[0].cells[i].width = Cm(8.5)
        table.rows[1].cells[i].width = Cm(8.5)
        _opinion_text(table.rows[0].cells[i], heading, lines)
        _opinion_sign(table.rows[1].cells[i], name, position, date_txt)
    return table


def _subject(plan) -> str:
    term = f" ภาคเรียนที่ {plan.term}" if plan.term else ""
    year = f" ปีการศึกษา {plan.year}" if plan.year else ""
    return f"ขออนุมัติใช้แผนการจัดการเรียนรู้ {_v(plan.title)}{term}{year}"


def _intro(plan, teacher, units) -> str:
    """ตอนที่ 1 ของเนื้อความ: อ้างระเบียบแล้วแจ้งว่าจัดทำแผนเสร็จแล้ว"""
    term = f"ภาคเรียนที่ {plan.term} " if plan.term else ""
    year = f"ปีการศึกษา {plan.year} " if plan.year else ""
    n = len(units)
    th = total_hours(units)
    count = (f" จำนวน {n} หน่วยการเรียนรู้" if n else "")
    count += (f" รวมเวลาเรียน {_hours_text(th)} ชั่วโมง" if th else "")
    return ("ตามที่หลักสูตรแกนกลางการศึกษาขั้นพื้นฐาน พุทธศักราช 2551 กำหนดให้ครูผู้สอนจัดทำ "
            "แผนการจัดการเรียนรู้ให้สอดคล้องกับมาตรฐานการเรียนรู้ ตัวชี้วัด และโครงสร้างรายวิชา นั้น "
            f"บัดนี้ ข้าพเจ้า {_v(getattr(teacher, 'name', ''))} ตำแหน่ง {_teacher_pos(teacher)} "
            f"ได้จัดทำแผนการจัดการเรียนรู้ {_v(plan.title)} {term}{year}เสร็จเรียบร้อยแล้ว{count} "
            "รายละเอียดปรากฏตามเอกสารแผนการจัดการเรียนรู้ที่แนบมาพร้อมบันทึกฉบับนี้"
            + (" โดยมีรายการหน่วยการเรียนรู้ ดังนี้" if units else ""))


def render_plan_memo(plan, school, *, academic=None, director=None) -> str:
    """ออกบันทึกข้อความขออนุมัติใช้แผนการจัดการเรียนรู้ คืน path ไฟล์ .docx

    academic / director = Person ผู้ลงนาม (หัวหน้าวิชาการ / ผอ.) ส่งเป็น None ได้
    ถ้ายังไม่ถึงคิวลงนาม เอกสารจะเว้นช่องลงนามไว้ให้เซ็นมือ
    """
    doc = Document()
    set_a4(doc)
    _font(doc)
    units = parse_units(getattr(plan, "units", "") or "")
    teacher = plan.teacher
    submitted = thai_date(plan.submitted_at) if plan.submitted_at else ""

    _memo_head(doc, school, _subject(plan), submitted)
    _p(doc, _intro(plan, teacher, units), align="justify", indent=2.5, after=4)

    if units:
        _units_table(doc, units)
        _p(doc, "", after=0)
    if (plan.note or "").strip():
        _p(doc, f"หมายเหตุ {plan.note.strip()}", align="justify", indent=2.5, after=4)

    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติให้ใช้แผนการจัดการเรียนรู้ดังกล่าว "
            "ในการจัดกิจกรรมการเรียนการสอนตามรายการที่เสนอต่อไป",
       align="justify", indent=2.5, after=6)

    tbl = _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ......................................", "center"),
        (f"( {_v(getattr(teacher, 'name', ''))} )", "center"),
        (_teacher_pos(teacher) + " ผู้เสนอ", "center"),
    ]], after=0, sign_gap=2)
    if teacher is not None and (teacher.name or "").strip():
        _float_signature(tbl.rows[0].cells[1].paragraphs[0], teacher.name,
                         height_cm=_SIG_CM, dy_cm=-0.45)

    # ---- ความเห็นวิชาการ | คำสั่ง ผอ. (สองช่องเคียงกัน) ----
    acad_name = (getattr(academic, "name", "") or "").strip() or (school.academic_head_name or "").strip()
    acad_pos = (getattr(academic, "position", "") or "").strip() or "หัวหน้ากลุ่มบริหารงานวิชาการ"
    if plan.reviewed_at:
        acad_lines = ["ได้ตรวจสอบแผนการจัดการเรียนรู้ที่เสนอแล้ว เห็นว่ามีองค์ประกอบครบถ้วน "
                      "สอดคล้องกับหลักสูตรสถานศึกษา เห็นควรอนุมัติ"]
        if (plan.comment or "").strip():
            acad_lines.append(f"ความเห็นเพิ่มเติม {plan.comment.strip()}")
    else:
        acad_lines = [_DOTS, _DOTS, _DOTS]

    dir_name = (getattr(director, "name", "") or "").strip() or (school.director_name or "").strip()
    if plan.status == "approved":
        dir_lines = ["อนุมัติให้ใช้แผนการจัดการเรียนรู้ตามเสนอ"]
    elif plan.status == "revise" and plan.director_at:
        dir_lines = ["ส่งคืนเพื่อปรับปรุงแก้ไขตามความเห็น แล้วนำเสนออีกครั้ง"]
    else:
        dir_lines = ["อนุมัติ / ไม่อนุมัติ", _DOTS, _DOTS]
    if (plan.director_comment or "").strip():
        dir_lines.append(f"ความเห็นเพิ่มเติม {plan.director_comment.strip()}")

    _opinion_pair(doc,
                  ("ความเห็นหัวหน้ากลุ่มบริหารงานวิชาการ", acad_lines,
                   acad_name if plan.reviewed_at else "", acad_pos,
                   thai_date(plan.reviewed_at) if plan.reviewed_at else ""),
                  ("คำสั่งผู้อำนวยการ", dir_lines,
                   dir_name if plan.director_at else "", head_title(school),
                   thai_date(plan.director_at) if plan.director_at else ""))

    return _save_doc(doc, _safe(f"บันทึกขออนุมัติใช้แผนการจัดการเรียนรู้_{plan.id}") + ".docx")
