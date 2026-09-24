# -*- coding: utf-8 -*-
"""
kinder_teacher.py - บัญชีเรียกชื่อและสมุดบันทึกพัฒนาการเด็กนักเรียน ระดับปฐมวัย
                    (เล่มของครูประจำชั้น · แบบ อบ.2/1 - อบ.2/3)

ต่างจากสมุดพก (kinder_book.py) ตรงที่เล่มนี้เป็น "ทั้งห้องในหน้าเดียว" ครูเก็บไว้เอง
ส่วนสมุดพกเป็นรายคนส่งผู้ปกครอง · ใช้ข้อมูลชุดเดียวกันทั้งหมด ไม่ต้องกรอกซ้ำ

เรียงหน้าตามต้นฉบับ
  1  ปก + จำนวนเด็กในชั้น (ชาย/หญิง/รวม)
  2  ข้อมูลเด็ก (เลขที่ · เลขประจำตัว · ชื่อ-สกุล · วัน เดือน ปีเกิด · อายุ)
  3  สรุปน้ำหนัก - ส่วนสูง ทั้งห้อง (ภาคเรียนละ 2 ครั้ง + ผลตามเกณฑ์กรมอนามัย)
  4  สรุปเวลาเรียน ทั้งห้อง 11 เดือน + รวม + มาเรียนร้อยละ
  5+ บันทึกพัฒนาการรายด้าน ทั้งห้อง (นักเรียน x ตัวบ่งชี้) แยกภาคเรียน
  ท้ายเล่ม  สรุปผลการพัฒนา - เด็กที่ควรได้รับการเสริมรายด้าน + ลงนาม

หน้าที่เป็นตารางกว้างใช้กระดาษแนวนอน (พื้นที่พิมพ์ 26.7 ซม.)
ข้อมูลที่ระบบไม่ได้เก็บ (เลขบัตรประชาชน หมู่เลือด ชื่อ-อาชีพผู้ปกครอง) เว้นช่องให้ครูเขียนเอง
ตามนโยบายลดการเก็บข้อมูลส่วนบุคคลของเด็ก
"""
from docx import Document
from docx.shared import Cm, Pt

from app.database import get_data_dir
from app.services.doc_page import set_a4, A4_W, A4_H
from app.services.acad_doc import (_p, _cell, _widths, _logo_header, _class_label,
                                   _safe, THAI_FONT)
from app.services.build_templates import _repeat_header_row
from app.services import kinder as kd
from app.services import growth
from app.services.academic import TH_MONTHS, count_marks
from app.thai_utils import be_date_input, level_full

_TICK = "✓"
_MAX_PER_PAGE = 30          # ต้นฉบับพิมพ์หน้าละ 30 คน (นักเรียนเลขที่ 1-30)


def _new_doc(landscape=False):
    doc = Document()
    set_a4(doc, landscape=landscape)
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin = Cm(1.5)
    sec.bottom_margin = Cm(1.2)
    base = doc.styles["Normal"]
    base.font.name = THAI_FONT
    base.font.size = Pt(14)
    return doc


def _section(doc, *, landscape):
    """ขึ้นหน้าใหม่พร้อมสลับแนวกระดาษ (ห้ามใช้ set_a4 ซ้ำ มันบังคับทุก section)"""
    from docx.enum.section import WD_SECTION
    from docx.enum.section import WD_ORIENT
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    if landscape:
        sec.orientation = WD_ORIENT.LANDSCAPE
        sec.page_width, sec.page_height = A4_H, A4_W
    else:
        sec.orientation = WD_ORIENT.PORTRAIT
        sec.page_width, sec.page_height = A4_W, A4_H
    sec.left_margin = sec.right_margin = Cm(1.5)
    sec.top_margin = Cm(1.5)
    sec.bottom_margin = Cm(1.2)
    return sec


def _chunks(items, n=_MAX_PER_PAGE):
    """แบ่งนักเรียนเป็นหน้า ๆ ละ n คน (ต้นฉบับหน้าละ 30 คน)"""
    return [items[i:i + n] for i in range(0, len(items), n)] or [[]]


def _age_of(birth, at_year):
    """อายุ (ปี) ณ วันเปิดเรียนของปีการศึกษานั้น"""
    if not birth:
        return ""
    return max(0, (at_year - 543) - birth.year - (1 if birth.month > 5 else 0))


# ---------------------------------------------------------------- หน้า 1 ปก
def _cover(doc, school, klass, students, meta):
    _logo_header(doc, school, height_cm=3.0, after=8)
    _p(doc, f"อบ.2/{meta['form'].split('/')[-1]}", align="right", size=13, after=10)
    _p(doc, "บัญชีเรียกชื่อและสมุดบันทึกพัฒนาการเด็กนักเรียน", align="center", bold=True,
       size=22, after=6)
    _p(doc, "ระดับปฐมวัย", align="center", bold=True, size=20, after=14)
    _p(doc, f"{level_full(klass.level)}  (อายุ {meta['age']} ขวบ)"
            + (f"  ห้อง {klass.room}" if (klass.room or "").strip() else ""),
       align="center", size=16, after=4)
    _p(doc, f"ปีการศึกษา {klass.year}", align="center", size=15, after=14)
    _p(doc, f"โรงเรียน{school.name or ''}", align="center", bold=True, size=17, after=2)
    loc = []
    for attr, prefix in (("subdistrict", "ตำบล"), ("district", "อำเภอ"), ("province", "จังหวัด")):
        v = (getattr(school, attr, "") or "").strip()
        loc.append(prefix + (v if v else " ................"))
    _p(doc, "   ".join(loc), align="center", size=14, after=2)
    if getattr(school, "area_office", ""):
        _p(doc, f"สำนักงานเขตพื้นที่การศึกษา{school.area_office}", align="center", size=14, after=16)
    else:
        _p(doc, "", after=16)

    male = sum(1 for s in students if s.sex == "M")
    female = sum(1 for s in students if s.sex == "F")
    _p(doc, "ข้อมูล / จำนวนเด็ก", bold=True, size=15, after=3)
    t = doc.add_table(rows=1, cols=4)
    t.style = "Table Grid"
    for i, h in enumerate(["", "ชาย", "หญิง", "รวม"]):
        _cell(t.rows[0].cells[i], h, bold=True, fill="EDE9FE")
    for label, m, f in [("จำนวนเด็กนักเรียนในชั้น", male, female),
                        ("จำนวนเด็กที่เข้าระหว่างเรียน", "", ""),
                        ("จำนวนเด็กที่ออกระหว่างเรียน", "", "")]:
        cells = t.add_row().cells
        _cell(cells[0], label, align="left")
        _cell(cells[1], m)
        _cell(cells[2], f)
        _cell(cells[3], (m + f) if isinstance(m, int) else "")
    _widths(t, [Cm(7.0), Cm(3.0), Cm(3.0), Cm(3.0)])

    _p(doc, "", after=16)
    homerooms = [p.name for p in (klass.homeroom, klass.co_homeroom) if p]
    _p(doc, "ครูประจำชั้น  " + (" / ".join(homerooms) if homerooms else "......................"),
       align="center", size=14, after=2)
    _p(doc, "ผู้บริหารสถานศึกษา  "
            + (getattr(school, "director_name", "") or "......................"),
       align="center", size=14, after=0)


# ---------------------------------------------------------------- หน้า 2 ข้อมูลเด็ก
def _students_page(doc, klass, students, central):
    _section(doc, landscape=False)
    _p(doc, "ข้อมูลเด็ก", align="center", bold=True, size=18, after=3)
    _p(doc, f"{level_full(klass.level)}"
            + (f"/{klass.room}" if (klass.room or "").strip() else "")
            + f"   ปีการศึกษา {klass.year}", align="center", size=14, after=6)
    heads = ["เลขที่", "เลขประจำตัว\nนักเรียน", "ชื่อ - นามสกุล", "เพศ",
             "วัน/เดือน/ปี เกิด", "อายุ\n(ปี)", "เลขประจำตัวประชาชน"]
    t = doc.add_table(rows=1, cols=len(heads))
    t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, size=12, fill="EDE9FE")
    _repeat_header_row(t.rows[0])
    for s in students:
        st = central.get(s.student_id)
        cells = t.add_row().cells
        _cell(cells[0], s.seq or "", size=12)
        _cell(cells[1], s.student_no or "", size=12)
        _cell(cells[2], s.name, align="left", size=12)
        _cell(cells[3], "ชาย" if s.sex == "M" else "หญิง" if s.sex == "F" else "", size=12)
        _cell(cells[4], be_date_input(st.birthdate) if (st and st.birthdate) else "", size=12)
        _cell(cells[5], _age_of(st.birthdate if st else None, klass.year), size=12)
        _cell(cells[6], "", size=12)          # ระบบไม่เก็บเลขบัตรประชาชนของเด็ก
    _widths(t, [Cm(1.3), Cm(2.2), Cm(5.2), Cm(1.4), Cm(2.4), Cm(1.2), Cm(2.8)])
    _p(doc, "ช่องเลขประจำตัวประชาชนเว้นไว้ให้เขียนเอง (ระบบไม่เก็บข้อมูลส่วนบุคคลของเด็ก)",
       size=11, after=0)


# ---------------------------------------------------------------- หน้า 3 น้ำหนัก-ส่วนสูง
def _growth_page(doc, klass, students, central, ms_all):
    _section(doc, landscape=True)
    _p(doc, "สรุปผลน้ำหนัก - ส่วนสูง", align="center", bold=True, size=18, after=3)
    _p(doc, f"{level_full(klass.level)}"
            + (f"/{klass.room}" if (klass.room or "").strip() else "")
            + f"   ปีการศึกษา {klass.year}", align="center", size=13, after=6)
    # หัว 3 ชั้น: น้ำหนัก/ส่วนสูง -> ภาคเรียน -> ครั้งที่
    t = doc.add_table(rows=3, cols=2 + 8)
    t.style = "Table Grid"
    r0, r1, r2 = (t.rows[i].cells for i in range(3))
    for i, h in enumerate(["เลขที่", "ชื่อ - นามสกุล"]):
        r0[i].merge(r1[i]).merge(r2[i])
        _cell(r0[i], h, bold=True, size=12, fill="EDE9FE")
    for gi, gname in enumerate(["น้ำหนัก (กิโลกรัม)", "ส่วนสูง (เซนติเมตร)"]):
        base = 2 + gi * 4
        r0[base].merge(r0[base + 3])
        _cell(r0[base], gname, bold=True, size=12, fill="EDE9FE")
        for ti, term in enumerate((1, 2)):
            c = base + ti * 2
            r1[c].merge(r1[c + 1])
            _cell(r1[c], f"ภาคเรียนที่ {term}", bold=True, size=11, fill="F5F3FF")
            for ni, times in enumerate((1, 2)):
                _cell(r2[c + ni], f"ครั้งที่ {times}", bold=True, size=10, fill="F8FAFC")
    _repeat_header_row(t.rows[0])
    for s in students:
        st = central.get(s.student_id)
        ms = ms_all.get(s.student_id, {})
        cells = t.add_row().cells
        _cell(cells[0], s.seq or "", size=11)
        _cell(cells[1], s.name, align="left", size=11)
        for gi, attr in enumerate(("weight", "height")):
            for si, slot in enumerate(growth.SLOTS):
                m = ms.get(slot)
                v = getattr(m, attr, None) if m else None
                _cell(cells[2 + gi * 4 + si], f"{v:g}" if v else "", size=11)
    _widths(t, [Cm(1.3), Cm(5.4)] + [Cm(2.5)] * 8)
    _p(doc, "เกณฑ์อ้างอิง: กราฟการเจริญเติบโตของกรมอนามัย · ดูผลการประเมินรายคนได้ที่สมุดพก",
       size=11, after=0)


# ---------------------------------------------------------------- หน้า 4 สรุปเวลาเรียน
def _attendance_page(doc, klass, students, att_all, open_days):
    _section(doc, landscape=True)
    _p(doc, "สรุปเวลาเรียน", align="center", bold=True, size=18, after=3)
    _p(doc, f"{level_full(klass.level)}"
            + (f"/{klass.room}" if (klass.room or "").strip() else "")
            + f"   ปีการศึกษา {klass.year}", align="center", size=13, after=6)
    months = list(TH_MONTHS)
    heads = ["เลขที่", "ชื่อ - นามสกุล"] + [a for _m, a in months] + ["รวมเวลาเรียน",
                                                                      "มาเรียนร้อยละ"]
    t = doc.add_table(rows=1, cols=len(heads))
    t.style = "Table Grid"
    for i, h in enumerate(heads):
        _cell(t.rows[0].cells[i], h, bold=True, size=11, fill="EDE9FE")
    _repeat_header_row(t.rows[0])
    # แถวแรก = วันเปิดเรียนของแต่ละเดือน (ทั้งห้องเท่ากัน)
    hr = t.add_row().cells
    _cell(hr[0], "", size=11, fill="F8FAFC")
    _cell(hr[1], "วันเปิดเรียน", bold=True, align="left", size=11, fill="F8FAFC")
    for i, (mo, _a) in enumerate(months):
        _cell(hr[2 + i], open_days.get(mo) or "", size=11, fill="F8FAFC")
    _cell(hr[2 + len(months)], sum(open_days.values()) or "", bold=True, size=11, fill="F8FAFC")
    _cell(hr[3 + len(months)], "", size=11, fill="F8FAFC")
    for s in students:
        att = att_all.get(s.id, {})
        cells = t.add_row().cells
        _cell(cells[0], s.seq or "", size=11)
        _cell(cells[1], s.name, align="left", size=11)
        total = 0
        for i, (mo, _a) in enumerate(months):
            n = att.get(mo)
            _cell(cells[2 + i], n if n else "", size=11)
            total += n or 0
        _cell(cells[2 + len(months)], total or "", bold=True, size=11)
        opened = sum(open_days.values())
        _cell(cells[3 + len(months)], f"{100.0 * total / opened:.1f}" if opened else "", size=11)
    _widths(t, [Cm(1.2), Cm(4.6)] + [Cm(1.35)] * len(months) + [Cm(2.2), Cm(2.2)])


# ---------------------------------------------------------------- หน้าพัฒนาการรายด้าน
def _domain_page(doc, klass, students, level, domain, title, items, res_all, term):
    _section(doc, landscape=True)
    _p(doc, f"บันทึกพัฒนาการ{title}   ภาคเรียนที่ {term}", align="center", bold=True,
       size=17, after=3)
    _p(doc, f"{level_full(klass.level)}"
            + (f"/{klass.room}" if (klass.room or "").strip() else "")
            + f"   ปีการศึกษา {klass.year}", align="center", size=13, after=6)
    t = doc.add_table(rows=1, cols=2 + len(items))
    t.style = "Table Grid"
    _cell(t.rows[0].cells[0], "เลขที่", bold=True, size=11, fill="EDE9FE")
    _cell(t.rows[0].cells[1], "ชื่อ - นามสกุล", bold=True, size=11, fill="EDE9FE")
    for i, (n, _g, _txt) in enumerate(items):
        _cell(t.rows[0].cells[2 + i], n, bold=True, size=11, fill="EDE9FE")
    _repeat_header_row(t.rows[0])
    for s in students:
        res = res_all.get(s.id, {})
        cells = t.add_row().cells
        _cell(cells[0], s.seq or "", size=11)
        _cell(cells[1], s.name, align="left", size=11)
        for i, (n, _g, _txt) in enumerate(items):
            v = res.get((term, kd.code_of(domain, n)))
            _cell(cells[2 + i], v or "", size=11)
    body_w = 26.7 - 1.2 - 5.6
    _widths(t, [Cm(1.2), Cm(5.6)] + [Cm(round(body_w / len(items), 2))] * len(items))
    _p(doc, "ใส่ระดับ  3 = ปฏิบัติได้ · 2 = ปฏิบัติได้บางครั้ง · 1 = ควรเสริม", size=11, after=4)
    # รายการตัวบ่งชี้ท้ายตาราง (หัวตารางใส่ได้แค่หมายเลข)
    for n, grp, txt in items:
        _p(doc, f"        {n}. {txt}  ({grp})", size=11, after=1)


# ---------------------------------------------------------------- หน้าสุดท้าย สรุป
def _summary_page(doc, school, klass, students, res_all, level):
    _section(doc, landscape=False)
    _p(doc, "สรุปผลการพัฒนา", align="center", bold=True, size=18, after=3)
    _p(doc, f"{level_full(klass.level)}"
            + (f"/{klass.room}" if (klass.room or "").strip() else "")
            + f"   ปีการศึกษา {klass.year}", align="center", size=14, after=2)
    _p(doc, f"โรงเรียน{school.name or ''}"
            + (f"  สำนักงานเขตพื้นที่การศึกษา{school.area_office}"
               if getattr(school, "area_office", "") else ""),
       align="center", size=13, after=10)
    for term in (1, 2):
        _p(doc, f"ภาคเรียนที่ {term}", bold=True, size=15, after=2)
        _p(doc, "เด็กที่ควรได้รับการเสริม", size=13, after=2)
        t = doc.add_table(rows=1, cols=2)
        t.style = "Table Grid"
        _cell(t.rows[0].cells[0], "ด้าน", bold=True, size=12, fill="EDE9FE")
        _cell(t.rows[0].cells[1], "เลขที่", bold=True, size=12, fill="EDE9FE")
        for key, full, _short in kd.DOMAINS:
            items = kd.items_for(level, key)
            weak = []
            for s in students:
                res = res_all.get(s.id, {})
                vals = [res.get((term, kd.code_of(key, n))) for n, _g, _t in items]
                if kd.domain_average(vals) == 1:      # สรุปรายด้านได้ "ควรเสริม"
                    weak.append(str(s.seq or ""))
            cells = t.add_row().cells
            _cell(cells[0], full, align="left", size=12)
            _cell(cells[1], ", ".join(x for x in weak if x), align="left", size=12)
        _widths(t, [Cm(6.0), Cm(10.0)])
        _p(doc, "", after=10)

    _p(doc, "", after=14)
    homerooms = [p.name for p in (klass.homeroom, klass.co_homeroom) if p]
    sig = doc.add_table(rows=0, cols=2)
    r1 = sig.add_row().cells
    for i, (name, role) in enumerate([
            (homerooms[0] if homerooms else "", "ครูประจำชั้น"),
            (getattr(school, "director_name", "") or "", "ผู้บริหารสถานศึกษา")]):
        _cell(r1[i], "\n\nลงชื่อ ..........................................\n"
                     f"({name or '..........................................'})\n{role}",
              size=13)
    _widths(sig, [Cm(8.0), Cm(8.0)])


# ---------------------------------------------------------------- เล่มเต็ม
def render_kinder_teacher_book(school, klass, db) -> str:
    """บัญชีเรียกชื่อและสมุดบันทึกพัฒนาการ (เล่มของครู) ของห้องอนุบาล 1 ห้อง"""
    from app.models import Student, AcadAttendance, KinderResult, StudentMeasure
    level = (klass.level or "").strip()
    meta = kd.KINDER_LEVELS.get(level)
    doc = _new_doc(landscape=False)
    if not meta:
        _p(doc, "ชั้นนี้ไม่ใช่ระดับปฐมวัย จึงออกเล่มนี้ไม่ได้", align="center", size=16)
        path = get_data_dir() / f"บัญชีเรียกชื่อ_{_safe(_class_label(klass))}.docx"
        doc.save(path)
        return str(path)

    students = sorted(klass.students, key=lambda x: (x.seq or 999, x.name))
    sids = [s.id for s in students]
    cids = [s.student_id for s in students if s.student_id]

    central = {}
    if cids:
        central = {st.id: st for st in db.query(Student).filter(Student.id.in_(cids)).all()}
    ms_all = {}
    if cids:
        for m in (db.query(StudentMeasure)
                  .filter(StudentMeasure.student_id.in_(cids),
                          StudentMeasure.year == klass.year).all()):
            ms_all.setdefault(m.student_id, {})[(m.term, m.times or 1)] = m
    att_all, open_days = {}, {}
    if sids:
        for a in (db.query(AcadAttendance)
                  .filter(AcadAttendance.acad_student_id.in_(sids),
                          AcadAttendance.subject_id.is_(None)).all()):
            cm = count_marks(a.marks) if (a.marks or "").strip() else None
            if cm:
                att_all.setdefault(a.acad_student_id, {})[a.month] = cm["/"]
                opened = cm["/"] + cm["ป"] + cm["ล"] + cm["ข"]
                open_days[a.month] = max(open_days.get(a.month, 0), opened)
            elif a.present is not None:
                att_all.setdefault(a.acad_student_id, {})[a.month] = a.present
    res_all = {}
    if sids:
        for r in (db.query(KinderResult)
                  .filter(KinderResult.acad_student_id.in_(sids)).all()):
            res_all.setdefault(r.acad_student_id, {})[(r.term, r.code)] = r.value

    _cover(doc, school, klass, students, meta)
    _students_page(doc, klass, students, central)
    _growth_page(doc, klass, students, central, ms_all)
    _attendance_page(doc, klass, students, att_all, open_days)
    for key, full, _short in kd.DOMAINS:
        items = kd.items_for(level, key)
        groups = ([(full + " (ข้อ 1 - 10)", items[:10]), (full + " (ข้อ 11 - 20)", items[10:])]
                  if key == "intel" and len(items) > 10 else [(full, items)])
        for term in (1, 2):
            for title, part in groups:
                _domain_page(doc, klass, students, level, key, title, part, res_all, term)
    _summary_page(doc, school, klass, students, res_all, level)

    path = get_data_dir() / f"บัญชีเรียกชื่อ_{_safe(_class_label(klass))}.docx"
    doc.save(path)
    return str(path)
