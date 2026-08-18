# -*- coding: utf-8 -*-
"""
acad_doc.py - เอกสารงานวิชาการ
- ปพ.5 : แบบบันทึกผลการพัฒนาคุณภาพผู้เรียน (รายวิชา x ห้อง) - แนวนอน
- ปพ.6 : แบบรายงานผลการพัฒนาคุณภาพผู้เรียนรายบุคคล (สมุดพก) - รายคน / ทั้งห้อง

ความกว้างตารางต้องไม่เกินพื้นที่พิมพ์ A4: แนวตั้ง 16.0 / แนวนอน 26.7 ซม.
(บทเรียนจากรอบไล่แก้ A4 - python-docx ไม่บีบให้เอง)
"""
from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.section import WD_ORIENT
from docx.oxml.ns import qn

from app.services.doc_page import set_a4
from app.services.office_doc import _float_signature

from app.database import get_data_dir
from app.thai_utils import thai_date, is_secondary, be_date_input
from app.services.academic import (term_label, CHAR_ITEMS, CHAR_FIELDS, READ_DOMAINS,
                                   TH_MONTHS, quality_of_avg, char_avg, read_avg,
                                   effective_eval, weighted_avg, activities_for,
                                   activity_summary, onet_for, is_exit_level, ONET_SUBJECTS,
                                   count_marks)

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


def _p(doc, text="", *, align="left", bold=False, size=14, after=2, page_break=False):
    p = doc.add_paragraph()
    # ขึ้นหน้าใหม่โดยติดที่ย่อหน้านี้เอง (ไม่ใช่ add_page_break ที่สร้างย่อหน้าเปล่า
    # ทับกับตารางที่เต็มหน้าพอดี -> เกิดหน้าว่างคั่น)
    if page_break:
        p.paragraph_format.page_break_before = True
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
    _center(table)


def _center(table):
    """จัดตารางให้อยู่กึ่งกลางหน้ากระดาษ (python-docx ชิดซ้ายเป็นค่าปริยาย)"""
    from docx.enum.table import WD_TABLE_ALIGNMENT
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False


def _new_section(doc, *, landscape: bool):
    """ขึ้น section ใหม่พร้อมตั้งแนวกระดาษเอง
    (ห้ามเรียก set_a4 ซ้ำ เพราะมันบังคับ *ทุก* section ให้เป็นแนวเดียวกัน
     - เอกสารนี้ต้องผสม ปกแนวตั้ง + เนื้อในแนวนอน)"""
    from docx.enum.section import WD_SECTION
    from app.services.doc_page import A4_W, A4_H
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    if landscape:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = A4_H, A4_W
    else:
        sec.orientation = WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = A4_W, A4_H
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin = Cm(1.5); sec.bottom_margin = Cm(1.2)
    return sec


def _class_label(c) -> str:
    return f"{c.level}/{c.room}" if (c.room or "").strip() else (c.level or "")


def _sign_block(doc, name, role, *, after=0):
    """บล็อกลงนาม + วางลายเซ็นลอยทับถ้าผู้ลงนามอัปโหลดไว้"""
    p = _p(doc, "(ลงชื่อ).............................................", align="center", after=0)
    if name:
        _float_signature(p, name)
    _p(doc, f"( {name or '.......................................'} )", align="center", after=0)
    _p(doc, role, align="center", after=after)


def _logo_header(doc, school, *, page_break=False, height_cm=2.0, after=2):
    """แทรกโลโก้/ตราโรงเรียนกึ่งกลางหัวเอกสาร (ถ้าตั้งค่าไว้) · คืน True ถ้าใส่สำเร็จ
    รับ page_break มาแปะที่ย่อหน้าโลโก้ เพื่อให้ตัวเรียกไม่ต้องขึ้นหน้าซ้ำ"""
    import io
    logo = getattr(school, "logo", None)
    if not logo:
        return False
    p = doc.add_paragraph()
    if page_break:
        p.paragraph_format.page_break_before = True
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(after)
    try:
        p.add_run().add_picture(io.BytesIO(logo), height=Cm(height_cm))
    except Exception:      # ไฟล์เสีย/ฟอร์แมตไม่รองรับ - ข้ามโลโก้ ไม่ให้ล้มทั้งเอกสาร
        p._element.getparent().remove(p._element)
        return False
    return True


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

    added = _logo_header(doc, school, page_break=page_break, height_cm=1.7)
    _p(doc, "แบบบันทึกผลการพัฒนาคุณภาพผู้เรียน (ปพ.5)", align="center", bold=True, size=18, after=0,
       page_break=(page_break and not added))
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
        _p(doc, "  |  ".join(meta), align="center", size=13, after=8)

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
    """แบบบันทึกผลการพัฒนาคุณภาพผู้เรียน - รายวิชา x ห้อง (แนวนอน แผ่นเดี่ยว)"""
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


def _pp5_char_page(doc, klass, subject, db, students):
    """หน้าประเมินคุณลักษณะอันพึงประสงค์ 8 ข้อ ของ 1 รายวิชา"""
    from app.models import AcadCharEval
    _p(doc, "ผลการประเมินคุณลักษณะอันพึงประสงค์ (รายวิชา)",
       align="center", bold=True, size=16, after=0, page_break=True)
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
    _p(doc, "คุณลักษณะฯ: " + " | ".join(f"ข้อ {i} {nm}" for i, nm in enumerate(CHAR_ITEMS, 1)),
       size=10, after=2, align="center")
    _p(doc, "คะแนน 0-3 ต่อข้อ | เฉลี่ย ≥2.5 ดีเยี่ยม | 1.5-2.49 ดี | 1-1.49 ผ่าน | ต่ำกว่า 1 ไม่ผ่าน "
            "| ช่องว่าง = ยังไม่ประเมิน", size=10, after=0, align="center")


def _pp5_read_page(doc, klass, subject, db, students):
    """หน้าประเมินการอ่าน คิดวิเคราะห์ และเขียน 3 ด้าน ของ 1 รายวิชา"""
    from app.models import AcadReadEval
    _p(doc, "ผลการประเมินการอ่าน คิดวิเคราะห์ และเขียน (รายวิชา)",
       align="center", bold=True, size=16, after=0, page_break=True)
    _p(doc, f"รายวิชา {subject.code or ''} {subject.name}   ชั้น {_class_label(klass)}   "
            f"ปีการศึกษา {klass.year}", align="center", size=13, after=6)

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
    _p(doc, "การอ่าน คิดวิเคราะห์ และเขียน: " + " | ".join(lb for _, lb in READ_DOMAINS),
       size=10, after=2, align="center")
    _p(doc, "คะแนน 0-3 ต่อด้าน | เฉลี่ย ≥2.5 ดีเยี่ยม | 1.5-2.49 ดี | 1-1.49 ผ่าน | ต่ำกว่า 1 ไม่ผ่าน "
            "| ช่องว่าง = ยังไม่ประเมิน", size=10, after=0, align="center")


def _pp5_quality_summary(doc, klass, subjects, students, db, kind, title):
    """สรุปทั้งปี: นักเรียน x วิชา (ผลรายวิชาเป็นเลข 0-3) -> เฉลี่ย -> ผลสุดท้าย
    (ตามชีต 'พิมพ์สรุปคุณลักษณะทั้งปี' / 'พิมพ์สรุปอ่านคิดเขียนทั้งปี' ของไฟล์จริง)"""
    from app.models import AcadCharEval, AcadReadEval
    Model = AcadCharEval if kind == "char" else AcadReadEval
    avg_fn = char_avg if kind == "char" else read_avg
    _p(doc, f"{title} ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}",
       align="center", bold=True, size=16, after=6, page_break=True)
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
    _p(doc, "ตัวเลขในตาราง = ผลรายวิชา (3 ดีเยี่ยม | 2 ดี | 1 ผ่าน | 0 ไม่ผ่าน) | "
            "ผลสุดท้ายมาจากเฉลี่ยข้ามวิชาด้วยเกณฑ์เดียวกัน", size=10, after=0, align="center")


def render_pp5_book(school, klass, db, term: int | None = None) -> str:
    """ปพ.5 ทั้งเล่ม: ปก (แนวตั้ง · ลายเซ็นครบทุกคนอยู่หน้าแรก)
    -> รายชื่อ -> สรุปเวลาเรียน -> คะแนนรายวิชา (วิชาละหน้า)
    -> สรุปผลทุกวิชา -> สรุปผลการประเมินทั้งปี  (ส่วนนี้แนวนอน)
    มัธยม: เล่มรายภาค (term 1/2) · ประถม: ทั้งปี (term 0)"""
    from app.models import AcadScore, AcadSubject
    from app.services.academic import weighted_avg, QUALITY_LEVELS

    sec = is_secondary(klass.level)
    t = (term if term in (1, 2) else 1) if sec else 0
    doc = _doc()                      # ปกเป็นแนวตั้ง แล้วค่อยสลับเป็นแนวนอนหลังปก
    students = sorted(klass.students, key=lambda s: (s.seq or 999, s.name))
    # ค่าที่ใช้จริงต่อคน (คำนวณจากรายวิชา/รายเดือนถ้ามี · ไม่มีก็ค่า manual) - จุดตัดสินใจเดียว
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

    # ---------- หน้า 1: ปก (แนวตั้ง · พื้นที่พิมพ์ 18.0 ซม.) ----------
    _p(doc, "สมุดบันทึกผลการพัฒนาคุณภาพผู้เรียน (ปพ.5)", align="center", bold=True, size=19, after=2)
    _p(doc, f"ชั้น {_class_label(klass)}   ปีการศึกษา {klass.year}" + (f"   {term_txt}" if sec else ""),
       align="center", bold=True, size=15, after=0)
    loc = [school.name or ""]
    if (school.district or "").strip():
        loc.append(f"อำเภอ{school.district.strip()}")
    if (school.province or "").strip():
        loc.append(f"จังหวัด{school.province.strip()}")
    _p(doc, "  ".join(loc), align="center", size=14, after=0)
    if (school.area_office or "").strip():
        _p(doc, f"สำนักงานเขตพื้นที่การศึกษา{school.area_office.strip()}", align="center", size=13, after=0)
    boys = sum(1 for s in students if s.sex == "M")
    girls = sum(1 for s in students if s.sex == "F")
    _p(doc, f"นักเรียนทั้งหมด {len(students)} คน  (ชาย {boys} | หญิง {girls})",
       align="center", size=13, after=6)

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
    _cell(top, "จำนวนนักเรียนแยกตามระดับผลการเรียน (คน)", bold=True, fill="EDE9FE", size=11)
    for i, g in enumerate(grade_cols):
        _cell(gt.rows[1].cells[2 + i], g, bold=True, fill="EDE9FE", size=10)
    for i, sub in enumerate(subjects, start=1):
        cells = gt.add_row().cells
        _cell(cells[0], i, size=11)
        _cell(cells[1], f"{sub.code or ''} {sub.name}".strip(), align="left", size=11)
        cnt = _grade_counts((sc_map.get((s.id, sub.id)).grade
                             if sc_map.get((s.id, sub.id)) else "") for s in students)
        for j, g in enumerate(grade_cols):
            _cell(cells[2 + j], cnt[g] or "", size=11)
    # แนวตั้ง: 1.0 + 6.0 + 10x1.1 = 18.0 ซม. พอดีพื้นที่พิมพ์
    _widths(gt, [Cm(1.0), Cm(6.0)] + [Cm(1.1)] * len(grade_cols))

    # ตารางเล็ก: คุณลักษณะฯ + อ่านคิดฯ (ค่าที่ใช้จริง - คำนวณจากรายวิชาถ้ามี)
    _p(doc, "", after=4)
    qt = doc.add_table(rows=1, cols=1 + len(QUALITY_LEVELS)); qt.style = "Table Grid"
    _cell(qt.rows[0].cells[0], "ผลการประเมิน (คน)", bold=True, fill="EDE9FE", size=11)
    for i, q in enumerate(QUALITY_LEVELS):
        _cell(qt.rows[0].cells[1 + i], q, bold=True, fill="EDE9FE", size=11)
    for lab, key in [("คุณลักษณะอันพึงประสงค์", "desired_char"),
                     ("การอ่าน คิดวิเคราะห์ และเขียน", "read_think")]:
        cells = qt.add_row().cells
        _cell(cells[0], lab, align="left", size=11)
        for i, q in enumerate(QUALITY_LEVELS):
            n = sum(1 for s in students if effs[s.id][key] == q)
            _cell(cells[1 + i], n or "", size=11)
    _widths(qt, [Cm(7.2)] + [Cm(2.7)] * len(QUALITY_LEVELS))     # รวม 18.0

    # ---------- ลายเซ็นทุกคนต้องอยู่หน้าปก ----------
    # จัดเป็นตาราง 3 คอลัมน์ ครูประจำชั้น(1-2) + หัวหน้าฝ่ายวิชาการ ในแถวเดียว
    # แล้ว ผอ. อยู่ตรงกลางด้านล่าง - กินพื้นที่แนวตั้งน้อยกว่าเรียงลงมาทีละบล็อก
    _p(doc, "", after=8)
    head = (getattr(school, "academic_head_name", "") or "").strip()
    signers = [(p.name, "ครูประจำชั้น") for p in (klass.homeroom, klass.co_homeroom) if p]
    signers.append((head, "หัวหน้าฝ่ายวิชาการ"))
    st = doc.add_table(rows=1, cols=len(signers))
    for cell, (nm, role) in zip(st.rows[0].cells, signers):
        for i, txt in enumerate(["(ลงชื่อ)......................................",
                                 f"( {nm or '.....................................'} )", role]):
            p = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.paragraph_format.space_after = Pt(0)
            r = p.add_run(txt); r.font.size = Pt(12.5); r.font.name = THAI_FONT
            r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
            if i == 0 and nm:
                _float_signature(p, nm)
    _widths(st, [Cm(18.0 / len(signers))] * len(signers))

    _p(doc, "", after=8)
    _p(doc, "ผลการตรวจสอบ    [   ] อนุมัติ        [   ] ไม่อนุมัติ", align="center", size=13, after=6)
    director = (getattr(school, "director_name", "") or "").strip()
    dpos = ("ผู้อำนวยการ" + school.name) if (school.name or "").startswith("โรงเรียน") \
        else "ผู้อำนวยการโรงเรียน"
    _sign_block(doc, director, dpos)
    _p(doc, "วันที่ ........ เดือน ......................... พ.ศ. ..........", align="center", size=12.5, after=0)

    # ---------- หน้า 2 เป็นต้นไป: สลับเป็นแนวนอน ----------
    _new_section(doc, landscape=True)
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
    _p(doc, f"สรุปเวลาเรียน ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}",
       align="center", bold=True, size=16, after=6, page_break=True)
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
        _pp5_char_page(doc, klass, sub, db, students)
        _pp5_read_page(doc, klass, sub, db, students)

    # ---------- สรุปผลการเรียนทุกวิชา ----------
    _p(doc, f"สรุปผลการเรียนทุกรายวิชา ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}"
       + (f" {term_txt}" if sec else ""), align="center", bold=True, size=16, after=6, page_break=True)
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
           + " | ร/มส/ผ/มผ ไม่นำมาคิดเฉลี่ย", size=12, after=0, align="center")

    # ---------- สรุปคุณลักษณะฯ / อ่านคิดเขียน ทุกวิชา ----------
    _pp5_quality_summary(doc, klass, subjects, students, db, "char",
                         "สรุปผลการประเมินคุณลักษณะอันพึงประสงค์ทุกรายวิชา")
    _pp5_quality_summary(doc, klass, subjects, students, db, "read",
                         "สรุปผลการประเมินการอ่าน คิดวิเคราะห์ และเขียนทุกรายวิชา")

    # ---------- สรุปผลการประเมินทั้งปี ----------
    _p(doc, f"สรุปผลการประเมิน ชั้น {_class_label(klass)} ปีการศึกษา {klass.year}"
       + (f" {term_txt}" if sec else ""), align="center", bold=True, size=16, after=6, page_break=True)
    from app.models import AcadActivityResult
    from app.services.academic import activities_for, activity_summary
    acts = activities_for(klass.year, klass.level, db)
    ares = {}
    if acts and students:
        for r in (db.query(AcadActivityResult)
                  .filter(AcadActivityResult.acad_student_id.in_([s.id for s in students])).all()):
            ares[(r.acad_student_id, r.activity_id)] = (r.result or "").strip()
    heads = ["เลขที่", "ชื่อ-นามสกุล", "ผลการเรียนเฉลี่ย", "คุณลักษณะฯ", "อ่านคิดวิเคราะห์"]
    heads += [a.name for a in acts] + ["สรุป"]
    ft = doc.add_table(rows=1, cols=len(heads)); ft.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(ft.rows[0].cells[i], h, bold=True, fill="EDE9FE", size=11)
    for s in students:
        cells = ft.add_row().cells
        _cell(cells[0], s.seq or "", size=11)
        _cell(cells[1], s.name, align="left", size=11)
        pairs, grades = [], []
        for sub in subjects:
            row = sc_map.get((s.id, sub.id))
            g = row.grade if row else ""
            grades.append(g)
            pairs.append((g, sub.credit if sec else sub.hours))
        avg = weighted_avg(pairs)
        ef = effs[s.id]
        _cell(cells[2], f"{avg:.2f}" if avg is not None else "", bold=True, size=11)
        _cell(cells[3], ef["desired_char"], size=11)
        _cell(cells[4], ef["read_think"], size=11)
        act_vals = [ares.get((s.id, a.id), "") for a in acts]
        for j, av in enumerate(act_vals):
            _cell(cells[5 + j], av, size=11)
        # สรุป ผ/มผ: ครบทุกวิชา + ไม่มี 0/ร/มส + กิจกรรมผ่านครบ + คุณฯ/อ่านฯ ไม่เป็น "ไม่ผ่าน"
        # ข้อมูลไม่ครบ = เว้นว่าง (ไม่เดา) · ใช้ activity_summary เป็นตัวตัดสินฝั่งกิจกรรม
        overall = ""
        asum = activity_summary(s, db) if acts else "ผ"    # ไม่มีกิจกรรม = ไม่กันด้วยกิจกรรม
        if subjects and all((g or "").strip() for g in grades):
            bad_grade = any((g or "").strip() in ("0", "ร", "มส") for g in grades)
            bad_qual = "ไม่ผ่าน" in (ef["desired_char"], ef["read_think"])
            no_qual = not ef["desired_char"].strip() or not ef["read_think"].strip()
            act_ok = (asum != "")          # ประเมินกิจกรรมครบแล้ว
            if not no_qual and act_ok:
                overall = "มผ" if (bad_grade or bad_qual or asum == "มผ") else "ผ"
        _cell(cells[-1], overall, bold=True, size=11)
    # ความกว้าง: fixed 16.5 + กิจกรรม N ช่อง ต้องรวม ≤26.7 → per-act = min(2.6, 10.2/N)
    per = min(2.6, 10.2 / len(acts)) if acts else 2.6
    _widths(ft, [Cm(1.4), Cm(5.6), Cm(2.5), Cm(2.5), Cm(2.5)]
            + [Cm(per)] * len(acts) + [Cm(2.0)])
    _p(doc, "สรุป ผ = ผลการเรียนครบทุกวิชาไม่มี 0/ร/มส | กิจกรรมพัฒนาผู้เรียนผ่านครบ | "
            "คุณลักษณะฯ และอ่านคิดวิเคราะห์ฯ ไม่ต่ำกว่าระดับผ่าน (ข้อมูลไม่ครบ = เว้นว่าง)",
       size=12, after=0, align="center")

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    suffix = f"_ภาค{t}" if sec else ""
    out = out_dir / (_safe(f"ปพ.5_ทั้งเล่ม_{_class_label(klass)}_{klass.year}{suffix}") + ".docx")
    doc.save(str(out))
    return str(out)


# ============================ ปพ.6 ============================
_DOTS = "................................................................................................"


def _pp6_central(s, db):
    """คืนทะเบียนกลาง (Student) ของ AcadStudent - None ถ้าเพิ่มมือ (ไม่ได้ดึงจากทะเบียน)"""
    from app.models import Student
    return db.get(Student, s.student_id) if s.student_id else None


def _pp6_cover(doc, school, s, db, *, page_break):
    """หน้า 1 : ปกสมุดรายงานประจำตัวนักเรียน"""
    klass = s.klass
    added = _logo_header(doc, school, page_break=page_break, height_cm=3.0, after=6)
    _p(doc, "", after=0, page_break=(page_break and not added))
    if not added:
        _p(doc, "", after=0)
    _p(doc, "สมุดรายงานประจำตัวนักเรียน", align="center", bold=True, size=26, after=6)
    _p(doc, "แบบรายงานผลการพัฒนาคุณภาพผู้เรียนรายบุคคล (ปพ.6)", align="center", bold=True, size=16, after=2)
    _p(doc, f"ปีการศึกษา {klass.year}", align="center", size=15, after=18)
    _p(doc, school.name or "", align="center", bold=True, size=17, after=2)
    loc = []
    if getattr(school, "district", ""):
        loc.append(f"อำเภอ{school.district}")
    if getattr(school, "province", ""):
        loc.append(f"จังหวัด{school.province}")
    if loc:
        _p(doc, "  ".join(loc), align="center", size=14, after=2)
    if getattr(school, "area_office", ""):
        _p(doc, school.area_office, align="center", size=14, after=24)
    else:
        _p(doc, "", after=24)
    _p(doc, f"เลขที่ {s.seq or '.....'}", align="center", size=15, after=4)
    _p(doc, f"ชื่อ  {s.name}", align="center", bold=True, size=18, after=4)
    _p(doc, f"เลขประจำตัวนักเรียน  {s.student_no or '................'}", align="center", size=14, after=4)
    _p(doc, f"ชั้น  {_class_label(klass)}", align="center", size=15, after=24)
    homerooms = [p.name for p in (klass.homeroom, klass.co_homeroom) if p]
    _p(doc, "ครูประจำชั้น", align="center", size=14, after=2)
    if homerooms:
        for nm in homerooms:
            _p(doc, nm, align="center", bold=True, size=15, after=2)
    else:
        _p(doc, ".............................................", align="center", size=14, after=2)


def _fmt_addr(st) -> str:
    """เรียงที่อยู่จากฟิลด์แยกเป็นบรรทัดเดียว"""
    parts = []
    if st.addr_no:
        parts.append(f"บ้านเลขที่ {st.addr_no}")
    if st.addr_moo:
        parts.append(f"หมู่ {st.addr_moo}")
    if st.addr_soi:
        parts.append(f"ซอย{st.addr_soi}")
    if st.addr_road:
        parts.append(f"ถนน{st.addr_road}")
    if st.addr_tambon:
        parts.append(f"ตำบล{st.addr_tambon}")
    if st.addr_amphoe:
        parts.append(f"อำเภอ{st.addr_amphoe}")
    if st.addr_province:
        parts.append(f"จังหวัด{st.addr_province}")
    if st.addr_zip:
        parts.append(st.addr_zip)
    return " ".join(parts)


def _pp6_personal(doc, school, s, db):
    """หน้า 2 : ข้อมูลส่วนตัว (จากทะเบียนนักเรียนกลาง)"""
    st = _pp6_central(s, db)
    _p(doc, "ข้อมูลส่วนตัว", align="center", bold=True, size=17, after=6, page_break=True)

    def g(attr):
        return (getattr(st, attr, "") or "") if st else ""

    rows = [
        ("ชื่อ-นามสกุล", s.name),
        ("เลขประจำตัวนักเรียน", s.student_no or ""),
        ("เลขประจำตัวประชาชน", g("id_card")),
        ("วันเกิด", thai_date(st.birthdate) if (st and st.birthdate) else ""),
        ("เชื้อชาติ / สัญชาติ / ศาสนา",
         " / ".join(x for x in [g("race"), g("nationality"), g("religion")] if x)),
        ("หมู่เลือด", g("blood_group")),
        ("โรคประจำตัว", g("congenital_disease")),
        ("ที่อยู่", _fmt_addr(st) if st else ""),
        ("โทรศัพท์", g("phone")),
        ("ชื่อบิดา", g("father_name")),
        ("ชื่อมารดา", g("mother_name")),
        ("โรงเรียนเดิม", g("prev_school")),
        ("วันเข้าเรียน", thai_date(st.enroll_date) if (st and st.enroll_date) else ""),
    ]
    t = doc.add_table(rows=0, cols=2); t.style = "Table Grid"
    for lab, val in rows:
        cells = t.add_row().cells
        _cell(cells[0], lab, bold=True, align="left", fill="F1F5F9")
        _cell(cells[1], val or "", align="left")
    _widths(t, [Cm(5.0), Cm(11.0)])

    # รูปนักเรียน: ฝังรูปจริงถ้ามี ไม่งั้นเว้นกล่องกรอบให้ติดรูป
    _p(doc, "", after=6)
    photo = doc.add_table(rows=1, cols=1); photo.style = "Table Grid"
    photo.rows[0].height = Cm(4.0)
    if st and getattr(st, "photo", None):
        import io as _io
        cell = photo.rows[0].cells[0]
        cell.text = ""
        pp = cell.paragraphs[0]; pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        try:
            pp.add_run().add_picture(_io.BytesIO(st.photo), height=Cm(3.8))
        except Exception:
            _cell(cell, "รูปนักเรียน", align="center", size=12)
    else:
        _cell(photo.rows[0].cells[0], "รูปนักเรียน\n(ขนาด 1-2 นิ้ว)", align="center", size=12)
    _widths(photo, [Cm(3.5)])
    if not st:
        _p(doc, "", after=2)
        _p(doc, "(นักเรียนคนนี้เพิ่มด้วยมือ ยังไม่ได้ผูกทะเบียนนักเรียนกลาง จึงยังไม่มีข้อมูลส่วนตัว)",
           size=12, after=0)


def _pp6_attendance_growth(doc, school, s, db, ef):
    """หน้า 3 : เวลาเรียนรายเดือน + น้ำหนัก/ส่วนสูง (ภาวะโภชนาการ)"""
    from app.models import AcadAttendance
    from app.services import growth
    klass = s.klass
    _p(doc, "เวลาเรียน", align="center", bold=True, size=17, after=6, page_break=True)

    att = {a.month: a for a in db.query(AcadAttendance).filter_by(acad_student_id=s.id).all()}
    heads = ["เดือน", "มา", "ป่วย", "ลา", "ขาด"]
    t = doc.add_table(rows=1, cols=5); t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, fill="EDE9FE")
    tot = {"/": 0, "ป": 0, "ล": 0, "ข": 0}
    for m, abbr in TH_MONTHS:
        a = att.get(m)
        cm = count_marks(a.marks) if (a and a.marks) else None
        cells = t.add_row().cells
        _cell(cells[0], abbr, align="left")
        if cm:
            _cell(cells[1], cm["/"] or "")
            _cell(cells[2], cm["ป"] or "")
            _cell(cells[3], cm["ล"] or "")
            _cell(cells[4], cm["ข"] or "")
            for k in tot:
                tot[k] += cm[k]
        elif a and a.present is not None:
            _cell(cells[1], a.present)
            for c in cells[2:]:
                _cell(c, "")
            tot["/"] += a.present
        else:
            for c in cells[1:]:
                _cell(c, "")
    rc = t.add_row().cells
    _cell(rc[0], "รวม", bold=True, fill="F1F5F9")
    _cell(rc[1], tot["/"] or "", bold=True); _cell(rc[2], tot["ป"] or "", bold=True)
    _cell(rc[3], tot["ล"] or "", bold=True); _cell(rc[4], tot["ข"] or "", bold=True)
    _widths(t, [Cm(4.0), Cm(3.0), Cm(3.0), Cm(3.0), Cm(3.0)])

    days_open = ef.get("days_open")
    present = ef.get("days_present")
    if days_open and present is not None:
        pct = 100.0 * present / days_open if days_open else 0
        _p(doc, f"วันเปิดเรียนทั้งปี {days_open} วัน  มาเรียน {present} วัน  คิดเป็นร้อยละ {pct:.1f}",
           size=13, after=6)
    else:
        _p(doc, "", after=4)

    # ---- น้ำหนัก/ส่วนสูง (ภาวะโภชนาการ) ----
    _p(doc, "น้ำหนัก / ส่วนสูง", bold=True, size=15, after=2)
    st = _pp6_central(s, db)
    who = st or s     # ใช้ทะเบียนกลาง (มีวันเกิด) ถ้ามี ไม่งั้น AcadStudent
    ms = growth.measures_for(db, s.student_id, klass.year) if s.student_id else {}
    gh = ["ภาคเรียน", "ครั้งที่", "วันที่", "น้ำหนัก (กก.)", "ส่วนสูง (ซม.)", "ภาวะโภชนาการ"]
    gt = doc.add_table(rows=1, cols=6); gt.style = "Table Grid"
    for i, h in enumerate(gh):
        _cell(gt.rows[0].cells[i], h, bold=True, fill="EDE9FE")
    for term in (1, 2):
        m = ms.get(term)
        cells = gt.add_row().cells
        _cell(cells[0], term)
        _cell(cells[1], 1)
        _cell(cells[2], be_date_input(m.date) if (m and m.date) else "")
        _cell(cells[3], f"{m.weight:g}" if (m and m.weight) else "")
        _cell(cells[4], f"{m.height:g}" if (m and m.height) else "")
        res = growth.measure_result(who, m) if m else None
        _cell(cells[5], res["wh"] if (res and res.get("wh")) else "")
    _widths(gt, [Cm(2.8), Cm(2.2), Cm(3.0), Cm(3.0), Cm(3.0), Cm(3.6)])
    _p(doc, "เกณฑ์อ้างอิง: กราฟการเจริญเติบโตของกรมอนามัย", align="center", size=12, after=0)


def _pp6_grades(doc, school, s, db, ef):
    """หน้า 4 : ผลการเรียนรายวิชา (เว้นคอลัมน์ตัวชี้วัด) + GPA"""
    from app.models import AcadScore, AcadSubject
    klass = s.klass
    sec = is_secondary(klass.level)
    _p(doc, "ผลการเรียน", align="center", bold=True, size=17, after=6, page_break=True)

    subs = (db.query(AcadSubject).filter_by(year=klass.year, level=klass.level)
            .order_by(AcadSubject.seq, AcadSubject.code).all())
    my = {(x.subject_id, x.term): x for x in
          db.query(AcadScore).filter_by(acad_student_id=s.id).all()}
    gpa_pairs = []

    if sec:
        heads = ["ที่", "รหัสวิชา", "รายวิชา", "หน่วยกิต", "ตัวชี้วัด", "ภาค 1", "ภาค 2"]
        ws = [Cm(1.0), Cm(2.2), Cm(6.0), Cm(1.8), Cm(2.0), Cm(2.0), Cm(2.0)]
    else:
        heads = ["ที่", "รหัสวิชา", "รายวิชา", "เวลาเรียน", "ตัวชี้วัด", "คะแนน", "ผลการเรียน"]
        ws = [Cm(1.0), Cm(2.4), Cm(6.2), Cm(2.0), Cm(2.0), Cm(2.0), Cm(2.4)]
    t = doc.add_table(rows=1, cols=len(heads)); t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, fill="EDE9FE")

    seen, no = set(), 0
    for sub in subs:
        key = (sub.code or "", sub.name)
        if sec and key in seen:
            continue
        seen.add(key)
        no += 1
        cells = t.add_row().cells
        _cell(cells[0], no)
        _cell(cells[1], sub.code or "")
        _cell(cells[2], sub.name, align="left")
        if sec:
            _cell(cells[3], f"{sub.credit:g}" if sub.credit else "")
            _cell(cells[4], "")   # ตัวชี้วัด: เว้นว่าง (ยังไม่ติดตามรายตัวชี้วัด)
            for i, tm in enumerate((1, 2)):
                ids = [x.id for x in subs if (x.code or "", x.name) == key and x.term == tm]
                g = ""
                for sid2 in ids:
                    row = my.get((sid2, tm))
                    if row and row.grade:
                        g = row.grade
                _cell(cells[5 + i], g, bold=True)
                gpa_pairs.append((g, sub.credit or 1))
        else:
            _cell(cells[3], sub.hours or "")
            _cell(cells[4], "")   # ตัวชี้วัด: เว้นว่าง
            row = my.get((sub.id, 0))
            _cell(cells[5], f"{row.score:g}" if (row and row.score is not None) else "")
            _cell(cells[6], row.grade if row else "", bold=True)
            gpa_pairs.append(((row.grade if row else ""), sub.credit or 1))
    _widths(t, ws)

    gpa = weighted_avg(gpa_pairs)
    _p(doc, "", after=2)
    _p(doc, f"ผลการเรียนเฉลี่ย (GPA): {gpa:.2f}" if gpa is not None else "ผลการเรียนเฉลี่ย (GPA): -",
       bold=True, size=14, after=0)


def _pp6_assess_table(doc, s, db, title, model, avg_fn, summary_val):
    """หน้าประเมินรายวิชา (คุณลักษณะ / อ่านคิดเขียน) : รายวิชา -> ผลการประเมิน + สรุป
    เรียงรายวิชาตามลำดับเดียวกับหน้าผลการเรียน (seq, รหัส) ให้ทุกหน้าตรงกัน"""
    from app.models import AcadSubject
    klass = s.klass
    _p(doc, title, align="center", bold=True, size=17, after=6, page_break=True)
    subs = (db.query(AcadSubject).filter_by(year=klass.year, level=klass.level)
            .order_by(AcadSubject.seq, AcadSubject.code).all())
    by_subj = {r.subject_id: r for r in db.query(model).filter_by(acad_student_id=s.id).all()}
    heads = ["รหัสวิชา", "รายวิชา", "ผลการประเมิน"]
    t = doc.add_table(rows=1, cols=3); t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, fill="EDE9FE")
    any_row = False
    seen = set()
    for sub in subs:
        key = (sub.code or "", sub.name)
        if key in seen:
            continue
        seen.add(key)
        r = by_subj.get(sub.id)
        label = quality_of_avg(avg_fn(r))[1] if r else ""
        if not label:
            continue
        any_row = True
        cells = t.add_row().cells
        _cell(cells[0], sub.code or "")
        _cell(cells[1], sub.name or "", align="left")
        _cell(cells[2], label, bold=True)
    if not any_row:
        cells = t.add_row().cells
        _cell(cells[0], "")
        _cell(cells[1], "(ยังไม่ได้ประเมินรายวิชา)", align="left")
        _cell(cells[2], "")
    _widths(t, [Cm(2.6), Cm(9.4), Cm(4.0)])
    _p(doc, "", after=2)
    _p(doc, f"สรุปผลการประเมิน: {summary_val or '-'}", bold=True, size=14, after=0)


def _pp6_activities_onet(doc, school, s, db):
    """หน้า 7 : กิจกรรมพัฒนาผู้เรียน + ผลการทดสอบระดับชาติ (O-NET)"""
    from app.models import AcadActivityResult
    klass = s.klass
    _p(doc, "กิจกรรมพัฒนาผู้เรียน", align="center", bold=True, size=17, after=6, page_break=True)
    acts = activities_for(klass.year, klass.level, db)
    my_act = {r.activity_id: (r.result or "").strip() for r in
              db.query(AcadActivityResult).filter_by(acad_student_id=s.id).all()}
    t = doc.add_table(rows=1, cols=2); t.style = "Table Grid"
    _cell(t.rows[0].cells[0], "กิจกรรม", bold=True, fill="EDE9FE", align="left")
    _cell(t.rows[0].cells[1], "ผลการประเมิน", bold=True, fill="EDE9FE")
    if acts:
        for a in acts:
            cells = t.add_row().cells
            _cell(cells[0], a.name, align="left")
            _cell(cells[1], my_act.get(a.id, "") or "")
    else:
        cells = t.add_row().cells
        _cell(cells[0], "(ยังไม่ได้ตั้งกิจกรรมพัฒนาผู้เรียน)", align="left")
        _cell(cells[1], "")
    _widths(t, [Cm(12.0), Cm(4.0)])
    _p(doc, "", after=2)
    _p(doc, f"สรุปผลกิจกรรมพัฒนาผู้เรียน: {activity_summary(s, db) or '-'}", bold=True, size=14, after=6)

    # ---- O-NET เฉพาะชั้นปลายทาง ----
    if is_exit_level(klass.level):
        _p(doc, "ผลการทดสอบทางการศึกษาระดับชาติขั้นพื้นฐาน (O-NET)", bold=True, size=14, after=2)
        o = onet_for(s, db)
        oh = ["วิชา", "คะแนนเต็ม", "คะแนนที่ได้"]
        ot = doc.add_table(rows=1, cols=3); ot.style = "Table Grid"
        for i, h in enumerate(oh):
            _cell(ot.rows[0].cells[i], h, bold=True, fill="EDE9FE")
        for subj in ONET_SUBJECTS:
            row = o.get(subj)
            cells = ot.add_row().cells
            _cell(cells[0], subj, align="left")
            _cell(cells[1], f"{row.full_score:g}" if (row and row.full_score is not None) else "")
            _cell(cells[2], f"{row.score:g}" if (row and row.score is not None) else "")
        _widths(ot, [Cm(6.0), Cm(4.0), Cm(4.0)])


_CDOTS = "..............................................................................................."


def _comment_table(doc, title, *, lines_per_term=4):
    """ตารางกรอบความคิดเห็น 1 ชุด: หัวรวม + [ภาคเรียน | ความคิดเห็น...] + แถวภาค 1/2 (เว้นเขียนมือ)"""
    t = doc.add_table(rows=0, cols=2); t.style = "Table Grid"
    # หัวรวม (ผสาน 2 ช่อง)
    hr = t.add_row().cells
    hr[0].merge(hr[1])
    _cell(hr[0], title, bold=True, size=15, fill="F1F5F9")
    # หัวคอลัมน์
    sh = t.add_row().cells
    _cell(sh[0], "ภาคเรียน", bold=True, size=13, fill="F8FAFC")
    _cell(sh[1], title, bold=True, size=13, fill="F8FAFC")
    for term in (1, 2):
        cells = t.add_row().cells
        _cell(cells[0], f"ภาคเรียนที่ {term}", size=13)
        cells[1].text = ""
        first = cells[1].paragraphs[0]
        for i in range(lines_per_term):
            p = first if i == 0 else cells[1].add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
            p.paragraph_format.space_after = Pt(4)
            r = p.add_run(_CDOTS); r.font.size = Pt(13); r.font.name = THAI_FONT
            r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    _widths(t, [Cm(3.0), Cm(13.0)])
    return t


def _pp6_comments(doc, school, s, db):
    """หน้า 8 : ความคิดเห็นครูประจำชั้น + ผู้ปกครอง (ตารางกรอบ แยกภาคเรียน 1/2)"""
    _p(doc, "ความคิดเห็นของครูประจำชั้นและผู้ปกครอง", align="center", bold=True, size=17, after=8,
       page_break=True)
    _comment_table(doc, "ความคิดเห็นของครูประจำชั้น")
    _p(doc, "", after=8)
    _comment_table(doc, "ความคิดเห็นของผู้ปกครอง")


def _pp6_summary(doc, school, s, db, ef):
    """หน้า 9 : แบบสรุปผลการประเมินการเรียน (ตาม ปพ.6) + เกณฑ์ตัดสิน + ลงนาม"""
    from app.models import AcadScore, AcadSubject
    klass = s.klass
    sec = is_secondary(klass.level)
    _p(doc, "ผลการประเมินการเรียนระดับชั้น", align="center", bold=True, size=17, after=8,
       page_break=True)

    # เลขที่ / ชื่อ-นามสกุล
    _p(doc, f"เลขที่  {s.seq or '.......'}     ชื่อ-นามสกุล  {s.name}", size=14, after=4)
    # ย้ายเข้าระหว่างปีการศึกษา (เว้นให้ติ๊ก/กรอกวันที่เอง)
    _p(doc, "ย้ายเข้าระหว่างปีการศึกษา   ☐ ใช่   ☐ ไม่ใช่      วันที่ย้ายเข้า .............................",
       size=14, after=6)

    subs = (db.query(AcadSubject).filter_by(year=klass.year, level=klass.level).all())
    my = {(x.subject_id, x.term): x for x in
          db.query(AcadScore).filter_by(acad_student_id=s.id).all()}
    pairs, grades = [], []
    for sub in subs:
        row = my.get((sub.id, sub.term if sec else 0))
        if row:
            pairs.append((row.grade, sub.credit or 1))
            grades.append((str(row.grade) if row.grade is not None else "").strip())
    gpa = weighted_avg(pairs)

    present = ef.get("days_present")
    days_open = ef.get("days_open")
    att_pct = (100.0 * present / days_open) if (days_open and present is not None) else None
    att_txt = f"{att_pct:.2f}" if att_pct is not None else ""

    char = (ef.get("desired_char") or "").strip()
    read = (ef.get("read_think") or "").strip()
    act = (activity_summary(s, db) or "").strip()
    has_zero = any(g == "0" for g in grades)

    def _pass(ok):
        return "ผ่าน" if ok else "ไม่ผ่าน"

    # ที่ | การประเมิน | จำนวน/คะแนน/ร้อยละ | ผลการประเมิน
    rows = [
        ("มีเวลาเรียนตลอดปีการศึกษาร้อยละ 80 ขึ้นไป", att_txt,
         _pass(att_pct is None or att_pct >= 80)),
        ("ผ่านการประเมินตัวชี้วัดรายวิชา ร้อยละ 100", "100.00", "ผ่าน"),
        ("ผ่านการประเมินกิจกรรมพัฒนาผู้เรียนทุกกิจกรรม", act,
         _pass(act != "มผ")),
        ("การตัดสินคุณลักษณะอันพึงประสงค์", char or "-",
         _pass(char not in ("", "ไม่ผ่าน"))),
        ("การตัดสินการอ่าน คิดวิเคราะห์ เขียนสื่อความ", read or "-",
         _pass(read not in ("", "ไม่ผ่าน"))),
        ("ไม่มีรายวิชาที่มีผลการเรียน 0",
         "มีรายวิชาได้ 0" if has_zero else "ผ่านทุกรายวิชา", _pass(not has_zero)),
    ]
    t = doc.add_table(rows=1, cols=4); t.style = "Table Grid"
    for i, h in enumerate(["ที่", "การประเมิน", "จำนวน/คะแนน/ร้อยละ", "ผลการ\nประเมิน"]):
        _cell(t.rows[0].cells[i], h.replace("\n", " "), bold=True, fill="EDE9FE")
    for i, (lab, num, res) in enumerate(rows, 1):
        cells = t.add_row().cells
        _cell(cells[0], i)
        _cell(cells[1], lab, align="left")
        _cell(cells[2], num)
        _cell(cells[3], res, bold=True)
    # แถวสรุป GPA
    fr = t.add_row().cells
    fr[0].merge(fr[1])
    _cell(fr[0], "ผลการเรียนเฉลี่ยตลอดหนึ่งปีการศึกษา", align="left", bold=True, fill="F1F5F9")
    _cell(fr[2], f"{gpa:.2f}" if gpa is not None else "-", bold=True)
    _cell(fr[3], f"ได้  {len(pairs)}", bold=True)
    _widths(t, [Cm(1.2), Cm(8.3), Cm(3.7), Cm(2.8)])

    all_pass = (att_pct is None or att_pct >= 80) and not has_zero and \
        char not in ("", "ไม่ผ่าน") and read not in ("", "ไม่ผ่าน")
    grad = is_exit_level(klass.level)
    verb = "จบการศึกษา" if grad else "เลื่อนชั้น"
    _p(doc, "", after=2)
    _p(doc, f"หมายเหตุ   นักเรียน{'ผ่าน' if all_pass else 'ยังไม่ผ่าน'}การประเมินทุกรายการ "
            f"{'สามารถ ' + verb + 'ได้' if all_pass else 'ต้องปรับปรุงก่อน' + verb}",
       size=13, after=6)
    tick_pass = "☑" if all_pass else "☐"
    tick_repeat = "☐" if all_pass else "☑"
    _p(doc, f"สรุปผลการประเมิน   {tick_pass} ได้{verb}      {tick_repeat} ซ้ำชั้น",
       size=14, after=4)
    _p(doc, "วันที่อนุมัติการเรียน  ...............................................", size=14, after=16)

    homerooms = [p.name for p in (klass.homeroom, klass.co_homeroom) if p]
    # ลงนามครูประจำชั้น (สูงสุด 2 คน) วางเคียงกันในตารางไร้เส้น
    st = doc.add_table(rows=1, cols=2)
    _no_border_signs(st.rows[0].cells[0], homerooms[0] if len(homerooms) > 0 else "", "ครูประจำชั้น")
    _no_border_signs(st.rows[0].cells[1], homerooms[1] if len(homerooms) > 1 else "", "ครูประจำชั้น")
    _widths(st, [Cm(8.0), Cm(8.0)])

    _p(doc, "", after=10)
    director = (getattr(school, "director_name", "") or "").strip()
    dpos = ("ผู้อำนวยการ" + school.name) if (school.name or "").startswith("โรงเรียน") \
        else "ผู้อำนวยการโรงเรียน"
    _sign_block(doc, director, dpos)


def _no_border_signs(cell, name, role):
    """ช่องลงนามไร้เส้นในตาราง (ลายเซ็นลอยถ้ามี)"""
    from docx.oxml.ns import qn as _qn
    tcpr = cell._tc.get_or_add_tcPr()
    borders = tcpr.makeelement(_qn("w:tcBorders"), {})
    for edge in ("top", "left", "bottom", "right"):
        borders.append(borders.makeelement(_qn(f"w:{edge}"), {_qn("w:val"): "nil"}))
    tcpr.append(borders)
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(0)
    r = p.add_run("(ลงชื่อ)........................................."); r.font.size = Pt(14); r.font.name = THAI_FONT
    r._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    if name:
        _float_signature(p, name)
    for txt in (f"( {name or '.......................................'} )", role):
        pp = cell.add_paragraph(); pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pp.paragraph_format.space_after = Pt(0)
        rr = pp.add_run(txt); rr.font.size = Pt(14); rr.font.name = THAI_FONT
        rr._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)


def _pp6_body(doc, school, s, db, *, page_break: bool = False):
    """สมุดพก ปพ.6 ของนักเรียน 1 คน (9 หน้า) - แนวตั้ง"""
    from app.models import AcadCharEval, AcadReadEval
    ef = effective_eval(s, db)
    _pp6_cover(doc, school, s, db, page_break=page_break)               # 1
    _pp6_personal(doc, school, s, db)                                  # 2
    _pp6_attendance_growth(doc, school, s, db, ef)                     # 3
    _pp6_grades(doc, school, s, db, ef)                                # 4
    _pp6_assess_table(doc, s, db, "คุณลักษณะอันพึงประสงค์",           # 5
                      AcadCharEval, char_avg, ef.get("desired_char"))
    _pp6_assess_table(doc, s, db, "การอ่าน คิดวิเคราะห์ และเขียน",     # 6
                      AcadReadEval, read_avg, ef.get("read_think"))
    _pp6_activities_onet(doc, school, s, db)                           # 7
    _pp6_comments(doc, school, s, db)                                  # 8
    _pp6_summary(doc, school, s, db, ef)                               # 9


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
