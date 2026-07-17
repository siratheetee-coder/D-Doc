# -*- coding: utf-8 -*-
"""
acad_doc.py — เอกสารงานวิชาการ
- ปพ.5 : แบบบันทึกผลการพัฒนาคุณภาพผู้เรียน (รายวิชา x ห้อง) — แนวนอน
- ปพ.6 : แบบรายงานผลการพัฒนาคุณภาพผู้เรียนรายบุคคล (สมุดพก) — รายคน / ทั้งห้อง

ความกว้างตารางต้องไม่เกินพื้นที่พิมพ์ A4: แนวตั้ง 16.0 / แนวนอน 26.7 ซม.
(บทเรียนจากรอบไล่แก้ A4 — python-docx ไม่บีบให้เอง)
"""
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

from app.services.doc_page import set_a4
from app.services.office_doc import _float_signature

from app.database import get_data_dir
from app.thai_utils import thai_date, is_secondary
from app.services.academic import term_label

THAI_FONT = "TH Sarabun New"


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _doc(landscape: bool = False):
    doc = Document(); set_a4(doc, landscape=landscape)
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin = Cm(1.5); sec.bottom_margin = Cm(1.2)
    base = doc.styles["Normal"]; base.font.name = THAI_FONT; base.font.size = Pt(14)
    base._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    return doc


def _p(doc, text="", *, align="left", bold=False, size=14, after=2):
    p = doc.add_paragraph()
    p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text); r.bold = bold; r.font.size = Pt(size); r.font.name = THAI_FONT
    r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    return p


def _cell(cell, text, *, bold=False, align="center", size=13, fill=None):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run(str(text)); r.bold = bold; r.font.size = Pt(size); r.font.name = THAI_FONT
    r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    if fill:
        tcpr = cell._tc.get_or_add_tcPr()
        tcpr.append(tcpr.makeelement(qn("w:shd"), {qn("w:val"): "clear",
                                                   qn("w:color"): "auto", qn("w:fill"): fill}))


def _widths(table, widths):
    for row in table.rows:
        for c, w in zip(row.cells, widths):
            c.width = w


def _class_label(c) -> str:
    return f"{c.level}/{c.room}" if (c.room or "").strip() else (c.level or "")


def _sign_block(doc, name, role, *, after=0):
    """บล็อกลงนาม + วางลายเซ็นลอยทับถ้าผู้ลงนามอัปโหลดไว้"""
    p = _p(doc, "(ลงชื่อ).............................................", align="center", after=0)
    if name:
        _float_signature(p, name)
    _p(doc, f"( {name or '.......................................'} )", align="center", after=0)
    _p(doc, role, align="center", after=after)


# ============================ ปพ.5 ============================
def render_pp5(school, klass, subject, db) -> str:
    """แบบบันทึกผลการพัฒนาคุณภาพผู้เรียน — รายวิชา x ห้อง (แนวนอน)"""
    from app.models import AcadScore, AcadTeaching
    doc = _doc(landscape=True)
    students = sorted(klass.students, key=lambda s: (s.seq or 999, s.name))
    term = subject.term if subject.term is not None else 0
    scores = {s.acad_student_id: s for s in
              db.query(AcadScore).filter_by(subject_id=subject.id, term=term).all()}
    teach = db.query(AcadTeaching).filter_by(class_id=klass.id, subject_id=subject.id).first()
    teacher = teach.teacher.name if (teach and teach.teacher) else ""

    _p(doc, "แบบบันทึกผลการพัฒนาคุณภาพผู้เรียน (ปพ.5)", align="center", bold=True, size=18, after=0)
    _p(doc, school.name or "", align="center", bold=True, size=15, after=0)
    head = (f"รายวิชา {subject.code or ''} {subject.name}   ชั้น {_class_label(klass)}   "
            f"ปีการศึกษา {klass.year}   {term_label(term)}")
    _p(doc, head, align="center", size=14, after=2)
    meta = []
    if subject.learn_group:
        meta.append(f"กลุ่มสาระการเรียนรู้{subject.learn_group}")
    if subject.hours:
        meta.append(f"เวลาเรียน {subject.hours} ชั่วโมง")
    if subject.credit:
        meta.append(f"{subject.credit:g} หน่วยกิต")
    if meta:
        _p(doc, "  ·  ".join(meta), align="center", size=13, after=8)

    heads = ["เลขที่", "เลขประจำตัว", "ชื่อ-นามสกุล", "คะแนนเก็บ", "คะแนนปลายภาค",
             "รวม", "ผลการเรียน", "หมายเหตุ"]
    # รวม 26.7 = พื้นที่พิมพ์ A4 แนวนอน (29.7 - ขอบ 1.5x2)
    ws = [Cm(1.6), Cm(2.6), Cm(8.5), Cm(2.8), Cm(3.2), Cm(2.2), Cm(2.6), Cm(3.2)]
    t = doc.add_table(rows=1, cols=len(heads)); t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, fill="EDE9FE")
    for s in students:
        sc = scores.get(s.id)
        cells = t.add_row().cells
        _cell(cells[0], s.seq or "")
        _cell(cells[1], s.student_no or "")
        _cell(cells[2], s.name, align="left")
        _cell(cells[3], f"{sc.score_mid:g}" if sc and sc.score_mid is not None else "")
        _cell(cells[4], f"{sc.score_final:g}" if sc and sc.score_final is not None else "")
        _cell(cells[5], f"{sc.score:g}" if sc and sc.score is not None else "")
        _cell(cells[6], sc.grade if sc else "", bold=True)
        _cell(cells[7], "")
    _widths(t, ws)

    _p(doc, "", after=10)
    _sign_block(doc, teacher, "ครูผู้สอน")

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"ปพ.5_{subject.name}_{_class_label(klass)}_{klass.year}") + ".docx")
    doc.save(str(out))
    return str(out)


# ============================ ปพ.6 ============================
def _pp6_body(doc, school, s, db, *, page_break: bool = False):
    """เนื้อ ปพ.6 ของนักเรียน 1 คน (ใช้ทั้งแบบรายคนและแบบรวมทั้งห้อง)"""
    from app.models import AcadScore, AcadSubject
    klass = s.klass
    sec = is_secondary(klass.level)
    terms = [1, 2] if sec else [0]

    if page_break:
        doc.add_page_break()

    _p(doc, "แบบรายงานผลการพัฒนาคุณภาพผู้เรียนรายบุคคล (ปพ.6)", align="center", bold=True, size=17, after=0)
    _p(doc, school.name or "", align="center", bold=True, size=14, after=0)
    _p(doc, f"ปีการศึกษา {klass.year}", align="center", size=13, after=6)

    # ---- ประวัตินักเรียน ----
    info = doc.add_table(rows=2, cols=4); info.style = "Table Grid"
    iw = [Cm(3.0), Cm(6.0), Cm(3.0), Cm(4.0)]
    _cell(info.rows[0].cells[0], "ชื่อ-นามสกุล", bold=True, align="left", fill="F1F5F9")
    _cell(info.rows[0].cells[1], s.name, align="left")
    _cell(info.rows[0].cells[2], "เลขประจำตัว", bold=True, align="left", fill="F1F5F9")
    _cell(info.rows[0].cells[3], s.student_no or "-", align="left")
    _cell(info.rows[1].cells[0], "ชั้น", bold=True, align="left", fill="F1F5F9")
    _cell(info.rows[1].cells[1], _class_label(klass), align="left")
    _cell(info.rows[1].cells[2], "เลขที่", bold=True, align="left", fill="F1F5F9")
    _cell(info.rows[1].cells[3], s.seq or "-", align="left")
    _widths(info, iw)

    # ---- ผลการเรียนรายวิชา ----
    _p(doc, "", after=4)
    _p(doc, "ผลการเรียน", bold=True, size=14, after=2)
    subs = (db.query(AcadSubject).filter_by(year=klass.year, level=klass.level)
            .order_by(AcadSubject.seq, AcadSubject.code).all())
    my = {(x.subject_id, x.term): x for x in
          db.query(AcadScore).filter_by(acad_student_id=s.id).all()}

    if sec:
        heads = ["รหัสวิชา", "รายวิชา", "หน่วยกิต", "ภาค 1", "ภาค 2"]
        ws = [Cm(2.4), Cm(7.6), Cm(2.0), Cm(2.0), Cm(2.0)]
    else:
        heads = ["รหัสวิชา", "รายวิชา", "เวลาเรียน", "ผลการเรียน"]
        ws = [Cm(2.6), Cm(8.2), Cm(2.6), Cm(2.6)]
    t = doc.add_table(rows=1, cols=len(heads)); t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, fill="EDE9FE")

    # มัธยม: วิชาเดียวกันมี 2 แถว (ภาค 1/2) -> ยุบเป็นแถวเดียว 2 คอลัมน์
    seen = set()
    for sub in subs:
        key = (sub.code or "", sub.name)
        if sec and key in seen:
            continue
        seen.add(key)
        cells = t.add_row().cells
        _cell(cells[0], sub.code or "")
        _cell(cells[1], sub.name, align="left")
        if sec:
            _cell(cells[2], f"{sub.credit:g}" if sub.credit else "")
            for i, tm in enumerate(terms):
                sid_same = [x.id for x in subs if (x.code or "", x.name) == key and x.term == tm]
                g = ""
                for sid2 in sid_same:
                    row = my.get((sid2, tm))
                    if row and row.grade:
                        g = row.grade
                _cell(cells[3 + i], g, bold=True)
        else:
            _cell(cells[2], sub.hours or "")
            row = my.get((sub.id, 0))
            _cell(cells[3], row.grade if row else "", bold=True)
    _widths(t, ws)

    # ---- ผลการประเมินอื่น ----
    ev = s.eval
    _p(doc, "", after=4)
    _p(doc, "ผลการประเมิน", bold=True, size=14, after=2)
    rows = [("การอ่าน คิดวิเคราะห์ และเขียน", ev.read_think if ev else ""),
            ("คุณลักษณะอันพึงประสงค์", ev.desired_char if ev else ""),
            ("กิจกรรมแนะแนว", ev.act_guidance if ev else ""),
            ("กิจกรรมลูกเสือ/เนตรนารี", ev.act_scout if ev else ""),
            ("กิจกรรมชุมนุม", ev.act_club if ev else ""),
            ("กิจกรรมเพื่อสังคมและสาธารณประโยชน์", ev.act_social if ev else "")]
    t2 = doc.add_table(rows=0, cols=2); t2.style = "Table Grid"
    for lab, val in rows:
        cells = t2.add_row().cells
        _cell(cells[0], lab, align="left")
        _cell(cells[1], val or "-")
    _widths(t2, [Cm(11.0), Cm(5.0)])

    if ev and (ev.days_open or ev.days_present):
        _p(doc, "", after=2)
        _p(doc, f"เวลาเรียน: มาเรียน {ev.days_present or '-'} วัน จากทั้งหมด {ev.days_open or '-'} วัน",
           size=13, after=2)
    if ev and (ev.comment or "").strip():
        _p(doc, f"ความเห็นครูประจำชั้น: {ev.comment.strip()}", size=13, after=2)

    # ---- ลงนาม: ครูประจำชั้นตามจำนวนที่มีจริง + ผอ. ----
    _p(doc, "", after=8)
    homerooms = [p.name for p in (klass.homeroom, klass.co_homeroom) if p]
    if homerooms:
        st = doc.add_table(rows=1, cols=len(homerooms))
        for cell, nm in zip(st.rows[0].cells, homerooms):
            cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
            for i, txt in enumerate(["(ลงชื่อ).............................................",
                                     f"( {nm} )", "ครูประจำชั้น"]):
                p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after = Pt(0)
                r = p.add_run(txt); r.font.size = Pt(13); r.font.name = THAI_FONT
                r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
                if i == 0:
                    _float_signature(p, nm)
        _widths(st, [Cm(16.0 / len(homerooms))] * len(homerooms))
    _p(doc, "", after=6)
    director = (getattr(school, "director_name", "") or "").strip()
    dpos = ("ผู้อำนวยการ" + school.name) if (school.name or "").startswith("โรงเรียน") \
        else "ผู้อำนวยการโรงเรียน"
    _sign_block(doc, director, dpos)


def render_pp6(school, s, db) -> str:
    doc = _doc()
    _pp6_body(doc, school, s, db)
    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"ปพ.6_{s.name}_{s.klass.year}") + ".docx")
    doc.save(str(out))
    return str(out)


def render_pp6_class(school, klass, db) -> str:
    """สมุดพกทั้งห้อง รวมเป็นไฟล์เดียว (คนละหน้า)"""
    doc = _doc()
    students = sorted(klass.students, key=lambda s: (s.seq or 999, s.name))
    for i, s in enumerate(students):
        _pp6_body(doc, school, s, db, page_break=(i > 0))
    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"ปพ.6_ทั้งห้อง_{_class_label(klass)}_{klass.year}") + ".docx")
    doc.save(str(out))
    return str(out)
