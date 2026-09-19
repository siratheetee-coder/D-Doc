# -*- coding: utf-8 -*-
"""
book_proc_doc.py - เอกสารจัดซื้อ "หนังสือเรียน" ตามแฟ้มจริงของโรงเรียน

หนังสือเรียนใช้แบบฟอร์มต่างจากการจัดซื้อทั่วไปหลายจุด จึงทำเป็นชุดแยก
(แม่แบบพัสดุทั่วไปยังใช้กับเรื่องอื่นเหมือนเดิม - render.py เลือกให้อัตโนมัติ
เมื่อเรื่องนั้นผูกกับ TextbookPurchase)

ต่างจากแบบทั่วไปตรงนี้
  - รายงานขอซื้อมี 7 ข้อ · ข้อ 5 อ้างมาตรา 56 (1) (ง) ระบุยี่ห้อเฉพาะ
    (เพราะหนังสือต้องระบุสำนักพิมพ์/ผู้แต่ง) · ข้อ 7 ขออนุมัติแต่งตั้ง 2 คณะกรรมการ
  - คำสั่งแต่งตั้งเป็นฉบับเดียวมี 2 คณะ: จัดซื้อโดยวิธีเฉพาะเจาะจง (ข้อ 78)
    และตรวจรับพัสดุ (ข้อ 175)
  - รายการหนังสือไม่ลงทีละเล่มในใบสั่งซื้อ/ใบตรวจรับ แต่เขียนว่า
    "ตามบัญชีรายละเอียดแนบท้าย จำนวน N รายการ" แล้วแนบบัญชีท้ายเอกสาร
  - ลงนาม 3 ระดับ: เจ้าหน้าที่ -> หัวหน้าเจ้าหน้าที่ -> ผู้อำนวยการ
"""
from docx import Document
from docx.shared import Cm

from app.services.doc_page import set_a4
from app.database import get_data_dir
from app.thai_utils import thai_date, thai_date_official, bahttext
from app.services.book_receipt_doc import _safe
from app.services.build_templates import (
    _font, _p, _p_runs, _set_cell, _cell_line, _krut_and_title, _krut_center, _hr,
    _repeat_header_row, _no_split_row, _no_borders, _fixed_cols, _sign_table,
)

_BLANK = "................................"
_DOT = "..........................."

# ข้อกฎหมายที่อ้างในเอกสารชุดนี้ (แก้ที่เดียวใช้ทุกฉบับ)
LAW_BUY_METHOD = "มาตรา 56 (1) (ง)"     # เหตุผลที่ซื้อโดยวิธีเฉพาะเจาะจง (ระบุยี่ห้อเฉพาะ)
LAW_COMMITTEE_BUY = "ข้อ 78"             # หน้าที่คณะกรรมการจัดซื้อโดยวิธีเฉพาะเจาะจง
LAW_COMMITTEE_INSPECT = "ข้อ 175"        # หน้าที่คณะกรรมการตรวจรับพัสดุ
LAW_RESULT_REPORT = "ข้อ 24"             # รายงานผลการพิจารณา
LAW_NEGOTIATE = "ข้อ 79"                 # เจรจาตกลงราคา
FINE_RATE_ORDER = 0.2                    # ค่าปรับในใบสั่งซื้อ (ร้อยละ/วัน)


def _money(v) -> str:
    v = float(v or 0)
    return f"{int(v):,}" if v == int(v) else f"{v:,.2f}"


def _new(landscape: bool = False):
    doc = Document(); set_a4(doc, landscape=landscape); _font(doc)
    return doc


def _save(doc, name: str) -> str:
    out = get_data_dir() / "documents"
    out.mkdir(exist_ok=True)
    path = out / (_safe(name) + ".docx")
    doc.save(str(path))
    return str(path)


def _sname(school) -> str:
    return (school.name or "โรงเรียน").strip()


def _vendor(proc) -> str:
    return (proc.vendor.name if proc.vendor else "").strip() or _BLANK


def _committee(proc, kind):
    for c in (proc.committees or []):
        if c.kind == kind and c.members:
            return list(c.members)
    return []


def _n_items(proc) -> int:
    return len(proc.items or [])


def _subject_line(proc, tp) -> str:
    """ชื่อพัสดุที่ใช้ในทุกเอกสาร - หนังสือเรียนประจำปีการศึกษา XXXX"""
    return f"หนังสือเรียน ประจำปีการศึกษา {tp.year}"


def _members_table(doc, members, *, roles=None, indent=1.85, label_fmt="{i})"):
    """ตารางรายชื่อกรรมการไร้เส้นขอบ ให้ ชื่อ/ตำแหน่ง/บทบาท ตรงคอลัมน์"""
    rows = list(members) or [None, None, None]
    roles = roles or ["ประธานกรรมการ", "กรรมการ", "กรรมการ"]
    t = doc.add_table(rows=len(rows), cols=4)
    _no_borders(t)
    # วัดจากฟอนต์จริง TH Sarabun New 15pt + ขอบเซลล์ 0.38 ซม.
    #   ชื่อยาวสุด "ว่าที่ร้อยตรี เกริกไกร สุขเพลีย" 4.51 · "ตำแหน่ง ครูชำนาญการพิเศษ" 4.38
    #   บทบาทยาวสุด "กรรมการและเลขานุการ" 3.69  -> ทุกช่องต้องกว้างกว่านี้ ไม่งั้นตัดบรรทัด
    widths = [Cm(1.0), Cm(4.8), Cm(4.9), Cm(3.9)]
    _fixed_cols(t, widths)
    _tbl_indent(t, indent)
    for i, (row, m) in enumerate(zip(t.rows, rows), start=1):
        name = (getattr(m, "name", "") or "").strip() or _BLANK
        pos = (getattr(m, "position", "") or "").strip() or "ครู"
        role = (getattr(m, "role", "") or "").strip() or (
            roles[i - 1] if i <= len(roles) else "กรรมการ")
        _no_split_row(row)
        for c, v, w in zip(row.cells, [label_fmt.format(i=i), name,
                                       f"ตำแหน่ง {pos}", role], widths):
            _set_cell(c, v, size=15, align="left")
            c.width = w
    return t


def _tbl_indent(t, cm: float):
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    ind = OxmlElement("w:tblInd")
    ind.set(qn("w:w"), str(int(cm * 567)))
    ind.set(qn("w:type"), "dxa")
    t._tbl.tblPr.append(ind)


def _two_committees(doc, proc):
    """คณะกรรมการจัดซื้อโดยวิธีเฉพาะเจาะจง + คณะกรรมการตรวจรับพัสดุ"""
    buy = _committee(proc, "purchase") or _committee(proc, "spec")
    insp = _committee(proc, "inspect")
    _p(doc, "1. คณะกรรมการจัดซื้อโดยวิธีเฉพาะเจาะจง", bold=True, indent=1.25, after=1)
    _members_table(doc, buy)
    _p(doc, "2. คณะกรรมการตรวจรับพัสดุ", bold=True, indent=1.25, before=4, after=1)
    _members_table(doc, insp)


def _officer_signs(doc, school, *, dated=True, date=None):
    """ลงชื่อ เจ้าหน้าที่ | หัวหน้าเจ้าหน้าที่ (สองช่องเรียงกัน)"""
    d = thai_date(date) if date else _DOT
    left = [("ลงชื่อ...............................เจ้าหน้าที่", "center"),
            (f"( {(school.officer_name or '').strip() or _BLANK} )", "center")]
    right = [("ลงชื่อ...............................หัวหน้าเจ้าหน้าที่", "center"),
             (f"( {(school.head_officer_name or '').strip() or _BLANK} )", "center")]
    if dated:
        left.append((f"วันที่ {d}", "center"))
        right.append((f"วันที่ {d}", "center"))
    _sign_table(doc, [left, right])


def _director_sign(doc, school, *, date=None, label="ผู้อำนวยการโรงเรียน"):
    lines = [("ลงชื่อ.................................................", "center"),
             (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
             (label + _sname(school).replace("โรงเรียน", "", 1), "center")]
    if date is not None:
        lines.append((f"วันที่ {thai_date(date) if date else _DOT}", "center"))
    _sign_table(doc, [[("", "center")], lines])


def _attach_table(doc, school, proc, tp, *, title=None):
    """บัญชีรายละเอียดหนังสือแนบท้าย (ขึ้นหน้าใหม่)"""
    if not proc.items:
        return
    doc.add_page_break()
    _p(doc, title or "บัญชีรายละเอียดแนบท้าย", align="center", bold=True, size=18, after=0)
    _p(doc, f"{_subject_line(proc, tp)}  {_sname(school)}",
       align="center", bold=True, size=15, after=6)
    # ตัดคอลัมน์ "หน่วย" ออก (หนังสือเป็น "เล่ม" ทุกบรรทัดอยู่แล้ว) เอาที่ว่างไปให้ชื่อหนังสือ
    headers = ["ที่", "รายการหนังสือ", "จำนวน (เล่ม)", "ราคา/หน่วย", "จำนวนเงิน"]
    widths = [Cm(1.0), Cm(8.9), Cm(2.2), Cm(2.2), Cm(2.2)]
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    total = 0.0
    for i, it in enumerate(proc.items, start=1):
        total += it.amount
        vals = [str(i), it.name or "", f"{(it.quantity or 0):g}",
                _money(it.unit_price), _money(it.amount)]
        r = t.add_row(); _no_split_row(r)
        for c, v, w, al in zip(r.cells, vals, widths,
                               ["center", "left", "center", "right", "right"]):
            _set_cell(c, v, align=al, size=14)
            c.width = w
    r = t.add_row(); _no_split_row(r)
    _set_cell(r.cells[1], "รวมทั้งสิ้น", bold=True, align="right", size=14)
    _set_cell(r.cells[4], _money(total), bold=True, align="right", size=14)
    for c, w in zip(r.cells, widths):
        c.width = w


# ---------------------------------------------------------------- 1) รายงานขอซื้อ
def render_buy_report(school, proc, tp) -> str:
    doc = _new()
    name = _subject_line(proc, tp)
    total = float(proc.total_amount or 0)
    _krut_and_title(doc)
    _p_runs(doc, [("ส่วนราชการ  ", True),
                  ("  ".join(x for x in [_sname(school), (school.address or "").strip()] if x),
                   False)])
    _p_runs(doc, [("ที่  ", True), (proc.memo_no or _BLANK, False), ("\t", False),
                  ("วันที่ ", True), (thai_date(proc.request_date) if proc.request_date
                                      else _DOT, False)], tab_cm=8)
    _p_runs(doc, [("เรื่อง  ", True),
                  (f"รายงานขอซื้อหนังสือเรียนประจำปีการศึกษา {tp.year} "
                   f"โดยวิธี{proc.method or 'เฉพาะเจาะจง'}", False)])
    _p_runs(doc, [("เรียน  ", True), (f"ผู้อำนวยการ{_sname(school)}", False)])
    _hr(doc)

    from app.thai_utils import level_range
    levels = level_range(lv for lv, _ in (tp_groups(tp) or []) if lv)
    _p(doc, f"ด้วย{_sname(school)} มีความประสงค์จะซื้อ{name} "
            f"โดยวิธี{proc.method or 'เฉพาะเจาะจง'} ซึ่งมีรายละเอียด ดังต่อไปนี้",
       align="justify", indent=1.25, after=2)

    def item(no, text):
        _p(doc, f"{no}.  {text}", align="justify", indent=1.25, after=1)

    item(1, "เหตุผลและความจำเป็นที่ต้องซื้อ เพื่อใช้ประกอบการเรียนการสอนของนักเรียน"
            + (f" ระดับ{levels}" if levels else ""))
    item(2, f"รายละเอียดคุณลักษณะเฉพาะของพัสดุ {name} จำนวน {_n_items(proc)} รายการ "
            "(รายละเอียดตามเอกสารแนบท้าย)")
    item(3, f"ราคากลางของพัสดุที่จะซื้อ เป็นเงิน {_money(total)} บาท ({bahttext(total)}) "
            f"โดยมีแหล่งที่มาจาก{proc.price_ref_source or 'ราคากลาง (ราคาอ้างอิง)'}")
    item(4, f"วงเงินที่จะซื้อ {_money(total)} บาท ({bahttext(total)}) "
            "กำหนดเวลาที่ต้องการใช้พัสดุ ผู้ขายจะต้องส่งมอบพัสดุตามข้อ 2 ภายในระยะเวลา "
            f"{proc.delivery_days or 30} วัน นับถัดจากวันที่ลงนามในสัญญา")
    item(5, f"วิธีที่จะซื้อและเหตุผลที่ต้องซื้อโดยวิธี{proc.method or 'เฉพาะเจาะจง'} "
            "ตามพระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 "
            f"{LAW_BUY_METHOD} เป็นพัสดุที่โดยลักษณะของการใช้งานหรือมีข้อจำกัดทางเทคนิค"
            "ที่จำเป็นต้องระบุยี่ห้อเป็นการเฉพาะ เนื่องจากต้องระบุสำนักพิมพ์/ชื่อผู้แต่ง")
    item(6, "หลักเกณฑ์การพิจารณาคัดเลือกข้อเสนอ การพิจารณาคัดเลือกข้อเสนอโดยใช้เกณฑ์ราคา")
    item(7, "การขออนุมัติแต่งตั้งคณะกรรมการ")
    _p(doc, "เห็นควรให้มีการแต่งตั้งคณะกรรมการจัดซื้อโดยวิธีเฉพาะเจาะจง "
            "และคณะกรรมการตรวจรับพัสดุ โดยมีรายละเอียด ดังนี้",
       align="justify", indent=1.25, after=2)
    _two_committees(doc, proc)

    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบขอได้โปรด",
       align="justify", indent=1.25, before=6, after=1)
    for i, line in enumerate(["อนุมัติให้ดำเนินการตามรายละเอียดในรายงานขอซื้อดังกล่าวข้างต้น",
                              "ลงนามในคำสั่งแต่งตั้งคณะกรรมการจัดซื้อดังกล่าวข้างต้น"], start=1):
        pr = _p(doc, f"{i}. {line}", align="justify", after=1)
        pr.paragraph_format.left_indent = Cm(1.85)

    _p(doc, "", after=10)
    _officer_signs(doc, school, date=proc.request_date)
    _p(doc, "", after=6)
    _sign_table(doc, [[("", "center")], [("(   )  เห็นชอบ", "left"),
                                         ("(   )  ลงนามแล้ว", "left")]], gap=False)
    _p(doc, "", after=4)
    _director_sign(doc, school, date=proc.request_date)

    _attach_table(doc, school, proc, tp, title="รายละเอียดคุณลักษณะเฉพาะของพัสดุแนบท้ายรายงานขอซื้อ")
    return _save(doc, f"รายงานขอซื้อหนังสือเรียน_{tp.year}")


# ------------------------------------------------- 2) คำสั่งแต่งตั้งคณะกรรมการ (2 คณะ)
def render_buy_command(school, proc, tp) -> str:
    doc = _new()
    _krut_center(doc)
    _p(doc, f"คำสั่ง{_sname(school)}", align="center", bold=True, size=18, after=0)
    _p(doc, f"ที่ {proc.command_no or _BLANK}", align="center", bold=True, after=0)
    _p(doc, "เรื่อง แต่งตั้งคณะกรรมการจัดซื้อโดยวิธีเฉพาะเจาะจงและคณะกรรมการตรวจรับพัสดุ",
       align="center", bold=True, after=0)
    _p(doc, f"สำหรับการจัดซื้อหนังสือเรียน ประจำปีการศึกษา {tp.year}",
       align="center", bold=True, after=0)
    _p(doc, "-----------------------------------", align="center", after=6)

    _p(doc, f"ด้วย{_sname(school)} มีความประสงค์จะซื้อหนังสือเรียน ประจำปีการศึกษา {tp.year} "
            f"โดยวิธี{proc.method or 'เฉพาะเจาะจง'} และเพื่อให้เป็นไปตามระเบียบกระทรวงการคลัง"
            "ว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 "
            "จึงขอแต่งตั้งรายชื่อต่อไปนี้ เป็นคณะกรรมการจัดซื้อโดยวิธีเฉพาะเจาะจง "
            "และคณะกรรมการตรวจรับพัสดุ สำหรับการซื้อหนังสือเรียน "
            f"ประจำปีการศึกษา {tp.year} โดยวิธี{proc.method or 'เฉพาะเจาะจง'}",
       align="justify", indent=1.25, after=2)
    _two_committees(doc, proc)

    _p(doc, "อำนาจและหน้าที่", bold=True, before=6, after=1)
    for i, line in enumerate([
        "ให้คณะกรรมการจัดซื้อโดยวิธีเฉพาะเจาะจงที่ได้รับการแต่งตั้ง ปฏิบัติหน้าที่ตามระเบียบ"
        "กระทรวงการคลัง ว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 "
        + LAW_COMMITTEE_BUY,
        "ให้คณะกรรมการตรวจรับพัสดุที่ได้แต่งตั้ง ปฏิบัติหน้าที่ตามระเบียบกระทรวงการคลัง "
        "ว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 " + LAW_COMMITTEE_INSPECT,
    ], start=1):
        pr = _p(doc, f"{i}. {line}", align="justify", after=1)
        pr.paragraph_format.left_indent = Cm(1.25)

    _p(doc, f"สั่ง ณ วันที่ {thai_date_official(proc.command_date) if proc.command_date else _DOT}",
       align="center", before=8, after=12)
    _director_sign(doc, school)
    return _save(doc, f"คำสั่งแต่งตั้งกรรมการจัดซื้อหนังสือเรียน_{tp.year}")


# ------------------------------------------- 3) รายงานผลการพิจารณาและขออนุมัติสั่งซื้อ
def render_result_report(school, proc, tp) -> str:
    doc = _new()
    total = float(proc.total_amount or 0)
    _krut_and_title(doc)
    _p_runs(doc, [("ส่วนราชการ  ", True), (_sname(school) + "  " +
                                           (school.address or "").strip(), False)])
    _p_runs(doc, [("ที่  ", True), (proc.result_memo_no or _BLANK, False), ("\t", False),
                  ("วันที่ ", True),
                  (thai_date(proc.result_memo_date) if proc.result_memo_date else _DOT, False)],
            tab_cm=8)
    _p_runs(doc, [("เรื่อง  ", True), ("รายงานผลการพิจารณาและขออนุมัติสั่งซื้อ", False)])
    _p_runs(doc, [("เรียน  ", True), (f"ผู้อำนวยการ{_sname(school)}", False)])
    _hr(doc)

    _p(doc, f"ตามที่ผู้อำนวยการ{_sname(school)} เห็นชอบรายงานขอซื้อ "
            f"หนังสือเรียนประจำปีการศึกษา {tp.year} โดยวิธี{proc.method or 'เฉพาะเจาะจง'} "
            f"วงเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)}) "
            "ตามระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้าง และการบริหารพัสดุภาครัฐ "
            f"พ.ศ. 2560 {LAW_RESULT_REPORT} รายละเอียดดังแนบ",
       align="justify", indent=1.25, after=2)
    _p(doc, f"ในการนี้เจ้าหน้าที่ได้เจรจาตกลงราคากับ {_vendor(proc)} ซึ่งมีอาชีพขายแล้ว "
            f"ปรากฏว่าเสนอราคาเป็นเงิน {_money(total)} บาท ({bahttext(total)}) "
            "ดังนั้นเพื่อให้เป็นไปตามระเบียบกระทรวงการคลัง ว่าด้วยการจัดซื้อจัดจ้าง"
            f"และการบริหารพัสดุภาครัฐ พ.ศ. 2560 {LAW_NEGOTIATE} "
            "จึงเห็นควรจัดซื้อจากผู้เสนอราคา ดังกล่าว",
       align="justify", indent=1.25, after=2)
    _p(doc, "จึงเรียนมาเพื่อโปรดทราบและพิจารณา", align="justify", indent=1.25, after=1)
    for i, line in enumerate([
        f"อนุมัติให้สั่งซื้อ จาก {_vendor(proc)} เป็นผู้ขาย ในวงเงิน {_money(total)} บาท "
        f"({bahttext(total)}) กำหนดเวลาการส่งมอบ {proc.delivery_days or 30} วัน",
        "ลงนามในใบสั่งซื้อ ดังแนบ",
    ], start=1):
        pr = _p(doc, f"{i}. {line}", align="justify", after=1)
        pr.paragraph_format.left_indent = Cm(1.85)

    _p(doc, "", after=10)
    _officer_signs(doc, school, date=proc.result_memo_date)
    _p(doc, "", after=6)
    _sign_table(doc, [[("", "center")], [("(   )  เห็นชอบ", "left"),
                                         ("(   )  อนุมัติ", "left")]], gap=False)
    _p(doc, "", after=4)
    _director_sign(doc, school, date=proc.result_memo_date)
    return _save(doc, f"รายงานผลการพิจารณาและขออนุมัติสั่งซื้อหนังสือเรียน_{tp.year}")


# ------------------------------------------------------------- 4) ประกาศผู้ชนะการเสนอราคา
def render_winner(school, proc, tp) -> str:
    doc = _new()
    total = float(proc.total_amount or 0)
    owner = (proc.vendor.owner_name if proc.vendor else "") or ""
    _krut_center(doc)
    _p(doc, f"ประกาศ{_sname(school)}", align="center", bold=True, size=18, after=0)
    _p(doc, f"เรื่อง ผู้ชนะการเสนอราคาซื้อหนังสือเรียน ประจำปีการศึกษา {tp.year} "
            f"โดยวิธี{proc.method or 'เฉพาะเจาะจง'}", align="center", bold=True, after=0)
    _p(doc, "-----------------------------------", align="center", after=8)

    _p(doc, f"ตามที่{_sname(school)} ได้ดำเนินการจัดซื้อหนังสือเรียน "
            f"ประจำปีการศึกษา {tp.year} โดยวิธี{proc.method or 'เฉพาะเจาะจง'} นั้น",
       align="justify", indent=1.25, after=2)
    _p(doc, f"การจัดซื้อหนังสือเรียน ประจำปีการศึกษา {tp.year} "
            f"โดยวิธี{proc.method or 'เฉพาะเจาะจง'} (จำนวน {_n_items(proc)} รายการ) "
            f"ผู้ชนะการเสนอราคา ได้แก่ {_vendor(proc)}"
            + (f" โดย {owner.strip()}" if owner.strip() else "")
            + f" โดยเสนอราคาเป็นเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)}) "
              "รวมภาษีมูลค่าเพิ่ม และภาษีอื่น ค่าขนส่ง ค่าจดทะเบียน และค่าใช้จ่ายอื่น ๆ ทั้งปวง",
       align="justify", indent=1.25, after=10)
    _p(doc, f"ประกาศ ณ วันที่ {thai_date_official(proc.winner_date) if proc.winner_date else _DOT}",
       align="center", after=12)
    _director_sign(doc, school)
    return _save(doc, f"ประกาศผู้ชนะการเสนอราคาซื้อหนังสือเรียน_{tp.year}")


# ------------------------------------------------------------------------ 5) ใบสั่งซื้อ
def render_purchase_order(school, proc, tp) -> str:
    doc = _new()
    total = float(proc.total_amount or 0)
    v = proc.vendor
    _krut_center(doc)
    _p(doc, "ใบสั่งซื้อ", align="center", bold=True, size=20, after=6)

    # หัวใบสั่งซื้อรูปแบบเดียวกับงานพัสดุ: ป้ายกำกับตัวหนา
    # ซ้าย = ข้อมูลผู้ขาย | ขวา = เลขที่/วันที่ + ส่วนราชการ
    head = doc.add_table(rows=1, cols=2)
    _no_borders(head)
    _fixed_cols(head, [Cm(9.5), Cm(7.0)])
    hl, hr = head.rows[0].cells

    def vv(attr):
        return (getattr(v, attr, "") or "") if v else ""

    for i, (label, value) in enumerate([
            ("ผู้ขาย : ", (v.name if v else "") or _BLANK),
            ("ที่อยู่ : ", vv("address")),
            ("โทรศัพท์ : ", vv("phone")),
            ("เลขประจำตัวผู้เสียภาษี : ", vv("tax_id")),
            ("เลขที่บัญชีเงินฝากธนาคาร : ", vv("bank_account"))]):
        _cell_line(hl, [(label, True), (value, False)], first=(i == 0))
    for i, (label, value) in enumerate([
            ("ใบสั่งซื้อเลขที่ : ", proc.order_no or _BLANK),
            ("วันที่ : ", thai_date(proc.order_date) if proc.order_date else _DOT),
            ("ส่วนราชการ : ", _sname(school)),
            ("ที่อยู่ : ", (school.address or "").strip())]):
        _cell_line(hr, [(label, True), (value, False)], first=(i == 0))

    _p(doc, f"ตามที่ {(v.name if v else '') or _BLANK} ได้เสนอราคาไว้ต่อ{_sname(school)} "
            f"ลงวันที่ {thai_date(proc.quotation_date) if proc.quotation_date else _DOT} "
            "ซึ่งได้รับราคาและตกลงซื้อ ตามรายการดังต่อไปนี้",
       align="justify", indent=1.25, before=6, after=4)

    # หนังสือมีหลายสิบรายการ -> เขียนรวมบรรทัดเดียว แล้วแนบบัญชีท้ายเอกสาร
    headers = ["ลำดับที่", "รายการสินค้า", "จำนวน", "หน่วย", "ราคา", "รวมเงิน"]
    widths = [Cm(1.6), Cm(6.8), Cm(1.8), Cm(1.6), Cm(2.2), Cm(2.5)]
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    r = t.add_row(); _no_split_row(r)
    for c, v2, w, al in zip(r.cells,
                            ["1", f"ตามบัญชีรายละเอียดแนบท้าย\nจำนวน {_n_items(proc)} รายการ",
                             "", "", "", _money(total)],
                            widths, ["center", "left", "center", "center", "right", "right"]):
        _set_cell(c, v2, align=al, size=14)
        c.width = w
    r = t.add_row(); _no_split_row(r)
    _set_cell(r.cells[0], bahttext(total), bold=True, align="center", size=14)
    r.cells[0].merge(r.cells[3])
    _set_cell(r.cells[4], "รวมเงินทั้งสิ้น", bold=True, align="right", size=14)
    _set_cell(r.cells[5], _money(total), bold=True, align="right", size=14)

    _p(doc, "การสั่งซื้อ อยู่ภายใต้เงื่อนไขดังต่อไปนี้", bold=True, before=8, after=2)
    due = thai_date(proc.delivery_due_date) if proc.delivery_due_date else _DOT
    for i, line in enumerate([
        f"กำหนดส่งมอบภายใน {proc.delivery_days or 30} วัน นับถัดจากวันที่ผู้ขายได้รับใบสั่งซื้อ",
        f"ครบกำหนดส่งมอบวันที่ {due}",
        f"สถานที่ส่งมอบ {(tp.delivery_place or '').strip() or _sname(school)}",
        "ระยะเวลารับประกัน .........",
        f"สงวนสิทธิ์ค่าปรับกรณีส่งมอบเกินกำหนด โดยคิดค่าปรับเป็นรายวันในอัตราร้อยละ "
        f"{FINE_RATE_ORDER} บาท นับตั้งแต่วันที่ล่วงเลยกำหนดแล้วเสร็จตามใบสั่งซื้อ "
        "จนถึงวันที่งานแล้วเสร็จสมบูรณ์",
        "โรงเรียนสงวนสิทธิ์ที่จะไม่รับมอบถ้าปรากฏว่าสินค้านั้นมีลักษณะไม่ตรงตามรายการ"
        "ที่ระบุไว้ในใบสั่งซื้อ",
    ], start=1):
        pr = _p(doc, f"{i}. {line}", align="justify", after=1)
        pr.paragraph_format.left_indent = Cm(1.25)

    _p(doc, "", after=10)
    signer = ((school.head_officer_name or "").strip()
              if (proc.order_signer or "director") == "head_officer"
              else (school.director_name or "").strip())
    role = ("หัวหน้าเจ้าหน้าที่" if (proc.order_signer or "director") == "head_officer"
            else f"ผู้อำนวยการ{_sname(school)}")
    _sign_table(doc, [[
        ("(ลงชื่อ)...............................ผู้สั่งซื้อ", "center"),
        (f"( {signer or _BLANK} )", "center"), (role, "center"),
        (f"วันที่ {thai_date(proc.order_date) if proc.order_date else _DOT}", "center"),
    ], [
        ("(ลงชื่อ)...............................ผู้ขาย", "center"),
        (f"( {((getattr(v, 'owner_name', '') or '') if v else '') or _BLANK} )", "center"),
        (f"ผู้จัดการ{(v.name if v else '') or ''}", "center"),
        (f"วันที่ {thai_date(proc.order_date) if proc.order_date else _DOT}", "center"),
    ]])
    _attach_table(doc, school, proc, tp, title="บัญชีรายละเอียดแนบท้ายใบสั่งซื้อ")
    return _save(doc, f"ใบสั่งซื้อหนังสือเรียน_{tp.year}")


# --------------------------------------------------------------------- 6) ใบตรวจรับพัสดุ
def render_inspection(school, proc, tp) -> str:
    doc = _new()
    total = float(proc.total_amount or 0)
    overdue = int(proc.overdue_days or 0)
    fine = round(total * float(proc.penalty_rate or 0.1) / 100 * overdue, 2)
    _p(doc, "ใบตรวจรับพัสดุ", align="center", bold=True, size=20, after=0)
    _p(doc, "ตามระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ "
            f"พ.ศ. 2560 {LAW_COMMITTEE_INSPECT}", align="center", size=15, after=6)
    _sign_table(doc, [[("", "center")], [
        (f"เขียนที่ {_sname(school)}", "left"),
        (f"วันที่ {thai_date(proc.inspect_date) if proc.inspect_date else _DOT}", "left"),
    ]], gap=False)
    _p(doc, "", after=4)

    _p(doc, f"ตามที่{_sname(school)} ได้จัดซื้อหนังสือเรียน ปีการศึกษา {tp.year} "
            f"จาก {_vendor(proc)} ตามใบสั่งซื้อ เลขที่ {proc.order_no or _BLANK} "
            f"ลงวันที่ {thai_date(proc.order_date) if proc.order_date else _DOT} "
            f"ครบกำหนดส่งมอบวันที่ "
            f"{thai_date(proc.delivery_due_date) if proc.delivery_due_date else _DOT} "
            f"บัดนี้ ผู้ขายได้ส่งมอบพัสดุ ตามใบส่งของ "
            f"เล่มที่ {proc.delivery_note_book or _DOT} เลขที่ {proc.delivery_note_no or _DOT} "
            f"วันที่ {thai_date(proc.delivery_date) if proc.delivery_date else _DOT} "
            "คณะกรรมการตรวจรับพัสดุได้ตรวจรับพัสดุแล้ว ปรากฏว่าถูกต้องครบถ้วนตามใบสั่งซื้อ"
            f"ทุกประการ โดยส่งมอบเกินกำหนดจำนวน {overdue} วัน "
            f"คิดค่าปรับในอัตราร้อยละ {proc.penalty_rate or 0.1} ต่อวัน "
            f"เป็นเงินทั้งสิ้น {_money(fine)} บาท "
            f"จึงออกหนังสือสำคัญฉบับนี้ไว้ ผู้ขายควรได้รับเงินเป็นจำนวนเงินทั้งสิ้น "
            f"{_money(total - fine)} บาท ({bahttext(total - fine)}) ตามใบสั่งซื้อ",
       align="justify", indent=1.25, after=2)
    _p(doc, f"จึงขอเสนอรายงานต่อผู้อำนวยการ{_sname(school)} เพื่อโปรดทราบ "
            f"ตามนัย{LAW_COMMITTEE_INSPECT} (4) แห่งระเบียบกระทรวงการคลังว่าด้วย"
            "การจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560",
       align="justify", indent=1.25, after=8)

    roles = ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"]
    members = _committee(proc, "inspect") or [None, None, None]
    block = []
    for i, m in enumerate(members):
        role = (getattr(m, "role", "") or "").strip() or (
            roles[i] if i < len(roles) else "กรรมการ")
        block.append((f"(ลงชื่อ) ...................................... {role}", "center"))
        block.append((f"( {(getattr(m, 'name', '') or '').strip() or _BLANK} )", "center"))
    _sign_table(doc, [[("", "center")], block])

    _p_runs(doc, [("เรียน  ", True), (f"ผู้อำนวยการ{_sname(school)}", False)], after=2)
    _p(doc, f"เพื่อโปรดทราบผลการตรวจรับพัสดุ ค่าจัดซื้อหนังสือเรียน ปีการศึกษา {tp.year} "
            "คณะกรรมการตรวจรับพัสดุได้ดำเนินการตรวจรับพัสดุดังกล่าวเรียบร้อยแล้ว "
            "รายละเอียดตามใบตรวจรับพัสดุที่รายงานเสนอ และขออนุมัติเบิกจ่ายเงินให้ผู้ขาย "
            f"เป็นเงิน {_money(total - fine)} บาท ({bahttext(total - fine)})",
       align="justify", indent=1.25, after=6)
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ...............................เจ้าหน้าที่", "center"),
        (f"( {(school.officer_name or '').strip() or _BLANK} )", "center"),
    ]])
    _p(doc, "ความเห็นของหัวหน้าเจ้าหน้าที่", after=0)
    _p(doc, "." * 90, after=4)
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ...............................หัวหน้าเจ้าหน้าที่", "center"),
        (f"( {(school.head_officer_name or '').strip() or _BLANK} )", "center"),
    ]])
    _sign_table(doc, [[("คำสั่ง     (   ) ทราบ      (   ) อนุมัติ", "left")],
                      [("ลงชื่อ.................................................", "center"),
                       (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
                       (f"ผู้อำนวยการ{_sname(school)}", "center")]])
    _attach_table(doc, school, proc, tp, title="บัญชีรายละเอียดแนบท้ายใบตรวจรับพัสดุ")
    return _save(doc, f"ใบตรวจรับพัสดุหนังสือเรียน_{tp.year}")


def tp_groups(tp):
    """ระดับชั้นที่ซื้อหนังสือ (ใช้เขียนเหตุผลความจำเป็นในรายงานขอซื้อ)"""
    from app.services.textbook_selection import load_selection, selection_groups
    from app.thai_utils import SCHOOL_LEVELS
    if tp.selection_items is None:
        return []
    return selection_groups(load_selection(tp.selection_items), SCHOOL_LEVELS)


# แผนที่ชนิดเอกสารของงานพัสดุ -> ตัวสร้างฉบับหนังสือเรียน
BOOK_RENDERERS = {
    "รายงานขอซื้อ": render_buy_report,
    "คำสั่งแต่งตั้งผู้ตรวจรับ": render_buy_command,
    "รายงานผลการพิจารณา": render_result_report,
    "ประกาศผู้ชนะ": render_winner,
    "ใบสั่งซื้อ/สั่งจ้าง": render_purchase_order,
    "ใบตรวจรับพัสดุ": render_inspection,
}
