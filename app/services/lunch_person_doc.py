# -*- coding: utf-8 -*-
"""
lunch_person_doc.py - เอกสารการจ้างบุคคลเพื่อประกอบอาหารกลางวัน (รูปแบบ 2)
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
    _committee_lines, _menu_table3, _simple_table, _school_disp,
)
# ชุดซื้อวัตถุดิบ (ยืมเงิน->ส่งใช้) ใช้ซ้ำจากรูปแบบ 1
from app.services.lunch_ingredient_doc import (
    _month_year, _memo_ref,
    render_borrow_memo, render_estimate, render_purchase_form,
    render_material_report_form, render_receipt_form, render_control_report,
    render_repay_memo, render_purchase_report, render_loan_contract,
    render_inspection_note,
)

_WORK = "จ้างบุคคลประกอบอาหารกลางวัน"


def _period(rnd):
    return f"ประจำวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)}"


def render_p_tor(rnd, school, doc=None) -> str:
    """02 ขอบเขตของงาน (TOR) การจ้างบุคคลประกอบอาหารกลางวัน"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = _school_disp(school)
    total = round(float(rnd.amount or 0), 2)
    days = rnd.days or 0
    students = prog.total_students
    fund = (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"
    insts = list(rnd.installments or [])
    _p(doc, "ขอบเขตของงาน (TOR) การจ้างบุคคลประกอบอาหารกลางวัน", align="center", bold=True, size=18, after=0)
    _p(doc, f"{sname}  ประจำปีการศึกษา {prog.year}", align="center", after=6)
    _p(doc, "1. ความเป็นมา", bold=True, indent=0.5, after=0)
    _p(doc, f"{sname} จัดบริการอาหารกลางวันให้นักเรียนระดับอนุบาลถึงชั้นประถมศึกษาปีที่ 6 "
            "จึงจัดทำขอบเขตของงานจ้างบุคคลประกอบอาหารกลางวันฉบับนี้ เพื่อจ้างบุคคลมาประกอบอาหารกลางวัน "
            "ให้นักเรียนได้รับประทานอาหารที่มีคุณค่าทางโภชนาการ สะอาด และปลอดภัย", align="justify", indent=1)
    _p(doc, "2. วัตถุประสงค์", bold=True, indent=0.5, after=0)
    _p(doc, f"เพื่อจัดหาบุคคลประกอบอาหารกลางวันให้นักเรียนของ{sname} จำนวน {students} คน "
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
    """03 บันทึกข้อความ รายงานขอจ้างเหมาประกอบอาหารกลางวัน (จ้างแม่ครัว)
    ตรงตามคู่มืออาหารกลางวัน สพฐ. หน้า 25-26 - 7 ข้อ + ข้อ 8 แต่งตั้งผู้ควบคุม+ตรวจการประกอบอาหาร"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = _school_disp(school)
    officer = (school.officer_name or "").strip() or _BLANK
    head = (school.head_officer_name or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    students = prog.total_students
    total = round(float(rnd.amount or 0), 2)
    money, baht = _money(total), bahttext(total)
    days = rnd.days or 0
    month = _month_year(rnd.start_date)
    ds, de = _dnum(rnd.start_date), _dnum(rnd.end_date)
    _memo_head(doc, school,
               [f"รายงานขอจ้างเหมาประกอบอาหารกลางวัน ประจำเดือน {month}",
                f"ประจำปีการศึกษา {prog.year} (ระหว่างวันที่ {ds} ถึงวันที่ {de})"],
               *_memo_ref(rnd))
    _p(doc, f"ด้วย{sname} จ้างเหมาประกอบอาหารกลางวันให้แก่นักเรียนรับประทาน ประจำเดือน {month} "
            f"(ระหว่างวันที่ {ds} ถึงวันที่ {de} ปีการศึกษา {prog.year}) การจัดจ้างครั้งนี้ดำเนินการ โดยวิธี"
            "เฉพาะเจาะจง ตามมาตรา 56 (2) (ข) ประกอบหนังสือคณะกรรมการวินิจฉัยปัญหาการจัดซื้อจัดจ้างและ"
            "การบริหารพัสดุภาครัฐ ด่วนที่สุด ที่ กค (กวจ) 0405.2/ ว 116 ลงวันที่ 12 มีนาคม พ.ศ. 2562 "
            "ซึ่งมีรายละเอียดดังต่อไปนี้", align="justify", indent=1.25)
    _p(doc, "1. เหตุผลและความจำเป็นที่ต้องจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เพื่อประกอบอาหารให้นักเรียนรับประทานในมื้อกลางวัน สำหรับนักเรียน จำนวน {students} คน", indent=1.5)
    _p(doc, "2. ขอบเขตของงานพัสดุที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, "การจ้างประกอบอาหารกลางวันประจำภาคเรียน (รายละเอียดตามเอกสารแนบ)", indent=1.5)
    _p(doc, "3. ราคากลางของพัสดุที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เป็นเงิน {money} บาท ({baht})", indent=1.5)
    _p(doc, "4. วงเงินที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เป็นเงิน {money} บาท ({baht})", indent=1.5)
    _p(doc, "5. กำหนดเวลาที่ต้องการพัสดุ", bold=True, indent=1.25, after=0)
    _p(doc, f"ระยะเวลาการจ้าง จำนวน {days} วัน (ตั้งแต่วันที่ {ds} ถึงวันที่ {de})", indent=1.5)
    _p(doc, "6. วิธีที่จะจ้างและเหตุผลที่ต้องจ้างโดยวิธีนั้น", bold=True, indent=1.25, after=0)
    _p(doc, "ดำเนินการด้วยวิธีเฉพาะเจาะจง เนื่องจากการจัดซื้อจัดจ้างพัสดุที่มีการผลิต จำหน่าย หรือให้บริการ"
            "ทั่วไป และมีวงเงินในการจัดซื้อจัดจ้างครั้งหนึ่งไม่เกินวงเงินตามที่กำหนดในกฎกระทรวง", align="justify", indent=1.5)
    _p(doc, "7. หลักเกณฑ์การพิจารณาคัดเลือกข้อเสนอ", bold=True, indent=1.25, after=0)
    _p(doc, "การพิจารณาคัดเลือกข้อเสนอโดยใช้เกณฑ์ราคา", indent=1.5)
    _p(doc, "8. การอนุมัติแต่งตั้งบุคคลหรือคณะกรรมการ ดังนี้", bold=True, indent=1.25, after=0)
    _p(doc, "8.1 ผู้ควบคุมรับผิดชอบในการประกอบอาหาร ได้แก่", indent=1.5, after=0)
    _committee_lines(doc, [m for m in rnd.committees if m.kind == "cook_control"], fallback_n=1)
    _p(doc, "8.2 คณะกรรมการตรวจการประกอบอาหาร ประกอบด้วย", indent=1.5, before=2, after=0)
    _committee_lines(doc, [m for m in rnd.committees if m.kind == "food_inspect"])
    _p(doc, "ให้ (คณะกรรมการตรวจรับพัสดุ/ผู้ตรวจรับพัสดุ) ที่ได้รับการแต่งตั้ง ปฏิบัติหน้าที่ตามระเบียบ"
            "กระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 ข้อ 175 อย่างเคร่งครัด",
       align="justify", indent=1.25, before=2)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบขอได้โปรด", indent=1.25, after=0)
    _p(doc, f"1. อนุมัติให้ดำเนินการจ้างเหมาประกอบอาหารกลางวัน ประจำเดือน {month} ตามรายงานขอจ้างดังกล่าวข้างต้น",
       align="justify", indent=1.5, after=0)
    _p(doc, "2. อนุมัติให้แต่งตั้ง (คณะกรรมการตรวจรับพัสดุ/ผู้ตรวจรับพัสดุ) ตามที่เสนอมา / ลงนามในคำสั่งแต่งตั้ง"
            "ตามที่เสนอมาพร้อมนี้", align="justify", indent=1.5, after=10)
    _sign_table(doc, [[("(ลงชื่อ) ..............................................", "center"),
                       (f"( {officer} )", "center"), ("เจ้าหน้าที่", "center")]])
    _p(doc, "ความเห็นของหัวหน้าเจ้าหน้าที่ ......................................................................",
       indent=1.25, before=2, after=8)
    _sign_table(doc, [[("(ลงชื่อ) ..............................................หัวหน้าเจ้าหน้าที่", "center"),
                       (f"( {head} )", "center")]])
    _p(doc, "คำสั่ง   เห็นชอบ / อนุมัติ", align="center", bold=True, before=4, after=8)
    _sign_table(doc, [[("(ลงชื่อ) ..............................................ผู้อำนวยการโรงเรียน", "center"),
                       (f"( {director} )", "center")]])
    return _finish(doc, own, f"รายงานขอจ้างเหมาแม่ครัว_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_quotation(rnd, school, doc=None) -> str:
    """04 ใบเสนอราคา (จ้างบุคคลประกอบอาหารกลางวัน)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = _school_disp(school)
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
    _p(doc, f"เรียน  ผู้อำนวยการ{sname}", after=4)
    _p(doc, f"1. ข้าพเจ้า {vowner or vname} บ้านเลขที่/ที่อยู่ {vaddr or _BLANK} เลขประจำตัวประชาชน/ผู้เสียภาษี "
            f"{vtax or _BLANK} ได้ศึกษาขอบเขตของงานการจ้างบุคคลประกอบอาหารกลางวัน {dr} ของ{sname} "
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
    """05 บันทึกข้อความ รายงานการพิจารณาจ้างเหมาประกอบอาหารกลางวัน (จ้างแม่ครัว)
    ตรงตามคู่มืออาหารกลางวัน สพฐ. หน้า 29 - เลือกผู้รับจ้าง (นาง...) วิธีเฉพาะเจาะจง (ไม่มีตารางประมูล)"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = _school_disp(school)
    officer = (school.officer_name or "").strip() or _BLANK
    head = (school.head_officer_name or "").strip() or _BLANK
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    month = _month_year(rnd.start_date)
    ds, de = _dnum(rnd.start_date), _dnum(rnd.end_date)
    _memo_head(doc, school,
               [f"รายงานการพิจารณาจ้างเหมาประกอบอาหารกลางวัน ประจำเดือน {month}",
                f"ประจำปีการศึกษา {prog.year} (ระหว่างวันที่ {ds} ถึงวันที่ {de})"],
               *_memo_ref(rnd))
    _p(doc, f"ด้วย{sname} จ้างเหมาประกอบอาหารกลางวันให้แก่นักเรียนรับประทาน ประจำเดือน {month} "
            f"(ระหว่างวันที่ {ds} ถึงวันที่ {de} ปีการศึกษา {prog.year}) การจัดจ้างครั้งนี้ดำเนินการ โดยวิธี"
            "เฉพาะเจาะจง ตามมาตรา 56 (2) (ข) ประกอบหนังสือคณะกรรมการวินิจฉัยปัญหาการจัดซื้อจัดจ้างและ"
            "การบริหารพัสดุภาครัฐ ด่วนที่สุด ที่ กค (กวจ) 0405.2/ ว 116 ลงวันที่ 12 มีนาคม พ.ศ. 2562 "
            "ซึ่งมีรายละเอียดดังต่อไปนี้", align="justify", indent=1.25, after=4)
    _p(doc, f"จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบโปรดอนุมัติให้ดำเนินการจ้างเหมา {vname} "
            f"ประกอบอาหารกลางวัน ประจำเดือน {month}", align="justify", indent=1.25, after=12)
    _sign_table(doc, [[("(ลงชื่อ) ...........................................", "center"),
                       (f"( {officer} )", "center"), ("เจ้าหน้าที่", "center")]])
    _p(doc, "ความเห็นของหัวหน้าเจ้าหน้าที่ ......................................................................",
       indent=1.25, before=2, after=8)
    _sign_table(doc, [[("(ลงชื่อ) ...........................................หัวหน้าเจ้าหน้าที่", "center"),
                       (f"( {head} )", "center")]])
    _p(doc, "คำสั่ง   เห็นชอบ / อนุมัติ", align="center", bold=True, before=4, after=8)
    _sign_table(doc, [[("(ลงชื่อ) ...........................................ผู้อำนวยการโรงเรียน", "center"),
                       (f"( {director} )", "center")]])
    return _finish(doc, own, f"รายงานพิจารณาจ้างเหมาแม่ครัว_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_winner(rnd, school, doc=None) -> str:
    """06 ประกาศผู้ชนะการเสนอราคา สำหรับการจ้างบุคคลประกอบอาหารกลางวัน"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = _school_disp(school)
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    total = round(float(rnd.amount or 0), 2)
    dr = f"{_period(rnd)} ({rnd.days or ''} วันทำการ)"
    _krut_center(doc)
    _p(doc, f"ประกาศ{sname}", align="center", bold=True, size=18, after=0)
    _p(doc, "เรื่อง ประกาศผู้ชนะการเสนอราคา สำหรับการจ้างบุคคลประกอบอาหารกลางวัน", align="center", bold=True, after=0)
    _p(doc, f"{dr}", align="center", after=0)
    _p(doc, "โดยวิธีเฉพาะเจาะจง", align="center", after=0)
    _p(doc, "-------------------------------", align="center", after=6)
    _p(doc, f"ตามที่{sname} โดย{director} ได้มีโครงการจ้างบุคคลประกอบอาหารกลางวัน {dr} "
            "โดยวิธีเฉพาะเจาะจง นั้น", align="justify", indent=1.25)
    _p(doc, f"โครงการจ้างบุคคลประกอบอาหารกลางวัน {dr} ผู้ได้รับการคัดเลือก ได้แก่ {vname} โดยเสนอราคา"
            f"เป็นเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)}) รวมภาษีมูลค่าเพิ่มและภาษีอื่น "
            "ค่าขนส่ง ค่าจดทะเบียน และค่าใช้จ่ายอื่น ๆ ทั้งปวง", align="justify", indent=1.25, after=10)
    _p(doc, f"ประกาศ ณ วันที่ {_dnum(rnd.order_date)}", align="center", after=14)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)
    return _finish(doc, own, f"ประกาศผู้ชนะ_จ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_order(rnd, school, doc=None) -> str:
    """07 บันทึกตกลงจ้าง (จ้างบุคคล/แม่ครัว ประกอบอาหารกลางวัน)
    รูปแบบตามคู่มือ สพฐ. : ผู้ว่าจ้างจัดหาวัตถุดิบเอง จ่ายค่าจ้างรายวัน ค่าปรับวันละ 100 บาท"""
    doc, own = _begin(doc)
    prog = rnd.program
    sname = _school_disp(school)
    director = (school.director_name or "").strip() or _BLANK
    v = rnd.vendor
    vname = v.name if v else _BLANK
    vaddr = (getattr(v, "address", "") or "").strip() if v else ""
    order_no = (rnd.order_no or "").strip() or _BLANK
    total = round(float(rnd.amount or 0), 2)
    days = rnd.days or 0
    day_rate = round(total / days, 2) if days else 0.0

    _p(doc, order_no, indent=0.5, after=0)
    _p(doc, "บันทึกตกลงจ้าง", align="center", bold=True, size=20, before=2, after=8)
    _p(doc, f"เขียนที่ {sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(rnd.order_date)}", align="right", after=6)
    _p(doc, f"บันทึกตกลงจ้างฉบับนี้จัดทำขึ้นเพื่อแสดงว่า {director} ตำแหน่งผู้อำนวยการ{sname} "
            "ผู้ได้รับมอบหมายอำนาจจากเลขาธิการคณะกรรมการการศึกษาขั้นพื้นฐาน ตามคำสั่งสำนักงานคณะกรรมการ"
            "การศึกษาขั้นพื้นฐาน ซึ่งเรียกว่า “ผู้ว่าจ้าง” ฝ่ายหนึ่ง กับ "
            f"{vname} อยู่บ้านเลขที่ {vaddr or _BLANK} ซึ่งเรียกว่า “ผู้รับจ้าง” อีกฝ่ายหนึ่ง "
            "ทั้งสองฝ่ายมีข้อตกลง ดังนี้", align="justify", indent=1.25, after=4)
    _p(doc, f"1.  ผู้ว่าจ้างตกลงจ้างและผู้รับจ้างตกลงรับจ้างประกอบอาหารให้นักเรียนรับประทานระหว่างวันที่ "
            f"{_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} รวม {days} วัน "
            "โดยผู้ว่าจ้างเป็นผู้จัดหาวัตถุดิบในการประกอบอาหารเอง", align="justify", indent=1.25)
    _p(doc, "2.  ผู้รับจ้างต้องประกอบอาหารและส่งมอบให้ผู้ว่าจ้าง โดยจัดให้นักเรียนรับประทานที่โรงเรียน"
            "ในวันที่เปิดทำการเรียนการสอนในเวลา 11.00 น. ตามรายการอาหารที่ผู้ว่าจ้างกำหนดในแต่ละวัน",
       align="justify", indent=1.25)
    _p(doc, "3.  ถ้าผู้รับจ้างไม่ส่งมอบพัสดุตามข้อ 2 ผู้รับจ้างยอมชำระค่าปรับให้แก่ผู้ว่าจ้างในอัตราวันละ "
            "100 บาท (หนึ่งร้อยบาท) กรณีดังกล่าวผู้ว่าจ้างอาจยกเลิกข้อตกลงที่มีปัญหาได้ โดยที่ผู้รับจ้าง"
            "ไม่มีสิทธิเรียกร้องค่าเสียหายใด ๆ ทั้งสิ้น", align="justify", indent=1.25)
    _p(doc, f"4.  ผู้ว่าจ้างตกลงจ่ายค่าจ้างให้แก่ผู้รับจ้างในอัตราวันละ {_money(day_rate)} บาท "
            f"({bahttext(day_rate)}) รวมเป็นเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)})",
       align="justify", indent=1.25)
    _p(doc, "5.  การชำระเงินผู้ว่าจ้างจะชำระเงินให้แก่ผู้รับจ้างเป็นรายเดือน เมื่อผู้รับจ้างได้ปฏิบัติงาน"
            "แล้วเสร็จ ตามบันทึกตกลงจ้าง", align="justify", indent=1.25, after=4)
    _p(doc, "ข้อตกลงนี้จัดทำขึ้น 2 ฉบับ มีข้อความถูกต้องตรงกัน เก็บไว้ที่ผู้ว่าจ้าง และผู้รับจ้าง ฝ่ายละ 1 ฉบับ",
       align="justify", indent=1.25, after=16)
    _sign_table(doc, [
        [("ลงชื่อ ...........................................ผู้ว่าจ้าง", "center"),
         (f"( {director} )", "center")],
        [("ลงชื่อ ...........................................ผู้รับจ้าง", "center"),
         (f"( {vname} )", "center")]])
    _sign_table(doc, [
        [("ลงชื่อ ...........................................พยาน", "center"),
         ("(...........................................)", "center")],
        [("ลงชื่อ ...........................................พยาน", "center"),
         ("(...........................................)", "center")]])
    return _finish(doc, own, f"บันทึกตกลงจ้าง_จ้างบุคคล_รอบที่{rnd.seq}_ปี{prog.year}")


def render_p_installment(inst, school, menus=None, doc=None) -> str:
    """08-10 บันทึกควบคุม + ใบส่งมอบงาน + ใบตรวจรับพัสดุ (การจ้างบุคคล) รายงวด"""
    doc, own = _begin(doc)
    rnd = inst.round
    prog = rnd.program
    sname = _school_disp(school)
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    order_no = (rnd.order_no or "").strip() or _BLANK
    amount = _money(inst.amount or 0)
    period = f"งวดที่ {inst.seq} ระหว่างวันที่ {_dnum(inst.start_date)} ถึงวันที่ {_dnum(inst.end_date)}"

    _p(doc, "บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการประกอบอาหารกลางวัน (การจ้างบุคคล)",
       align="center", bold=True, size=16, after=4)
    _p(doc, f"เขียนที่ {sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่{sname} ได้ตกลงจ้าง {vname} ประกอบอาหารกลางวันให้นักเรียนรับประทาน {period} นั้น "
            "คณะกรรมการขอรายงานผลการดำเนินงานเป็นรายวัน ดังนี้", align="justify", indent=1.25, after=4)
    _menu_table3(doc, menus, "ผู้ควบคุมและคณะกรรมการ\nตรวจการประกอบอาหาร")
    _p(doc, "ความเห็นของผู้อำนวยการสถานศึกษา : ทราบผลการดำเนินการ", indent=1.25, before=4, after=8)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=6)

    doc.add_page_break()
    _p(doc, "ใบส่งมอบงาน", align="center", bold=True, size=18, after=6)
    _p(doc, f"วันที่ {_dnum(inst.deliver_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่{sname} ได้ตกลงจ้างข้าพเจ้า {vname} ตามใบสั่งจ้าง เลขที่ {order_no} เพื่อประกอบ"
            f"อาหารกลางวันสำหรับนักเรียน {period} บัดนี้ได้ดำเนินการเสร็จเรียบร้อยแล้ว จึงขอส่งมอบงาน",
       align="justify", indent=1.25, after=4)
    _menu_table3(doc, menus, "ผู้ส่งมอบงาน")
    _p(doc, f"ขอเบิกเงิน จำนวน {amount} บาท ({bahttext(inst.amount or 0)})", indent=1.25, before=4, after=14)
    _sign_table(doc, [[("(ลงชื่อ)...........................................ผู้ส่งมอบงาน", "center"),
                       (f"( {vname} )", "center")]])

    doc.add_page_break()
    _p(doc, "ใบตรวจรับพัสดุการจ้างบุคคลประกอบอาหารกลางวัน", align="center", bold=True, size=17, after=4)
    _p(doc, f"เขียนที่ {sname}   วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่{sname} ได้ตกลงจ้าง {vname} ประกอบอาหารกลางวันให้นักเรียนรับประทาน ตามใบสั่งจ้าง "
            f"เลขที่ {order_no} บัดนี้ผู้รับจ้างได้ส่งมอบพัสดุทุกวันตามข้อตกลง และคณะกรรมการตรวจรับพัสดุได้"
            f"ตรวจรับไว้ถูกต้องครบถ้วนแล้ว เห็นควรเบิกจ่ายให้ผู้รับจ้าง {period} เป็นเงิน {amount} บาท "
            f"({bahttext(inst.amount or 0)})", align="justify", indent=1.25, after=4)
    _menu_table3(doc, menus, "ผู้ตรวจรับพัสดุหรือคณะกรรมการ\nตรวจรับพัสดุ")
    _p(doc, f"เรียน ผู้อำนวยการ{sname} เพื่อโปรดทราบผลการตรวจรับพัสดุ และขออนุมัติจ่ายเงินให้ผู้รับจ้าง",
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
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)
    return _finish(doc, own, f"งวดจ้างบุคคล_งวดที่{inst.seq}_ปี{prog.year}")


def render_p_disburse(inst, school, wht_rate=0.01, doc=None) -> str:
    """11-13 ขออนุมัติเบิกจ่ายเงิน + ใบสำคัญรับเงิน + หนังสือรับรองหักภาษี ณ ที่จ่าย (จ้างบุคคล)"""
    doc, own = _begin(doc)
    rnd = inst.round
    prog = rnd.program
    sname = _school_disp(school)
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
               *_memo_ref(rnd))
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
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)

    doc.add_page_break()
    _p(doc, "ใบสำคัญรับเงิน", align="center", bold=True, size=18, after=4)
    _p(doc, f"{sname}  {saddr}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ข้าพเจ้า {vname} บ้านเลขที่ {vaddr} ได้รับเงินจาก{sname} ดังรายการต่อไปนี้",
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
    _p(doc, f"ส่วนราชการ {sname}   เลขประจำตัวผู้เสียภาษี {getattr(school,'tax_id','') or _BLANK}", after=0)
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
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)
    return _finish(doc, own, f"ขอเบิกจ่าย_จ้างบุคคล_งวดที่{inst.seq}_ปี{prog.year}")


def render_person_bundle(rnd, school) -> str:
    """ออกชุดเอกสารจ้างแม่ครัวทั้งชุดเป็นไฟล์เดียว ตรงตามคู่มืออาหารกลางวัน สพฐ.
    (จ้างเหมาประกอบอาหาร วิธีเฉพาะเจาะจง + ชุดยืมเงินซื้อวัตถุดิบที่โรงเรียนจัดหาเอง)"""
    doc = Document(); set_a4(doc); _font(doc)
    # ส่วนที่ 1: จ้างเหมาประกอบอาหาร (จ้างแม่ครัว)
    render_p_hire_report(rnd, school, doc)   # รายงานขอจ้างเหมา + แต่งตั้งผู้ควบคุม/ตรวจการประกอบอาหาร
    render_p_result(rnd, school, doc)        # รายงานการพิจารณาจ้าง (เลือกผู้รับจ้าง)
    render_p_order(rnd, school, doc)         # บันทึกตกลงจ้าง
    # ส่วนที่ 2: ชุดยืมเงินซื้อวัตถุดิบ (โรงเรียนจัดหาวัตถุดิบเอง - เหมือนรูปแบบซื้อวัตถุดิบ)
    render_borrow_memo(rnd, school, doc)
    render_loan_contract(rnd, school, doc)
    render_estimate(rnd, school, doc)
    render_repay_memo(rnd, school, doc)
    render_material_report_form(rnd, school, doc)
    render_receipt_form(rnd, school, doc)
    return _save(doc, f"ชุดเอกสารจ้างแม่ครัว_รอบที่{rnd.seq}_ปี{rnd.program.year}")
