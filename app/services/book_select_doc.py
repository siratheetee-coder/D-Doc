# -*- coding: utf-8 -*-
"""
book_select_doc.py - ชุดเอกสาร "คัดเลือกหนังสือเรียน" (ก่อนขั้นจัดซื้อ)

6 ฉบับตามแฟ้มจริงของโรงเรียน:
  1) บันทึกข้อความ ขออนุญาตดำเนินการคัดเลือกหนังสือเรียน
  2) ประมาณการค่าหนังสือเรียน (รายชั้น)
  3) คำสั่งแต่งตั้งคณะกรรมการคัดเลือกหนังสือเรียน (อำนวยการ/คัดเลือกรายชั้น/ดำเนินการประชุม)
  4) ประกาศแต่งตั้งคณะกรรมการภาคี 4 ฝ่าย
  5) หนังสือเชิญประชุม (หนังสือราชการภายนอก - ครุฑกลาง + ขอแสดงความนับถือ)
  6) แบบสำรวจความต้องการหนังสือเรียน (ชั้นละแผ่น)
  7) รายงานการประชุมคณะกรรมการร่วม 4 ฝ่าย (5 ระเบียบวาระ ตามแฟ้มจริง)
ออกทีละฉบับหรือรวมทั้งชุดเป็นไฟล์เดียวก็ได้ (render_select_bundle)
"""
import json

from docx import Document
from docx.shared import Cm, Pt
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.doc_page import set_a4
from app.database import get_data_dir
from app.thai_utils import thai_date, thai_date_official, bahttext
from app.services.book_receipt_doc import _safe
from app.services.build_templates import (
    _font, _p, _p_runs, _hr, _set_cell, _krut_and_title, _krut_center,
    _repeat_header_row, _no_split_row, _no_borders, _fixed_cols, _sign_table,
)

_BLANK = "................................"
_DOTS = "." * 46


def _money(v) -> str:
    return f"{float(v or 0):,.2f}"


def _jload(raw, default):
    try:
        v = json.loads(raw or "")
        return v if v else default
    except Exception:
        return default


def _office(school) -> str:
    return "  ".join(p for p in [(school.name or "").strip(),
                                 (school.address or "").strip()] if p)


def _director_line(school) -> str:
    name = (school.name or "").strip()
    return "ผู้อำนวยการ" + name if name.startswith("โรงเรียน") else "ผู้อำนวยการโรงเรียน"


def _memo_header(doc, school, subject, doc_no, date_txt):
    _krut_and_title(doc)
    _p_runs(doc, [("ส่วนราชการ  ", True), (_office(school), False)])
    _p_runs(doc, [("ที่  ", True), (doc_no or _BLANK, False),
                  ("\t", False), ("วันที่ ", True), (date_txt, False)], tab_cm=8)
    _p_runs(doc, [("เรื่อง  ", True), (subject, False)])
    _p_runs(doc, [("เรียน  ", True), (_director_line(school), False)])
    _hr(doc)


def _break(doc) -> None:
    """ขึ้นหน้าใหม่ก่อนฉบับถัดไป (ฉบับแรกของชุดไม่ขึ้น กันหน้าว่าง)"""
    if doc.paragraphs or doc.tables:
        doc.add_page_break()


def _new(landscape: bool = False):
    doc = Document(); set_a4(doc); _font(doc)
    return doc


def _save(doc, name: str) -> str:
    out = get_data_dir() / "documents"
    out.mkdir(exist_ok=True)
    path = out / (_safe(name) + ".docx")
    doc.save(str(path))
    return str(path)


# ระยะเยื้องมาตรฐานในคำสั่ง: หัวข้อคณะกรรมการ 1.25 ซม. · รายชื่อ/หน้าที่ เยื้องตามหัวข้อ
_IND_HEAD = 1.25
_IND_BODY = 1.85


def _tbl_indent(t, cm: float):
    """เยื้องทั้งตารางเข้ามาจากขอบซ้าย (ตาราง Word ไม่รับ paragraph indent)"""
    ind = OxmlElement("w:tblInd")
    ind.set(qn("w:w"), str(int(cm * 567)))
    ind.set(qn("w:type"), "dxa")
    t._tbl.tblPr.append(ind)


def _board_head(doc, text):
    """หัวข้อคณะกรรมการ (ตัวหนา เยื้องเท่ากันทุกหัวข้อ)"""
    pr = _p(doc, text, bold=True, after=1)
    pr.paragraph_format.left_indent = Cm(_IND_HEAD)
    return pr


def _duty(doc, text, *, extra=()):
    """บรรทัด "หน้าที่" - คำว่าหน้าที่เป็นตัวหนา และเยื้องระดับเดียวกับหัวข้อคณะกรรมการ
    extra = ข้อย่อย 2., 3. ... ที่ต้องเยื้องลึกกว่าอีกขั้น"""
    pr = _p_runs(doc, [("หน้าที่  ", True), (text, False)], size=16, after=0)
    pf = pr.paragraph_format
    pf.left_indent = Cm(_IND_HEAD)
    pf.alignment = None
    for i, t in enumerate(extra):
        q = _p(doc, t, after=0 if i < len(extra) - 1 else 2)
        q.paragraph_format.left_indent = Cm(_IND_BODY)
    if not extra:
        pr.paragraph_format.space_after = Pt(4)
    return pr


def _member_rows(doc, members, *, numbered=True, start=1, selection=False, inline=False):
    """รายชื่อกรรมการ เยื้องเข้ามาใต้หัวข้อคณะกรรมการ

    inline=True : เขียนต่อกันเป็นบรรทัดเดียว (ชื่อ ตำแหน่ง บทบาท) ประหยัดพื้นที่
    inline=False: ตารางไร้เส้นขอบ ให้ ชื่อ/ตำแหน่ง/บทบาท ตรงคอลัมน์กัน
    """
    rows = [m for m in (members or []) if (m.get("name") or "").strip()]
    if not rows:
        rows = [{"name": "", "position": "", "role": ""}]

    def parts(i, m):
        name = (m.get("name") or "").strip() or _BLANK
        pos = (m.get("position") or "").strip() or "ครู"
        role = (m.get("role") or "").strip() or "กรรมการ"
        label = f"2.{i}" if selection else (f"{i}." if numbered else "")
        if selection:
            name = f"{name} (ชั้น {(m.get('level') or '-').strip()})"
        return label, name, f"ตำแหน่ง {pos}", role

    if inline:
        for i, m in enumerate(rows, start=start):
            label, name, pos, role = parts(i, m)
            line = " ".join(x for x in [label, name, pos, role] if x)
            pr = _p(doc, line, size=15, after=0)
            pr.paragraph_format.left_indent = Cm(_IND_BODY)
        return None

    t = doc.add_table(rows=len(rows), cols=4)
    _no_borders(t)
    widths = [Cm(1.0), Cm(7.0), Cm(3.4), Cm(3.4)] if selection else [Cm(1.0), Cm(5.8), Cm(4.2), Cm(3.8)]
    _fixed_cols(t, widths)
    _tbl_indent(t, _IND_BODY)
    for i, (row, m) in enumerate(zip(t.rows, rows), start=start):
        vals = list(parts(i, m))
        _no_split_row(row)
        for c, v, w in zip(row.cells, vals, widths):
            _set_cell(c, v, size=15, align="left")
            c.width = w
    return t


def _director_sign(doc, school, *, role_line=True):
    _sign_table(doc, [[
        ("ลงชื่อ ......................................", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
    ] + ([(_director_line(school), "center")] if role_line else [])])


# ---------------------------------------------------------------- 1) บันทึกขออนุญาต
def render_select_memo(school, tp, doc=None):
    own = doc is None
    doc = doc or _new()
    if not own:
        _break(doc)
    head = (tp.academic_head or "").strip() or _BLANK
    subject = ("การคัดเลือกหนังสือเสริมประสบการณ์ หนังสือเรียนรายวิชาพื้นฐานใน 8 กลุ่มสาระ"
               f"การเรียนรู้ และแบบฝึกหัดรายวิชาพื้นฐาน ประจำปีการศึกษา {tp.year}")
    _memo_header(doc, school, subject, tp.memo_no, thai_date(tp.memo_date))
    sname = (school.name or "โรงเรียน").strip()
    _p(doc, f"เนื่องด้วย{sname} จะดำเนินการจัดซื้อหนังสือเสริมประสบการณ์ หนังสือเรียนรายวิชาพื้นฐาน"
            f"ใน 8 กลุ่มสาระการเรียนรู้ และแบบฝึกหัดรายวิชาพื้นฐาน ประจำปีการศึกษา {tp.year} "
            "ตามโครงการสนับสนุนค่าใช้จ่ายในการจัดการศึกษาตั้งแต่ระดับอนุบาลจนจบการศึกษาขั้นพื้นฐาน "
            "โดยถือปฏิบัติตามพระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 "
            "และระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560",
       align="justify", indent=1.25, after=2)
    _p(doc, "เพื่อให้การดำเนินการเป็นไปด้วยความเรียบร้อย จึงขออนุญาตดำเนินการ ดังนี้",
       indent=1.25, after=1)
    for i, line in enumerate([
        "จัดทำประมาณการค่าหนังสือเสริมประสบการณ์ หนังสือเรียนรายวิชาพื้นฐานใน 8 กลุ่มสาระ"
        "การเรียนรู้ และแบบฝึกหัดรายวิชาพื้นฐาน ตามจำนวนนักเรียนที่มีอยู่จริง",
        "แต่งตั้งคณะกรรมการคัดเลือกหนังสือจากครูผู้สอนแต่ละชั้น และแจ้งให้ดำเนินการคัดเลือก",
        "ขออนุญาตกำหนดวันประชุมคณะกรรมการคัดเลือกหนังสือ คณะกรรมการภาคี 4 ฝ่าย "
        "และคณะกรรมการสถานศึกษาขั้นพื้นฐาน",
    ], start=1):
        _p(doc, f"{i}. {line}", align="justify", indent=1.25, after=1)
    _p(doc, "จึงเรียนมาเพื่อ", indent=1.25, before=2, after=1)
    _p(doc, "1. โปรดทราบ", indent=2.0, after=0)
    _p(doc, "2. โปรดพิจารณาอนุญาตและลงนามในคำสั่งและหนังสือแจ้งคณะกรรมการฯ ดังแนบ",
       indent=2.0, after=10)
    _sign_table(doc, [[
        ("ลงชื่อ ......................................", "center"),
        (f"( {head} )", "center"),
        ("หัวหน้างานบริหารวิชาการ", "center"),
    ]])
    _p(doc, "คำสั่ง/การสั่งการ", bold=True, indent=1.25, before=6, after=1)
    _p(doc, "( ) ทราบ/อนุญาต    ( ) ลงนามแล้ว    ( ) อื่น ๆ ..................................",
       indent=1.25, after=8)
    _director_sign(doc, school)
    return _save(doc, f"บันทึกขออนุญาตคัดเลือกหนังสือเรียน_{tp.year}") if own else doc


# ------------------------------------------------------------- 2) ประมาณการค่าหนังสือ
def render_estimate(school, tp, rows, doc=None):
    """rows = [{level, students, rate}] · rate = อัตราค่าหนังสือต่อคน"""
    own = doc is None
    doc = doc or _new()
    if not own:
        _break(doc)
    _p(doc, f"ประมาณการค่าหนังสือเรียนและแบบฝึกหัดรายวิชาพื้นฐาน ปีการศึกษา {tp.year}",
       align="center", bold=True, size=17, after=0)
    _p(doc, (school.name or "").strip(), align="center", bold=True, size=16, after=6)
    headers = ["ที่", "ระดับชั้น", "จำนวนนักเรียน (คน)", "อัตราค่าหนังสือ/คน (บาท)", "รวมเป็นเงิน (บาท)"]
    widths = [Cm(1.1), Cm(3.4), Cm(3.6), Cm(4.4), Cm(3.8)]
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    total = 0.0
    n_students = 0
    for i, r in enumerate(rows or [], start=1):
        amount = float(r.get("rate") or 0) * int(r.get("students") or 0)
        total += amount
        n_students += int(r.get("students") or 0)
        vals = [str(i), r.get("level") or "-", str(r.get("students") or 0),
                _money(r.get("rate")), _money(amount)]
        row = t.add_row(); _no_split_row(row)
        for c, v, w, al in zip(row.cells, vals, widths,
                               ["center", "center", "center", "right", "right"]):
            _set_cell(c, v, align=al, size=14)
            c.width = w
    row = t.add_row(); _no_split_row(row)
    _set_cell(row.cells[1], "รวม", bold=True, align="center", size=14)
    _set_cell(row.cells[2], str(n_students), bold=True, align="center", size=14)
    _set_cell(row.cells[4], _money(total), bold=True, align="right", size=14)
    for c, w in zip(row.cells, widths):
        c.width = w
    _p(doc, f"รวมเป็นเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)})",
       bold=True, before=6, after=12)
    _sign_table(doc, [
        [("ลงชื่อ ......................................", "center"),
         (f"( {(tp.academic_head or '').strip() or _BLANK} )", "center"),
         ("ผู้จัดทำประมาณการ", "center")],
        [("ลงชื่อ ......................................", "center"),
         (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
         (_director_line(school), "center")],
    ])
    return _save(doc, f"ประมาณการค่าหนังสือเรียน_{tp.year}") if own else doc


# --------------------------------------------------- 3) คำสั่งแต่งตั้งกรรมการคัดเลือก
def render_select_order(school, tp, doc=None):
    own = doc is None
    doc = doc or _new()
    if not own:
        _break(doc)
    boards = _jload(tp.boards, {})
    sname = (school.name or "โรงเรียน").strip()
    _krut_center(doc)
    _p(doc, f"คำสั่ง{sname}", align="center", bold=True, size=18, after=0)
    _p(doc, f"ที่ {tp.order_no or _BLANK}", align="center", bold=True, after=0)
    _p(doc, "เรื่อง แต่งตั้งคณะกรรมการคัดเลือกหนังสือเสริมประสบการณ์ หนังสือเรียนรายวิชาพื้นฐาน",
       align="center", bold=True, after=0)
    _p(doc, f"ใน 8 กลุ่มสาระการเรียนรู้ และแบบฝึกหัดรายวิชาพื้นฐาน ประจำปีการศึกษา {tp.year}",
       align="center", bold=True, after=0)
    _p(doc, "-----------------------------------", align="center", after=6)
    _p(doc, f"ตามแนวทางการดำเนินงานโครงการสนับสนุนค่าใช้จ่ายในการจัดการศึกษาตั้งแต่ระดับอนุบาล"
            f"จนจบการศึกษาขั้นพื้นฐาน ปีการศึกษา {tp.year} กำหนดให้สถานศึกษาแต่งตั้งคณะกรรมการ"
            "คัดเลือกหนังสือเรียนให้ตรงตามหลักสูตรแกนกลางการศึกษาขั้นพื้นฐาน พุทธศักราช 2551 "
            "(ฉบับปรับปรุง พ.ศ. 2560) นั้น", align="justify", indent=1.25, after=2)
    _p(doc, "อาศัยอำนาจตามความในมาตรา 27 (1) แห่งพระราชบัญญัติระเบียบข้าราชการครูและบุคลากร"
            "ทางการศึกษา พ.ศ. 2547 จึงแต่งตั้งบุคคลผู้มีรายนามต่อไปนี้เป็นคณะกรรมการ ดังนี้",
       align="justify", indent=1.25, after=2)

    # คณะกรรมการอำนวยการ: เขียนติดกันบรรทัดเดียวต่อคน เพื่อประหยัดพื้นที่
    _board_head(doc, "1. คณะกรรมการอำนวยการ")
    _member_rows(doc, boards.get("exec") or [], inline=True)
    _duty(doc, "ให้คำปรึกษา แนะนำในการคัดเลือกหนังสือเรียนตามนโยบาย "
               "และการแต่งตั้งคณะกรรมการภาคี 4 ฝ่าย")

    _board_head(doc, "2. คณะกรรมการพิจารณาคัดเลือกหนังสือเรียน (รายชั้น)")
    _member_rows(doc, boards.get("select") or [], selection=True)
    _duty(doc, "1. พิจารณาคัดเลือกหนังสือให้ตรงตามหลักสูตรที่กระทรวงศึกษาธิการกำหนด "
               "ตามมาตรฐานการเรียนรู้และตัวชี้วัด (ฉบับปรับปรุง พ.ศ. 2560)",
          extra=["2. ประชุมคณะกรรมการคัดเลือกหนังสือเรียน",
                 "3. รวบรวมรายชื่อหนังสือส่งหัวหน้างานบริหารวิชาการ"])

    _board_head(doc, "3. คณะกรรมการดำเนินการจัดประชุม")
    _member_rows(doc, boards.get("meeting") or [])
    _duty(doc, "จัดประชุมคณะกรรมการคัดเลือกหนังสือเรียนและคณะกรรมการภาคี 4 ฝ่าย "
               "รวบรวมรายชื่อหนังสือส่งกลุ่มบริหารงบประมาณ จดบันทึกการประชุม และจัดทำแฟ้มสรุปงาน")

    _p(doc, "ให้คณะกรรมการที่ได้รับแต่งตั้งปฏิบัติหน้าที่ด้วยความเสียสละและรับผิดชอบ "
            "เกิดผลดีแก่ทางราชการ", align="justify", indent=1.25, before=4, after=1)
    _p(doc, f"สั่ง ณ วันที่ {thai_date(tp.order_date)}", align="center", before=4, after=12)
    _director_sign(doc, school)
    return _save(doc, f"คำสั่งแต่งตั้งกรรมการคัดเลือกหนังสือ_{tp.year}") if own else doc


# ------------------------------------------------------------- 4) ประกาศภาคี 4 ฝ่าย
_PARTY_LABELS = [("teacher", "ผู้แทนครู"), ("parent", "ผู้แทนผู้ปกครอง"),
                 ("community", "ผู้แทนชุมชน"), ("student", "ผู้แทนกรรมการนักเรียน")]


def render_parties_announce(school, tp, doc=None):
    own = doc is None
    doc = doc or _new()
    if not own:
        _break(doc)
    parties = _jload(tp.parties, {})
    sname = (school.name or "โรงเรียน").strip()
    _krut_center(doc)
    _p(doc, f"ประกาศ{sname}", align="center", bold=True, size=18, after=0)
    _p(doc, f"ที่ {tp.announce_no or _BLANK}", align="center", after=0)
    _p(doc, f"เรื่อง แต่งตั้งคณะกรรมการภาคี 4 ฝ่าย ปีการศึกษา {tp.year}",
       align="center", bold=True, after=0)
    _p(doc, "-----------------------------------", align="center", after=6)
    _p(doc, "ตามแนวทางการดำเนินงานโครงการสนับสนุนค่าใช้จ่ายในการจัดการศึกษาตั้งแต่ระดับอนุบาล"
            "จนจบการศึกษาขั้นพื้นฐาน กำหนดให้สถานศึกษาแต่งตั้งคณะกรรมการภาคี 4 ฝ่าย "
            "เพื่อร่วมพิจารณาให้ความเห็นชอบการใช้จ่ายเงินเรียนฟรี 15 ปี "
            "และการคัดเลือกหนังสือเรียน นั้น", align="justify", indent=1.25, after=2)
    _p(doc, f"{sname} จึงประกาศแต่งตั้งคณะกรรมการภาคี 4 ฝ่าย ประกอบด้วย",
       align="justify", indent=1.25, after=2)
    n = 1
    for key, label in _PARTY_LABELS:
        rows = [m for m in (parties.get(key) or []) if (m.get("name") or "").strip()]
        _board_head(doc, f"{n}. {label}")
        _member_rows(doc, rows or [{"name": "", "position": "", "role": label}], numbered=False)
        n += 1
    _p(doc, "ให้คณะกรรมการภาคี 4 ฝ่าย มีหน้าที่ร่วมพิจารณาให้ความเห็นชอบรายการหนังสือเรียน "
            "และการใช้จ่ายงบประมาณตามโครงการฯ ให้เกิดประโยชน์สูงสุดต่อผู้เรียน",
       align="justify", indent=1.25, before=2, after=1)
    _p(doc, f"ประกาศ ณ วันที่ {thai_date(tp.announce_date)}", align="center", before=4, after=12)
    _director_sign(doc, school)
    return _save(doc, f"ประกาศแต่งตั้งภาคี4ฝ่าย_{tp.year}") if own else doc


# ------------------------------------------------------------------ 5) หนังสือเชิญประชุม
def render_invite(school, tp, doc=None):
    """หนังสือเชิญประชุม - เป็น "หนังสือราชการภายนอก" (ครุฑกลาง + ขอแสดงความนับถือ)
    ไม่ใช่บันทึกข้อความ เพราะส่งถึงบุคคลภายนอก (ภาคี 4 ฝ่าย / กรรมการสถานศึกษา)"""
    own = doc is None
    doc = doc or _new()
    if not own:
        _break(doc)
    sname = (school.name or "โรงเรียน").strip()
    _krut_center(doc, height_cm=2.0)

    # ที่ ... (ซ้าย) + ชื่อ/ที่อยู่โรงเรียน (ขวา)
    t = doc.add_table(rows=1, cols=2)
    _no_borders(t)
    t.autofit = False
    widths = [Cm(8.0), Cm(8.5)]
    _fixed_cols(t, widths)
    _set_cell(t.rows[0].cells[0], "ที่  " + (tp.invite_no or _BLANK), align="left", size=16)
    addr = (getattr(school, "address", "") or "").strip()
    _set_cell(t.rows[0].cells[1], sname + (("\n" + addr) if addr else ""), align="right", size=16)
    for c, w in zip(t.rows[0].cells, widths):
        c.width = w

    _p(doc, thai_date_official(tp.invite_date) if tp.invite_date else _BLANK,
       align="center", before=4, after=6)
    _p_runs(doc, [("เรื่อง  ", True), ("ขอเชิญประชุมคัดเลือกหนังสือเรียน "
                                       f"ปีการศึกษา {tp.year}", False)])
    _p_runs(doc, [("เรียน  ", True), ("คณะกรรมการสถานศึกษาขั้นพื้นฐาน / คณะกรรมการภาคี 4 ฝ่าย "
                                      "และคณะกรรมการคัดเลือกหนังสือเรียน", False)])
    _p_runs(doc, [("สิ่งที่ส่งมาด้วย  ", True), ("1. ระเบียบวาระการประชุม", False),
                  ("	", False), ("จำนวน 1 ฉบับ", False)], tab_cm=11.5)
    for n, txt in [(2, "รายละเอียดประมาณการค่าหนังสือเรียนและแบบฝึกหัด"),
                   (3, "แบบสำรวจความต้องการหนังสือเรียนรายชั้น")]:
        pr = _p_runs(doc, [(f"{n}. {txt}", False), ("	", False), ("จำนวน 1 ฉบับ", False)],
                     tab_cm=11.5)
        pr.paragraph_format.left_indent = Cm(2.6)

    when = thai_date(tp.meet_date) if tp.meet_date else _BLANK
    _p(doc, "", after=4)
    _p(doc, "ตามแนวทางการดำเนินงานโครงการสนับสนุนค่าใช้จ่ายในการจัดการศึกษาตั้งแต่ระดับอนุบาล"
            f"จนจบการศึกษาขั้นพื้นฐาน ปีการศึกษา {tp.year} ได้กำหนดบทบาทหน้าที่ของคณะกรรมการ"
            "สถานศึกษาขั้นพื้นฐานและคณะกรรมการภาคี 4 ฝ่าย โดยการร่วมพิจารณาให้ความเห็นชอบ"
            "การคัดเลือกหนังสือเรียน นั้น", align="justify", indent=1.25, after=2)
    _p(doc, "เพื่อให้เป็นไปตามขั้นตอนตามแนวทางการดำเนินงานดังกล่าว "
            f"{sname} จึงใคร่ขอเรียนเชิญท่านเข้าร่วมประชุมคัดเลือกหนังสือเรียน "
            f"ประจำปีการศึกษา {tp.year} ในวันที่ {when} "
            f"เวลา {(tp.meet_time or '').strip() or _BLANK} "
            f"ณ {(tp.meet_place or '').strip() or _BLANK} รายละเอียดตามสิ่งที่ส่งมาด้วยพร้อมนี้",
       align="justify", indent=1.25, after=2)
    _p(doc, "จึงเรียนมาเพื่อโปรดทราบ และพิจารณา", align="justify", indent=1.25, after=8)

    _p(doc, "ขอแสดงความนับถือ", align="center", after=12)
    _director_sign(doc, school)
    head = (getattr(tp, "academic_head", "") or "").strip()
    _p(doc, "งานบริหารวิชาการ" + (f"  {head}" if head else ""), size=14, before=10, after=0)
    _p(doc, f"โทรศัพท์ {(getattr(school, 'phone', '') or '').strip() or _BLANK}",
       size=14, after=0)
    return _save(doc, f"หนังสือเชิญประชุมคัดเลือกหนังสือ_{tp.year}") if own else doc


# -------------------------------------------------- 6) แบบสำรวจความต้องการหนังสือเรียน
def render_survey(school, tp, groups, doc=None):
    """groups = [(level, [{title, publisher, price, qty}]), ...] · 1 ชั้น = 1 แผ่น
    รายการที่มีในทะเบียนจะเติมให้ แล้วเว้นบรรทัดว่างไว้เขียนเพิ่ม"""
    own = doc is None
    doc = doc or _new()
    first = True
    for level, items in (groups or [("", [])]):
        if own and not first:
            doc.add_page_break()
        elif not first or not own:
            _break(doc)
        first = False
        _p(doc, f"แบบสำรวจความต้องการหนังสือเรียนและแบบฝึกหัด ปีการศึกษา {tp.year}",
           align="center", bold=True, size=17, after=0)
        _p(doc, f"ชั้น{level or _BLANK} {(school.name or '').strip()}",
           align="center", bold=True, size=16, after=0)
        _p(doc, f"ครูผู้สอน/ครูประจำชั้น {_DOTS}", align="center", size=15, after=4)
        headers = ["ที่", "ชื่อหนังสือ", "สำนักพิมพ์", "ราคา/เล่ม", "จำนวน", "เป็นเงิน"]
        widths = [Cm(1.0), Cm(6.2), Cm(3.0), Cm(2.1), Cm(1.8), Cm(2.4)]
        t = doc.add_table(rows=1, cols=len(headers))
        t.style = "Table Grid"
        _fixed_cols(t, widths)
        _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
        for c, h, w in zip(t.rows[0].cells, headers, widths):
            _set_cell(c, h, bold=True, align="center", size=14)
            c.width = w
        rows = list(items or [])
        total = 0.0
        for i in range(max(len(rows), 12)):
            it = rows[i] if i < len(rows) else None
            row = t.add_row(); _no_split_row(row)
            if it:
                amount = float(it.get("price") or 0) * float(it.get("qty") or 0)
                total += amount
                vals = [str(i + 1), it.get("title") or "", it.get("publisher") or "",
                        _money(it.get("price")), f"{float(it.get('qty') or 0):g}", _money(amount)]
            else:
                vals = [""] * 6
            for c, v, w, al in zip(row.cells, vals, widths,
                                   ["center", "left", "left", "right", "center", "right"]):
                _set_cell(c, v, align=al, size=14)
                c.width = w
        row = t.add_row(); _no_split_row(row)
        _set_cell(row.cells[1], "รวม", bold=True, align="right", size=14)
        _set_cell(row.cells[5], _money(total) if total else "", bold=True, align="right", size=14)
        for c, w in zip(row.cells, widths):
            c.width = w
        _p(doc, "", after=8)
        _sign_table(doc, [[
            ("ลงชื่อ ......................................", "center"),
            ("(......................................)", "center"),
            ("ครูผู้สอน/ครูประจำชั้น", "center"),
        ]])
    return _save(doc, f"แบบสำรวจความต้องการหนังสือเรียน_{tp.year}") if own else doc


# --------------------------------------------------------------- 7) รายงานการประชุม
# อัตราเงินอุดหนุนเรียนฟรี 15 ปี ส่วนที่ไม่ใช่ค่าหนังสือเรียน (บาท)
# * ค่าหนังสือเรียนดึงจากอัตราที่โรงเรียนกรอกไว้ในระบบ (tp.rates) ไม่ได้ตายตัวที่นี่
# * สามส่วนนี้เป็นอัตรามาตรฐานตามแนวทางฯ - โรงเรียนควรตรวจกับหนังสือจัดสรรของปีนั้นก่อนใช้
_SUPPORT_RATES = [
    ("ค่าอุปกรณ์การเรียน", "บาท/ภาคเรียน", [
        ("ระดับก่อนประถมศึกษา", 145), ("ระดับประถมศึกษา", 220),
        ("ระดับมัธยมศึกษาตอนต้น", 260)]),
    ("ค่าเครื่องแบบนักเรียน", "บาท/คน/ปี", [
        ("ระดับก่อนประถมศึกษา", 325), ("ระดับประถมศึกษา", 400),
        ("ระดับมัธยมศึกษาตอนต้น", 500)]),
    ("ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", "บาท/ภาคเรียน", [
        ("ระดับก่อนประถมศึกษา", 232), ("ระดับประถมศึกษา", 259),
        ("ระดับมัธยมศึกษาตอนต้น", 475)]),
]


def _grid(doc, headers, widths, *, size=14):
    """ตารางมีเส้น + หัวตารางซ้ำทุกหน้า"""
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=size)
        c.width = w
    return t


def _row(t, vals, widths, aligns, *, size=14, bold=False):
    r = t.add_row(); _no_split_row(r)
    for c, v, w, al in zip(r.cells, vals, widths, aligns):
        _set_cell(c, v, align=al, size=size, bold=bold)
        c.width = w
    return r


def _agenda(doc, text):
    """หัวระเบียบวาระ (ตัวหนา ชิดซ้าย)"""
    return _p(doc, text, bold=True, size=16, before=6, after=2)


def _resolution(doc, text="ที่ประชุมรับทราบ"):
    _p_runs(doc, [("มติที่ประชุม : ", True), (text, False)], size=16, after=4)


def _sub(doc, text, *, ind=_IND_HEAD):
    pr = _p(doc, text, align="justify", size=16, after=2)
    pr.paragraph_format.left_indent = Cm(ind)
    return pr


def _rate_lines(doc, title, unit, rows):
    _sub(doc, title)
    t = doc.add_table(rows=len(rows), cols=2)
    _no_borders(t)
    widths = [Cm(7.0), Cm(5.0)]
    _fixed_cols(t, widths)
    _tbl_indent(t, _IND_BODY)
    for row, (name, amount) in zip(t.rows, rows):
        _no_split_row(row)
        _set_cell(row.cells[0], name, size=15, align="left")
        _set_cell(row.cells[1], f"{amount:,.2f} {unit}", size=15, align="left")


def _attendee_rows(school, tp):
    """รายชื่อผู้เข้าประชุม - ใช้ที่กรอกไว้ ถ้ายังไม่กรอกใช้ ผอ. + ภาคี 4 ฝ่าย ให้อัตโนมัติ"""
    rows = _jload(tp.attendees, [])
    if rows:
        return rows
    name = (school.director_name or "").strip()
    rows = ([{"name": name, "position": "ผู้อำนวยการโรงเรียน", "role": "ประธานกรรมการ"}]
            if name else [])
    parties = _jload(tp.parties, {})
    for key, label in _PARTY_LABELS:
        for m in parties.get(key) or []:
            if (m.get("name") or "").strip():
                rows.append({"name": m["name"], "position": label, "role": "กรรมการ"})
    if rows:
        rows[-1]["role"] = "กรรมการและเลขานุการ"
    return rows


def render_meeting_report(school, tp, groups, doc=None, *, est_rows=None):
    """รายงานการประชุมคณะกรรมการร่วม 4 ฝ่าย (โครงสร้าง 5 ระเบียบวาระตามแฟ้มจริง)"""
    own = doc is None
    doc = doc or _new()
    if not own:
        _break(doc)
    sname = (school.name or "โรงเรียน").strip()
    rows = _attendee_rows(school, tp)

    _p(doc, "รายงานการประชุมคณะกรรมการร่วม 4 ฝ่าย", align="center", bold=True, size=18, after=0)
    _p(doc, f"ครั้งที่ {tp.meet_no or 1}  ปีการศึกษา {tp.year}",
       align="center", bold=True, size=16, after=0)
    _p(doc, thai_date_official(tp.meet_date) if tp.meet_date else _BLANK,
       align="center", bold=True, size=16, after=0)
    _p(doc, f"ณ  {(tp.meet_place or '').strip() or _BLANK}",
       align="center", bold=True, size=16, after=6)

    _p(doc, "รายชื่อคณะกรรมการผู้เข้าประชุม", bold=True, size=16, after=2)
    _member_rows(doc, rows)

    _p(doc, f"เริ่มประชุมเวลา {(tp.meet_time or '').strip() or _BLANK}",
       bold=True, size=16, before=6, after=2)
    chair = next((m["name"] for m in rows if "ประธาน" in (m.get("role") or "")),
                 (school.director_name or "").strip())
    _sub(doc, f"ประธานในที่ประชุม {chair or _BLANK} ผู้อำนวยการ{sname} "
              "กล่าวเปิดประชุมและดำเนินการประชุมตามระเบียบวาระ ดังนี้")

    # ---- วาระ 1 ----
    _agenda(doc, "ระเบียบวาระที่ 1 เรื่องที่ประธานแจ้งให้ที่ประชุมทราบ")
    _sub(doc, "1.1 ประธานกล่าวถึงแนวทางการจัดการศึกษาของสถานศึกษา ซึ่งกำหนดให้ครูผู้สอน"
              "จัดการเรียนการสอนอย่างมีประสิทธิภาพ โดยผู้มีส่วนเกี่ยวข้องมีส่วนร่วม "
              "และรัฐบาลสนับสนุนค่าใช้จ่ายอย่างเสมอภาคและเป็นธรรมในรายการพื้นฐาน")
    counts = [r for r in (est_rows or []) if r.get("students")]
    if counts:
        _sub(doc, f"1.2 จำนวนนักเรียนที่ใช้คำนวณเงินอุดหนุนรายบุคคล ปีการศึกษา {tp.year}")
        headers = ["ระดับชั้น", "จำนวนนักเรียน", "อัตราค่าหนังสือ/คน", "เป็นเงิน", "หมายเหตุ"]
        widths = [Cm(5.4), Cm(2.6), Cm(3.2), Cm(2.8), Cm(2.5)]
        t = _grid(doc, headers, widths, size=14)
        tot_st = 0
        tot_amt = 0.0
        for r in counts:
            amt = float(r.get("rate") or 0) * int(r.get("students") or 0)
            tot_st += int(r.get("students") or 0)
            tot_amt += amt
            _row(t, [r["level"], str(r["students"]), _money(r.get("rate")), _money(amt), "-"],
                 widths, ["left", "center", "right", "right", "center"], size=14)
        _row(t, ["รวม", str(tot_st), "", _money(tot_amt), "-"], widths,
             ["center", "center", "right", "right", "center"], size=14, bold=True)
    _resolution(doc)

    # ---- วาระ 2 ----
    _agenda(doc, "ระเบียบวาระที่ 2 เรื่องรับรองรายงานการประชุมครั้งที่ผ่านมา")
    prev = (tp.meet_no or 1) - 1
    _sub(doc, "- ไม่มี -" if prev < 1 else
              f"รายงานการประชุมครั้งที่ {prev} ปีการศึกษา {tp.year}")
    _resolution(doc, "ที่ประชุมรับทราบ" if prev < 1 else "ที่ประชุมรับรองรายงานการประชุม")

    # ---- วาระ 3 ----
    _agenda(doc, "ระเบียบวาระที่ 3 เรื่องเสนอเพื่อทราบ")
    _sub(doc, f"3.1 แนวปฏิบัติโครงการเรียนฟรี 15 ปี อย่างมีคุณภาพ ปีการศึกษา {tp.year} "
              f"{sname} ได้รับเงินอุดหนุนจากรัฐบาล 5 รายการ ดังนี้")
    for i, name in enumerate(["ค่าจัดการเรียนการสอน", "ค่าหนังสือเรียน", "ค่าอุปกรณ์การเรียน",
                              "ค่าเครื่องแบบนักเรียน", "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน"], start=1):
        pr = _p(doc, f"{i}. {name}", size=15, after=0)
        pr.paragraph_format.left_indent = Cm(_IND_BODY)
    _p(doc, "", after=4)
    rates = _jload(tp.rates, {})
    book_rows = [(r["level"], float(rates.get(r["level"]) or r.get("rate") or 0))
                 for r in (est_rows or [])
                 if float(rates.get(r["level"]) or r.get("rate") or 0)]
    step = 2
    if book_rows:
        _rate_lines(doc, "3.2 อัตราค่าหนังสือเรียน", "บาท/ปี", book_rows)
        step = 3
    for title, unit, lines in _SUPPORT_RATES:
        _rate_lines(doc, f"3.{step} {title}", unit, lines)
        step += 1
    _resolution(doc)

    # ---- วาระ 4 ----
    _agenda(doc, "ระเบียบวาระที่ 4 เรื่องเสนอเพื่อพิจารณาให้ความเห็นชอบ")
    n_items = sum(len(items) for _, items in (groups or []))
    grand = sum(float(it["price"]) * float(it["qty"])
                for _, items in (groups or []) for it in items)
    _sub(doc, f"4.1 รับรองจำนวนนักเรียน ปีการศึกษา {tp.year} ที่ใช้คำนวณเงินอุดหนุน")
    _sub(doc, "4.2 การคัดเลือกหนังสือเรียนและแบบฝึกหัด ซึ่งคณะกรรมการคัดเลือกหนังสือเรียน"
              "ได้พิจารณาให้ตรงตามหลักสูตรแกนกลางการศึกษาขั้นพื้นฐาน พุทธศักราช 2551 "
              f"(ฉบับปรับปรุง พ.ศ. 2560) รวม {n_items} รายการ เป็นเงิน {_money(grand)} บาท "
              f"({bahttext(grand)}) รายละเอียดตามบัญชีรายการหนังสือเรียนแนบท้าย")
    _sub(doc, "4.3 การจัดซื้อหนังสือเรียน ให้จัดหาให้นักเรียนครบทุกคน เพื่อให้ได้รับ"
              "สื่อการเรียนรู้อย่างทั่วถึงและทันก่อนเปิดภาคเรียน")
    _resolution(doc, "ที่ประชุมให้ความเห็นชอบ")

    # ---- วาระ 5 ----
    _agenda(doc, "ระเบียบวาระที่ 5 เรื่องอื่น ๆ")
    _sub(doc, "- ไม่มี -")
    _p(doc, f"เลิกประชุมเวลา {_BLANK}", bold=True, size=16, before=4, after=12)

    _sign_table(doc, [[
        ("ลงชื่อ ..........................................", "center"),
        (f"( {(tp.recorder or '').strip() or _BLANK} )", "center"),
        ("ผู้บันทึกการประชุม", "center"),
    ], [
        ("ลงชื่อ ..........................................", "center"),
        (f"( {(tp.meet_checker or '').strip() or _BLANK} )", "center"),
        ("ผู้ตรวจบันทึกการประชุม", "center"),
    ]])
    return _save(doc, f"รายงานการประชุมคัดเลือกหนังสือเรียน_{tp.year}") if own else doc


# ------------------------------------------------------------------------ ทั้งชุด
def render_select_bundle(school, tp, groups, est_rows, survey_groups) -> str:
    """ออกชุดคัดเลือกหนังสือทั้ง 7 ฉบับเป็นไฟล์เดียว (เรียงตามลำดับการใช้งานจริง)"""
    doc = _new()
    render_select_memo(school, tp, doc)
    render_estimate(school, tp, est_rows, doc)
    render_select_order(school, tp, doc)
    render_parties_announce(school, tp, doc)
    render_invite(school, tp, doc)
    render_survey(school, tp, survey_groups, doc)
    render_meeting_report(school, tp, groups, doc, est_rows=est_rows)
    return _save(doc, f"ชุดคัดเลือกหนังสือเรียน_{tp.year}")
