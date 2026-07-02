# -*- coding: utf-8 -*-
"""
lunch_doc.py
------------
ออกเอกสารจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) รายงวด (สร้าง docx ตอนรันไทม์)
- render_installment_doc(inst, school, menus): ไฟล์ "งวด X" รวม 3 ส่วน
    (1) บันทึกรายงานผู้ควบคุม + ตารางเมนูรายวัน  (2) ใบส่งมอบงาน  (3) ใบตรวจรับพัสดุ

อิงโครงสร้าง/ถ้อยคำจากไฟล์จริงที่โรงเรียนใช้ ใช้ helper ร่วมกับ build_templates
ช่องลงนามคณะกรรมการเว้นจุดไข่ปลาให้เซ็น (ยังไม่เก็บรายชื่อกรรมการในระบบ)
"""
from pathlib import Path

from docx import Document
from docx.shared import Cm

from app.database import get_data_dir
from app.thai_utils import thai_date, bahttext
from app.services.build_templates import (
    _font, _p, _set_cell, _repeat_header_row, _no_split_row, _sign_table,
)

_BLANK = "............................"


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*\n\r\t':
        text = text.replace(ch, "_")
    return text.strip()[:80]


def _money(x) -> str:
    x = round(float(x or 0), 2)
    return f"{int(x):,}" if x == int(x) else f"{x:,.2f}"


def _save(doc, name: str) -> str:
    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / (_safe(name) + ".docx")
    doc.save(str(out_path))
    return str(out_path)


def _dnum(dt) -> str:
    return thai_date(dt) if dt else _BLANK


def _menu_text(m) -> str:
    parts = [(m.main or "").strip()]
    if (m.dessert or "").strip():
        parts.append((m.dessert or "").strip())
    return "  ".join(p for p in parts if p)


def _daily_table(doc, menus):
    """ตารางควบคุมงานรายวัน: วัน/เดือน/ปี | รายการอาหาร | ผลการดำเนินงาน | ผู้ควบคุมงาน"""
    widths = [Cm(2.6), Cm(6.6), Cm(3.4), Cm(3.6)]
    t = doc.add_table(rows=1, cols=4)
    t.style = "Table Grid"
    t.autofit = False
    hdr = t.rows[0]
    _repeat_header_row(hdr)
    for c, h, w in zip(hdr.cells, ["วัน/เดือน/ปี", "รายการอาหาร",
                                   "ผลการดำเนินงาน", "ผู้ควบคุมงาน"], widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    if menus:
        for m in menus:
            r = t.add_row()
            _no_split_row(r)
            vals = [thai_date(m.date) if m.date else "", _menu_text(m), "", ""]
            for c, v, w in zip(r.cells, vals, widths):
                _set_cell(c, v, size=14)
                c.width = w
    else:
        for _ in range(5):
            r = t.add_row()
            for c, w in zip(r.cells, widths):
                _set_cell(c, "", size=14)
                c.width = w
    return t


def render_installment_doc(inst, school, menus) -> str:
    doc = Document()
    _font(doc)
    rnd = inst.round
    vendor = rnd.vendor
    vname = vendor.name if vendor else _BLANK
    order_no = getattr(rnd, "order_no", None) or _BLANK
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip()
    amount = _money(inst.amount or 0)
    amt_text = bahttext(inst.amount or 0)
    period = f"วันที่ {_dnum(inst.start_date)} ถึงวันที่ {_dnum(inst.end_date)} รวม {inst.days or ''} วัน"

    # ===== ส่วนที่ 1: บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการจ้าง =====
    _p(doc, "บันทึกรายงานผู้ควบคุมและคณะกรรมการตรวจการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)",
       align="center", bold=True, size=16, after=4)
    _p(doc, f"เขียนที่ {sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่{sname} ได้ตกลงจ้าง {vname} ประกอบอาหารกลางวัน (ปรุงสำเร็จ) "
            f"ให้นักเรียนรับประทาน งวดที่ {inst.seq} ระหว่าง{period} นั้น",
       align="justify", indent=1.25)
    _p(doc, "คณะกรรมการควบคุมงานและคณะกรรมการตรวจการจ้าง ขอรายงานผลการดำเนินงาน "
            "การประกอบอาหารกลางวันเป็นรายวัน ดังนี้", align="justify", indent=1.25, after=4)
    _daily_table(doc, menus)
    _p(doc, "", after=4)
    _p(doc, "ความเห็นของผู้อำนวยการสถานศึกษา : ทราบผลการดำเนินการประกอบอาหารกลางวัน",
       indent=1.25, after=10)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director or _BLANK} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=6)

    # ===== ส่วนที่ 2: ใบส่งมอบงาน =====
    doc.add_page_break()
    _p(doc, "ใบส่งมอบงาน", align="center", bold=True, size=18, after=6)
    _p(doc, f"วันที่ {_dnum(inst.deliver_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่{sname} ได้ตกลงจ้างข้าพเจ้า {vname} ตามใบสั่งจ้าง เลขที่ {order_no} "
            f"เพื่อประกอบอาหารกลางวัน (ปรุงสำเร็จ) สำหรับนักเรียน งวดที่ {inst.seq} "
            f"ระหว่าง{period} นั้น", align="justify", indent=1.25)
    _p(doc, "บัดนี้ ข้าพเจ้าได้ดำเนินการประกอบอาหารเสร็จเรียบร้อยตามข้อกำหนดของงานแล้ว "
            "จึงขอส่งมอบงานตามเอกสารที่แนบมาพร้อมนี้", align="justify", indent=1.25)
    _p(doc, f"ขอเบิกเงิน จำนวน {amount} บาท ({amt_text})", indent=1.25, after=14)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................ผู้ส่งมอบงาน", "center"),
         (f"( {vname} )", "center")],
    ])

    # ===== ส่วนที่ 3: ใบตรวจรับพัสดุ =====
    doc.add_page_break()
    _p(doc, "ใบตรวจรับพัสดุ", align="center", bold=True, size=18, after=4)
    _p(doc, f"เขียนที่ {sname}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ตามที่{sname} ได้ตกลงจ้าง {vname} ประกอบอาหารกลางวัน (ปรุงสำเร็จ) "
            f"ให้นักเรียนรับประทาน ตามใบสั่งจ้าง เลขที่ {order_no} นั้น",
       align="justify", indent=1.25)
    _p(doc, f"บัดนี้ ผู้รับจ้างได้ส่งมอบพัสดุทุกวันตามข้อตกลง และคณะกรรมการตรวจรับพัสดุ "
            f"ได้ตรวจรับไว้ถูกต้องครบถ้วนแล้ว เห็นควรเบิกจ่ายเงินให้ผู้รับจ้าง งวดที่ {inst.seq} "
            f"ระหว่าง{period} เป็นเงิน {amount} บาท ({amt_text})", align="justify", indent=1.25, after=6)
    _p(doc, "เรียน  ผู้อำนวยการ" + sname, indent=1.25)
    _p(doc, "เพื่อโปรดทราบผลการตรวจรับพัสดุ และขออนุมัติจ่ายเงินให้ผู้รับจ้างต่อไป",
       align="justify", indent=1.25, after=10)
    inspectors = [m for m in getattr(rnd, "committees", []) if m.kind == "inspect"]
    if inspectors:
        rows = [[(f"(ลงชื่อ)...........................................{m.role}", "center"),
                 (f"( {m.name} )", "center")] for m in inspectors]
    else:
        rows = [[("(ลงชื่อ)...........................................ประธานกรรมการตรวจรับ", "center"),
                 ("(...........................................)", "center")],
                [("(ลงชื่อ)...........................................กรรมการ", "center"),
                 ("(...........................................)", "center")],
                [("(ลงชื่อ)...........................................กรรมการ", "center"),
                 ("(...........................................)", "center")]]
    _sign_table(doc, rows)
    _p(doc, "", after=4)
    _p(doc, "ความเห็นของผู้บริหารสถานศึกษา", indent=1.25, after=0)
    _p(doc, "(   ) ทราบผลการตรวจรับ          (   ) อนุมัติ", indent=1.5, after=10)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director or _BLANK} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)

    return _save(doc, f"งวดที่{inst.seq}_ปี{rnd.program.year}")


def _simple_table(doc, headers, rows, widths):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.autofit = False
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    for row in rows:
        rc = t.add_row().cells
        for c, v, w in zip(rc, row, widths):
            _set_cell(c, v, size=14)
            c.width = w
    return t


def render_disburse_lunch_doc(inst, school, wht_rate=0.01) -> str:
    """เอกสารขอเบิกจ่ายรายงวด: บันทึกขออนุมัติ + ใบสำคัญรับเงิน + หนังสือรับรองหักภาษี ณ ที่จ่าย"""
    doc = Document()
    _font(doc)
    rnd = inst.round
    prog = rnd.program
    vendor = rnd.vendor
    vname = vendor.name if vendor else _BLANK
    vaddr = (vendor.address if vendor else "") or _BLANK
    vtax = (vendor.tax_id if vendor else "") or _BLANK
    order_no = getattr(rnd, "order_no", None) or _BLANK
    sname = (school.name or "").strip() or "โรงเรียน"
    saddr = (school.address or "").strip()
    director = (school.director_name or "").strip() or _BLANK
    fin = (school.finance_officer_name or "").strip() or _BLANK
    fund = (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"
    amt = round(float(inst.amount or 0), 2)
    wht = round(amt * float(wht_rate or 0), 2)
    net = round(amt - wht, 2)
    A, W, N = _money(amt), _money(wht), _money(net)
    period = (f"งวดที่ {inst.seq} ระหว่างวันที่ {_dnum(inst.start_date)} ถึงวันที่ "
              f"{_dnum(inst.end_date)} รวม {inst.days or ''} วัน")

    # ===== 1. บันทึกข้อความ ขออนุมัติเบิกจ่าย =====
    _p(doc, "บันทึกข้อความ", align="center", bold=True, size=20, after=4)
    _p(doc, f"ส่วนราชการ  {sname}  {saddr}", after=0)
    _p(doc, f"ที่  -/{prog.year}                     วันที่  {_dnum(inst.inspect_date or inst.end_date)}", after=0)
    _p(doc, f"เรื่อง  ขออนุมัติเบิกจ่ายเงินอุดหนุนอาหารกลางวัน รับจาก{fund}", after=0)
    _p(doc, f"เรียน  ผู้อำนวยการ{sname}", after=6)
    _p(doc, f"ตามที่{sname}ได้จ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) จำนวน {inst.days or ''} วัน "
            f"จาก {vname} จำนวนเงิน {A} บาท ({bahttext(amt)}) ตามใบสั่งจ้าง เลขที่ {order_no} "
            f"{period} จากเงินนอกงบประมาณ ประเภทเงินอุดหนุนอาหารกลางวันรับจาก{fund} นั้น",
       align="justify", indent=1.25)
    _p(doc, "บัดนี้ ผู้รับจ้างได้ส่งมอบอาหาร (ตามรายการอาหาร) ถูกต้องครบถ้วนแล้ว ตามนัยข้อ ๑๗๕ (๔) "
            "แห่งระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. ๒๕๖๐ "
            "เห็นควรเบิกจ่ายให้แก่ผู้รับจ้าง โดยมีรายละเอียด ดังนี้", align="justify", indent=1.25, after=4)
    for label, val in [("จำนวนเงินขอเบิก", A), ("ภาษีมูลค่าเพิ่ม (ถ้ามี)", "-"),
                       ("มูลค่าสินค้า", "-"), ("หัก ภาษี ณ ที่จ่าย", W),
                       ("ค่าปรับ (ถ้ามี)", "-"), ("คงเหลือจ่ายจริง", N)]:
        _p(doc, f"        {label}        {val}  บาท", indent=1.5, after=0)
    _p(doc, f"จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติจ่ายเงิน (เงินอุดหนุนอาหารกลางวันรับจาก{fund}) "
            f"แก่ผู้รับจ้าง จำนวน {N} บาท ({bahttext(net)})", align="justify", indent=1.25, after=10)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................เจ้าหน้าที่การเงิน", "center"),
         (f"( {fin} )", "center")],
    ])
    _p(doc, "ความเห็นของผู้บริหารสถานศึกษา   (   ) อนุมัติ", indent=1.25, before=4, after=10)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)

    # ===== 2. ใบสำคัญรับเงิน =====
    doc.add_page_break()
    _p(doc, "ใบสำคัญรับเงิน", align="center", bold=True, size=18, after=4)
    _p(doc, f"{sname}  {saddr}", align="right", after=0)
    _p(doc, f"วันที่ {_dnum(inst.inspect_date or inst.end_date)}", align="right", after=6)
    _p(doc, f"ข้าพเจ้า {vname} บ้านเลขที่ {vaddr} ได้รับเงินจาก {sname} ดังรายการต่อไปนี้",
       align="justify", indent=1.25, after=4)
    _simple_table(doc, ["ลำดับที่", "รายการ", "จำนวนเงิน"],
                  [["1", f"ค่าจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) {period}", A],
                   ["", "รวมเงิน", A]],
                  [Cm(1.6), Cm(10.4), Cm(4.0)])
    _p(doc, f"(ตัวอักษร)  ({bahttext(amt)})", indent=1.25, before=2, after=12)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................ผู้รับเงิน", "center"),
         (f"( {vname} )", "center")],
        [("(ลงชื่อ)...........................................ผู้จ่ายเงิน", "center"),
         (f"( {fin} )", "center")],
    ])

    # ===== 3. หนังสือรับรองการหักภาษี ณ ที่จ่าย =====
    doc.add_page_break()
    _p(doc, "หนังสือรับรองการหักภาษี ณ ที่จ่าย", align="center", bold=True, size=18, after=2)
    _p(doc, "ตามมาตรา ๕๐ ทวิ แห่งประมวลรัษฎากร", align="center", after=8)
    _p(doc, "ผู้มีหน้าที่หักภาษี ณ ที่จ่าย :", bold=True, after=0)
    _p(doc, f"ส่วนราชการ {sname}   เลขประจำตัวผู้เสียภาษี {getattr(school,'tax_id','') or _BLANK}", after=0)
    _p(doc, f"ที่อยู่ {saddr or _BLANK}", after=0)
    _p(doc, f"ขอรับรองว่าได้หักภาษี ณ ที่จ่าย ตามใบสั่งจ้าง เลขที่ {order_no}", after=6)
    _p(doc, "ผู้ถูกหักภาษี ณ ที่จ่าย :", bold=True, after=0)
    _p(doc, f"ชื่อ {vname}   เลขประจำตัวประชาชน {vtax}", after=0)
    _p(doc, f"ที่อยู่ {vaddr}", after=6)
    _simple_table(doc, ["ประเภทเงินได้ที่จ่าย", "วันที่จ่าย", "จำนวนเงินที่จ่าย", "ภาษีที่หัก"],
                  [["ค่าจ้างเหมาประกอบอาหารกลางวัน", _dnum(inst.inspect_date or inst.end_date), A, W],
                   ["รวม", "", A, W]],
                  [Cm(6.4), Cm(3.2), Cm(3.2), Cm(3.2)])
    _p(doc, f"รวมเงินภาษีที่หัก (ตัวอักษร)  ({bahttext(wht)})", indent=1.25, before=2, after=12)
    _p(doc, "(ลงชื่อ)...........................................ผู้จ่ายเงิน", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)

    return _save(doc, f"ขอเบิกจ่าย_งวดที่{inst.seq}_ปี{prog.year}")


def _student_tiers(prog):
    """แยกนักเรียนเป็น 2 กลุ่มตามใบสั่งจ้าง: (อนุบาล-ประถม) และ (มัธยม)"""
    t1 = sum((c.num_students or 0) for c in prog.classes
             if (c.level or "").startswith(("อ", "ป")))
    t2 = sum((c.num_students or 0) for c in prog.classes
             if (c.level or "").startswith("ม"))
    return t1, t2


def render_order_doc(rnd, school) -> str:
    """ใบสั่งจ้างเหมาประกอบอาหารกลางวัน (สัญญา 1 รอบ) — ใช้ข้อมูลงวดที่บันทึกไว้"""
    doc = Document()
    _font(doc)
    prog = rnd.program
    vendor = rnd.vendor
    vname = vendor.name if vendor else _BLANK
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip() or _BLANK
    order_no = (rnd.order_no or "").strip() or _BLANK
    total = round(float(rnd.amount or 0), 2)
    rate = prog.rate_per_head or 0
    days = rnd.days or 0
    t1, t2 = _student_tiers(prog)
    insts = list(rnd.installments)
    n_inst = len(insts)
    per_days = (insts[0].days if insts else 0)

    _p(doc, "ใบสั่งจ้าง", align="center", bold=True, size=20, after=4)
    _simple_table(doc, ["ผู้รับจ้าง", "ใบสั่งจ้าง"],
                  [[vname, f"เลขที่ {order_no}  ลงวันที่ {_dnum(rnd.order_date)}"]],
                  [Cm(8.0), Cm(8.0)])
    _p(doc, f"ตามที่ {vname} ได้เสนอราคาไว้ต่อ{sname} ซึ่งได้รับราคาและตกลงจ้าง "
            f"ตามรายการดังต่อไปนี้", align="justify", indent=1.25, after=4)
    rows = []
    if t1:
        rows.append(["๑", "จ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ระดับอนุบาล-ประถมศึกษา",
                     f"{t1} คน", f"{_money(rate)} บาท/วัน", str(days), _money(t1*rate*days)])
    if t2:
        rows.append(["๒", "จ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ระดับมัธยมศึกษา",
                     f"{t2} คน", f"{_money(rate)} บาท/วัน", str(days), _money(t2*rate*days)])
    if not rows:
        rows.append(["๑", "จ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)",
                     f"{prog.total_students} คน", f"{_money(rate)} บาท/วัน", str(days), _money(total)])
    rows.append(["", "", "", "", "รวมเป็นเงินทั้งสิ้น", _money(total)])
    _simple_table(doc, ["ลำดับ", "รายการ", "จำนวน", "ราคาต่อหน่วย", "จำนวนวัน", "จำนวนเงิน (บาท)"],
                  rows, [Cm(1.2), Cm(6.0), Cm(2.0), Cm(2.6), Cm(1.8), Cm(2.6)])
    _p(doc, f"(ตัวอักษร) {bahttext(total)}", indent=1.25, before=2, after=6)

    _p(doc, "การสั่งจ้าง อยู่ภายใต้เงื่อนไขต่อไปนี้", bold=True, indent=1.25)
    _p(doc, f"๑. กำหนดส่งมอบภายใน ตามงวดงาน {n_inst or '-'} งวดงาน งวดงานละ {per_days or '-'} วัน "
            f"รวม {days} วัน นับถัดจากวันที่ผู้รับจ้างได้รับใบสั่งจ้าง", align="justify", indent=1.25)
    _p(doc, f"๒. สถานที่ส่งมอบ {sname}", indent=1.25)
    _p(doc, "๓. สงวนสิทธิ์ค่าปรับกรณีส่งมอบเกินกำหนด โดยคิดค่าปรับเป็นรายวันในอัตราร้อยละ ๐.๒๐ "
            "ของมูลค่าตามใบสั่งจ้าง", align="justify", indent=1.25)
    _p(doc, "๔. การส่งมอบงานและการจ่ายเงิน แบ่งจ่ายตามงวดงาน ดังนี้", indent=1.25)
    if insts:
        for i in insts:
            _p(doc, f"    งวดที่ {i.seq} จ่ายเป็นเงิน {_money(i.amount or 0)} บาท "
                    f"({bahttext(i.amount or 0)}) เมื่อได้ส่งมอบงานงวดที่ {i.seq} เรียบร้อยแล้ว",
               align="justify", indent=1.5, after=0)
    else:
        _p(doc, "    (ยังไม่ได้แบ่งงวด — เพิ่มงวดในหน้าจัดการงวด)", indent=1.5, after=0)
    _p(doc, f"๕. กำหนดมูลค่าตามใบสั่งจ้างให้อยู่ภายในวงเงิน {_money(total)} บาท ({bahttext(total)}) "
            f"ระยะเวลาดำเนินการภายใน {days} วัน นับถัดจากวันลงนามในใบสั่งจ้าง",
       align="justify", indent=1.25, before=4)
    _p(doc, "๖. เอกสารแนบท้ายใบสั่งจ้าง : ขอบเขตของงาน (TOR) และใบเสนอราคา",
       align="justify", indent=1.25, after=14)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................ผู้สั่งจ้าง", "center"),
         (f"( {director} )", "center"),
         (f"ผู้อำนวยการ{sname}", "center")],
        [("(ลงชื่อ)...........................................ผู้รับใบสั่งจ้าง", "center"),
         (f"( {vname} )", "center")],
    ])
    return _save(doc, f"ใบสั่งจ้าง_รอบที่{rnd.seq}_ปี{prog.year}")


_COM_ORDER = [
    ("tor", "แต่งตั้งคณะกรรมการจัดทำขอบเขตของงาน (TOR) การจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)",
     "จัดทำขอบเขตของงาน (TOR) การจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ให้ถูกต้องครบถ้วน"),
    ("control", "แต่งตั้งคณะกรรมการควบคุมงานจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)",
     "ควบคุมงานจ้างเหมาประกอบอาหารกลางวัน ตรวจสอบคุณภาพ ความสะอาด และปริมาณอาหารเป็นรายวัน"),
    ("inspect", "แต่งตั้งคณะกรรมการตรวจรับการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)",
     "ตรวจรับพัสดุงานจ้างเหมาประกอบอาหารกลางวัน ให้เป็นไปตามเงื่อนไขของสัญญาหรือข้อตกลง"),
]


def render_committee_order_doc(rnd, school) -> str:
    """คำสั่งแต่งตั้งคณะกรรมการ 3 ฉบับในไฟล์เดียว (TOR / ควบคุมงาน / ตรวจรับ)"""
    doc = Document()
    _font(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip() or _BLANK
    period = (f"(ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} "
              f"จำนวน {rnd.days or ''} วัน)")
    groups = {k: [m for m in rnd.committees if m.kind == k] for k, _, _ in _COM_ORDER}

    first = True
    for kind, subject, duty in _COM_ORDER:
        members = groups.get(kind) or []
        if not first:
            doc.add_page_break()
        first = False
        _p(doc, f"คำสั่ง{sname}", align="center", bold=True, size=18, after=0)
        _p(doc, f"ที่ ....../{prog.year}", align="center", bold=True, after=0)
        _p(doc, f"เรื่อง {subject}", align="center", bold=True, after=0)
        _p(doc, period, align="center", after=0)
        _p(doc, "─────────────────────", align="center", after=6)
        _p(doc, f"ด้วย{sname} จะดำเนินการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ให้บริการแก่นักเรียน "
                "เพื่อให้การดำเนินการจ้างดังกล่าวเป็นไปด้วยความเรียบร้อย บังเกิดผลดีแก่ทางราชการ "
                "จึงอาศัยอำนาจตามระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ "
                "พ.ศ. ๒๕๖๐ แต่งตั้งบุคคลต่อไปนี้เป็นคณะกรรมการ", align="justify", indent=1.25, after=4)
        if members:
            for i, m in enumerate(members, 1):
                _p(doc, f"{i}. {m.name}        ตำแหน่ง {m.position}        {m.role}",
                   indent=1.5, after=0)
        else:
            for i in range(1, 4):
                _p(doc, f"{i}. ...........................................        ตำแหน่ง ..................        "
                        f"{'ประธานกรรมการ' if i == 1 else 'กรรมการ'}", indent=1.5, after=0)
        _p(doc, f"ให้คณะกรรมการที่ได้รับแต่งตั้ง {duty} และปฏิบัติหน้าที่ให้ถูกต้องตามระเบียบ"
                "ของทางราชการอย่างเคร่งครัด", align="justify", indent=1.25, before=4)
        _p(doc, "ทั้งนี้ ตั้งแต่บัดนี้เป็นต้นไป", bold=True, indent=1.25, after=6)
        _p(doc, f"สั่ง ณ วันที่ {_dnum(rnd.order_date)}", align="center", after=14)
        _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
        _p(doc, f"( {director} )", align="center", after=0)
        _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)

    return _save(doc, f"คำสั่งแต่งตั้งกรรมการ_รอบที่{rnd.seq}_ปี{prog.year}")


def _committee_lines(doc, members, fallback_n=3):
    if members:
        for i, m in enumerate(members, 1):
            _p(doc, f"{i}. {m.name}        ตำแหน่ง {m.position}        {m.role}",
               indent=1.75, after=0)
    else:
        for i in range(1, fallback_n + 1):
            _p(doc, f"{i}. ...........................................  ตำแหน่ง ..............  "
                    f"{'ประธานกรรมการ' if i == 1 else 'กรรมการ'}", indent=1.75, after=0)


def render_hire_report_doc(rnd, school) -> str:
    """รายงานขอจ้างเหมาประกอบอาหารกลางวัน (บันทึกข้อความเปิดเรื่อง)"""
    doc = Document()
    _font(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    saddr = (school.address or "").strip()
    director = (school.director_name or "").strip() or _BLANK
    officer = (school.officer_name or "").strip() or _BLANK
    head = (school.head_officer_name or "").strip() or _BLANK
    fund = (prog.funding_org or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"
    total = round(float(rnd.amount or 0), 2)
    rate = prog.rate_per_head or 0
    days = rnd.days or 0
    t1, t2 = _student_tiers(prog)
    period = (f"ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} "
              f"จำนวน {days} วัน")

    _p(doc, "บันทึกข้อความ", align="center", bold=True, size=20, after=4)
    _p(doc, f"ส่วนราชการ  {sname}  {saddr}", after=0)
    _p(doc, f"ที่  -/{prog.year}                     วันที่  {_dnum(rnd.order_date)}", after=0)
    _p(doc, f"เรื่อง  รายงานขอจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ประจำปีการศึกษา {prog.year} "
            f"({period})", after=0)
    _p(doc, f"เรียน  ผู้อำนวยการ{sname}", after=6)
    _p(doc, f"ด้วย{sname} มีความประสงค์จ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ให้แก่นักเรียน "
            f"ระดับชั้นอนุบาลถึงระดับชั้นมัธยมศึกษา โดยมีรายละเอียด ดังนี้", align="justify", indent=1.25)
    _p(doc, "๑. เหตุผลและความจำเป็นที่ต้องจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เพื่อประกอบอาหารกลางวัน (ปรุงสำเร็จ) ให้กับนักเรียน{sname} ตั้งแต่ระดับชั้นอนุบาล"
            "ถึงระดับชั้นมัธยมศึกษาปีที่ ๓ (โรงเรียนขยายโอกาส) ให้ได้รับประทานอาหารที่มีคุณค่า "
            "ครบถ้วนตามหลักโภชนาการ", align="justify", indent=1.5)
    _p(doc, "๒. ขอบเขตของงานพัสดุที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, "การจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ตามรายละเอียดขอบเขตของงาน (TOR) แนบท้าย",
       align="justify", indent=1.5)
    _p(doc, "๓. ราคากลางของพัสดุที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เป็นเงิน {_money(total)} บาท ({bahttext(total)}) โดยมีแหล่งที่มาจาก{fund}",
       indent=1.5)
    _p(doc, "๔. วงเงินที่จะจ้าง", bold=True, indent=1.25, after=0)
    _p(doc, f"เป็นเงิน {_money(total)} บาท ({bahttext(total)})", indent=1.5)
    _p(doc, "๕. รายละเอียดการคำนวณ", bold=True, indent=1.25, after=0)
    if t1:
        _p(doc, f"ระดับชั้นอนุบาล-ประถมศึกษา จำนวนนักเรียน {t1} คน ในอัตราคนละ {_money(rate)} บาท/วัน "
                f"จำนวน {days} วัน เป็นเงิน {_money(t1*rate*days)} บาท", indent=1.5, after=0)
    if t2:
        _p(doc, f"ระดับชั้นมัธยมศึกษา จำนวนนักเรียน {t2} คน ในอัตราคนละ {_money(rate)} บาท/วัน "
                f"จำนวน {days} วัน เป็นเงิน {_money(t2*rate*days)} บาท", indent=1.5, after=0)
    _p(doc, f"รวมเป็นเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)})", indent=1.5, bold=True)
    _p(doc, "๖. วิธีที่จะจ้าง และเหตุผลที่จะจ้างโดยวิธีนั้น", bold=True, indent=1.25, after=0)
    _p(doc, "ดำเนินการด้วยวิธีเฉพาะเจาะจง เนื่องจากการจัดจ้างมีวงเงินไม่เกิน ๕๐๐,๐๐๐ บาท "
            "ตามระเบียบกระทรวงการคลังฯ", align="justify", indent=1.5)
    _p(doc, "๗. หลักเกณฑ์การพิจารณาคัดเลือกข้อเสนอ", bold=True, indent=1.25, after=0)
    _p(doc, "การพิจารณาคัดเลือกข้อเสนอโดยใช้เกณฑ์ราคา", indent=1.5)
    _p(doc, "๘. การขออนุมัติแต่งตั้งคณะกรรมการ", bold=True, indent=1.25, after=0)
    _p(doc, "๘.๑ คณะกรรมการควบคุมงานจ้างประกอบอาหารกลางวัน", indent=1.5, after=0)
    _committee_lines(doc, [m for m in rnd.committees if m.kind == "control"])
    _p(doc, "๘.๒ คณะกรรมการตรวจรับการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)", indent=1.5, before=2, after=0)
    _committee_lines(doc, [m for m in rnd.committees if m.kind == "inspect"])
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณา หากเห็นชอบขอได้โปรดอนุมัติให้ดำเนินการจ้างเหมาประกอบ"
            "อาหารกลางวัน (ปรุงสำเร็จ) และแต่งตั้งคณะกรรมการตามข้อ ๘.๑ และ ๘.๒",
       align="justify", indent=1.25, before=4, after=12)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................เจ้าหน้าที่", "center"),
         (f"( {officer} )", "center")],
        [("(ลงชื่อ)...........................................หัวหน้าเจ้าหน้าที่", "center"),
         (f"( {head} )", "center")],
    ])
    _p(doc, "ความเห็นของผู้อำนวยการ  (   ) เห็นชอบ/อนุมัติ", indent=1.25, before=4, after=10)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)
    return _save(doc, f"รายงานขอจ้าง_รอบที่{rnd.seq}_ปี{prog.year}")


def _hdr_memo(doc, school, prog, subject_lines, date):
    _p(doc, "บันทึกข้อความ", align="center", bold=True, size=20, after=4)
    _p(doc, f"ส่วนราชการ  {(school.name or '').strip()}  {(school.address or '').strip()}", after=0)
    _p(doc, f"ที่  -/{prog.year}                     วันที่  {date}", after=0)
    for i, s in enumerate(subject_lines):
        _p(doc, (("เรื่อง  " + s) if i == 0 else "        " + s), after=0)
    _p(doc, f"เรียน  ผู้อำนวยการ{(school.name or '').strip()}", after=6)


def render_winner_doc(rnd, school) -> str:
    """ประกาศผู้ชนะการเสนอราคา (จ้างเหมาอาหารกลางวัน)"""
    doc = Document()
    _font(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    total = round(float(rnd.amount or 0), 2)
    period = (f"ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} "
              f"จำนวน {rnd.days or ''} วัน")
    _p(doc, f"ประกาศ{sname}", align="center", bold=True, size=18, after=0)
    _p(doc, "เรื่อง ประกาศผู้ชนะการเสนอราคา สำหรับการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)",
       align="center", bold=True, after=0)
    _p(doc, f"({period}) โดยวิธีเฉพาะเจาะจง", align="center", after=0)
    _p(doc, "─────────────────────", align="center", after=6)
    _p(doc, f"ตามที่{sname} ได้มีโครงการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) {period} "
            f"โดยวิธีเฉพาะเจาะจงนั้น", align="justify", indent=1.25)
    _p(doc, f"การจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ผู้ได้รับการคัดเลือก ได้แก่ {vname} "
            f"โดยเสนอราคาเป็นเงินทั้งสิ้น {_money(total)} บาท ({bahttext(total)})",
       align="justify", indent=1.25, after=10)
    _p(doc, f"ประกาศ ณ วันที่ {_dnum(rnd.order_date)}", align="center", after=14)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)
    return _save(doc, f"ประกาศผู้ชนะ_รอบที่{rnd.seq}_ปี{prog.year}")


def render_result_doc(rnd, school) -> str:
    """รายงานผลการพิจารณาและขออนุมัติสั่งจ้าง"""
    doc = Document()
    _font(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    director = (school.director_name or "").strip() or _BLANK
    officer = (school.officer_name or "").strip() or _BLANK
    head = (school.head_officer_name or "").strip() or _BLANK
    vname = rnd.vendor.name if rnd.vendor else _BLANK
    total = round(float(rnd.amount or 0), 2)
    period = f"ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} จำนวน {rnd.days or ''} วัน"
    _hdr_memo(doc, school, prog,
              ["รายงานผลการพิจารณาและขออนุมัติสั่งจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)",
               f"ประจำปีการศึกษา {prog.year} ({period})"], _dnum(rnd.order_date))
    _p(doc, f"ตามที่ผู้อำนวยการ{sname} เห็นชอบให้ดำเนินการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) "
            f"ให้แก่นักเรียน {period} โดยวิธีเฉพาะเจาะจงนั้น", align="justify", indent=1.25)
    _p(doc, f"บัดนี้ ได้ดำเนินการพิจารณาแล้ว จึงเห็นสมควรรับราคาจาก {vname} เป็นเงิน {_money(total)} บาท "
            f"({bahttext(total)}) การจัดจ้างครั้งนี้ไม่เกินวงเงินที่ประมาณไว้และไม่สูงกว่าราคากลาง",
       align="justify", indent=1.25)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติให้ดำเนินการจัดจ้างจากผู้ชนะการเสนอราคาดังกล่าว "
            "และลงนามในประกาศรายชื่อผู้ชนะการเสนอราคา", align="justify", indent=1.25, after=12)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................เจ้าหน้าที่", "center"),
         (f"( {officer} )", "center")],
        [("(ลงชื่อ)...........................................หัวหน้าเจ้าหน้าที่", "center"),
         (f"( {head} )", "center")],
    ])
    _p(doc, "อนุมัติ/ลงนามแล้ว", align="center", bold=True, before=4, after=8)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)
    return _save(doc, f"รายงานผลพิจารณา_รอบที่{rnd.seq}_ปี{prog.year}")


def render_tor_request_doc(rnd, school) -> str:
    """บันทึกข้อความขออนุมัติแต่งตั้งคณะกรรมการจัดทำ TOR"""
    doc = Document()
    _font(doc)
    prog = rnd.program
    sname = (school.name or "").strip() or "โรงเรียน"
    officer = (school.officer_name or "").strip() or _BLANK
    head = (school.head_officer_name or "").strip() or _BLANK
    period = f"ระหว่างวันที่ {_dnum(rnd.start_date)} ถึงวันที่ {_dnum(rnd.end_date)} จำนวน {rnd.days or ''} วัน"
    _hdr_memo(doc, school, prog,
              ["ขออนุมัติแต่งตั้งคณะกรรมการจัดทำขอบเขตของงาน (TOR) "
               "งานจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ)"], _dnum(rnd.order_date))
    _p(doc, "ข้อเท็จจริง", bold=True, indent=1.25, after=0)
    _p(doc, f"{sname} ดำเนินการจ้างเหมาประกอบอาหารกลางวัน (ปรุงสำเร็จ) ประจำปีการศึกษา {prog.year} "
            f"({period}) โดยวิธีเฉพาะเจาะจง สำหรับนักเรียนระดับชั้นอนุบาลถึงระดับชั้นมัธยมศึกษาปีที่ ๓ "
            "ในโรงเรียนขยายโอกาสทางการศึกษา", align="justify", indent=1.5)
    _p(doc, "ข้อเสนอและข้อพิจารณา", bold=True, indent=1.25, after=0)
    _p(doc, "เพื่อให้เป็นไปตามระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ "
            "พ.ศ. ๒๕๖๐ ข้อ ๒๑ เห็นควรแต่งตั้งคณะกรรมการจัดทำขอบเขตของงาน (TOR) ดังรายชื่อต่อไปนี้",
       align="justify", indent=1.5)
    _committee_lines(doc, [m for m in rnd.committees if m.kind == "tor"])
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณา", indent=1.25, before=4, after=12)
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................เจ้าหน้าที่", "center"),
         (f"( {officer} )", "center")],
        [("(ลงชื่อ)...........................................หัวหน้าเจ้าหน้าที่", "center"),
         (f"( {head} )", "center")],
    ])
    return _save(doc, f"ขออนุมัติTOR_รอบที่{rnd.seq}_ปี{prog.year}")
