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
    _sign_table(doc, [
        [("(ลงชื่อ)...........................................ประธานกรรมการตรวจรับ", "center"),
         ("(...........................................)", "center")],
        [("(ลงชื่อ)...........................................กรรมการ", "center"),
         ("(...........................................)", "center")],
        [("(ลงชื่อ)...........................................กรรมการ", "center"),
         ("(...........................................)", "center")],
    ])
    _p(doc, "", after=4)
    _p(doc, "ความเห็นของผู้บริหารสถานศึกษา", indent=1.25, after=0)
    _p(doc, "(   ) ทราบผลการตรวจรับ          (   ) อนุมัติ", indent=1.5, after=10)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {director or _BLANK} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการ{sname}", align="center", after=0)

    return _save(doc, f"งวดที่{inst.seq}_ปี{rnd.program.year}")
