# -*- coding: utf-8 -*-
"""
lunch_person_doc.py — เอกสารการจ้างบุคคลเพื่อประกอบอาหารกลางวัน (รูปแบบ 2)
ตามคู่มืออาหารกลางวัน สพฐ. = ชุดซื้อวัตถุดิบ (ยืมเงิน -> ส่งใช้ เหมือนรูปแบบ 1)
+ ชุดจ้างบุคคล (ค่าตอบแทน/ค่าแรง) ที่คล้ายรูปแบบ 3 แต่เป็น "จ้างบุคคล" อ้างข้อ 22 ค่าปรับ 0.1
อ้างถ้อยคำจากไฟล์ตัวอย่างจริง (Lunch examples/2 ...) ใช้ helper ร่วมกับ lunch_doc/lunch_ingredient_doc
"""
from docx import Document
from docx.shared import Cm

from app.services.doc_page import set_a4

from app.thai_utils import bahttext
from app.services.build_templates import (
    _font, _p, _sign_table, _krut_center, _hr,
)
from app.services.lunch_doc import (
    _BLANK, _money, _dnum, _save, _begin, _finish, _memo_head,
    _committee_lines, _menu_table3, _simple_table,
)
# ชุดซื้อวัตถุดิบ (ยืมเงิน->ส่งใช้) ใช้ซ้ำจากรูปแบบ 1
from app.services.lunch_ingredient_doc import (
    render_borrow_memo, render_estimate, render_purchase_form,
    render_material_report_form, render_receipt_form, render_control_report,
    render_repay_memo,
)

_WORK = "จ้างบุคคลประกอบอาหารกลางวัน"


def _period(rnd):
    return f"ประจำวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)}"


def render_p_tor(rnd, school, doc=None) -> str:
    """02 ขอบเขตของงาน (TOR) การจ้างบุคคลประกอบอาหารกลางวัน"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    total = round(float(rnd.amount or 0), 2)
    days = rnd.days or 0
    students = prog.total_students
    fund = (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"
    insts = list(rnd.installments or [])
    _p(doc, "ขอบเขตของงาน (TOR) การจ้างบุคคลประกอบอาหารกลางวัน", align="center", bold=True, size=18, after=0)
    _p(doc, f"โรงเรียน{sname}  ประจำปีการศึกษา {prog.year}", align="center", after=6)
    _p(doc, "1. ความเป็นมา", bold=True, indent=0.5, after=0)
    _p(doc, f"โรงเรียน{sname} จัดบริการอาหารกลางวันให้นักเรียนระดับอนุบาลถึงชั้นประถมศึกษาปีที่ 6 "
            "จึงจัดทำขอบเขตของงานจ้างบุคคลประกอบอาหารกลางวันฉบับนี้ เพื่อจ้างบุคคลมาประกอบอาหารกลางวัน "
            "ให้นักเรียนได้รับประทานอาหารที่มีคุณค่าทางโภชนาการ สะอาด และปลอดภัย", align="justify", indent=1)
    _p(doc, "2. วัตถุประสงค์", bold=True, indent=0.5, after=0)
    _p(doc, f"เพื่อจัดหาบุคคลประกอบอาหารกลางวันให้นักเรียนของโรงเรียน{sname} จำนวน {students} คน "
            f"จำนวน {days} วัน (เว้นวันหยุดราชการ)", align="justify", indent=1)
    _p(doc, "3. คุณสมบัติของผู้เสนอราคา", bold=True, indent=0.5, after=0)
    _p(doc, "เป็นบุคคลธรรมดา มีความสามารถตามกฎหมาย ไม่เป็นผู้ทิ้งงานของทางราชการ และสามารถประกอบอาหาร "
            "ที่สะอาดถูกสุขลักษณะได้ตามเวลาที่โรงเรียนกำหนดในทุกวันทำการ", align="justify", indent=1)
    _p(doc, "4. ขอบเขตการดำเนินงาน", bold=True, indent=0.5, after=0)
    _p(doc, f"ผู้รับจ้างต้องประกอบอาหารกลางวันให้แก่นักเรียน {_period(rnd)} ภายในวงเงินไม่เกิน "
            f"{_money(total)} บาท ({bahttext(total)}) โดยจัดรายการอาหารตามหลักโภชนาการที่โรงเรียนกำหนด",
       align="justify", indent=1)
    _p(doc, "5. การส่งมอบและการจ่ายเงิน", bold=True, indent=0.5, after=0)
    _p(doc, f"แบ่งงวดงานจำนวน {len(insts) or '.......'} งวด จ่ายเมื่อผู้รับจ้างสรุปรายการประกอบอาหาร "
            "และคณะกรรมการตรวจรับพัสดุตรวจรับเรียบร้อยแล้ว", align="justify", indent=1)
    _p(doc, "6. วงเงินงบประมาณ", bold=True, indent=0.5, after=0)
    _p(doc, f"เป็นเงิน {_money(total)} บาท ({bahttext(total)}) จาก{fund}", align="justify", indent=1)
    _p(doc, "7. ค่าปรับ", bold=True, indent=0.5, after=0)
    _p(doc, "กำหนดค่าปรับอัตราร้อยละ 0.10 ของค่าจ้างต่อวัน แต่ไม่ต่ำกว่าวันละ 100 บาท อ้างอิงหนังสือ "
            "ที่ กค (กวจ) 0405.2/ว 116 ลงวันที่ 12 มีนาคม 2562", align="justify", indent=1)
    return _finish(doc, own, f"ขอบเขตของงาน_จ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_hire_report(rnd, school, doc=None) -> str:
    """03 รายงานขอจ้างบุคคลประกอบอาหารกลางวัน (ค่าตอบแทน/ค่าแรง)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    officer = (school.officer_name or "").strip() or _BLANK
    head = (school.head_officer_name or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    fund = (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"
    total = round(float(rnd.amount or 0), 2)
    days = rnd.days or 0
    dr = _period(rnd)
    _memo_head(doc, school, [f"รายงานขอจ้างบุคคลประกอบอาหารกลางวัน (ค่าตอบแทน/ค่าแรง)"],
               _dnum(rnd.order_date), rnd.order_no)
    _p(doc, f"ด้วยโรงเรียน{sname} มีความจำเป็นขอจ้างบุคคลประกอบอาหารกลางวันให้แก่นักเรียนรับประทาน "
            f"{dr} จึงรายงานขอจ้างตามระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ "
            "พ.ศ. 2560 ข้อ 22 และขอดำเนินการจ้างโดยวิธีเฉพาะเจาะจง ตามพระราชบัญญัติการจัดซื้อจัดจ้างและ"
            f"การบริหารพัสดุภาครัฐ พ.ศ. 2560 มาตรา 56 (2) (ข) จากเงินนอกงบประมาณ ประเภทเงินอุดหนุน"
            f"อาหารกลางวันรับจาก{fund} เป็นเงิน {_money(total)} บาท ดังนี้", align="justify", indent=1.25)
    _p(doc, "1. เหตุผลและความจำเป็นที่ต้องจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, "เพื่อประกอบอาหารกลางวันให้แก่นักเรียนระดับอนุบาลจนถึงชั้นประถมศึกษาปีที่ 6", indent=1.5)
    _p(doc, "2. ขอบเขตของงานพัสดุที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"การจ้างประกอบอาหารกลางวัน {dr} (รายละเอียดตามเอกสารแนบ)", indent=1.5)
    _p(doc, "3. ราคากลางของพัสดุที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เป็นเงิน {_money(total)} บาท ({bahttext(total)}) โดยมีแหล่งที่มาจาก{fund}", indent=1.5)
    _p(doc, "4. วงเงินที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เป็นเงิน {_money(total)} บาท ({bahttext(total)})", indent=1.5)
    _p(doc, "5. กำหนดเวลาที่ต้องการให้งานนั้นแล้วเสร็จ", bold=True, indent=1.25, after=0)
    _p(doc, f"ระยะเวลาการจ้าง จำนวน {days} วัน ตั้งแต่วันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)}",
       indent=1.5)
    _p(doc, "6. วิธีที่จะจ้าง และเหตุผลที่จะต้องจ้างโดยวิธีนั้น", bold=True, indent=1.25, after=0)
    _p(doc, "ดำเนินการด้วยวิธีเฉพาะเจาะจง เนื่องจากการจัดซื้อจัดจ้างพัสดุที่มีการผลิต จำหน่าย หรือให้บริการ"
            "ทั่วไป และมีวงเงินในการจัดซื้อจัดจ้างครั้งหนึ่งไม่เกินวงเงินตามที่กำหนดในกฎกระทรวง", align="justify", indent=1.5)
    _p(doc, "7. หลักเกณฑ์การพิจารณาคัดเลือกข้อเสนอ", bold=True, indent=1.25, after=0)
    _p(doc, "การพิจารณาคัดเลือกข้อเสนอโดยใช้เกณฑ์ราคา", indent=1.5)
    _p(doc, "8. การขออนุมัติแต่งตั้งคณะกรรมการต่าง ๆ", bold=True, indent=1.25, after=0)
    _p(doc, "8.1 แต่งตั้งผู้ควบคุมและคณะกรรมการผู้ตรวจการประกอบอาหาร", indent=1.5, after=0)
    _committee_lines(doc, [m for m in rnd.committees if m.kind == "control"])
    _p(doc, "8.2 คณะกรรมการตรวจรับพัสดุ/ผู้ตรวจรับพัสดุ", indent=1.5, before=2, after=0)
    _committee_lines(doc, [m for m in rnd.committees if m.kind == "inspect"])
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบขอได้โปรด", indent=1.25, before=2, after=0)
    _p(doc, f"1. อนุมัติให้ดำเนินการจ้างบุคคลประกอบอาหารกลางวัน (ค่าตอบแทน/ค่าแรง) {dr} ตามรายงานขอจ้างข้างต้น",
       align="justify", indent=1.5, after=0)
    _p(doc, "2. อนุมัติให้แต่งตั้งคณะกรรมการ ตามข้อ 8.1 และ 8.2", indent=1.5, after=10)
    _sign_table(doc, [[("ลงชื่อ ..............................................เจ้าหน้าที่", "center"),
                       (f"( {officer} )", "center")]])
    _p(doc, "ความเห็นของหัวหน้าเจ้าหน้าที่ ......................................................................",
       indent=1.25, before=2, after=8)
    _sign_table(doc, [[("ลงชื่อ ..............................................หัวหน้าเจ้าหน้าที่", "center"),
                       (f"( {head} )", "center")]])
    _p(doc, "คำสั่ง   เห็นชอบ / อนุมัติ / ลงนามแล้ว", align="center", bold=True, before=4, after=8)
    _sign_table(doc, [[("ลงชื่อ ..............................................ผู้อำนวยการโรงเรียน", "center"),
                       (f"( {director} )", "center")]])
    return _finish(doc, own, f"รายงานขอจ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_quotation(rnd, school, doc=None) -> str:
    """04 ใบเสนอราคา (จ้างบุคคลประกอบอาหารกลางวัน)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    officer = (school.officer_name or "").strip() or _BLANK
    v = rnd.vendor
    vname = v.name if v else _BLANK
    vowner = (getattr(v, "owner_name", "") or "").strip() if v else ""
    vaddr = (getattr(v, "address", "") or "").strip() if v else ""
    vtax = (getattr(v, "tax_id", "") or "").strip() if v else ""
    total = round(float(rnd.amount or 0), 2)
    dr = _period(rnd)
    _p(doc, "ใบเสนอราคา", align="center", bold=True, size=20, after=6)
    _p(doc, f"วันที่  {_dnum(rnd.order_date)}", align="right", after=4)
    _p(doc, f"เรียน  ผู้อำนวยการโรงเรียน{sname}", after=4)
    _p(doc, f"1. ข้าพเจ้า {vowner or vname} บ้านเลขที่/ที่อยู่ {vaddr or _BLANK} เลขประจำตัวประชาชน/ผู้เสียภาษี "
            f"{vtax or _BLANK} ได้ศึกษาขอบเขตของงานการจ้างบุคคลประกอบอาหารกลางวัน {dr} ของโรงเรียน{sname} "
            "โดยตลอดและยอมรับข้อกำหนดและเงื่อนไขแล้ว รวมทั้งรับรองว่าเป็นผู้มีคุณสมบัติครบถ้วนและไม่เป็น"
            "ผู้ทิ้งงานของทางราชการ", align="justify", indent=1.25, after=2)
    _p(doc, f"2. ข้าพเจ้าขอเสนอราคาจ้างบุคคลประกอบอาหารกลางวัน {dr} เป็นเงินทั้งสิ้น {_money(total)} บาท "
            f"(ตัวอักษร {bahttext(total)}) ซึ่งรวมค่าใช้จ่ายทั้งปวงไว้ด้วยแล้ว", align="justify", indent=1.25, after=2)
    _p(doc, "3. คำเสนอนี้จะยืนอยู่เป็นระยะเวลา ๓๐ วัน นับตั้งแต่วันที่ได้ยื่นใบเสนอราคา", indent=1.25, after=2)
    _p(doc, f"4. กำหนดส่งมอบ {dr} นับถัดจากวันลงนามใบสั่งจ้าง/ข้อตกลงจ้าง", indent=1.25, after=14)
    _sign_table(doc, [
        [("ลงชื่อ ....................................ผู้เจรจาตกลงราคา", "center"),
         ("ลงชื่อ ....................................ผู้เสนอราคา", "center")],
        [(f"( {officer} )", "center"), (f"( {vowner or vname} )", "center")],
        [("เจ้าหน้าที่", "center"), ("", "center")]])
    return _finish(doc, own, f"ใบเสนอราคา_จ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_result(rnd, school, doc=None) -> str:
    """05 รายงานผลการพิจารณาและขออนุมัติสั่งจ้างบุคคลประกอบอาหารกลางวัน"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    officer = (school.officer_name or "").strip() or _BLANK
    head = (school.head_officer_name or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    total = round(float(rnd.amount or 0), 2)
    dr = f"{_period(rnd)} ({rnd.days or ''} วันทำการ)"
    _memo_head(doc, school, ["รายงานผลการพิจารณาและขออนุมัติสั่งจ้างบุคคลประกอบอาหารกลางวัน", dr],
               _dnum(rnd.order_date), rnd.order_no)
    _p(doc, f"ตามที่ผู้อำนวยการโรงเรียน{sname} เห็นชอบให้ดำเนินการจ้างบุคคลประกอบอาหารกลางวัน {dr} "
            f"โดยวิธีเฉพาะเจาะจง วงเงินงบประมาณ {_money(total)} บาท ({bahttext(total)}) นั้น เจ้าหน้าที่ได้"
            "เจรจาตกลงราคากับผู้ประกอบการโดยตรงตามระเบียบกระทรวงการคลังฯ พ.ศ. 2560 ข้อ 79 แล้ว "
            "ขอรายงานผลการพิจารณา ดังนี้", align="justify", indent=1.25, after=4)
    _simple_table(doc,
                  ["รายการพิจารณา", "ผู้ชนะการเสนอราคา", "ราคาที่เสนอ\n(รวม VAT)", "ราคาที่ตกลงจ้าง\n(รวม VAT)"],
                  [[f"ดำเนินการจ้างบุคคลประกอบอาหารกลางวัน {dr}", vname, _money(total), _money(total)],
                   ["รวม", "", _money(total), _money(total)]],
                  [Cm(6.05), Cm(4.2), Cm(3), Cm(3)])   # รวม 16.25 = พื้นที่พิมพ์ A4
    _p(doc, f"จึงเห็นสมควรรับราคาจาก {vname} การจัดจ้างคราวนี้ไม่เกินวงเงินที่ประมาณไว้และไม่สูงกว่าราคากลาง "
            f"สถานที่ส่งมอบ ณ โรงเรียน{sname}", align="justify", indent=1.25, before=4)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติให้ดำเนินการจัดจ้างจากผู้ชนะการเสนอราคาดังกล่าว และลงนาม"
            "ในประกาศรายชื่อผู้ชนะการเสนอราคา และใบสั่งจ้าง ที่เสนอมาพร้อมนี้", align="justify", indent=1.25, after=12)
    _sign_table(doc, [
        [("ลงชื่อ ..........................................เจ้าหน้าที่", "center"), (f"( {officer} )", "center")],
        [("ลงชื่อ ..........................................หัวหน้าเจ้าหน้าที่", "center"), (f"( {head} )", "center")]])
    _p(doc, "อนุมัติ/ลงนามแล้ว", align="center", bold=True, before=4, after=8)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการโรงเรียน{sname}", align="center", after=0)
    return _finish(doc, own, f"รายงานผลพิจารณา_จ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_winner(rnd, school, doc=None) -> str:
    """06 ประกาศผู้ชนะการเสนอราคา สำหรับการจ้างบุคคลประกอบอาหารกลางวัน"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    total = round(float(rnd.amount or 0), 2)
    dr = f"{_period(rnd)} ({rnd.days or ''} วันทำการ)"
    _krut_center(doc)
    _p(doc, f"ประกาศโรงเรียน{sname}", align="center", bold=True, size=18, after=0)
    _p(doc, "เรื่อง ประกาศผู้ชนะการเสนอราคา สำหรับการจ้างบุคคลประกอบอาหารกลางวัน", align="center", bold=True, after=0)
    _p(doc, f"{dr}", align="center", after=0)
    _p(doc, "โดยวิธีเฉพาะเจาะจง", align="center", after=0)
    _p(doc, "-------------------------------", align="center", after=6)
    _p(doc, f"ตามที่โรงเรียน{sname} โดย{director} ได้มีโครงการจ้างบุคคลประกอบอาหารกลางวัน {dr} "
            "โดยวิธีเฉพาะเจาะจง นั้น", align="justify", indent=1.25)
    _p(doc, f"โครงการจ้างบุคคลประกอบอาหารกลางวัน {dr} ผู้ได้รับการคัดเลือก ได้แก่ {vname} โดยเสนอราคา"
            f"เป็นเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)}) รวมภาษีมูลค่าเพิ่มและภาษีอื่น "
            "ค่าขนส่ง ค่าจดทะเบียน และค่าใช้จ่ายอื่น ๆ ทั้งปวง", align="justify", indent=1.25, after=10)
    _p(doc, f"ประกาศ ณ วันที่ {_dnum(rnd.order_date)}", align="center", after=14)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการโรงเรียน{sname}", align="center", after=0)
    return _finish(doc, own, f"ประกาศผู้ชนะ_จ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_order(rnd, school, doc=None) -> str:
    """07 ใบสั่งจ้าง (จ้างบุคคลประกอบอาหารกลางวัน) — ค่าปรับ 0.1"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    order_no = (rnd.order_no or "").strip() or _BLANK
    total = round(float(rnd.amount or 0), 2)
    days = rnd.days or 0
    insts = list(rnd.installments or [])
    _p(doc, "ใบสั่งจ้าง", align="center", bold=True, size=20, after=4)
    _simple_table(doc, ["ผู้รับจ้าง", "ใบสั่งจ้าง"],
                  [[vname, f"เลขที่ {order_no}  ลงวันที่ {_dnum(rnd.order_date)}"]], [Cm(8.0), Cm(8.0)])
    _p(doc, f"ตามที่ {vname} ได้เสนอราคาไว้ต่อโรงเรียน{sname} ซึ่งได้รับราคาและตกลงจ้าง ตามรายการดังต่อไปนี้",
       align="justify", indent=1.25, after=4)
    _simple_table(doc, ["ลำดับ", "รายการ", "จำนวน", "หน่วย", "ราคาต่อหน่วย", "จำนวนเงิน (บาท)"],
                  [["1", f"การจ้างบุคคลประกอบอาหารกลางวัน {_period(rnd)}",
                    str(prog.total_students), "คน", "", _money(total)],
                   ["", "", "", "", "รวมเป็นเงินทั้งสิ้น", _money(total)]],
                  [Cm(1.2), Cm(6.0), Cm(1.6), Cm(1.6), Cm(2.6), Cm(2.6)])
    _p(doc, f"(ตัวอักษร) {bahttext(total)}", indent=1.25, before=2, after=6)
    _p(doc, "การสั่งจ้าง อยู่ภายใต้เงื่อนไขต่อไปนี้", bold=True, indent=1.25)
    _p(doc, f"๑. กำหนดส่งมอบภายในตามงวดงาน {len(insts) or '-'} งวด รวม {days} วัน นับถัดจากวันที่ผู้รับจ้าง"
            "ลงนามในใบสั่งจ้าง", align="justify", indent=1.25)
    _p(doc, f"๒. สถานที่ส่งมอบ โรงเรียน{sname}", indent=1.25)
    _p(doc, "๓. สงวนสิทธิ์ค่าปรับกรณีส่งมอบเกินกำหนด คิดค่าปรับรายวันอัตราร้อยละ ๐.๑๐ ของมูลค่าตามใบสั่งจ้าง "
            "แต่ไม่ต่ำกว่าวันละ ๑๐๐ บาท", align="justify", indent=1.25)
    _p(doc, "๔. ผู้รับจ้างต้องไม่เอางานไปจ้างช่วงอีกทอดหนึ่ง เว้นแต่ได้รับอนุญาตเป็นหนังสือ หากฝ่าฝืนปรับ"
            "ร้อยละ ๑๐ ของวงเงินงานที่จ้างช่วง", align="justify", indent=1.25)
    _p(doc, "๕. การส่งมอบงานและการจ่ายเงิน แบ่งจ่ายตามงวดงาน ดังนี้", indent=1.25)
    if insts:
        for i in insts:
            _p(doc, f"    งวดที่ {i.seq} จ่ายเป็นเงิน {_money(i.amount or 0)} บาท เมื่อส่งมอบและตรวจรับเรียบร้อยแล้ว",
               align="justify", indent=1.5, after=0)
    _p(doc, f"๖. กำหนดมูลค่าตามใบสั่งจ้างภายในวงเงิน {_money(total)} บาท ({bahttext(total)})",
       align="justify", indent=1.25, before=4)
    _p(doc, "๗. เอกสารแนบท้ายใบสั่งจ้าง : ขอบเขตของงาน (TOR) และใบเสนอราคา", indent=1.25, after=14)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................ผู้สั่งจ้าง", "center"),
         (f"( {director} )", "center"), (f"ผู้อำนวยการโรงเรียน{sname}", "center")],
        [("(ลงชื่อ)...........................................ผู้รับใบสั่งจ้าง", "center"),
         (f"( {vname} )", "center")]])
    return _finish(doc, own, f"ใบสั่งจ้าง_จ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_installment(inst, school, menus=None, doc=None) -> str:
    """08-10 บันทึกควบคุม + ใบส่งมอบงาน + ใบตรวจรับพัสดุ (การจ้างบุคคล) รายงวด"""
    doc, own = _begin(doc)
    rnd = inst.round
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    order_no = (rnd.order_no or "").strip() or _BLANK
    amount = _money(inst.amount or 0)
    period = f"งวดที่ {inst.seq} ระหว่างวันที่ {_dnum(inst.start_date)} ถึงวันที่ {_dnum(inst.end_date)}"

    _p(doc, "บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหารกลางวัน (การจ้างบุคคล)",
       align="center", bold=True, size=16, after=4)
    _p(doc, f"เขียนที่ โรงเรียน{sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่โรงเรียน{sname} ได้ตกลงจ้าง {vname} ประกอบอาหารกลางวันให้นักเรียนรับประทาน {period} นั้น "
            "คณะกรรมการขอรายงานผลการดำเนินงานเป็นรายวัน ดังนี้", align="justify", indent=1.25, after=4)
    _menu_table3(doc, menus, "ผู้ควบคุมและคณะกรรมการ\nตรวจการประกอบอาหาร")
    _p(doc, "ความเห็นของผู้อำนวยการสถานศึกษา : ทราบผลการดำเนินการ", indent=1.25, before=4, after=8)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการโรงเรียน{sname}", align="center", after=6)

    doc.add_page_break()
    _p(doc, "ใบส่งมอบงาน", align="center", bold=True, size=18, after=6)
    _p(doc, f"วันที่ {_dnum(inst.deliver_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่โรงเรียน{sname} ได้ตกลงจ้างข้าพเจ้า {vname} ตามใบสั่งจ้าง เลขที่ {order_no} เพื่อประกอบ"
            f"อาหารกลางวันสำหรับนักเรียน {period} บัดนี้ได้ดำเนินการเสร็จเรียบร้อยแล้ว จึงขอส่งมอบงาน",
       align="justify", indent=1.25, after=4)
    _menu_table3(doc, menus, "ผู้ส่งมอบงาน")
    _p(doc, f"ขอเบิกเงิน จำนวน {amount} บาท ({bahttext(inst.amount or 0)})", indent=1.25, before=4, after=14)
    _sign_table(doc, [[("(ลงชื่อ)...........................................ผู้ส่งมอบงาน", "center"),
                       (f"( {vname} )", "center")]])

    doc.add_page_break()
    _p(doc, "ใบตรวจรับพัสดุการจ้างบุคคลประกอบอาหารกลางวัน", align="center", bold=True, size=17, after=4)
    _p(doc, f"เขียนที่ โรงเรียน{sname}   วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่โรงเรียน{sname} ได้ตกลงจ้าง {vname} ประกอบอาหารกลางวันให้นักเรียนรับประทาน ตามใบสั่งจ้าง "
            f"เลขที่ {order_no} บัดนี้ผู้รับจ้างได้ส่งมอบพัสดุทุกวันตามข้อตกลง และคณะกรรมการตรวจรับพัสดุได้"
            f"ตรวจรับไว้ถูกต้องครบถ้วนแล้ว เห็นควรเบิกจ่ายให้ผู้รับจ้าง {period} เป็นเงิน {amount} บาท "
            f"({bahttext(inst.amount or 0)})", align="justify", indent=1.25, after=4)
    _menu_table3(doc, menus, "ผู้ตรวจรับพัสดุหรือคณะกรรมการ\nตรวจรับพัสดุ")
    _p(doc, f"เรียน ผู้อำนวยการโรงเรียน{sname} เพื่อโปรดทราบผลการตรวจรับพัสดุ และขออนุมัติจ่ายเงินให้ผู้รับจ้าง",
       align="justify", indent=1.25, before=4, after=10)
    inspectors = [m for m in rnd.committees if m.kind == "inspect"]
    rows = ([[(f"(ลงชื่อ)...........................................{m.role}", "center"),
              (f"( {m.name} )", "center")] for m in inspectors]
            if inspectors else [[("(ลงชื่อ)...........................................ประธานกรรมการตรวจรับ", "center"),
                                 ("(...........................................)", "center")]])
    _sign_table(doc, rows)
    _p(doc, "ความเห็นของผู้บริหารสถานศึกษา   (   ) ทราบผลการตรวจรับ   (   ) อนุมัติ", indent=1.25, before=4, after=8)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการโรงเรียน{sname}", align="center", after=0)
    return _finish(doc, own, f"งวดจ้างบุคคล_งวดที่{inst.seq}_ปี{prog.year}")


def render_p_disburse(inst, school, wht_rate=0.01, doc=None) -> str:
    """11-13 ขออนุมัติเบิกจ่ายเงิน + ใบสำคัญรับเงิน + หนังสือรับรองหักภาษี ณ ที่จ่าย (จ้างบุคคล)"""
    doc, own = _begin(doc)
    rnd = inst.round
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    saddr = (school.address or "").strip()
    fund = (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"
    vendor = rnd.vendor
    vname = vendor.name if vendor else _BLANK
    vaddr = (getattr(vendor, "address", "") or "").strip() if vendor else _BLANK
    vtax = (getattr(vendor, "tax_id", "") or "").strip() if vendor else _BLANK
    order_no = (rnd.order_no or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    fin = (getattr(school, "finance_officer_name", "") or "").strip() or _BLANK
    amt = round(float(inst.amount or 0), 2)
    wht = round(amt * float(wht_rate or 0), 2)
    net = round(amt - wht, 2)
    A, W, N = _money(amt), _money(wht), _money(net)
    period = f"งวดที่ {inst.seq} ({_dnum(inst.start_date)}-{_dnum(inst.end_date)})"

    _memo_head(doc, school, [f"ขออนุมัติเบิกจ่ายเงินอุดหนุนอาหารกลางวันรับจาก{fund}"],
               _dnum(inst.inspect_date or inst.end_date), order_no)
    _p(doc, f"ตามที่โรงเรียนได้จัดจ้างบุคคลประกอบอาหารกลางวัน จาก {vname} จำนวนเงิน {A} บาท ({bahttext(amt)}) "
            f"ตามบันทึกตกลงจ้าง เลขที่ {order_no} {period} จากเงินนอกงบประมาณ ประเภทเงินอุดหนุนอาหารกลางวัน"
            f"รับจาก{fund} นั้น", align="justify", indent=1.25)
    _p(doc, "บัดนี้ ผู้รับจ้างได้ส่งมอบอาหาร (ตามรายการอาหาร) ถูกต้องครบถ้วนแล้ว และคณะกรรมการได้ตรวจสอบ"
            "เรียบร้อยแล้ว ตามระเบียบกระทรวงการคลังฯ พ.ศ. 2560 ตามนัยข้อ 175 เห็นควรเบิกจ่ายให้แก่ผู้รับจ้าง "
            "โดยมีรายละเอียด ดังนี้", align="justify", indent=1.25, after=4)
    for label, val in [("จำนวนเงินขอเบิก", A), ("ภาษีมูลค่าเพิ่ม (ถ้ามี)", "-"), ("มูลค่าสินค้า", "-"),
                       ("หัก ภาษี ณ ที่จ่าย", W), ("ค่าปรับ (ถ้ามี)", "-"), ("คงเหลือจ่ายจริง", N)]:
        _p(doc, f"        {label}        {val}  บาท", indent=1.5, after=0)
    _p(doc, f"จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติเบิกจ่ายเงิน (เงินอุดหนุนอาหารกลางวันรับจาก{fund}) แก่ผู้รับจ้าง "
            f"จำนวน {N} บาท ({bahttext(net)})", align="justify", indent=1.25, after=10)
    _sign_table(doc, [[("(ลงชื่อ)...........................................เจ้าหน้าที่การเงิน", "center"),
                       (f"( {fin} )", "center")]])
    _p(doc, "ความเห็นของผู้อำนวยการสถานศึกษา   (   ) อนุมัติ", indent=1.25, before=4, after=10)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการโรงเรียน{sname}", align="center", after=0)

    doc.add_page_break()
    _p(doc, "ใบสำคัญรับเงิน", align="center", bold=True, size=18, after=4)
    _p(doc, f"โรงเรียน{sname}  {saddr}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ข้าพเจ้า {vname} บ้านเลขที่ {vaddr} ได้รับเงินจากโรงเรียน{sname} ดังรายการต่อไปนี้",
       align="justify", indent=1.25, after=4)
    _simple_table(doc, ["ลำดับที่", "รายการ", "จำนวนเงิน"],
                  [["1", f"ค่าจ้างบุคคลประกอบอาหารกลางวัน {period}", A], ["", "รวมเงิน", A]],
                  [Cm(1.6), Cm(10.4), Cm(4.0)])
    _p(doc, f"(ตัวอักษร) ({bahttext(amt)})", indent=1.25, before=2, after=12)
    _sign_table(doc, [[("(ลงชื่อ)...........................................ผู้รับเงิน", "center"),
                       (f"( {vname} )", "center")],
                      [("(ลงชื่อ)...........................................ผู้จ่ายเงิน", "center"),
                       (f"( {fin} )", "center")]])

    doc.add_page_break()
    _p(doc, "หนังสือรับรองการหักภาษี ณ ที่จ่าย", align="center", bold=True, size=18, after=2)
    _p(doc, "ตามมาตรา ๕๐ ทวิ แห่งประมวลรัษฎากร", align="center", after=8)
    _p(doc, "ผู้มีหน้าที่หักภาษี ณ ที่จ่าย :", bold=True, after=0)
    _p(doc, f"ส่วนราชการ โรงเรียน{sname}   เลขประจำตัวผู้เสียภาษี {getattr(school,'tax_id','') or _BLANK}", after=0)
    _p(doc, f"ที่อยู่ {saddr or _BLANK}", after=6)
    _p(doc, "ผู้ถูกหักภาษี ณ ที่จ่าย :", bold=True, after=0)
    _p(doc, f"ชื่อ {vname}   เลขประจำตัวประชาชน/ผู้เสียภาษี {vtax}", after=0)
    _p(doc, f"ที่อยู่ {vaddr}", after=6)
    _simple_table(doc, ["ประเภทเงินได้ที่จ่าย", "วันที่จ่าย", "จำนวนเงินที่จ่าย", "ภาษีที่หัก"],
                  [["ค่าจ้างบุคคลประกอบอาหารกลางวัน", _dnum(inst.inspect_date or inst.end_date), A, W],
                   ["รวม", "", A, W]], [Cm(6.4), Cm(3.2), Cm(3.2), Cm(3.2)])
    _p(doc, f"รวมเงินภาษีที่หัก (ตัวอักษร) ({bahttext(wht)})", indent=1.25, before=2, after=12)
    _p(doc, "(ลงชื่อ)...........................................ผู้จ่ายเงิน", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการโรงเรียน{sname}", align="center", after=0)
    return _finish(doc, own, f"ขอเบิกจ่าย_จ้างบุคคล_งวดที่{inst.seq}_ปี{prog.year}")


def render_person_bundle(rnd, school) -> str:
    """ออกชุดเอกสารจ้างบุคคลทั้งชุดเป็นไฟล์เดียว (ยืมเงินซื้อวัตถุดิบ + จ้างบุคคล)"""
    doc = Document(); set_a4(doc); _font(doc)
    # ส่วนที่ 1: ขออนุมัติจ้างบุคคล
    render_p_tor(rnd, school, doc)
    render_p_hire_report(rnd, school, doc)
    render_p_quotation(rnd, school, doc)
    render_p_result(rnd, school, doc)
    render_p_winner(rnd, school, doc)
    render_p_order(rnd, school, doc)
    # ส่วนที่ 2: ชุดยืมเงินซื้อวัตถุดิบ (เหมือนรูปแบบ 1)
    render_borrow_memo(rnd, school, doc)
    render_estimate(rnd, school, doc)
    render_purchase_form(rnd, school, doc)
    render_material_report_form(rnd, school, doc)
    render_receipt_form(rnd, school, doc)
    render_control_report(rnd, school, doc)
    render_repay_memo(rnd, school, doc)
    return _save(doc, f"ชุดเอกสารจ้างบุคคล_รอบที่{rnd.seq}_ปี{rnd.program.year}")
