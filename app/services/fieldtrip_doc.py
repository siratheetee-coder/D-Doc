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
    if trip.trip_type == "day" and trip.ctrl_name:
        return trip.ctrl_name, trip.ctrl_pos or "ครู"
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
    ctrl = trip.ctrl_name or DOT
    return (f"โดยมี {ctrl} เป็นผู้ควบคุมไปเพื่อ{_v(_aim(trip))} ณ {_v(trip.place)} "
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
    if trip.ctrl_name:
        staff.append((trip.ctrl_name, trip.ctrl_pos or "", "ผู้ควบคุม"))
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

    ctrl_n, ctrl_p = trip.ctrl_name, trip.ctrl_pos
    name = (school.name or "").strip()
    dpos = "ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else (school.director_position or "")
    tbl = _sign_table(doc, [
        [("ลงชื่อ ................................ ผู้เสนอโครงการ", "center"),
         (f"({_v(ctrl_n)})", "center"),
         (_v(ctrl_p), "center")],
        [("ลงชื่อ ................................ ผู้อนุมัติโครงการ", "center"),
         (f"({_v(school.director_name)})", "center"), (dpos, "center")],
    ])
    if ctrl_n:
        _float_signature(tbl.rows[0].cells[0].paragraphs[0], ctrl_n)
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
    if trip.ctrl_name:
        lines.append(f"{n}. {trip.ctrl_name} ตำแหน่ง {trip.ctrl_pos or 'ครู'} ผู้ควบคุม")
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


# ---------------- 6) ใบเบิกค่าใช้จ่ายในการเดินทางไปราชการ (แบบ 8708) ----------------
_O, _X = "○", "◉"


def _duration(a, b):
    """รวมเวลาไปราชการ (วัน, ชั่วโมง) จากเวลาออกถึงเวลากลับ"""
    if not (a and b) or b < a:
        return ("....", "....")
    secs = int((b - a).total_seconds())
    return (str(secs // 86400), str((secs % 86400) // 3600))


def render_travel_claim(trip, school) -> str:
    """แบบ 8708 ส่วนที่ 1 (ใบเบิก - คณะเดินทาง) + ส่วนที่ 2 (หลักฐานการจ่ายเงิน รายคน)
    ยกช่องตามแบบของกรมบัญชีกลาง · ผู้ขอรับเงิน = ผู้ควบคุม (หัวหน้าคณะ)"""
    from sqlalchemy.orm import object_session
    from docx.enum.section import WD_ORIENT, WD_SECTION
    from app.models import MoneyLoan, SchoolOrder
    from app.services.build_templates import _repeat_header_row, _no_split_row, _fixed_cols
    from app.services.fieldtrip import travel_costs, staff_people, cost_label
    db = object_session(trip)
    loan = db.get(MoneyLoan, trip.loan_id) if (db and trip.loan_id) else None
    order = db.get(SchoolOrder, trip.order_id) if (db and trip.order_id) else None
    c = counts(trip)
    people = staff_people(trip)
    costs = travel_costs(trip)
    per_person = sum(cost_amount(x, dict(c, staff=1, students=0, people=1)) for x in costs)
    total = round(sum(cost_amount(x, c) for x in costs), 2)
    days_claim = max((x.times or 0) for x in costs) if costs else 0
    name = (school.name or "").strip()
    dpos = "ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else (school.director_position or "")
    ctrl_name, ctrl_pos = (people[0][0], people[0][1]) if people else ("", "")

    doc = _new_doc()
    t = doc.add_table(rows=2, cols=2)
    from app.services.build_templates import _no_borders
    _no_borders(t)
    _set_cell(t.rows[0].cells[0], f"สัญญาเงินยืมเลขที่ {_v(loan.contract_no if loan else '')}  วันที่ "
              f"{thai_date(loan.date) if loan and loan.date else DOT}", size=14)
    _set_cell(t.rows[0].cells[1], "ส่วนที่ 1", align="right", size=14)
    _set_cell(t.rows[1].cells[0], f"ชื่อผู้ยืม {_v(loan.borrower if loan else '')}  จำนวนเงิน "
              f"{_money(loan.amount) if loan else DOT} บาท", size=14)
    _set_cell(t.rows[1].cells[1], "แบบ 8708", align="right", size=14)
    from app.services.build_templates import _fixed_cols as _fc
    _fc(t, [Cm(13.5), Cm(2.5)])
    _p(doc, "ใบเบิกค่าใช้จ่ายในการเดินทางไปราชการ", align="center", bold=True, size=18, before=6, after=6)
    _p(doc, f"ที่ทำการ {_v(school.name)}", align="right", after=0)
    _p(doc, "วันที่ .......... เดือน .......................... พ.ศ. ..........", align="right", after=6)
    _p_runs(doc, [("เรื่อง  ", False), ("ขออนุมัติเบิกค่าใช้จ่ายในการเดินทางไปราชการ", False)])
    _p_runs(doc, [("เรียน  ", False), (dpos or DOT, False)], after=6)

    others = ", ".join(f"{n} ตำแหน่ง {p}" for n, p, _ in people[1:]) or "-"
    d1, m1, y1, t1 = _parts(trip.depart_at)
    d2, m2, y2, t2 = _parts(trip.return_at)
    dd, hh = _duration(trip.depart_at, trip.return_at)
    body = (f"ตามคำสั่ง/บันทึกที่ {_v(order.order_no if order else '')} ลงวันที่ "
            f"{thai_date(order.date) if order and order.date else DOT} ได้อนุมัติให้ ข้าพเจ้า {_v(ctrl_name)} "
            f"ตำแหน่ง {_v(ctrl_pos)} สังกัด {_v(school.name)} พร้อมด้วย {others} "
            f"เดินทางไปปฏิบัติราชการ ควบคุมนักเรียนไป{_v(trip.purpose)} ณ {_v(trip.place)} จังหวัด {_v(trip.province)} "
            f"โดยออกเดินทางจาก {_O} บ้านพัก {_X} สำนักงาน {_O} ประเทศไทย ตั้งแต่วันที่ {d1} เดือน {m1} พ.ศ. {y1} "
            f"เวลา {t1} น. และกลับถึง {_O} บ้านพัก {_X} สำนักงาน {_O} ประเทศไทย วันที่ {d2} เดือน {m2} พ.ศ. {y2} "
            f"เวลา {t2} น. รวมเวลาไปราชการครั้งนี้ {dd} วัน {hh} ชั่วโมง")
    _p(doc, body, align="justify", indent=2.5, after=6)
    group = len(people) > 1
    _p(doc, f"ข้าพเจ้าขอเบิกค่าใช้จ่ายในการเดินทางไปราชการสำหรับ {_X if not group else _O} ข้าพเจ้า "
            f"{_X if group else _O} คณะเดินทาง ดังนี้", indent=2.5, after=2)
    _p(doc, f"ค่าเบี้ยเลี้ยงเดินทางประเภท ......................  จำนวน {days_claim:g} วัน  รวม {_money(total)} บาท"
            if costs else f"ค่าเบี้ยเลี้ยงเดินทางประเภท ...................... จำนวน ...... วัน รวม {DOT} บาท", after=0)
    _p(doc, f"ค่าเช่าที่พักประเภท ...................... จำนวน ...... วัน รวม {DOT} บาท", after=0)
    _p(doc, f"ค่าพาหนะ ................................................ รวม {DOT} บาท", after=0)
    _p(doc, f"ค่าใช้จ่ายอื่น ............................................ รวม {DOT} บาท", after=0)
    _p(doc, f"รวมเงินทั้งสิ้น {_money(total) if total else DOT} บาท", align="right", after=0)
    _p(doc, f"จำนวนเงิน (ตัวอักษร) {bahttext(total) if total else DOT}", after=6)
    _p(doc, "ข้าพเจ้าขอรับรองว่ารายการที่กล่าวมาข้างต้นเป็นความจริง และหลักฐานการจ่ายที่ส่งมาด้วย จำนวน "
            ".......... ฉบับ รวมทั้งจำนวนเงินที่ขอเบิกถูกต้องตามกฎหมายทุกประการ", align="justify", indent=2.5, after=10)
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ...................................... ผู้ขอรับเงิน", "center"),
        (f"({_v(ctrl_name)})", "center"), (f"ตำแหน่ง {_v(ctrl_pos)}", "center")]])

    doc.add_page_break()
    _p(doc, "- 2 -", align="center", after=6)
    box = doc.add_table(rows=1, cols=2)
    box.style = "Table Grid"
    for cell, head in zip(box.rows[0].cells, ("ได้ตรวจสอบหลักฐานการเบิกจ่ายเงินที่แนบถูกต้องแล้ว\nเห็นควรอนุมัติให้เบิกจ่ายได้",
                                              "อนุมัติให้จ่ายได้")):
        _set_cell(cell, head + "\n\nลงชื่อ ......................................\n(......................................)\n"
                  "ตำแหน่ง ......................................\nวันที่ ......................................", size=15)
    _p(doc, "", after=4)
    _p(doc, f"ได้รับเงินค่าใช้จ่ายในการเดินทางไปราชการ จำนวน {_money(total) if total else DOT} บาท "
            f"({bahttext(total) if total else DOT}) ไว้เป็นการถูกต้องแล้ว", align="justify", indent=2.5, after=10)
    _sign_table(doc, [
        [("ลงชื่อ ............................ ผู้รับเงิน", "center"), ("(......................................)", "center"),
         ("ตำแหน่ง ......................................", "center"), ("วันที่ ......................................", "center")],
        [("ลงชื่อ ............................ ผู้จ่ายเงิน", "center"), ("(......................................)", "center"),
         ("ตำแหน่ง ......................................", "center"), ("วันที่ ......................................", "center")],
    ])
    _p(doc, f"จากเงินยืมตามสัญญาเลขที่ {_v(loan.contract_no if loan else '')} วันที่ "
            f"{thai_date(loan.date) if loan and loan.date else DOT}", after=6)
    _p(doc, "หมายเหตุ  ในการเดินทางครั้งนี้เป็นการควบคุมนักเรียนไปนอกสถานศึกษา ตามระเบียบกระทรวงศึกษาธิการ "
            "ว่าด้วยการพานักเรียน และนักศึกษาไปนอกสถานศึกษา พ.ศ. 2562 ข้อ 14", align="justify", after=4)

    # ส่วนที่ 2 (แนวนอน)
    sec = doc.add_section(WD_SECTION.NEW_PAGE)
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = sec.page_height, sec.page_width
    _p(doc, "ส่วนที่ 2", align="right", size=14, after=0)
    _p(doc, "แบบ 8708", align="right", size=14, after=0)
    _p(doc, "หลักฐานการจ่ายเงินค่าใช้จ่ายในการเดินทางไปราชการ", align="center", bold=True, size=17, after=2)
    _p(doc, f"ชื่อส่วนราชการ {_v(school.name)}  จังหวัด {_v(school.province)}", align="center", size=15, after=0)
    _p(doc, f"ประกอบใบเบิกค่าใช้จ่ายในการเดินทางของ {_v(ctrl_name)}  ลงวันที่ .......... เดือน .................. พ.ศ. ..........",
       align="center", size=15, after=4)
    headers = ["ลำดับที่", "ชื่อ", "ตำแหน่ง", "ค่าเบี้ยเลี้ยง", "ค่าเช่าที่พัก", "ค่าพาหนะ", "ค่าใช้จ่ายอื่น",
               "รวม", "ลายมือชื่อ\nผู้รับเงิน", "วัน เดือน ปี\nที่รับเงิน", "หมายเหตุ"]
    widths = [Cm(1.3), Cm(4.4), Cm(3.4), Cm(2.0), Cm(2.0), Cm(1.9), Cm(2.0), Cm(2.0), Cm(3.0), Cm(2.4), Cm(2.2)]
    tb = doc.add_table(rows=1, cols=len(headers))
    tb.style = "Table Grid"
    _fixed_cols(tb, widths)
    _repeat_header_row(tb.rows[0]); _no_split_row(tb.rows[0])
    for cell, h, w in zip(tb.rows[0].cells, headers, widths):
        _set_cell(cell, h, bold=True, align="center", size=13)
        cell.width = w
    rate_note = ", ".join(f"{x.rate:,.0f} บ. x {x.times:g} วัน" for x in costs)
    for i, (n, p, _) in enumerate(people, 1):
        r = tb.add_row(); _no_split_row(r)
        amt = _money(per_person) if per_person else ""
        for j, (cell, v, w) in enumerate(zip(r.cells, [str(i), n, p, amt, "", "", "", amt, "", "", rate_note], widths)):
            _set_cell(cell, v, size=13, align="left" if j in (1, 2, 10) else ("right" if j in (3, 7) else "center"))
            cell.width = w
    r = tb.add_row(); _no_split_row(r)
    _set_cell(r.cells[2], "รวมเงิน", bold=True, align="right", size=13)
    _set_cell(r.cells[3], _money(total) if total else "", bold=True, align="right", size=13)
    _set_cell(r.cells[7], _money(total) if total else "", bold=True, align="right", size=13)
    _set_cell(r.cells[8], f"ตามสัญญาเงินยืมเลขที่ {loan.contract_no if loan and loan.contract_no else '.......'}", size=12)
    for cell, w in zip(r.cells, widths):
        cell.width = w
    _p(doc, f"จำนวนเงินรวมทั้งสิ้น (ตัวอักษร) {bahttext(total) if total else DOT}", size=15, before=4, after=6)
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ...................................... ผู้จ่ายเงิน", "center"),
        ("(......................................)", "center"),
        ("ตำแหน่ง ......................................", "center"),
        ("วันที่ ......................................", "center")]])
    return _save_doc(doc, _safe(f"ใบเบิกค่าเดินทางไปราชการ_8708_{trip.id}") + ".docx")


# ======================================================================
# ชุดบันทึกข้อความ (ตามแบบที่โรงเรียนใช้จริง) + กำหนดการ + ใบลงเวลา + คำสั่งแบบตาราง
# ======================================================================


def level_text(trip) -> str:
    """ระดับชั้นที่ไป แบบช่วง (ชั้นแรก ถึง ชั้นสุดท้าย) - ใช้ helper กลาง thai_utils.level_range"""
    from app.thai_utils import level_range
    return level_range(s.level for s in trip.students) or DOT


def _aim(trip) -> str:
    """จุดประสงค์ ตัดคำว่า 'เพื่อ' นำหน้าออก (เอกสารเขียน 'ไปเพื่อ ...' อยู่แล้ว)"""
    t = (trip.purpose or "").strip()
    return t[len("เพื่อ"):].strip() if t.startswith("เพื่อ") else t


def _period_text(trip) -> str:
    if not trip.depart_at:
        return DOT
    if trip.return_at and trip.return_at.date() != trip.depart_at.date():
        return f"{thai_date(trip.depart_at)} ถึงวันที่ {thai_date(trip.return_at)}"
    return thai_date(trip.depart_at)


def _year_of(trip) -> str:
    return str(trip.year or "")


def _memo_head(doc, school, subject, to):
    from app.services.build_templates import _krut_and_title, _hr
    _krut_and_title(doc)
    _p_runs(doc, [("ส่วนราชการ  ", True), (f"{_v(school.name)}", False)])
    _p_runs(doc, [("ที่  ", True), ("......................................", False), ("\t", False),
                  ("วันที่  ", True), ("......................................", False)], tab_cm=8)
    _p_runs(doc, [("เรื่อง  ", True), (subject, False)])
    _hr(doc)
    _p_runs(doc, [("เรียน  ", False), (to, False)], after=6)


def _director_title(school) -> str:
    name = (school.name or "").strip()
    return "ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else (school.director_position or "ผู้อำนวยการโรงเรียน")


def render_request_memo(trip, school) -> str:
    """บันทึกข้อความขออนุญาตพานักเรียนไปทัศนศึกษา (ครูผู้รับผิดชอบเสนอ ผอ.)
    เนื้อความตามแบบขออนุญาตผู้บังคับบัญชาท้ายระเบียบฯ 2562 จัดเป็นบันทึกข้อความแบบที่โรงเรียนใช้"""
    doc = _new_doc()
    c = counts(trip)
    total = total_cost(trip)
    d1, m1, y1, t1 = _parts(trip.depart_at)
    d2, m2, y2, t2 = _parts(trip.return_at)
    _memo_head(doc, school, f"ขออนุญาตพานักเรียนไป{_v(trip.title)} ประจำปีการศึกษา {_year_of(trip)}",
               approver_title(trip, school) or _director_title(school))
    lodging = f" พักค้างที่ {trip.lodging}" if trip.trip_type != "day" and (trip.lodging or "").strip() else ""
    _p(doc, f"ข้าพเจ้าขออนุญาตนำนักเรียน ระดับ{level_text(trip)} มีจำนวน {c['students']} คน และครูควบคุม "
            f"{c['staff']} คน โดยมี {_v(trip.ctrl_name)} เป็นผู้ควบคุมไปเพื่อ{_v(_aim(trip))} ณ {_v(trip.place)} "
            f"จังหวัด {_v(trip.province)} เริ่มออกเดินทางวันที่ {d1} เดือน {m1} พ.ศ. {y1} เวลา {t1} น. "
            f"และจะไปตามเส้นทางผ่าน {_v(trip.route)} โดย{_v(trip.vehicle)}{lodging} "
            f"และกลับถึงสถานศึกษา วันที่ {d2} เดือน {m2} พ.ศ. {y2} เวลา {t2} น. "
            f"ค่าใช้จ่ายทั้งสิ้น จำนวน {_money(total)} บาท ({bahttext(total)})",
       align="justify", indent=2.5, after=4)
    _p(doc, "การไปครั้งนี้ได้ปฏิบัติตามระเบียบกระทรวงศึกษาธิการว่าด้วยการพานักเรียนและนักศึกษาไปนอกสถานศึกษาแล้ว",
       align="justify", indent=2.5, after=4)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณา", indent=2.5, after=16)
    tbl = _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ......................................", "center"),
        (f"({_v(trip.ctrl_name)})", "center"), ("ครูผู้รับผิดชอบโครงการ", "center")]])
    if trip.ctrl_name:
        _float_signature(tbl.rows[0].cells[1].paragraphs[0], trip.ctrl_name)
    return _save_doc(doc, _safe(f"บันทึกขออนุญาตพานักเรียนไปนอกสถานศึกษา_{trip.id}") + ".docx")


REPORT_OK = ("ในการนี้ การดำเนินกิจกรรมดังกล่าวเสร็จเป็นที่เรียบร้อยแล้ว นักเรียนและครูผู้ควบคุมเดินทางกลับถึง"
             "สถานศึกษาโดยสวัสดิภาพ จึงขอส่งสรุปผลการดำเนินกิจกรรม \"{title}\" ประจำปีการศึกษา {year} "
             "พร้อมสรุปข้อเสนอแนะและแนวทางในการพัฒนางานต่อไป")
REPORT_BAD = ("ในการนี้ การดำเนินกิจกรรมดังกล่าวได้ดำเนินการแล้ว แต่มีเหตุการณ์ที่ไม่เรียบร้อย ดังนี้ {detail} "
              "จึงขอรายงานผลการดำเนินกิจกรรม \"{title}\" ประจำปีการศึกษา {year} มาเพื่อทราบ")


def render_report_memo(trip, school) -> str:
    """บันทึกข้อความรายงานผลการดำเนินกิจกรรม (ข้อ 13) - ผู้ใช้ติ๊กแค่ เรียบร้อย/ไม่เรียบร้อย ระบบเขียนให้"""
    doc = _new_doc()
    c = counts(trip)
    title = _v(trip.title)
    _memo_head(doc, school, f"รายงานผลการดำเนินกิจกรรม \"{title}\" ประจำปีการศึกษา {_year_of(trip)}",
               _director_title(school))
    _p(doc, f"ด้วยข้าพเจ้า {_v(trip.ctrl_name)} ตำแหน่ง {_v(trip.ctrl_pos)} ได้รับมอบหมายให้ดำเนินกิจกรรม "
            f"\"{title}\" ประจำปีการศึกษา {_year_of(trip)} โดยนำนักเรียน จำนวน {c['students']} คน และครูผู้ควบคุม "
            f"จำนวน {c['staff']} คน ไป ณ {_v(trip.place)} จังหวัด {_v(trip.province)} ในวันที่ {_period_text(trip)} "
            f"โดยมีวัตถุประสงค์เพื่อ{_v(_aim(trip))}", align="justify", indent=2.5, after=4)
    if trip.result == "ไม่เรียบร้อย":
        text = REPORT_BAD.format(detail=_v(trip.result_detail), title=title, year=_year_of(trip))
    else:
        text = REPORT_OK.format(title=title, year=_year_of(trip))
    _p(doc, text, align="justify", indent=2.5, after=4)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณา", indent=2.5, after=14)
    tbl = _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ......................................", "center"),
        (f"({_v(trip.ctrl_name)})", "center"), ("ผู้รายงานกิจกรรม", "center")]])
    if trip.ctrl_name:
        _float_signature(tbl.rows[0].cells[1].paragraphs[0], trip.ctrl_name)
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    box = doc.add_table(rows=1, cols=1)
    box.style = "Table Grid"
    cell = box.rows[0].cells[0]
    lines = [("ความเห็นของผู้บริหารโรงเรียน", True, "left"), ("." * 168, False, "left"), ("." * 168, False, "left"),
             ("", False, "left"), ("ลงชื่อ ......................................", False, "center"),
             (f"({_v(school.director_name)})", False, "center"), (_director_title(school), False, "center")]
    for i, (txt, bold, al) in enumerate(lines):
        para = cell.paragraphs[0] if i == 0 else cell.add_paragraph()
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER if al == "center" else WD_ALIGN_PARAGRAPH.LEFT
        para.paragraph_format.space_after = Pt(0)
        run = para.add_run(txt)
        from app.services.build_templates import _csize, _bcs, THAI_FONT
        from docx.oxml.ns import qn
        _csize(run, 16); _bcs(run, bold); run.font.name = THAI_FONT
        run._element.rPr.rFonts.set(qn("w:cs"), THAI_FONT)
    return _save_doc(doc, _safe(f"บันทึกรายงานผลทัศนศึกษา_{trip.id}") + ".docx")


def schedule_rows(trip) -> list:
    import json
    try:
        rows = json.loads(trip.schedule or "[]")
        return [r for r in rows if isinstance(r, dict)]
    except (ValueError, TypeError):
        return []


def default_schedule(trip, school) -> list:
    """กำหนดการตัวอย่าง (ตามแบบที่โรงเรียนใช้) คำนวณจากเวลาไป-กลับ ผู้ใช้แก้ต่อได้"""
    from datetime import timedelta
    dep = trip.depart_at
    ret = trip.return_at
    hm = lambda d: f"{d:%H.%M}"
    if not (dep and ret) or not (dep.hour or dep.minute) or ret <= dep:
        return [{"day": "", "time": "", "act": "นักเรียนรายงานตัว คณะครูให้ความรู้และแนวปฏิบัติในการทัศนศึกษา"}]
    place = trip.place or "......"
    rows = [
        {"day": "", "time": f"{hm(dep - timedelta(minutes=30))} - {hm(dep)} น.",
         "act": "นักเรียนรายงานตัวร่วมกิจกรรม คณะครูให้ความรู้และแนวปฏิบัติในการทัศนศึกษา"},
        {"day": "", "time": f"{hm(dep)} - 10.00 น.", "act": f"ออกเดินทางไป {place}"},
        {"day": "", "time": "10.00 - 12.00 น.", "act": f"เข้าชม/ทำกิจกรรม ณ {place}"},
        {"day": "", "time": "12.00 - 13.00 น.", "act": "พักรับประทานอาหารกลางวัน"},
        {"day": "", "time": "13.00 - 15.00 น.", "act": "เข้าชม/ทำกิจกรรม (ต่อ) และสรุปการเรียนรู้"},
        {"day": "", "time": f"15.00 - {hm(ret)} น.", "act": "เดินทางกลับโรงเรียน"},
        {"day": "", "time": f"{hm(ret)} น.", "act": f"เดินทางกลับถึง{school.name or 'โรงเรียน'} โดยสวัสดิภาพ"},
    ]
    if ret.date() != dep.date():
        rows[0]["day"] = f"วันที่ {thai_date(dep)}"
        rows[-2]["day"] = f"วันที่ {thai_date(ret)}"
    return rows


def render_schedule(trip, school) -> str:
    """กำหนดการกิจกรรมโครงการทัศนศึกษา (ตามแบบที่โรงเรียนใช้)"""
    from app.services.build_templates import _no_borders, _fixed_cols
    doc = _new_doc()
    _p(doc, f"กำหนดการกิจกรรมโครงการ{_v(trip.title)} ประจำปีการศึกษา {_year_of(trip)}", align="center", bold=True,
       size=17, after=0)
    _p(doc, f"นักเรียน{level_text(trip)} {_v(school.name)}", align="center", bold=True, after=0)
    _p(doc, f"ณ {_v(trip.place)} จังหวัด {_v(trip.province)}", align="center", bold=True, after=0)
    _p(doc, f"ในวันที่ {_period_text(trip)}", align="center", bold=True, after=10)
    rows = schedule_rows(trip) or default_schedule(trip, school)
    t = doc.add_table(rows=0, cols=2)
    _no_borders(t)
    _fixed_cols(t, [Cm(4.2), Cm(11.8)])
    for r in rows:
        if (r.get("day") or "").strip():
            cells = t.add_row().cells
            _set_cell(cells[0], r["day"].strip(), bold=True, size=16)
            cells[0].merge(cells[1])
        cells = t.add_row().cells
        _set_cell(cells[0], (r.get("time") or "").strip(), size=16)
        _set_cell(cells[1], (r.get("act") or "").strip(), size=16)
    _p(doc, "", after=6)
    _p(doc, "*******************************", after=2)
    _p_runs(doc, [("*หมายเหตุ*  ", True), ("กำหนดการอาจเปลี่ยนแปลงได้ตามความเหมาะสม", False)])
    return _save_doc(doc, _safe(f"กำหนดการทัศนศึกษา_{trip.id}") + ".docx")


def render_signin(trip, school, who="students") -> str:
    """ใบลงเวลา มา/กลับ แยกนักเรียน กับ ครู (ลงชื่อ เวลามา ลงชื่อ เวลากลับ หมายเหตุ)"""
    from docx.enum.section import WD_ORIENT
    from app.services.build_templates import _repeat_header_row, _no_split_row, _fixed_cols
    from app.services.fieldtrip import staff_people
    doc = Document(); set_a4(doc, landscape=True); _font(doc)
    is_stu = who == "students"
    head = "บัญชีลงเวลานักเรียน" if is_stu else "บัญชีลงเวลาครูผู้ควบคุมและผู้ช่วยผู้ควบคุม"
    _p(doc, f"{head} การพานักเรียนไปนอกสถานศึกษา", align="center", bold=True, size=17, after=0)
    _p(doc, f"กิจกรรม {_v(trip.title)}  ณ {_v(trip.place)} จังหวัด {_v(trip.province)}", align="center", size=15, after=0)
    _p(doc, f"วันที่ {_period_text(trip)}   {_v(school.name)}", align="center", size=15, after=6)
    col3 = "ชั้น" if is_stu else "ตำแหน่ง / หน้าที่"
    headers = ["ที่", "ชื่อ - สกุล", col3, "ลงชื่อ (มา)", "เวลามา", "ลงชื่อ (กลับ)", "เวลากลับ", "หมายเหตุ"]
    widths = [Cm(1.2), Cm(6.2), Cm(3.6 if not is_stu else 2.0), Cm(4.0), Cm(2.0), Cm(4.0), Cm(2.0),
              Cm(2.7 if not is_stu else 4.3)]
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for cell, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(cell, h, bold=True, align="center", size=14)
        cell.width = w
    if is_stu:
        rows = [(s.name, f"{s.level}/{s.room}" if s.room else s.level) for s in trip.students]
    else:
        rows = [(n, f"{p} / {r}") for n, p, r in staff_people(trip)]
    from docx.enum.table import WD_ROW_HEIGHT_RULE
    for i, (n, x) in enumerate(rows, 1):
        r = t.add_row(); _no_split_row(r)
        r.height = Cm(0.95); r.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST   # พื้นที่พอให้เซ็นชื่อ
        for j, (cell, v, w) in enumerate(zip(r.cells, [str(i), n, x, "", "", "", "", ""], widths)):
            _set_cell(cell, v, size=14, align="left" if j in (1, 2) and not (is_stu and j == 2) else "center")
            cell.width = w
    _p(doc, f"รวม {len(rows)} คน", size=15, before=4, after=8)
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ...................................... ผู้ควบคุม", "center"),
        (f"({_v(trip.ctrl_name)})", "center")]])
    return _save_doc(doc, _safe(f"ใบลงเวลา{'นักเรียน' if is_stu else 'ครู'}_ทัศนศึกษา_{trip.id}") + ".docx")


def render_trip_order(trip, order, school) -> str:
    """คำสั่งแต่งตั้งผู้ควบคุม/ผู้ช่วยผู้ควบคุม - รายชื่อจัดเป็นตารางไร้เส้น (ชื่อ ตำแหน่ง หน้าที่ ตรงกันทุกบรรทัด)
    หัว/ท้ายเหมือนแบบคำสั่งโรงเรียนเดิมของระบบ (office_doc.render_order)"""
    from app.services.build_templates import _krut_center, _no_borders, _fixed_cols
    from app.services.office_doc import _director_office
    from app.services.fieldtrip import staff_people
    from app.thai_utils import thai_date_official
    doc = _new_doc()
    _krut_center(doc, height_cm=1.8)
    _p(doc, "คำสั่ง" + (school.name or ""), align="center", bold=True, size=18, after=0)
    _p(doc, "ที่ " + (order.order_no or ""), align="center", bold=True, after=0)
    _p(doc, "เรื่อง " + (order.subject or ""), align="center", bold=True, after=0)
    _p(doc, "─────────────────────", align="center", after=6)
    c = counts(trip)
    _p(doc, f"ด้วย{_v(school.name)} จะนำนักเรียน จำนวน {c['students']} คน ไป{_v(trip.purpose)} ณ {_v(trip.place)} "
            f"จังหวัด {_v(trip.province)} ในวันที่ {_period_text(trip)} ซึ่ง{REG_NAME} ข้อ 7(3) กำหนดให้มีผู้ควบคุม 1 คน "
            f"และผู้ช่วยผู้ควบคุม 1 คน ต่อนักเรียนไม่เกิน 30 คน", align="justify", indent=2.5, after=2)
    _p(doc, "จึงแต่งตั้งบุคลากรดังต่อไปนี้", indent=2.5, after=2)
    people = staff_people(trip)
    t = doc.add_table(rows=0, cols=4)
    _no_borders(t)
    _fixed_cols(t, [Cm(1.4), Cm(5.8), Cm(5.4), Cm(3.4)])
    for i, (n, p, r) in enumerate(people, 1):
        cells = t.add_row().cells
        _set_cell(cells[0], f"{i}.", align="right", size=16)
        _set_cell(cells[1], n, size=16)
        _set_cell(cells[2], f"ตำแหน่ง {p}", size=16)
        _set_cell(cells[3], r, size=16)
    _p(doc, "ให้ผู้ที่ได้รับแต่งตั้งปฏิบัติหน้าที่ตามระเบียบดังกล่าว ข้อ 10 ข้อ 11"
            + (" และข้อ 12" if trip.trip_type == "overnight" else "")
            + " อย่างเคร่งครัด โดยคำนึงถึงความปลอดภัยของนักเรียนเป็นอันดับแรก", align="justify", indent=2.5,
       before=4, after=2)
    _p(doc, "ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป", indent=2.5, after=6)
    _p(doc, "สั่ง ณ วันที่ " + thai_date_official(order.date), align="center", after=12)
    sign_p = _p(doc, "(ลงชื่อ).........................................", align="center")
    _float_signature(sign_p, school.director_name)
    _p(doc, f"( {school.director_name or ''} )", align="center")
    _p(doc, _director_office(school), align="center")
    return _save_doc(doc, _safe(f"คำสั่ง_{order.order_no or order.id}_ผู้ควบคุมทัศนศึกษา") + ".docx")
