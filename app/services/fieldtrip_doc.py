# -*- coding: utf-8 -*-
"""
fieldtrip_doc.py - เอกสารการพานักเรียนไปนอกสถานศึกษา (ทัศนศึกษา)

แบบ 3 ฉบับยกข้อความจาก "แบบท้ายระเบียบ" ระเบียบกระทรวงศึกษาธิการ ว่าด้วยการพานักเรียน
และนักศึกษาไปนอกสถานศึกษา พ.ศ. 2562 (ราชกิจจานุเบกษา 22 พ.ค. 2563) คำต่อคำ
เลือกคำที่ใช้กับโรงเรียน (นักเรียน/นักศึกษา -> นักเรียน, ครู/อาจารย์ -> ครู) แล้วเติมข้อมูลลงช่องว่าง
  1) แบบขออนุญาตผู้บังคับบัญชา   (ข้อ 7(2))
  2) แบบขออนุญาตผู้ปกครอง       (ข้อ 6) - 1 หน้าต่อนักเรียน 1 คน
  3) แบบรายงานผล                (ข้อ 13)
เอกสารโครงการ = หัวข้อตามข้อ 9 วรรคสอง (ระเบียบกำหนดหัวข้อ ไม่ได้กำหนดแบบฟอร์ม)
"""
from docx import Document
from docx.shared import Cm

from app.services.doc_page import set_a4
from app.services.build_templates import _font, _p, _p_runs, _sign_table, _set_cell
from app.services.office_doc import _save_doc, _safe, _float_signature
from app.services.fieldtrip import (REG_NAME, TRIP_TYPES, approver_title, counts, cost_amount,
                                    total_cost, COST_BASIS, cost_label)
from app.thai_utils import thai_date, bahttext, _THAI_MONTHS

DOT = "................................"


def _money(v) -> str:
    return f"{v:,.2f}"


def _v(text, dots=DOT) -> str:
    text = (str(text) if text is not None else "").strip()
    return text or dots


def _parts(dt):
    """(วันที่, เดือน, พ.ศ., เวลา) สำหรับช่องในแบบ"""
    if not dt:
        return (DOT[:12], DOT[:18], DOT[:10], DOT[:10])
    return (str(dt.day), _THAI_MONTHS[dt.month], str(dt.year + 543),
            f"{dt.hour:02d}.{dt.minute:02d}")


def _signer(trip, school):
    """ผู้ลงนามแบบขออนุญาต/รายงาน: ไม่พักแรม = ผู้ควบคุมเสนอหัวหน้าสถานศึกษา
    พักแรม/นอกราชอาณาจักร = หัวหน้าสถานศึกษาเสนอผู้อนุญาตตามข้อ 8"""
    if trip.trip_type == "day" and trip.controller:
        return trip.controller.name, trip.controller.position or "ครู"
    name = (school.name or "").strip()
    return (school.director_name or "", "ผู้อำนวยการ" + name if name.startswith("โรงเรียน")
            else (school.director_position or "ผู้อำนวยการโรงเรียน"))


def _head(doc, school, date, to):
    """ส่วนหัวของแบบท้ายระเบียบ: สถานศึกษา / (วัน เดือน ปี) / เรื่อง / เรียน"""
    _p(doc, f"สถานศึกษา {_v(school.name)}", align="right", after=0)
    _p(doc, thai_date(date) if date else "(วัน เดือน ปี) " + DOT, align="right", after=8)
    _p_runs(doc, [("เรื่อง  ", False), ("การพานักเรียนไปนอกสถานศึกษา", False)])
    _p_runs(doc, [("เรียน  ", False), (_v(to), False)], after=6)


def _trip_sentence(trip, c):
    """ข้อความส่วนกลางที่ใช้ร่วมกันในแบบทั้ง 3 (ไปเพื่อ ณ จังหวัด เริ่มออกเดินทาง ... พาหนะ)"""
    d, m, y, t = _parts(trip.depart_at)
    ctrl = trip.controller.name if trip.controller else DOT
    return (f"โดยมี {ctrl} เป็นผู้ควบคุมไปเพื่อ {_v(trip.purpose)} ณ {_v(trip.place)} "
            f"จังหวัด {_v(trip.province)} เริ่มออกเดินทางวันที่ {d} เดือน {m} พ.ศ. {y} "
            f"เวลา {t} น.")


def _sign(doc, name, position, *, float_sig=True):
    tbl = _sign_table(doc, [[("", "center")], [
        ("ขอแสดงความนับถือ", "center"), ("", "center"), ("", "center"),
        (f"({_v(name, DOT + '.........')})", "center"),
        (f"ตำแหน่ง {_v(position)}", "center"),
    ]])
    if float_sig and name:
        _float_signature(tbl.rows[0].cells[1].paragraphs[2], name)


def _new_doc():
    doc = Document(); set_a4(doc)
    _font(doc)
    return doc


# ---------------- 1) แบบขออนุญาตผู้บังคับบัญชา ----------------
def render_request(trip, school) -> str:
    doc = _new_doc()
    c = counts(trip)
    _p(doc, "แบบขออนุญาตผู้บังคับบัญชาพานักเรียน/นักศึกษา", align="center", bold=True, after=0)
    _p(doc, "ไปนอกสถานศึกษา", align="center", bold=True, after=10)
    _head(doc, school, trip.request_date, approver_title(trip, school))
    rd, rm, ry, _ = _parts(trip.return_at)
    total = total_cost(trip)
    body = (f"ข้าพเจ้าขออนุญาตนำนักเรียน มีจำนวน {c['students']} คน และครูควบคุม {c['staff']} คน "
            + _trip_sentence(trip, c)
            + f" และจะไปตามเส้นทางผ่าน {_v(trip.route)} โดยพาหนะ {_v(trip.vehicle)} "
            + f"จะพักค้างที่ {_v(trip.lodging) if trip.trip_type != 'day' else '-'} "
            + f"และกลับถึงสถานศึกษา วันที่ {rd} เดือน {rm} พ.ศ. {ry} "
            + f"ค่าใช้จ่ายทั้งสิ้น จำนวน {_money(total)} บาท ({bahttext(total)}) "
            + "การไปครั้งนี้ได้ปฏิบัติตามระเบียบกระทรวงศึกษาธิการ ว่าด้วยการพานักเรียนและนักศึกษา"
            + "ไปนอกสถานศึกษาแล้ว")
    _p(doc, body, align="justify", indent=2.5, after=12)
    _sign(doc, *_signer(trip, school))
    return _save_doc(doc, _safe(f"ขออนุญาตพานักเรียนไปนอกสถานศึกษา_{trip.id}") + ".docx")


# ---------------- 2) แบบขออนุญาตผู้ปกครอง (รายคน) ----------------
def render_parent_letters(trip, school, students=None) -> str:
    doc = _new_doc()
    c = counts(trip)
    rd, rm, ry, _ = _parts(trip.return_at)
    total = total_cost(trip)
    director = school.director_name or ""
    name = (school.name or "").strip()
    dpos = "ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else (school.director_position or "")
    rows = students if students is not None else list(trip.students)
    if not rows:
        rows = [None]                              # ยังไม่เลือกนักเรียน -> ออกแบบเปล่า 1 หน้า
    for i, st in enumerate(rows):
        if i:
            doc.add_page_break()
        sname = st.name if st else ""
        _p(doc, "แบบขออนุญาตผู้ปกครองพานักเรียน/นักศึกษา", align="center", bold=True, after=0)
        _p(doc, "ไปนอกสถานศึกษา", align="center", bold=True, after=10)
        _head(doc, school, trip.request_date, f"ผู้ปกครองของ {sname}" if sname else "")
        body = (f"ด้วย {_v(school.name)} มีความประสงค์จะขออนุญาตนำ {_v(sname)} ไปศึกษานอกสถานศึกษา "
                f"ในการไปครั้งนี้มีนักเรียน จำนวน {c['students']} คน มีครูควบคุม จำนวน {c['staff']} คน "
                + _trip_sentence(trip, c)
                + f" และจะไปตามเส้นทางผ่าน {_v(trip.route)} โดยพาหนะ {_v(trip.vehicle)} "
                + f"จะพักค้างที่ {_v(trip.lodging) if trip.trip_type != 'day' else '-'} "
                + f"และกลับถึงสถานศึกษา วันที่ {rd} เดือน {rm} พ.ศ. {ry} "
                + f"ค่าใช้จ่ายทั้งสิ้น จำนวน {_money(total)} บาท ({bahttext(total)}) "
                + "การไปครั้งนี้ได้ปฏิบัติตามระเบียบกระทรวงศึกษาธิการ ว่าด้วยการพานักเรียนและนักศึกษา"
                + "ไปนอกสถานศึกษาแล้ว")
        _p(doc, body, align="justify", indent=2.5, after=8)
        _sign(doc, director, dpos)
        _p(doc, "โปรดกรอกแบบข้างล่างนี้แล้วส่งกลับคืนสถานศึกษา", align="center", bold=True, before=4, after=6)
        _p(doc, f"ข้าพเจ้า {DOT}............ ผู้ปกครองของ {_v(sname)}", indent=1.25, after=2)
        _p(doc, "☐  อนุญาต", indent=2.5, after=0)
        _p(doc, f"☐  ไม่อนุญาต  ให้ {_v(sname)} ไปศึกษานอกสถานศึกษาในครั้งนี้", indent=2.5, after=10)
        _sign_table(doc, [[("", "center")], [
            ("ลงชื่อ ........................................ ผู้ปกครอง", "center"),
            ("(........................................)", "center"),
        ]], gap=False)
    return _save_doc(doc, _safe(f"ขออนุญาตผู้ปกครอง_{trip.id}") + ".docx")


# ---------------- 3) แบบรายงานผล ----------------
def render_report(trip, school) -> str:
    doc = _new_doc()
    c = counts(trip)
    _p(doc, "แบบรายงานผลการพานักเรียน/นักศึกษา", align="center", bold=True, after=0)
    _p(doc, "ไปนอกสถานศึกษา", align="center", bold=True, after=10)
    _head(doc, school, trip.report_date, approver_title(trip, school))
    rd, rm, ry, _ = _parts(trip.return_at)
    body = (f"ตามที่ข้าพเจ้าได้รับอนุญาตให้นำนักเรียน มีจำนวน {c['students']} คน ครูควบคุม จำนวน "
            f"{c['staff']} คน " + _trip_sentence(trip, c)
            + f" ได้ไปตามเส้นทางผ่าน {_v(trip.route)} โดยพาหนะ {_v(trip.vehicle)} "
            + f"และได้กลับถึงสถานศึกษา วันที่ {rd} เดือน {rm} พ.ศ. {ry} นั้น")
    _p(doc, body, align="justify", indent=2.5, after=4)
    _p(doc, f"การพานักเรียนไปครั้งนี้ เป็นไปด้วยความ{_v(trip.result)}", indent=2.5, after=2)
    detail = (trip.result_detail or "").strip()
    if detail:
        for line in detail.splitlines():
            if line.strip():
                _p(doc, line.strip(), align="justify", indent=2.5, after=2)
    else:
        for _ in range(3):
            _p(doc, "." * 130, after=2)
    _p(doc, "", after=6)
    _sign(doc, *_signer(trip, school))
    return _save_doc(doc, _safe(f"รายงานผลพานักเรียนไปนอกสถานศึกษา_{trip.id}") + ".docx")


# ---------------- 4) เอกสารโครงการ (หัวข้อตามข้อ 9 วรรคสอง) ----------------
def _lines(text):
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def _grid(doc, headers, rows, widths, aligns=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for cell, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(cell, h, bold=True, align="center", size=15)
        cell.width = Cm(w)
    for r in rows:
        cells = t.add_row().cells
        for i, (cell, val) in enumerate(zip(cells, r)):
            _set_cell(cell, str(val), size=15, align=(aligns[i] if aligns else "left"))
            cell.width = Cm(widths[i])
    _p(doc, "", after=2)
    return t


def render_project(trip, school) -> str:
    doc = _new_doc()
    c = counts(trip)
    _p(doc, f"โครงการ{_v(trip.title)}", align="center", bold=True, size=18, after=8)

    def head(n, text):
        _p(doc, f"{n}. {text}", bold=True, before=4, after=2)

    def body(text):
        _p(doc, text, align="justify", indent=1.25, after=2)

    def items(text, empty="-"):
        rows = _lines(text)
        for i, ln in enumerate(rows or [empty], 1):
            _p(doc, f"{i}) {ln}" if rows else ln, indent=1.25, after=0)

    head(1, "ชื่อโครงการ"); body(_v(trip.title))
    head(2, "หลักการและเหตุผล"); body(_v(trip.principle))
    head(3, "วัตถุประสงค์"); items(trip.objectives)
    head(4, "เป้าหมาย"); items(trip.targets)
    head(5, "ขั้นตอนการดำเนินงาน"); items(trip.steps)
    head(6, "ระยะเวลาและสถานที่ดำเนินการกิจกรรม")
    period = thai_date(trip.depart_at) if trip.depart_at else DOT
    if trip.return_at and (not trip.depart_at or trip.return_at.date() != trip.depart_at.date()):
        period += " ถึง " + thai_date(trip.return_at)
    body(f"วันที่ {period} ณ {_v(trip.place)} จังหวัด {_v(trip.province)} "
         f"({TRIP_TYPES.get(trip.trip_type, {}).get('label', '')})"
         + (f" พักค้างที่ {trip.lodging}" if trip.trip_type != "day" and trip.lodging else ""))
    head(7, "หน่วยงานและผู้รับผิดชอบโครงการ"); body(_v(trip.responsible or school.name))
    head(8, "รายชื่อผู้ควบคุมและผู้ช่วยผู้ควบคุมในการเดินทาง")
    staff = []
    if trip.controller:
        staff.append((trip.controller.name, trip.controller.position or "", "ผู้ควบคุม"))
    staff += [(s.name, s.position, "ผู้ช่วยผู้ควบคุม") for s in trip.staff]
    _grid(doc, ["ที่", "ชื่อ - สกุล", "ตำแหน่ง", "หน้าที่"],
          [(i, n, p, r) for i, (n, p, r) in enumerate(staff, 1)] or [("", "", "", "")],
          [1.2, 6.3, 4.5, 4.0], ["center", "left", "left", "left"])
    head(9, f"รายชื่อนักเรียนที่จะเดินทางไปนอกสถานศึกษา (จำนวน {c['students']} คน)")
    _grid(doc, ["ที่", "ชื่อ - สกุล", "ชั้น", "หมายเหตุ"],
          [(i, s.name, f"{s.level}/{s.room}" if s.room else s.level, "") for i, s in enumerate(trip.students, 1)]
          or [("", "", "", "")], [1.2, 8.3, 2.5, 4.0], ["center", "left", "center", "left"])
    head(10, "แผนที่สังเขปแสดงเส้นทางการเดินทาง และแผนผังแสดงที่ตั้งของสถานที่"
             + ("หรือสถานที่พักแรม" if trip.trip_type != "day" else ""))
    body(f"เส้นทางผ่าน {_v(trip.route)} โดยพาหนะ {_v(trip.vehicle)} (แผนที่และแผนผังแนบท้าย)")
    head(11, "แผนสำรองกรณีเหตุฉุกเฉิน"); items(trip.emergency_plan)
    head(12, "งบประมาณ")
    rows = []
    for i, x in enumerate(trip.costs, 1):
        heads = {"student": c["students"], "person": c["people"]}.get(x.basis)
        calc = (f"{_money(x.rate)} x {heads} คน" if heads is not None else f"{_money(x.rate)}")
        if (x.times or 1) != 1:
            calc += f" x {x.times:g}"
        rows.append((i, cost_label(x), calc, _money(cost_amount(x, c))))
    rows.append(("", "รวมทั้งสิ้น", "", _money(total_cost(trip))))
    _grid(doc, ["ที่", "รายการ", "การคำนวณ", "จำนวนเงิน (บาท)"], rows,
          [1.2, 6.8, 4.5, 3.5], ["center", "left", "left", "right"])
    if trip.project:
        body(f"ใช้งบประมาณจากโครงการ{trip.project.name}")
    _p(doc, f"ทั้งนี้ ดำเนินการตาม{REG_NAME}", align="justify", indent=1.25, before=4, after=10)

    ctrl = trip.controller
    name = (school.name or "").strip()
    dpos = "ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else (school.director_position or "")
    tbl = _sign_table(doc, [
        [("ลงชื่อ ................................ ผู้เสนอโครงการ", "center"),
         (f"({_v(ctrl.name if ctrl else '')})", "center"),
         (_v(ctrl.position if ctrl else ""), "center")],
        [("ลงชื่อ ................................ ผู้อนุมัติโครงการ", "center"),
         (f"({_v(school.director_name)})", "center"), (dpos, "center")],
    ])
    if ctrl:
        _float_signature(tbl.rows[0].cells[0].paragraphs[0], ctrl.name)
    _float_signature(tbl.rows[0].cells[1].paragraphs[0], school.director_name)
    return _save_doc(doc, _safe(f"โครงการทัศนศึกษา_{trip.id}") + ".docx")


def order_body(trip, school) -> str:
    """เนื้อความคำสั่งแต่งตั้งผู้ควบคุม/ผู้ช่วยผู้ควบคุม (ข้อ 7(3)) - ใช้แบบคำสั่งโรงเรียนเดิมของระบบ"""
    c = counts(trip)
    d = thai_date(trip.depart_at) if trip.depart_at else DOT
    lines = [
        f"ด้วย{_v(school.name)} จะนำนักเรียน จำนวน {c['students']} คน ไป{_v(trip.purpose)} ณ {_v(trip.place)} "
        f"จังหวัด {_v(trip.province)} ในวันที่ {d} ซึ่ง{REG_NAME} ข้อ 7(3) กำหนดให้มีผู้ควบคุม 1 คน "
        f"และผู้ช่วยผู้ควบคุม 1 คน ต่อนักเรียนไม่เกิน 30 คน",
        "จึงแต่งตั้งบุคลากรดังต่อไปนี้",
    ]
    n = 1
    if trip.controller:
        lines.append(f"{n}. {trip.controller.name} ตำแหน่ง {trip.controller.position or 'ครู'} ผู้ควบคุม")
        n += 1
    for s in trip.staff:
        lines.append(f"{n}. {s.name} ตำแหน่ง {s.position or 'ครู'} ผู้ช่วยผู้ควบคุม")
        n += 1
    lines.append("ให้ผู้ที่ได้รับแต่งตั้งปฏิบัติหน้าที่ตามระเบียบดังกล่าว ข้อ 10 ข้อ 11"
                 + (" และข้อ 12" if trip.trip_type == "overnight" else "")
                 + " อย่างเคร่งครัด โดยคำนึงถึงความปลอดภัยของนักเรียนเป็นอันดับแรก")
    lines.append("ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป")
    return "\n".join(lines)


# ---------------- 5) เอกสารแนบ 2 ท้ายหนังสือ สพฐ. ว 2983 ----------------
def render_allowance(trip, school) -> str:
    """แบบใบสำคัญรับเงินค่าใช้จ่ายในการจัดกิจกรรมสำหรับนักเรียน (เอกสารแนบ 2)
    ยกหัวเรื่อง/คอลัมน์ตามแบบแนบท้ายหนังสือ สพฐ. ที่ ศธ 04002/ว 2983 ลว. 23 พ.ย. 2555
    ช่อง "ที่อยู่" เว้นว่างให้กรอกด้วยลายมือ (ระบบไม่เก็บที่อยู่นักเรียน)"""
    from app.services.build_templates import _repeat_header_row, _no_split_row, _fixed_cols
    from app.services.fieldtrip import cost_amount
    doc = Document(); set_a4(doc, landscape=True); _font(doc)
    c = counts(trip)
    per_student = {"allowance": 0.0}
    one = dict(c, students=1, people=1)
    for x in trip.costs:
        if x.pay_method == "allowance":
            per_student["allowance"] += cost_amount(x, one)
    food = round(per_student["allowance"], 2)
    d1, m1, y1, _ = _parts(trip.depart_at)
    d2, m2, y2, _ = _parts(trip.return_at)
    area = (school.area_office or "").strip()

    _p(doc, "เอกสารแนบ 2", align="right", size=14, after=0)
    _p(doc, "แบบใบสำคัญรับเงินค่าใช้จ่ายในการจัดกิจกรรมสำหรับนักเรียน", align="center", bold=True, size=17, after=4)
    _p(doc, f"ชื่อส่วนราชการผู้จัดกิจกรรม {_v(school.name)}    โครงการ/หลักสูตร/กิจกรรม {_v(trip.title)}",
       size=15, after=0)
    _p(doc, f"วันที่ {d1} เดือน {m1} พ.ศ. {y1}  ถึงวันที่ {d2} เดือน {m2} พ.ศ. {y2}    "
            f"จำนวนผู้เข้าร่วมกิจกรรมทั้งสิ้น {c['students']} คน", size=15, after=0)
    _p(doc, f"ผู้เข้าร่วมกิจกรรม ได้รับเงินจากโรงเรียน {_v(school.name)}  สังกัด {_v(area)}", size=15, after=0)
    _p(doc, "ปรากฏรายละเอียดดังนี้", size=15, after=4)

    headers = ["ลำดับที่", "ชื่อ - สกุล", "ที่อยู่", "ค่าอาหาร\n(บาท)", "ค่าเช่าที่พัก\n(บาท)",
               "ค่าพาหนะ\n(บาท)", "รวมเป็นเงิน\n(บาท)", "วัน เดือน ปี\nที่รับเงิน", "ลายมือชื่อ\nผู้รับเงิน"]
    widths = [Cm(1.4), Cm(5.0), Cm(4.4), Cm(2.2), Cm(2.3), Cm(2.2), Cm(2.4), Cm(2.6), Cm(4.0)]
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for cell, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(cell, h, bold=True, align="center", size=13)
        cell.width = w
    money = _money(food) if food else ""
    for i, s in enumerate(trip.students, 1):
        r = t.add_row(); _no_split_row(r)
        vals = [str(i), s.name, "", money, "-", "-", money, "", ""]
        for j, (cell, v, w) in enumerate(zip(r.cells, vals, widths)):
            _set_cell(cell, v, size=13, align="left" if j == 1 else ("right" if j in (3, 6) else "center"))
            cell.width = w
    r = t.add_row(); _no_split_row(r)
    _set_cell(r.cells[1], "รวมเป็นเงินทั้งสิ้น", bold=True, align="right", size=13)
    total = round(food * c["students"], 2)
    _set_cell(r.cells[3], _money(total) if total else "", bold=True, align="right", size=13)
    _set_cell(r.cells[6], _money(total) if total else "", bold=True, align="right", size=13)
    for cell, w in zip(r.cells, widths):
        cell.width = w
    if total:
        _p(doc, f"({bahttext(total)})", align="center", size=14, before=2, after=6)
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ...................................... ผู้จ่ายเงิน", "center"),
        ("(......................................)", "center"),
        ("ตำแหน่ง ......................................", "center"),
    ]])
    return _save_doc(doc, _safe(f"ใบสำคัญรับเงินนักเรียน_เอกสารแนบ2_{trip.id}") + ".docx")
