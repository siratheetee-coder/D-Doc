# -*- coding: utf-8 -*-
"""
lunch_ingredient_doc.py - เอกสารการจัดซื้อวัตถุดิบเพื่อประกอบอาหารกลางวัน (รูปแบบ 1)
ตามคู่มือการดำเนินงานโครงการอาหารกลางวัน สพฐ. (วงเงินไม่เกิน 500,000 บาท) แบบยืมเงิน->ส่งใช้
อ้างถ้อยคำ/โครงสร้างจากไฟล์ตัวอย่างที่โรงเรียนใช้จริง (Lunch examples/1 ...)

ชุดเอกสาร (ต่อรอบ/เดือน):
  02 บันทึกขออนุมัติยืมเงิน   03 สัญญายืมเงิน (ฟอร์ม)   04 แบบประมาณการค่าใช้จ่าย
  05 ใบจัดซื้อวัสดุเครื่องบริโภค (4 ส่วน)   06 ใบรับรายงานวัตถุดิบ (ฟอร์ม)
  07 ใบเสร็จรับเงิน (ฟอร์ม)   08 ใบรับรองการจ่ายเงิน (ฟอร์ม)
  09 บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหาร   10 ขออนุมัติเบิกจ่ายส่งใช้เงินยืม
"""
from datetime import datetime
from docx import Document
from docx.shared import Cm

from app.services.doc_page import set_a4

from app.thai_utils import bahttext
from app.services.build_templates import (
    _font, _p, _sign_table, _set_cell, _repeat_header_row, _no_split_row,
    _krut_and_title,
)
from app.services.lunch_doc import _money, _dnum, _save, _simple_table, _BLANK, _memo_head

_THAI_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def _month_year(dt) -> str:
    if not dt:
        return "................"
    return f"{_THAI_MONTHS[dt.month]} {dt.year + 543}"


def _fund(prog) -> str:
    return (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"


def _borrower(school, prog=None):
    """ผู้ยืมเงิน/ผู้จ่ายเงิน = เจ้าหน้าที่โครงการอาหารกลางวัน (ถ้าตั้งไว้ในโครงการ)
    ถ้าไม่ได้ตั้ง จึงใช้เจ้าหน้าที่พัสดุเป็นค่าตั้งต้น (อาจเป็นคนละคนกัน)"""
    name = ((getattr(prog, "lunch_officer", "") or "").strip()
            or (getattr(school, "officer_name", "") or "").strip() or _BLANK)
    return name, "เจ้าหน้าที่โครงการอาหารกลางวัน"


def _round_ingredients(rnd):
    """วัตถุดิบของโครงการที่อยู่ในช่วงวันของรอบนี้ (เรียงตามวัน/ลำดับ)"""
    prog = rnd.program
    s = rnd.start_date.date() if rnd.start_date else None
    e = rnd.end_date.date() if rnd.end_date else None
    out = []
    for ig in sorted(prog.ingredients, key=lambda x: (x.date or datetime.max, x.seq, x.id)):
        d = ig.date.date() if ig.date else None
        if s and e and d and (d < s or d > e):
            continue
        out.append(ig)
    return out


def _committee(rnd, kind):
    """รายชื่อกรรมการชนิดที่ระบุ (เรียงตามลำดับ)"""
    return [m for m in sorted(rnd.committees, key=lambda x: x.seq) if m.kind == kind]


def _crit_cell():
    """เกณฑ์ประเมินการประกอบอาหาร (ให้ติ๊กในเอกสาร)"""
    return ("ความสะอาด ☐ดีมาก ☐ดี ☐พอใช้ ☐ปรับปรุง\n"
            "คุณภาพอาหาร ☐ดีมาก ☐ดี ☐พอใช้ ☐ปรับปรุง\n"
            "ความทันเวลา ☐ดีมาก ☐ดี ☐พอใช้ ☐ปรับปรุง\n"
            "ความเพียงพอ ☐ดีมาก ☐ดี ☐พอใช้ ☐ปรับปรุง")


def _round_menu_days(rnd):
    """เมนูรายวันในช่วงของรอบ (เรียงตามวัน)"""
    prog = rnd.program
    return [m for m in sorted(prog.menus, key=lambda x: (x.date or datetime.max))
            if m.date and rnd.start_date and rnd.end_date and rnd.start_date <= m.date <= rnd.end_date]


def _begin(doc):
    if doc is None:
        d = Document(); set_a4(d); _font(d); return d, True
    if doc.paragraphs or doc.tables:
        doc.add_page_break()
    return doc, False


def _finish(doc, own, name):
    return _save(doc, name) if own else doc


def render_borrow_memo(rnd, school, doc=None) -> str:
    """02 บันทึกขออนุมัติยืมเงินอุดหนุนอาหารกลางวัน"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    saddr = (school.address or "").strip()
    fund = _fund(prog)
    bname, bpos = _borrower(school, rnd.program)
    fin = (getattr(school, "finance_officer_name", "") or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    students = prog.total_students
    days = rnd.days or 0
    rate = prog.rate_per_head or 0
    total = round(float(rnd.amount or 0), 2)

    _memo_head(doc, school, [f"ขออนุมัติยืมเงิน (เงินอุดหนุนอาหารกลางวันรับจาก{fund})"],
               _dnum(rnd.order_date), rnd.order_no)
    _p(doc, f"ด้วยข้าพเจ้า {bname} ตำแหน่ง {bpos} มีความประสงค์ขอยืมเงิน (เงินอุดหนุนอาหารกลางวัน"
            f"รับจาก{fund}) สำหรับเป็นค่าใช้จ่ายอาหารกลางวันให้นักเรียนระดับอนุบาลถึงประถมศึกษาปีที่ 6 "
            f"จำนวน {students} คน ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} "
            f"รวมระยะเวลา {days} วัน เป็นเงิน {_money(total)} บาท (ตัวอักษร {bahttext(total)}) "
            f"({students} คน x {days} วัน x {_money(rate)} บาท) ตามสัญญาการยืมเงินและประมาณการดังแนบ "
            "และขอรับรองว่า ข้าพเจ้าไม่มีหนี้ผูกพันเกี่ยวกับเงินยืมกับทางราชการแต่อย่างใด",
       align="justify", indent=1.25, after=2)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติ", indent=1.25, after=12)
    _sign_table(doc, [
        [("(ลงชื่อ)....................................................ผู้ยืม", "center"),
         (f"( {bname} )", "center")],
        [(f"ตำแหน่ง {bpos}", "center"), ("", "center")]])
    _p(doc, "", after=4)
    _simple_table(doc, ["ความคิดเห็นเจ้าหน้าที่การเงิน", "คำสั่ง/การสั่งการ"],
                  [[f"ได้ตรวจสอบสัญญาการยืมเงินและเอกสารประกอบแล้วถูกต้องตามระเบียบ เห็นควรอนุมัติ"
                    f"ให้ยืมเงินให้แก่ผู้ยืม\n\n(ลงชื่อ)....................เจ้าหน้าที่การเงิน\n( {fin} )",
                    f"(  ) ทราบ  (  ) อนุมัติ  (  ) ลงนามในสัญญาการยืมเงิน\n\n"
                    f"(ลงชื่อ)....................ผู้อำนวยการโรงเรียน\n( {director} )"]],
                  [Cm(8.2), Cm(7.8)])
    return _finish(doc, own, f"บันทึกขออนุมัติยืมเงิน_รอบที่{rnd.seq}_ปี{prog.year}")


def render_estimate(rnd, school, doc=None) -> str:
    """04 แบบประมาณการค่าใช้จ่าย (แนบท้ายสัญญายืมเงิน)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    bname, bpos = _borrower(school, rnd.program)
    students = prog.total_students
    days = rnd.days or 0
    rate = prog.rate_per_head or 0
    total = round(float(rnd.amount or 0), 2)

    _p(doc, "แบบประมาณการค่าใช้จ่าย", align="center", bold=True, size=18, after=0)
    _p(doc, f"โรงเรียน{sname}", align="center", after=0)
    _p(doc, f"แนบท้ายสัญญาเงินยืมเลขที่ {(rnd.order_no or '').strip() or '........./.........'} "
            f"ลงวันที่ {_dnum(rnd.order_date)}", align="center", after=6)
    _simple_table(doc, ["รายการ", "จำนวนเงิน"],
                  [[f"ประมาณการค่าอาหารกลางวัน ประจำเดือน {_month_year(rnd.start_date)} "
                    f"จำนวน {students} คน x อัตราวันละ {_money(rate)} บาท x จำนวน {days} วัน",
                    _money(total)],
                   [f"รวมจำนวนเงินทั้งสิ้น (ตัวอักษร {bahttext(total)})", _money(total)]],
                  [Cm(11.5), Cm(4.5)])
    _p(doc, "", after=12)
    _sign_table(doc, [
        [("(ลงชื่อ)..................................................ผู้ประมาณการ/ผู้ยืม", "center"),
         (f"( {bname} )", "center")],
        [(f"ตำแหน่ง {bpos}", "center"), ("", "center")]])
    return _finish(doc, own, f"แบบประมาณการค่าใช้จ่าย_รอบที่{rnd.seq}_ปี{prog.year}")


def render_purchase_form(rnd, school, doc=None) -> str:
    """05 ใบจัดซื้อวัสดุเครื่องบริโภค วงเงินไม่เกิน 500,000 บาท (รวม 4 ส่วนในใบเดียว)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    bname, bpos = _borrower(school, rnd.program)
    officer = (getattr(school, "officer_name", "") or "").strip() or _BLANK
    head = (getattr(school, "head_officer_name", "") or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK

    _p(doc, "ใบจัดซื้อวัสดุเครื่องบริโภค วงเงินไม่เกิน 500,000 บาท", align="center", bold=True, size=17, after=0)
    _p(doc, f"โรงเรียน{sname}", align="center", after=6)

    _p(doc, "ส่วนที่ 1 รายงานขอซื้อ", bold=True, indent=0.5, after=0)
    _p(doc, f"ด้วยโรงเรียน{sname} ขอจัดซื้อวัสดุเครื่องบริโภคตามรายการต่อไปนี้ เพื่อประกอบอาหารให้แก่"
            "นักเรียนรับประทาน การจัดซื้อครั้งนี้ดำเนินการโดยวิธีเฉพาะเจาะจงตามมาตรา 56 (2) (ข) ประกอบ"
            "หนังสือกระทรวงการคลัง ด่วนที่สุด ที่ กค (กวจ) 0405.2/ว 116 ลงวันที่ 12 มีนาคม 2562",
       align="justify", indent=1)
    _ings = _round_ingredients(rnd)
    _menus = {m.date.date(): (m.main or "") for m in prog.menus if m.date}
    _body, _pd, _tot = [], None, 0.0
    for ig in _ings:
        d = ig.date.date() if ig.date else None
        amt = (ig.quantity or 0) * (ig.unit_price or 0); _tot += amt
        _body.append([_menus.get(d, "") if d != _pd else "", ig.name or "",
                      f"{_money(ig.quantity)} {ig.unit or ''}".strip(),
                      _money(ig.unit_price), _money(amt), ""])
        _pd = d
    if _body:
        _body.append(["", "รวมเป็นเงินทั้งสิ้น", "", "", _money(_tot), ""])
    else:
        _body = [["", "", "", "", "", ""] for _ in range(3)]
    _simple_table(doc,
                  ["รายการอาหาร", "วัสดุเครื่องบริโภค", "จำนวนหน่วย", "ราคาต่อหน่วย", "จำนวนเงิน", "หมายเหตุ"],
                  _body,
                  [Cm(3.4), Cm(3.4), Cm(2.2), Cm(2.2), Cm(2.2), Cm(2.6)])
    _p(doc, "(ลงชื่อ)..................................ผู้จัดทำรายการ", align="center", before=2, after=8)

    _p(doc, "ส่วนที่ 2 การจัดซื้อ (เสนอเห็นชอบและแต่งตั้งกรรมการ)", bold=True, indent=0.5, after=0)
    _p(doc, f"เรียน ผู้อำนวยการโรงเรียน{sname} เพื่อโปรดทราบและเห็นชอบตามรายงานขอซื้อ และแต่งตั้ง",
       align="justify", indent=1, after=0)
    _p(doc, "ผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหาร และผู้ตรวจรับพัสดุ/คณะกรรมการตรวจรับพัสดุ",
       indent=1, after=6)
    _sign_table(doc, [
        [("(ลงชื่อ)..............................เจ้าหน้าที่", "center"),
         (f"( {officer} )", "center")],
        [("(ลงชื่อ)..............................หัวหน้าเจ้าหน้าที่", "center"),
         (f"( {head} )", "center")]])
    _p(doc, "อนุมัติตามเสนอ ข้อ 1 และข้อ 2", align="center", bold=True, before=2, after=6)
    _sign_table(doc, [
        [("(ลงชื่อ)..............................ผู้อำนวยการโรงเรียน", "center"),
         (f"( {director} )", "center")]])

    _p(doc, "ส่วนที่ 3 ใบรับรองการจ่ายเงิน", bold=True, indent=0.5, before=4, after=0)
    _p(doc, f"ข้าพเจ้า {bname} ตำแหน่ง {bpos} ได้จ่ายเงินค่าวัสดุเครื่องบริโภคตามรายการข้างต้น "
            "โดยไม่อาจเรียกใบเสร็จรับเงินจากผู้รับเงินได้ ตามรายการที่ปรากฏในส่วนที่ 1",
       align="justify", indent=1, after=8)
    _p(doc, "(ลงชื่อ)..................................ผู้จ่ายเงิน", align="center", after=8)

    _p(doc, "ส่วนที่ 4 ผลการตรวจและอนุมัติการจ่ายเงิน", bold=True, indent=0.5, after=0)
    _p(doc, f"เรียน ผู้อำนวยการโรงเรียน{sname} เพื่อโปรดทราบ พัสดุตามรายการข้างต้นได้ทำการตรวจรับไว้"
            "เป็นการถูกต้องครบถ้วนแล้ว และได้ตรวจสอบหลักฐานแล้วถูกต้อง จึงขออนุมัติเบิกจ่ายเงิน",
       align="justify", indent=1, after=6)
    _sign_table(doc, [
        [("(ลงชื่อ)..............................เจ้าหน้าที่การเงิน", "center"),
         ("(ลงชื่อ)..............................หัวหน้าเจ้าหน้าที่", "center")]])
    _p(doc, "ทราบ/อนุมัติตามรายการที่ขอเบิกและจ่ายเงินได้", align="center", bold=True, before=2, after=6)
    _sign_table(doc, [
        [("(ลงชื่อ)..............................ผู้อำนวยการโรงเรียน", "center"),
         (f"( {director} )", "center")]])
    return _finish(doc, own, f"ใบจัดซื้อวัสดุเครื่องบริโภค_รอบที่{rnd.seq}_ปี{prog.year}")


def render_material_report_form(rnd, school, doc=None) -> str:
    """06 ใบรับรายงานวัตถุดิบและปริมาณการจัดซื้อ (ฟอร์มเปล่าตามโปรแกรม Thai School Lunch)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    _p(doc, "ใบรับรายงานวัตถุดิบและปริมาณการจัดซื้อ", align="center", bold=True, size=17, after=0)
    _p(doc, "(ตามโปรแกรม Thai School Lunch หรือปรับใช้ตามหลักโภชนาการ)", align="center", after=0)
    _p(doc, f"โรงเรียน{sname}", align="center", after=0)
    _p(doc, f"ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)}", align="center", after=6)
    # ดึงวัตถุดิบรายวันมาเติมให้ (แสดงวัน/เมนู เฉพาะแถวแรกของแต่ละวัน) - ถ้ายังไม่กรอกให้เป็นฟอร์มเปล่า
    ings = _round_ingredients(rnd)
    menus_by_date = {m.date.date(): (m.main or "") for m in prog.menus if m.date}
    body, prev_d, total = [], None, 0.0
    for ig in ings:
        d = ig.date.date() if ig.date else None
        amt = (ig.quantity or 0) * (ig.unit_price or 0)
        total += amt
        body.append([_dnum(ig.date) if (ig.date and d != prev_d) else "",
                     menus_by_date.get(d, "") if d != prev_d else "",
                     ig.name or "", _money(ig.quantity), ig.unit or "",
                     _money(ig.unit_price), _money(amt)])
        prev_d = d
    if body:
        body.append(["", "", "รวมเป็นเงินทั้งสิ้น", "", "", "", _money(total)])
    else:
        body = [["", "", "", "", "", "", ""] for _ in range(6)]
    _simple_table(doc,
                  ["วันที่", "เมนูอาหาร", "ส่วนประกอบ", "จำนวน", "หน่วย", "ราคาต่อหน่วย", "จำนวนเงิน"],
                  body,
                  [Cm(2), Cm(3), Cm(3), Cm(1.6), Cm(1.6), Cm(2.4), Cm(2.4)])
    if body and total:
        _p(doc, f"รวมเป็นเงินทั้งสิ้น (ตัวอักษร) {bahttext(total)}", align="right", before=2, after=2, size=13)
    _p(doc, "(ลงชื่อ)....................................ผู้จัดทำรายงาน", align="center", before=6, after=0)
    return _finish(doc, own, f"ใบรับรายงานวัตถุดิบ_รอบที่{rnd.seq}_ปี{prog.year}")


def render_receipt_form(rnd, school, doc=None) -> str:
    """07 ใบเสร็จรับเงิน + 08 ใบรับรองการจ่ายเงิน (ฟอร์มเปล่าตามระเบียบฯ พ.ศ. 2562 ข้อ 48)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    bname, bpos = _borrower(school, rnd.program)
    # 07 ใบเสร็จรับเงิน
    _p(doc, "ใบเสร็จรับเงิน", align="center", bold=True, size=18, after=2)
    _p(doc, "เล่มที่................    เลขที่................", align="right", after=4)
    for line in ["ชื่อบุคคล/ร้านค้า/ห้างหุ้นส่วนจำกัด/บริษัท ...........................................................",
                 "ที่อยู่ ...................................................................................................................",
                 "เลขที่ผู้เสียภาษีอากร ..................................    วันที่ ..............................................",
                 f"ชื่อ (ผู้ซื้อ)  โรงเรียน{sname}"]:
        _p(doc, line, indent=1, after=0)
    _p(doc, "ลงชื่อ....................................................ผู้รับเงิน", align="center", before=8, after=0)
    # 08 ใบรับรองการจ่ายเงิน
    doc.add_page_break()
    _p(doc, "ใบรับรองการจ่ายเงิน", align="center", bold=True, size=18, after=2)
    _p(doc, f"โรงเรียน{sname}", align="center", after=0)
    _p(doc, "วันที่.............. เดือน ...................... พ.ศ. ..............", align="center", after=6)
    _rtotal = sum((ig.quantity or 0) * (ig.unit_price or 0) for ig in _round_ingredients(rnd))
    _p(doc, "รวมทั้งสิ้น (ตัวอักษร) "
            + (f"{bahttext(_rtotal)} ({_money(_rtotal)} บาท)" if _rtotal
               else "............................................................................................"),
       indent=1, after=2)
    _p(doc, f"ข้าพเจ้า {bname} ตำแหน่ง {bpos} โรงเรียน{sname} ขอรับรองว่ารายจ่ายข้างต้นนี้ไม่อาจเรียก"
            "ใบเสร็จรับเงินจากผู้ขายได้ และข้าพเจ้าได้จ่ายไปในงานของราชการโดยแท้",
       align="justify", indent=1, after=10)
    _p(doc, "ลงชื่อ..........................................................", align="center", after=0)
    _p(doc, f"( {bname} )", align="center", after=0)
    _p(doc, "หมายเหตุ กรณีไม่สามารถเรียกใบเสร็จรับเงินจากผู้ขายได้ ให้ใช้ใบรับรองการจ่ายเงินแทน "
            "(อ้างอิงระเบียบกระทรวงการคลังฯ พ.ศ. 2562 ข้อ 48)", indent=0.5, before=8, size=13)
    return _finish(doc, own, f"ใบเสร็จ_ใบรับรองการจ่าย_รอบที่{rnd.seq}_ปี{prog.year}")


def render_control_report(rnd, school, doc=None) -> str:
    """09 บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหารกลางวัน"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    bname, _ = _borrower(school, rnd.program)
    director = (school.director_name or "").strip() or _BLANK
    _p(doc, "บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหารกลางวัน",
       align="center", bold=True, size=17, after=4)
    _p(doc, f"เขียนที่ โรงเรียน{sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(rnd.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่โรงเรียน{sname} ได้มอบหมายให้ {bname} จัดซื้อวัตถุดิบและประกอบอาหารกลางวันให้นักเรียน"
            f"รับประทาน ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} บัดนี้ "
            "ได้ดำเนินการประกอบอาหารทุกวันตามที่กำหนด ผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหารกลางวัน "
            "ขอรายงานผลการดำเนินงาน ดังนี้", align="justify", indent=1.25, after=4)
    # ผู้ควบคุม + คณะกรรมการตรวจการประกอบอาหาร (ดึงชื่อจากที่ตั้งไว้)
    ctrl = _committee(rnd, "cook_control") + _committee(rnd, "food_inspect")
    ctrl_names = "\n".join(f"{i + 1}. {m.name}" for i, m in enumerate(ctrl)) if ctrl else ""
    days = _round_menu_days(rnd)
    if days:
        body = [[_dnum(m.date), (m.main or ""), _crit_cell(), ctrl_names] for m in days]
    else:
        body = [["", "", _crit_cell(), ctrl_names] for _ in range(5)]
    _simple_table(doc,
                  ["วัน เดือน ปี", "รายการอาหาร", "ผลการตรวจสอบ", "ผู้ควบคุม/คณะกรรมการตรวจการ"],
                  body,
                  [Cm(2.1), Cm(3.4), Cm(6.2), Cm(4.55)])
    _p(doc, "(  ) ทราบผลการดำเนินการประกอบอาหารกลางวัน", indent=1.25, before=4, after=10)
    _p(doc, "ลงชื่อ......................................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ตำแหน่ง ผู้อำนวยการโรงเรียน{sname}", align="center", after=0)
    return _finish(doc, own, f"บันทึกรายงานตรวจการประกอบอาหาร_รอบที่{rnd.seq}_ปี{prog.year}")


def render_repay_memo(rnd, school, doc=None) -> str:
    """10 บันทึกขออนุมัติเบิกจ่ายเงินเพื่อส่งใช้เงินยืม"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    saddr = (school.address or "").strip()
    fund = _fund(prog)
    bname, bpos = _borrower(school, rnd.program)
    fin = (getattr(school, "finance_officer_name", "") or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    total = round(float(rnd.amount or 0), 2)

    _memo_head(doc, school, [f"ขออนุมัติเบิกจ่ายเงินเพื่อส่งใช้เงินยืม (เงินอุดหนุนอาหารกลางวันรับจาก{fund})"],
               _dnum(rnd.end_date), rnd.order_no)
    _p(doc, f"ตามที่อนุมัติให้ {bname} ผู้ยืมเงินโครงการอาหารกลางวัน ยืมเงิน (เงินอุดหนุนอาหารกลางวัน"
            f"รับจาก{fund}) เพื่อเป็นค่าใช้จ่ายอาหารกลางวันให้นักเรียนรับประทาน จำนวนเงิน {_money(total)} "
            f"บาท (ตัวอักษร {bahttext(total)}) ตามสัญญาการยืมเงินที่ {(rnd.order_no or '').strip() or _BLANK} "
            f"ลงวันที่ {_dnum(rnd.order_date)} นั้น", align="justify", indent=1.25, after=2)
    _p(doc, "บัดนี้ ได้ดำเนินการตามวัตถุประสงค์แล้ว ขอส่งใช้หลักฐาน และเงินสด (ถ้ามี) ดังนี้",
       align="justify", indent=1.25, after=0)
    _p(doc, f"1. หลักฐานค่าอาหารกลางวัน\t\tจำนวน {_money(total)} บาท", indent=1.5, after=0)
    _p(doc, "2. เงินสด (ถ้ามี)\t\t\tจำนวน - บาท", indent=1.5, after=0)
    _p(doc, f"รวมเป็นเงิน {_money(total)} บาท", indent=1.5, after=2)
    _p(doc, f"จึงเรียนมาเพื่อโปรดทราบ และอนุมัติเบิกจ่ายเงิน (เงินอุดหนุนอาหารกลางวันรับจาก{fund}) "
            f"จำนวน {_money(total)} บาท (ตัวอักษร {bahttext(total)})", align="justify", indent=1.25, after=12)
    _sign_table(doc, [
        [("(ลงชื่อ)....................................................ผู้ยืม", "center"),
         (f"( {bname} )", "center")],
        [(f"ตำแหน่ง {bpos}", "center"), ("", "center")]])
    _p(doc, "", after=4)
    _simple_table(doc, ["ความคิดเห็นเจ้าหน้าที่การเงิน", "คำสั่ง/การสั่งการ"],
                  [[f"ได้ตรวจสอบหลักฐานและเอกสารประกอบการส่งใช้เงินยืมแล้วถูกต้องครบถ้วนตามระเบียบ "
                    f"เห็นควรอนุมัติเบิกจ่ายเงิน\n\n(ลงชื่อ)....................เจ้าหน้าที่การเงิน\n( {fin} )",
                    f"(  ) ทราบ  (  ) อนุมัติ\n\n(ลงชื่อ)....................ผู้อำนวยการโรงเรียน\n( {director} )"]],
                  [Cm(8.2), Cm(7.8)])
    return _finish(doc, own, f"ขออนุมัติเบิกจ่ายส่งใช้เงินยืม_รอบที่{rnd.seq}_ปี{prog.year}")


def _committee_signs(doc, members):
    """ลายเซ็นคณะกรรมการตรวจรับ (ประธาน/กรรมการ) - ไม่มีชื่อ = เส้นจุด 3 คน"""
    seq = members if members else [None, None, None]
    for i, mem in enumerate(seq):
        role = (mem.role if mem else "") or ("ประธานกรรมการ" if i == 0 else "กรรมการ")
        _p(doc, f"(ลงชื่อ) ........................................... {role}", align="center", before=6, after=0)
        _p(doc, (f"( {mem.name} )" if mem else "(...........................................)"),
           align="center", after=0)


def render_purchase_summary(rnd, school, doc=None) -> str:
    """สรุปรายการจัดซื้อวัตถุดิบ (เพื่อประกอบการตรวจรับพัสดุ) - ดึงวัตถุดิบ+กรรมการตรวจรับมาเติม"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    ings = _round_ingredients(rnd)
    total = sum((i.quantity or 0) * (i.unit_price or 0) for i in ings)
    _p(doc, "สรุปรายการจัดซื้อวัตถุดิบเพื่อใช้ประกอบอาหาร", align="center", bold=True, size=17, after=0)
    _p(doc, f"โรงเรียน{sname}  ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)}",
       align="center", after=4)
    _p(doc, "เรียน  ประธานคณะกรรมการตรวจรับพัสดุ/ผู้ตรวจรับพัสดุ", indent=1, after=2)
    _p(doc, "ขอรายงานรายการจัดซื้อวัตถุดิบเพื่อใช้ประกอบอาหาร เพื่อประกอบการตรวจรับพัสดุ ดังนี้",
       indent=1.25, after=2)
    body = [[i.name or "", _money(i.quantity), i.unit or "", _money(i.unit_price),
             _money((i.quantity or 0) * (i.unit_price or 0)), ""] for i in ings]
    if body:
        body.append(["รวมเป็นเงินทั้งสิ้น", "", "", "", _money(total), ""])
    else:
        body = [["", "", "", "", "", ""] for _ in range(5)]
    _simple_table(doc, ["วัตถุดิบ/เครื่องปรุง", "จำนวน", "หน่วยนับ", "ราคาต่อหน่วย", "จำนวนเงิน", "หมายเหตุ"],
                  body, [Cm(5.0), Cm(1.8), Cm(1.8), Cm(2.6), Cm(2.6), Cm(2.45)])
    _p(doc, "ได้ตรวจสอบรายการวัตถุดิบดังกล่าวแล้ว รายการ จำนวน ถูกต้องครบถ้วน",
       indent=1.25, before=4, after=8)
    _committee_signs(doc, _committee(rnd, "inspect"))
    return _finish(doc, own, f"สรุปรายการจัดซื้อวัตถุดิบ_รอบที่{rnd.seq}_ปี{prog.year}")


def render_inspection_note(rnd, school, doc=None) -> str:
    """ใบตรวจรับพัสดุ (ตามข้อ 175 ระเบียบฯ พ.ศ. 2560) - ดึงกรรมการตรวจรับ + เจ้าหน้าที่พัสดุ"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    officer = (getattr(school, "officer_name", "") or "").strip() or _BLANK
    days = len(_round_menu_days(rnd)) or (rnd.days or 0)
    _p(doc, "ใบตรวจรับพัสดุ", align="center", bold=True, size=18, after=2)
    _p(doc, f"เขียนที่ โรงเรียน{sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(rnd.end_date)}", align="right", after=6)
    _p(doc, f"ตามรายงานสรุปการตรวจรับวัตถุดิบเพื่อใช้ประกอบอาหารกลางวัน ในระหว่างวันที่ "
            f"{_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} รวม {days} วัน รายละเอียดตามแนบ "
            "คณะกรรมการตรวจรับพัสดุ ได้ตรวจรับและให้ถือว่าพัสดุ", align="justify", indent=1.25, after=2)
    _p(doc, "( / )  ถูกต้อง          (   )  ไม่ถูกต้อง  จำนวน .............. รายการ", indent=1.5, after=2)
    _p(doc, f"จึงรายงานต่อผู้อำนวยการโรงเรียน{sname} เพื่อโปรดทราบผลการตรวจรับ ตามนัยข้อ 175 "
            "แห่งระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560",
       align="justify", indent=1.25, after=8)
    _committee_signs(doc, _committee(rnd, "inspect"))
    _p(doc, f"เรียน  ผู้อำนวยการโรงเรียน{sname}", indent=1, before=10, after=0)
    _p(doc, "     เพื่อโปรดทราบ คณะกรรมการตรวจรับพัสดุได้ดำเนินการตรวจรับพัสดุเรียบร้อยแล้ว",
       indent=1.25, after=6)
    _p(doc, "(ลงชื่อ) ........................................... เจ้าหน้าที่พัสดุ", align="center", after=0)
    _p(doc, f"( {officer} )", align="center", after=0)
    return _finish(doc, own, f"ใบตรวจรับพัสดุ_รอบที่{rnd.seq}_ปี{prog.year}")


def render_ingredient_bundle(rnd, school) -> str:
    """ออกชุดเอกสารซื้อวัตถุดิบทั้งชุดเป็นไฟล์เดียว (เรียงตามลำดับงานจริง)"""
    doc = Document(); set_a4(doc); _font(doc)
    render_borrow_memo(rnd, school, doc)          # 02 ขออนุมัติยืมเงิน
    render_estimate(rnd, school, doc)             # 04 แบบประมาณการ
    render_purchase_form(rnd, school, doc)        # 05 ใบจัดซื้อวัสดุเครื่องบริโภค
    render_material_report_form(rnd, school, doc) # 06 ใบรับรายงานวัตถุดิบ
    render_receipt_form(rnd, school, doc)         # 07+08 ใบเสร็จ/ใบรับรองการจ่าย
    render_purchase_summary(rnd, school, doc)     # สรุปรายการจัดซื้อ (เพื่อตรวจรับ)
    render_control_report(rnd, school, doc)       # 09 บันทึกตรวจการประกอบอาหาร
    render_inspection_note(rnd, school, doc)      # ใบตรวจรับพัสดุ (ข้อ 175)
    render_repay_memo(rnd, school, doc)           # 10 ขออนุมัติเบิกจ่ายส่งใช้เงินยืม
    return _save(doc, f"ชุดเอกสารซื้อวัตถุดิบ_รอบที่{rnd.seq}_ปี{rnd.program.year}")
