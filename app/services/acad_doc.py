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
from app.services.academic import (term_label, CHAR_ITEMS, CHAR_FIELDS, READ_DOMAINS,
                                   TH_MONTHS, quality_of_avg, char_avg, read_avg,
                                   effective_eval)

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
def _pp5_score_page(doc, school, klass, subject, db, *, page_break: bool = False):
    """หน้าใบคะแนนของ 1 รายวิชา (ใช้ทั้งแบบแผ่นเดี่ยวและในเล่มรวม)"""
    from app.models import AcadScore, AcadTeaching
    students = sorted(klass.students, key=lambda s: (s.seq or 999, s.name))
    term = subject.term if subject.term is not None else 0
    scores = {s.acad_student_id: s for s in
              db.query(AcadScore).filter_by(subject_id=subject.id, term=term).all()}
    teach = db.query(AcadTeaching).filter_by(class_id=klass.id, subject_id=subject.id).first()
    teacher = teach.teacher.name if (teach and teach.teacher) else ""

    if page_break:
        doc.add_page_break()
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

    mmax = subject.mid_max if (subject.mid_max or 0) > 0 else 70
    fmax = subject.final_max if (subject.final_max or 0) > 0 else 30
    heads = ["เลขที่", "เลขประจำตัว", "ชื่อ-นามสกุล", f"คะแนนเก็บ (เต็ม {mmax})",
             f"คะแนนปลายภาค (เต็ม {fmax})", f"รวม (เต็ม {mmax + fmax})", "ผลการเรียน", "หมายเหตุ"]
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


def render_pp5(school, klass, subject, db) -> str:
    """แบบบันทึกผลการพัฒนาคุณภาพผู้เรียน — รายวิชา x ห้อง (แนวนอน แผ่นเดี่ยว)"""
    doc = _doc(landscape=True)
    _pp5_score_page(doc, school, klass, subject, db)
    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"ปพ.5_{subject.name}_{_class_label(klass)}_{klass.year}") + ".docx")
    doc.save(str(out))
    return str(out)


# ---------------- ปพ.5 ทั้งเล่ม ----------------
def _grade_counts(grades):
    """นับจำนวนคนต่อระดับผลการเรียน -> dict ตามคอลัมน์ปก"""
    cols = ["4", "3.5", "3", "2.5", "2", "1.5", "1", "0", "ร", "มส"]
    n = {c: 0 for c in cols}
    for g in grades:
        g = (str(g) if g is not None else "").strip()
        if g in n:
            n[g] += 1
    return n


def _pp5_assess_page(doc, klass, subject, db, students):
    """หน้า คุณลักษณะฯ 8 ข้อ + อ่านคิดเขียน 3 ด้าน ของ 1 รายวิชา (ต่อท้ายใบคะแนน)"""
    from app.models import AcadCharEval, AcadReadEval
    doc.add_page_break()
    _p(doc, "ผลการประเมินคุณลักษณะอันพึงประสงค์ และการอ่าน คิดวิเคราะห์ และเขียน (รายวิชา)",
       align="center", bold=True, size=16, after=0)
    _p(doc, f"รายวิชา {subject.code or ''} {subject.name}   ชั้น {_class_label(klass)}   "
            f"ปีการศึกษา {klass.year}", align="center", size=13, after=6)

    chars = {r.acad_student_id: r for r in
             db.query(AcadCharEval).filter_by(subject_id=subject.id).all()}
    heads = ["เลขที่", "ชื่อ-นามสกุล"] + [f"ข้อ {i}" for i in range(1, 9)] + ["เฉลี่ย", "ผล"]
    t = doc.add_table(rows=1, cols=len(heads)); t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, fill="EDE9FE", size=11)
    for s in students:
        r = chars.get(s.id)
        cells = t.add_row().cells
        _cell(cells[0], s.seq or "", size=11)
        _cell(cells[1], s.name, align="left", size=11)
        for j, f in enumerate(CHAR_FIELDS):
            v = getattr(r, f) if r else None
            _cell(cells[2 + j], v if v is not None else "", size=11)
        avg = char_avg(r) if r else None
        _cell(cells[10], f"{avg:.2f}" if avg is not None else "", size=11, bold=True)
        _cell(cells[11], quality_of_avg(avg)[1], size=11, bold=True)
    _widths(t, [Cm(1.2), Cm(5.6)] + [Cm(1.55)] * 8 + [Cm(1.6), Cm(2.4)])   # รวม 23.2
    _p(doc, "คุณลักษณะฯ: " + " · ".join(f"ข้อ {i} {nm}" for i, nm in enumerate(CHAR_ITEMS, 1)),
       size=10, after=8)

    reads = {r.acad_student_id: r for r in
             db.query(AcadReadEval).filter_by(subject_id=subject.id).all()}
    heads2 = ["เลขที่", "ชื่อ-นามสกุล"] + [lb for _, lb in READ_DOMAINS] + ["เฉลี่ย", "ผล"]
    t2 = doc.add_table(rows=1, cols=len(heads2)); t2.style = "Table Grid"
    for i, h in enumerate(heads2):
        _cell(t2.rows[0].cells[i], h, bold=True, fill="EDE9FE", size=11)
    for s in students:
        r = reads.get(s.id)
        cells = t2.add_row().cells
        _cell(cells[0], s.seq or "", size=11)
        _cell(cells[1], s.name, align="left", size=11)
        for j, (f, _lb) in enumerate(READ_DOMAINS):
            v = getattr(r, f) if r else None
            _cell(cells[2 + j], v if v is not None else "", size=11)
        avg = read_avg(r) if r else None
        _cell(cells[5], f"{avg:.2f}" if avg is not None else "", size=11, bold=True)
        _cell(cells[6], quality_of_avg(avg)[1], size=11, bold=True)
    _widths(t2, [Cm(1.2), Cm(5.6), Cm(3.4), Cm(3.4), Cm(3.4), Cm(1.6), Cm(2.4)])   # รวม 21.0
    _p(doc, "คะแนน 0-3 ต่อข้อ · เฉลี่ย ≥2.5 ดีเยี่ยม · 1.5-2.49 ดี · 1-1.49 ผ่าน · ต่ำกว่า 1 ไม่ผ่าน "
            "· ช่องว่าง = ยังไม่ประเมิน", size=10, after=0)


def _pp5_quality_summary(doc, klass, subjects, students, db, kind, title):
    """สรุปทั้งปี: นักเรียน x วิชา (ผลรายวิชาเป็นเลข 0-3) -> เฉลี่ย -> ผลสุดท้าย
    (ตามชีต 'พิมพ์สรุปคุณลักษณะทั้งปี' / 'พิมพ์สรุปอ่านคิดเขียนทั้งปี' ของไฟล์จริง)"""
    from app.models import AcadCharEval, AcadReadEval
    Model = AcadCharEval if kind == "char" else AcadReadEval
    avg_fn = char_avg if kind == "char" else read_avg
    doc.add_page_break()
    _p(doc, f"{title} ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}",
       align="center", bold=True, size=16, after=6)
    if not subjects:
        return
    rows_by = {}
    for r in (db.query(Model)
              .filter(Model.subject_id.in_([x.id for x in subjects])).all()):
        rows_by[(r.acad_student_id, r.subject_id)] = r
    sw = min(2.2, 15.5 / len(subjects))
    t = doc.add_table(rows=1, cols=2 + len(subjects) + 2); t.style = "Table Grid"
    _cell(t.rows[0].cells[0], "เลขที่", bold=True, fill="EDE9FE", size=11)
    _cell(t.rows[0].cells[1], "ชื่อ-นามสกุล", bold=True, fill="EDE9FE", size=11)
    for i, sub in enumerate(subjects):
        _cell(t.rows[0].cells[2 + i], sub.code or sub.name[:6], bold=True, fill="EDE9FE", size=10)
    _cell(t.rows[0].cells[-2], "เฉลี่ย", bold=True, fill="EDE9FE", size=11)
    _cell(t.rows[0].cells[-1], "ผล", bold=True, fill="EDE9FE", size=11)
    for s in students:
        cells = t.add_row().cells
        _cell(cells[0], s.seq or "", size=11)
        _cell(cells[1], s.name, align="left", size=11)
        nums = []
        for j, sub in enumerate(subjects):
            r = rows_by.get((s.id, sub.id))
            n = quality_of_avg(avg_fn(r))[0] if r else ""
            _cell(cells[2 + j], n if n != "" else "", size=11)
            if n != "":
                nums.append(n)
        avg = (sum(nums) / len(nums)) if nums else None
        _cell(cells[-2], f"{avg:.2f}" if avg is not None else "", size=11, bold=True)
        _cell(cells[-1], quality_of_avg(avg)[1], size=11, bold=True)
    _widths(t, [Cm(1.2), Cm(6.0)] + [Cm(sw)] * len(subjects) + [Cm(1.6), Cm(2.2)])
    _p(doc, "ตัวเลขในตาราง = ผลรายวิชา (3 ดีเยี่ยม · 2 ดี · 1 ผ่าน · 0 ไม่ผ่าน) · "
            "ผลสุดท้ายมาจากเฉลี่ยข้ามวิชาด้วยเกณฑ์เดียวกัน", size=10, after=0)


def render_pp5_book(school, klass, db, term: int | None = None) -> str:
    """ปพ.5 ทั้งเล่ม: ปก -> รายชื่อ -> สรุปเวลาเรียน -> คะแนนรายวิชา (วิชาละหน้า)
    -> สรุปผลทุกวิชา -> สรุปผลการประเมินทั้งปี · แนวนอนล้วน
    มัธยม: เล่มรายภาค (term 1/2) · ประถม: ทั้งปี (term 0)"""
    from app.models import AcadScore, AcadSubject
    from app.services.academic import weighted_avg, QUALITY_LEVELS

    sec = is_secondary(klass.level)
    t = (term if term in (1, 2) else 1) if sec else 0
    doc = _doc(landscape=True)
    students = sorted(klass.students, key=lambda s: (s.seq or 999, s.name))
    # ค่าที่ใช้จริงต่อคน (คำนวณจากรายวิชา/รายเดือนถ้ามี · ไม่มีก็ค่า manual) — จุดตัดสินใจเดียว
    effs = {s.id: effective_eval(s, db) for s in students}
    subjects = (db.query(AcadSubject).filter_by(year=klass.year, level=klass.level, term=t)
                .order_by(AcadSubject.seq, AcadSubject.code).all())
    sub_ids = [x.id for x in subjects]
    # เกรดทุกคน x ทุกวิชาของภาคนี้ (คิวรีเดียว)
    sc_map = {}
    if sub_ids:
        for row in db.query(AcadScore).filter(AcadScore.subject_id.in_(sub_ids),
                                              AcadScore.term == t).all():
            sc_map[(row.acad_student_id, row.subject_id)] = row
    term_txt = f"ภาคเรียนที่ {t}" if sec else "ตลอดปีการศึกษา"

    # ---------- หน้า 1: ปก ----------
    _p(doc, "", after=6)
    _p(doc, "สมุดบันทึกผลการพัฒนาคุณภาพผู้เรียน (ปพ.5)", align="center", bold=True, size=20, after=2)
    _p(doc, f"ชั้น {_class_label(klass)}   ปีการศึกษา {klass.year}" + (f"   {term_txt}" if sec else ""),
       align="center", bold=True, size=16, after=0)
    loc = [school.name or ""]
    if (school.district or "").strip():
        loc.append(f"อำเภอ{school.district.strip()}")
    if (school.province or "").strip():
        loc.append(f"จังหวัด{school.province.strip()}")
    _p(doc, "  ".join(loc), align="center", size=15, after=0)
    if (school.area_office or "").strip():
        _p(doc, f"สำนักงานเขตพื้นที่การศึกษา{school.area_office.strip()}", align="center", size=14, after=0)
    boys = sum(1 for s in students if s.sex == "M")
    girls = sum(1 for s in students if s.sex == "F")
    _p(doc, f"นักเรียนทั้งหมด {len(students)} คน  (ชาย {boys} · หญิง {girls})",
       align="center", size=14, after=8)

    # ตารางแจกแจงระดับผลการเรียนรายวิชา
    grade_cols = ["4", "3.5", "3", "2.5", "2", "1.5", "1", "0", "ร", "มส"]
    gt = doc.add_table(rows=2, cols=2 + len(grade_cols)); gt.style = "Table Grid"
    gt.rows[0].cells[0].merge(gt.rows[1].cells[0])
    gt.rows[0].cells[1].merge(gt.rows[1].cells[1])
    _cell(gt.rows[0].cells[0], "ที่", bold=True, fill="EDE9FE")
    _cell(gt.rows[0].cells[1], "รายวิชา", bold=True, fill="EDE9FE")
    top = gt.rows[0].cells[2]
    for c in gt.rows[0].cells[3:]:
        top = top.merge(c)
    _cell(top, "จำนวนนักเรียนแยกตามระดับผลการเรียน (คน)", bold=True, fill="EDE9FE")
    for i, g in enumerate(grade_cols):
        _cell(gt.rows[1].cells[2 + i], g, bold=True, fill="EDE9FE", size=12)
    for i, sub in enumerate(subjects, start=1):
        cells = gt.add_row().cells
        _cell(cells[0], i, size=12)
        _cell(cells[1], f"{sub.code or ''} {sub.name}".strip(), align="left", size=12)
        cnt = _grade_counts((sc_map.get((s.id, sub.id)).grade
                             if sc_map.get((s.id, sub.id)) else "") for s in students)
        for j, g in enumerate(grade_cols):
            _cell(cells[2 + j], cnt[g] or "", size=12)
    _widths(gt, [Cm(1.2), Cm(8.1)] + [Cm(1.74)] * len(grade_cols))

    # ตารางเล็ก: คุณลักษณะฯ + อ่านคิดฯ (ค่าที่ใช้จริง — คำนวณจากรายวิชาถ้ามี)
    _p(doc, "", after=6)
    qt = doc.add_table(rows=1, cols=1 + len(QUALITY_LEVELS)); qt.style = "Table Grid"
    _cell(qt.rows[0].cells[0], "ผลการประเมิน (คน)", bold=True, fill="EDE9FE")
    for i, q in enumerate(QUALITY_LEVELS):
        _cell(qt.rows[0].cells[1 + i], q, bold=True, fill="EDE9FE")
    for lab, key in [("คุณลักษณะอันพึงประสงค์", "desired_char"),
                     ("การอ่าน คิดวิเคราะห์ และเขียน", "read_think")]:
        cells = qt.add_row().cells
        _cell(cells[0], lab, align="left")
        for i, q in enumerate(QUALITY_LEVELS):
            n = sum(1 for s in students if effs[s.id][key] == q)
            _cell(cells[1 + i], n or "")
    _widths(qt, [Cm(10.0)] + [Cm(4.175)] * len(QUALITY_LEVELS))

    # ลงนาม: ครูประจำชั้น -> หัวหน้าฝ่ายวิชาการ -> ผอ. (อนุมัติ)
    _p(doc, "", after=10)
    homerooms = [p.name for p in (klass.homeroom, klass.co_homeroom) if p]
    if homerooms:
        st = doc.add_table(rows=1, cols=len(homerooms))
        for cell, nm in zip(st.rows[0].cells, homerooms):
            for i, txt in enumerate(["(ลงชื่อ).............................................",
                                     f"( {nm} )", "ครูประจำชั้น"]):
                p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                p.paragraph_format.space_after = Pt(0)
                r = p.add_run(txt); r.font.size = Pt(13); r.font.name = THAI_FONT
                r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
                if i == 0:
                    _float_signature(p, nm)
        _widths(st, [Cm(26.0 / len(homerooms))] * len(homerooms))
        _p(doc, "", after=6)
    head = (getattr(school, "academic_head_name", "") or "").strip()
    _sign_block(doc, head, "หัวหน้าฝ่ายวิชาการ", after=6)
    _p(doc, "ผลการตรวจสอบ    [   ] อนุมัติ        [   ] ไม่อนุมัติ", align="center", size=14, after=4)
    director = (getattr(school, "director_name", "") or "").strip()
    dpos = ("ผู้อำนวยการ" + school.name) if (school.name or "").startswith("โรงเรียน") \
        else "ผู้อำนวยการโรงเรียน"
    _sign_block(doc, director, dpos)
    _p(doc, "วันที่ ........ เดือน ......................... พ.ศ. ..........", align="center", size=13, after=0)

    # ---------- หน้า 2: รายชื่อนักเรียน ----------
    doc.add_page_break()
    _p(doc, f"รายชื่อนักเรียน ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}",
       align="center", bold=True, size=16, after=6)
    rt = doc.add_table(rows=1, cols=5); rt.style = "Table Grid"
    for i, h in enumerate(["เลขที่", "เลขประจำตัว", "ชื่อ-นามสกุล", "เพศ", "หมายเหตุ"]):
        _cell(rt.rows[0].cells[i], h, bold=True, fill="EDE9FE")
    for s in students:
        cells = rt.add_row().cells
        _cell(cells[0], s.seq or "")
        _cell(cells[1], s.student_no or "")
        _cell(cells[2], s.name, align="left")
        _cell(cells[3], {"M": "ชาย", "F": "หญิง"}.get(s.sex, ""))
        _cell(cells[4], "")
    _widths(rt, [Cm(2.0), Cm(3.2), Cm(11.0), Cm(2.5), Cm(5.0)])

    # ---------- หน้า 3: สรุปเวลาเรียน ----------
    doc.add_page_break()
    _p(doc, f"สรุปเวลาเรียน ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}",
       align="center", bold=True, size=16, after=6)
    monthly = any(effs[s.id]["months"] for s in students)
    if monthly:
        # แบบรายเดือน (ตามไฟล์ ปพ.5 จริง): เดือน พ.ค.-มี.ค. + รวม + ป่วย/ลา/ขาด + ร้อยละ
        from app.models import AcadClassMonth
        opens = {m.month: m.days_open for m in
                 db.query(AcadClassMonth).filter_by(class_id=klass.id).all()}
        heads = ["เลขที่", "ชื่อ-นามสกุล"] + [nm for _, nm in TH_MONTHS] + \
                ["รวม", "ป่วย", "ลา", "ขาด", "ร้อยละ", "ผล"]
        at = doc.add_table(rows=1, cols=len(heads)); at.style = "Table Grid"
        for i, h in enumerate(heads):
            _cell(at.rows[0].cells[i], h, bold=True, fill="EDE9FE", size=10)
        cells = at.add_row().cells      # แถววันเปิดเรียนของห้อง (ตัวหารร้อยละ)
        _cell(cells[0], "", size=10)
        _cell(cells[1], "วันเปิดเรียน", align="left", bold=True, size=10)
        tot_open = 0
        for j, (mnum, _nm) in enumerate(TH_MONTHS):
            v = opens.get(mnum)
            _cell(cells[2 + j], v if v is not None else "", bold=True, size=10)
            tot_open += v or 0
        _cell(cells[13], tot_open or "", bold=True, size=10)
        for k in range(14, 19):
            _cell(cells[k], "", size=10)
        for s in students:
            ef = effs[s.id]
            cells = at.add_row().cells
            _cell(cells[0], s.seq or "", size=10)
            _cell(cells[1], s.name, align="left", size=10)
            for j, (mnum, _nm) in enumerate(TH_MONTHS):
                v = ef["months"].get(mnum)
                _cell(cells[2 + j], v if v is not None else "", size=10)
            _cell(cells[13], ef["days_present"] if ef["days_present"] is not None else "",
                  bold=True, size=10)
            for k, key in ((14, "days_sick"), (15, "days_leave"), (16, "days_absent")):
                _cell(cells[k], ef[key] if ef[key] is not None else "", size=10)
            pct = None
            if (ef["days_open"] or 0) > 0 and ef["days_present"] is not None:
                pct = ef["days_present"] * 100.0 / ef["days_open"]
            _cell(cells[17], f"{pct:.1f}" if pct is not None else "", size=10)
            _cell(cells[18], ("ผ่าน" if pct >= 80 else "ไม่ผ่าน") if pct is not None else "",
                  bold=True, size=10)
        _widths(at, [Cm(1.0), Cm(4.65)] + [Cm(1.25)] * 11 +
                [Cm(1.3), Cm(1.1), Cm(1.1), Cm(1.1), Cm(1.35), Cm(1.35)])   # รวม 26.7
    else:
        # แบบยอดรวมทั้งปี (โรงเรียนที่ไม่กรอกรายเดือน)
        at = doc.add_table(rows=1, cols=10); at.style = "Table Grid"
        for i, h in enumerate(["เลขที่", "เลขประจำตัว", "ชื่อ-นามสกุล", "วันเปิดเรียน", "มาเรียน",
                               "ป่วย", "ลา", "ขาด", "ร้อยละ", "ผล"]):
            _cell(at.rows[0].cells[i], h, bold=True, fill="EDE9FE")
        for s in students:
            ef = effs[s.id]
            cells = at.add_row().cells
            _cell(cells[0], s.seq or "")
            _cell(cells[1], s.student_no or "")
            _cell(cells[2], s.name, align="left")
            vals = [ef["days_open"], ef["days_present"],
                    ef["days_sick"], ef["days_leave"], ef["days_absent"]]
            for j, v in enumerate(vals):
                _cell(cells[3 + j], v if v is not None else "")
            pct = None
            if (ef["days_open"] or 0) > 0 and ef["days_present"] is not None:
                pct = ef["days_present"] * 100.0 / ef["days_open"]
            _cell(cells[8], f"{pct:.1f}" if pct is not None else "")
            _cell(cells[9], ("ผ่าน" if pct >= 80 else "ไม่ผ่าน") if pct is not None else "", bold=True)
        _widths(at, [Cm(1.6), Cm(2.6), Cm(8.0), Cm(2.4), Cm(2.4),
                     Cm(2.0), Cm(2.0), Cm(2.0), Cm(2.0), Cm(1.7)])
    _p(doc, "เกณฑ์การผ่าน: มีเวลาเรียนไม่น้อยกว่าร้อยละ 80 ของเวลาเรียนทั้งหมด", size=12, after=0)

    # ---------- คะแนนรายวิชา + ประเมินรายวิชา (วิชาละ 2 หน้า) ----------
    for sub in subjects:
        _pp5_score_page(doc, school, klass, sub, db, page_break=True)
        _pp5_assess_page(doc, klass, sub, db, students)

    # ---------- สรุปผลการเรียนทุกวิชา ----------
    doc.add_page_break()
    _p(doc, f"สรุปผลการเรียนทุกรายวิชา ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}"
       + (f" {term_txt}" if sec else ""), align="center", bold=True, size=16, after=6)
    if subjects:
        sw = min(2.6, 17.5 / len(subjects))
        mt = doc.add_table(rows=1, cols=2 + len(subjects) + 1); mt.style = "Table Grid"
        _cell(mt.rows[0].cells[0], "เลขที่", bold=True, fill="EDE9FE", size=11)
        _cell(mt.rows[0].cells[1], "ชื่อ-นามสกุล", bold=True, fill="EDE9FE", size=11)
        for i, sub in enumerate(subjects):
            _cell(mt.rows[0].cells[2 + i], sub.code or sub.name[:6], bold=True, fill="EDE9FE", size=10)
        _cell(mt.rows[0].cells[-1], "เฉลี่ย", bold=True, fill="EDE9FE", size=11)
        for s in students:
            cells = mt.add_row().cells
            _cell(cells[0], s.seq or "", size=11)
            _cell(cells[1], s.name, align="left", size=11)
            pairs = []
            for i, sub in enumerate(subjects):
                row = sc_map.get((s.id, sub.id))
                g = row.grade if row else ""
                _cell(cells[2 + i], g or "", size=11, bold=True)
                pairs.append((g, sub.credit if sec else sub.hours))
            avg = weighted_avg(pairs)
            _cell(cells[-1], f"{avg:.2f}" if avg is not None else "", bold=True, size=11)
        _widths(mt, [Cm(1.2), Cm(6.0)] + [Cm(sw)] * len(subjects) + [Cm(1.8)])
        _p(doc, "เฉลี่ยถ่วงน้ำหนักด้วย" + ("หน่วยกิต" if sec else "เวลาเรียน")
           + " · ร/มส/ผ/มผ ไม่นำมาคิดเฉลี่ย", size=12, after=0)

    # ---------- สรุปคุณลักษณะฯ / อ่านคิดเขียน ทุกวิชา ----------
    _pp5_quality_summary(doc, klass, subjects, students, db, "char",
                         "สรุปผลการประเมินคุณลักษณะอันพึงประสงค์ทุกรายวิชา")
    _pp5_quality_summary(doc, klass, subjects, students, db, "read",
                         "สรุปผลการประเมินการอ่าน คิดวิเคราะห์ และเขียนทุกรายวิชา")

    # ---------- สรุปผลการประเมินทั้งปี ----------
    doc.add_page_break()
    _p(doc, f"สรุปผลการประเมิน ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}"
       + (f" {term_txt}" if sec else ""), align="center", bold=True, size=16, after=6)
    ft = doc.add_table(rows=1, cols=10); ft.style = "Table Grid"
    for i, h in enumerate(["เลขที่", "ชื่อ-นามสกุล", "ผลการเรียนเฉลี่ย", "คุณลักษณะฯ",
                           "อ่านคิดวิเคราะห์", "แนะแนว", "ลูกเสือ", "ชุมนุม", "เพื่อสังคม", "สรุป"]):
        _cell(ft.rows[0].cells[i], h, bold=True, fill="EDE9FE", size=12)
    for s in students:
        e = s.eval
        cells = ft.add_row().cells
        _cell(cells[0], s.seq or "")
        _cell(cells[1], s.name, align="left")
        pairs, grades = [], []
        for sub in subjects:
            row = sc_map.get((s.id, sub.id))
            g = row.grade if row else ""
            grades.append(g)
            pairs.append((g, sub.credit if sec else sub.hours))
        avg = weighted_avg(pairs)
        ef = effs[s.id]
        _cell(cells[2], f"{avg:.2f}" if avg is not None else "", bold=True)
        _cell(cells[3], ef["desired_char"])
        _cell(cells[4], ef["read_think"])
        acts = [e.act_guidance if e else "", e.act_scout if e else "",
                e.act_club if e else "", e.act_social if e else ""]
        for j, a in enumerate(acts):
            _cell(cells[5 + j], a or "")
        # สรุป ผ/มผ: ครบทุกวิชา + ไม่มี 0/ร/มส + กิจกรรมทุกตัว ผ + คุณฯ/อ่านฯ ไม่เป็น "ไม่ผ่าน"
        # ข้อมูลไม่ครบ = เว้นว่าง (ไม่เดา)
        overall = ""
        if subjects and all((g or "").strip() for g in grades) and e:
            bad_grade = any((g or "").strip() in ("0", "ร", "มส") for g in grades)
            bad_act = any((a or "").strip() != "ผ" for a in acts)
            bad_qual = "ไม่ผ่าน" in (ef["desired_char"], ef["read_think"])
            no_qual = not ef["desired_char"].strip() or not ef["read_think"].strip()
            if not no_qual and not any((a or "") == "" for a in acts):
                overall = "มผ" if (bad_grade or bad_act or bad_qual) else "ผ"
        _cell(cells[9], overall, bold=True)
    _widths(ft, [Cm(1.4), Cm(5.6), Cm(2.7), Cm(2.9), Cm(2.9),
                 Cm(2.2), Cm(2.2), Cm(2.2), Cm(2.4), Cm(2.2)])
    _p(doc, "สรุป ผ = ผลการเรียนครบทุกวิชาไม่มี 0/ร/มส · กิจกรรมผ่านทุกกิจกรรม · "
            "คุณลักษณะฯ และอ่านคิดวิเคราะห์ฯ ไม่ต่ำกว่าระดับผ่าน (ข้อมูลไม่ครบ = เว้นว่าง)",
       size=12, after=0)

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    suffix = f"_ภาค{t}" if sec else ""
    out = out_dir / (_safe(f"ปพ.5_ทั้งเล่ม_{_class_label(klass)}_{klass.year}{suffix}") + ".docx")
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
    ef = effective_eval(s, db)     # ใช้ค่าคำนวณจากรายวิชา/รายเดือนถ้ามี
    _p(doc, "", after=4)
    _p(doc, "ผลการประเมิน", bold=True, size=14, after=2)
    rows = [("การอ่าน คิดวิเคราะห์ และเขียน", ef["read_think"]),
            ("คุณลักษณะอันพึงประสงค์", ef["desired_char"]),
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

    if ef["days_open"] or ef["days_present"]:
        _p(doc, "", after=2)
        _p(doc, f"เวลาเรียน: มาเรียน {ef['days_present'] if ef['days_present'] is not None else '-'} วัน "
                f"จากทั้งหมด {ef['days_open'] if ef['days_open'] is not None else '-'} วัน",
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
