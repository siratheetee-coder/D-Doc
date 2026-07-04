# -*- coding: utf-8 -*-
"""
lunch_ingredient_doc.py — เอกสารการจัดซื้อวัตถุดิบเพื่อประกอบอาหารกลางวัน (รูปแบบ 1)
ตามคู่มือการดำเนินงานโครงการอาหารกลางวัน สพฐ. (วงเงินไม่เกิน 500,000 บาท) แบบยืมเงิน->ส่งใช้
อ้างถ้อยคำ/โครงสร้างจากไฟล์ตัวอย่างที่โรงเรียนใช้จริง (Lunch examples/1 ...)

ชุดเอกสาร (ต่อรอบ/เดือน):
  02 บันทึกขออนุมัติยืมเงิน   03 สัญญายืมเงิน (ฟอร์ม)   04 แบบประมาณการค่าใช้จ่าย
  05 ใบจัดซื้อวัสดุเครื่องบริโภค (4 ส่วน)   06 ใบรับรายงานวัตถุดิบ (ฟอร์ม)
  07 ใบเสร็จรับเงิน (ฟอร์ม)   08 ใบรับรองการจ่ายเงิน (ฟอร์ม)
  09 บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหาร   10 ขออนุมัติเบิกจ่ายส่งใช้เงินยืม
"""
from docx import Document
from docx.shared import Cm

from app.thai_utils import bahttext
from app.services.build_templates import (
    _font, _p, _sign_table, _set_cell, _repeat_header_row, _no_split_row,
)
from app.services.lunch_doc import _money, _dnum, _save, _simple_table, _BLANK

_THAI_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def _month_year(dt) -> str:
    if not dt:
        return "................"
    return f"{_THAI_MONTHS[dt.month]} {dt.year + 543}"


def _fund(prog) -> str:
    return (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"


def _borrower(school):
    """ผู้ยืมเงิน = เจ้าหน้าที่โครงการอาหารกลางวัน (ใช้เจ้าหน้าที่พัสดุเป็นค่าตั้งต้น)"""
    name = (getattr(school, "officer_name", "") or "").strip() or _BLANK
    return name, "เจ้าหน้าที่โครงการอาหารกลางวัน"


def _begin(doc):
    if doc is None:
        d = Document(); _font(d); return d, True
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
    bname, bpos = _borrower(school)
    fin = (getattr(school, "finance_officer_name", "") or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    students = prog.total_students
    days = rnd.days or 0
    rate = prog.rate_per_head or 0
    total = round(float(rnd.amount or 0), 2)

    _p(doc, "บันทึกข้อความ", align="center", bold=True, size=20, after=4)
    _p(doc, f"ส่วนราชการ  โรงเรียน{sname}  {saddr}", after=0)
    _p(doc, f"ที่  {(rnd.order_no or '').strip() or _BLANK}\t\tวันที่  {_dnum(rnd.order_date)}", after=0)
    _p(doc, f"เรื่อง  ขออนุมัติยืมเงิน (เงินอุดหนุนอาหารกลางวันรับจาก{fund})", after=0)
    _p(doc, f"เรียน  ผู้อำนวยการโรงเรียน{sname}", after=6)
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
    bname, bpos = _borrower(school)
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
    bname, bpos = _borrower(school)
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
    _simple_table(doc,
                  ["รายการอาหาร", "วัสดุเครื่องบริโภค", "จำนวนหน่วย", "ราคาต่อหน่วย", "จำนวนเงิน", "หมายเหตุ"],
                  [["", "", "", "", "", ""], ["", "", "", "", "", ""], ["", "", "", "", "", ""]],
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
    _simple_table(doc,
                  ["วันที่", "เมนูอาหาร", "ส่วนประกอบ", "จำนวน", "หน่วย", "ราคาต่อหน่วย", "จำนวนเงิน"],
                  [["", "", "", "", "", "", ""] for _ in range(6)],
                  [Cm(2), Cm(3), Cm(3), Cm(1.6), Cm(1.6), Cm(2.4), Cm(2.4)])
    _p(doc, "(ลงชื่อ)....................................ผู้จัดทำรายงาน", align="center", before=6, after=0)
    return _finish(doc, own, f"ใบรับรายงานวัตถุดิบ_รอบที่{rnd.seq}_ปี{prog.year}")


def render_receipt_form(rnd, school, doc=None) -> str:
    """07 ใบเสร็จรับเงิน + 08 ใบรับรองการจ่ายเงิน (ฟอร์มเปล่าตามระเบียบฯ พ.ศ. 2562 ข้อ 48)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    bname, bpos = _borrower(school)
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
    _p(doc, "รวมทั้งสิ้น (ตัวอักษร)............................................................................................",
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
    bname, _ = _borrower(school)
    director = (school.director_name or "").strip() or _BLANK
    _p(doc, "บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหารกลางวัน",
       align="center", bold=True, size=17, after=4)
    _p(doc, f"เขียนที่ โรงเรียน{sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(rnd.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่โรงเรียน{sname} ได้มอบหมายให้ {bname} จัดซื้อวัตถุดิบและประกอบอาหารกลางวันให้นักเรียน"
            f"รับประทาน ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} บัดนี้ "
            "ได้ดำเนินการประกอบอาหารทุกวันตามที่กำหนด ผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหารกลางวัน "
            "ขอรายงานผลการดำเนินงาน ดังนี้", align="justify", indent=1.25, after=4)
    _simple_table(doc,
                  ["วัน เดือน ปี", "รายการอาหาร", "ผลการดำเนินงาน", "ผู้ควบคุมและคณะกรรมการตรวจการ"],
                  [["", "", "", ""] for _ in range(5)],
                  [Cm(2.4), Cm(4.6), Cm(3.4), Cm(5.0)])
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
    bname, bpos = _borrower(school)
    fin = (getattr(school, "finance_officer_name", "") or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    total = round(float(rnd.amount or 0), 2)

    _p(doc, "บันทึกข้อความ", align="center", bold=True, size=20, after=4)
    _p(doc, f"ส่วนราชการ  โรงเรียน{sname}  {saddr}", after=0)
    _p(doc, f"ที่  {(rnd.order_no or '').strip() or _BLANK}\t\tวันที่  {_dnum(rnd.end_date)}", after=0)
    _p(doc, f"เรื่อง  ขออนุมัติเบิกจ่ายเงินเพื่อส่งใช้เงินยืม (เงินอุดหนุนอาหารกลางวันรับจาก{fund})", after=0)
    _p(doc, f"เรียน  ผู้อำนวยการโรงเรียน{sname}", after=6)
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


def render_ingredient_bundle(rnd, school) -> str:
    """ออกชุดเอกสารซื้อวัตถุดิบทั้งชุดเป็นไฟล์เดียว (เรียงตามลำดับงานจริง)"""
    doc = Document(); _font(doc)
    render_borrow_memo(rnd, school, doc)          # 02 ขออนุมัติยืมเงิน
    render_estimate(rnd, school, doc)             # 04 แบบประมาณการ
    render_purchase_form(rnd, school, doc)        # 05 ใบจัดซื้อวัสดุเครื่องบริโภค
    render_material_report_form(rnd, school, doc) # 06 ใบรับรายงานวัตถุดิบ
    render_receipt_form(rnd, school, doc)         # 07+08 ใบเสร็จ/ใบรับรองการจ่าย
    render_control_report(rnd, school, doc)       # 09 บันทึกตรวจการประกอบอาหาร
    render_repay_memo(rnd, school, doc)           # 10 ขออนุมัติเบิกจ่ายส่งใช้เงินยืม
    return _save(doc, f"ชุดเอกสารซื้อวัตถุดิบ_รอบที่{rnd.seq}_ปี{rnd.program.year}")
