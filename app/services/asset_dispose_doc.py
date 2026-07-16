# -*- coding: utf-8 -*-
"""
asset_dispose_doc.py
--------------------
สร้างไฟล์ Word "บันทึกข้อความ ขออนุมัติจำหน่ายครุภัณฑ์" (ชำรุด/เสื่อมสภาพ/หมดความจำเป็น)
ตามแบบราชการ: เนื้อความ + ตารางรายการครุภัณฑ์ที่ขอจำหน่าย + ลงนามเจ้าหน้าที่พัสดุ + บล็อกอนุมัติ ผอ.
ใช้ helper ร่วมกับ build_templates (ฟอนต์ TH Sarabun, ครุฑ, จัดกระจายแบบไทย)
"""
from pathlib import Path

from docx.shared import Cm, Pt

from app.services.doc_page import set_a4

from app.database import get_data_dir
from app.thai_utils import thai_date, bahttext
from app.services.build_templates import (
    _font, _p, _p_runs, _krut_and_title, _sign_table, _set_cell,
    _repeat_header_row, _no_split_row,
)


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*\n\r\t':
        text = text.replace(ch, "_")
    return text.strip()[:80]


def _school_office(school) -> str:
    parts = [school.name or "", school.address or ""]
    return "  ".join(p for p in parts if p).strip()


def _director_office(school) -> str:
    name = (school.name or "").strip()
    if name.startswith("โรงเรียน"):
        return "ผู้อำนวยการ" + name
    return getattr(school, "director_position", None) or "ผู้อำนวยการโรงเรียน"


def _fmt(v) -> str:
    return "{:,.2f}".format(float(v or 0))


def render_asset_disposal(assets, school, *, doc_no="", doc_date=None,
                          method="", reason="", note="") -> str:
    """สร้าง .docx ขออนุมัติจำหน่ายครุภัณฑ์ จากรายการครุภัณฑ์ที่เลือก คืนค่าที่อยู่ไฟล์"""
    from docx import Document
    doc = Document(); set_a4(doc)
    _font(doc)
    _krut_and_title(doc)   # ครุฑ + "บันทึกข้อความ"

    total_cost = sum(float(a.cost or 0) for a in assets)
    total_value = sum(float(a.dispose_value or 0) for a in assets)
    reason_txt = reason or "ชำรุด เสื่อมสภาพ และหมดความจำเป็นในการใช้งาน"
    method_txt = method or "ตามที่คณะกรรมการเห็นสมควร"

    _p_runs(doc, [("ส่วนราชการ  ", True), (_school_office(school), False)])
    _p_runs(doc, [("ที่  ", True), (doc_no or "", False),
                  ("\t", False), ("วันที่ ", True), (thai_date(doc_date), False)], tab_cm=8)
    _p_runs(doc, [("เรื่อง  ", True), ("ขออนุมัติจำหน่ายครุภัณฑ์", False)])
    _p_runs(doc, [("เรียน  ", True), (_director_office(school), False)])
    _p(doc, "", after=4)

    # ย่อหน้านำ
    _p(doc,
       f"ด้วย{school.name or 'โรงเรียน'} ได้ดำเนินการตรวจสอบพัสดุประจำปี ปรากฏว่ามีครุภัณฑ์ "
       f"จำนวน {len(assets)} รายการ มีสภาพ{reason_txt} ไม่สามารถใช้งานได้ตามปกติ "
       "หากเก็บรักษาไว้จะเป็นภาระในการดูแลและสิ้นเปลืองสถานที่ รายละเอียดดังนี้",
       align="justify", indent=1.25, after=4)

    # ตารางรายการครุภัณฑ์ที่ขอจำหน่าย
    headers = ["ลำดับ", "เลขครุภัณฑ์", "รายการ", "จำนวน", "ราคาทุน (บาท)",
               "วันที่ได้มา", "เหตุผล/สภาพ", "วิธีจำหน่าย"]
    widths = [Cm(1.1), Cm(2.8), Cm(3.6), Cm(1.4), Cm(2.2), Cm(2.2), Cm(2.8), Cm(2.2)]
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.autofit = False
    hdr = table.rows[0]
    _repeat_header_row(hdr)
    _no_split_row(hdr)
    for c, h, w in zip(hdr.cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    for i, a in enumerate(assets, 1):
        row = table.add_row()
        _no_split_row(row)
        qty = f"{(a.quantity or 1):g} {a.unit or 'หน่วย'}"
        cells = [str(i), a.asset_code or "-", a.name or "-", qty, _fmt(a.cost),
                 thai_date(a.acquired_date) if a.acquired_date else "-",
                 a.dispose_reason or reason_txt, a.dispose_method or method_txt]
        aligns = ["center", "left", "left", "center", "right", "center", "left", "center"]
        for c, val, al, w in zip(row.cells, cells, aligns, widths):
            _set_cell(c, val, align=al, size=14)
            c.width = w
    # แถวรวม
    trow = table.add_row()
    _no_split_row(trow)
    _set_cell(trow.cells[0], "รวม", bold=True, align="center", size=14)
    trow.cells[0].merge(trow.cells[3])
    _set_cell(trow.cells[4], _fmt(total_cost), bold=True, align="right", size=14)

    _p(doc, "", after=4)
    if total_value > 0:
        _p(doc,
           f"ทั้งนี้ หากจำหน่ายโดยวิธีขาย คาดว่าจะได้รับเงินประมาณ {_fmt(total_value)} บาท "
           f"({bahttext(total_value)})", align="justify", indent=1.25, after=2)
    if (note or "").strip():
        _p(doc, note.strip(), align="justify", indent=1.25, after=2)

    _p(doc,
       "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติจำหน่ายครุภัณฑ์ตามรายการข้างต้น และแต่งตั้งคณะกรรมการ"
       "ดำเนินการจำหน่ายตามระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ "
       "พ.ศ. 2560 ต่อไป", align="justify", indent=1.25, after=10)

    # ลงนามเจ้าหน้าที่พัสดุ
    officer = (getattr(school, "officer_name", "") or "").strip()
    _sign_table(doc, [[
        ("ลงชื่อ.........................................เจ้าหน้าที่พัสดุ", "center"),
        (f"( {officer} )", "center"),
    ]])

    # บล็อกอนุมัติของผู้อำนวยการ
    _p(doc, "", after=6)
    _p(doc, "ความเห็น/คำสั่ง", bold=True, indent=1.25, after=1)
    _p(doc, "1.  ทราบ", indent=1.25, after=1)
    _p(doc, "2.  อนุมัติให้จำหน่ายครุภัณฑ์ตามรายการข้างต้น", indent=1.25, after=1)
    _p(doc, "3.  แต่งตั้งคณะกรรมการดำเนินการจำหน่าย", indent=1.25, after=10)
    _sign_table(doc, [[
        ("ลงชื่อ.........................................", "center"),
        (f"( {(getattr(school, 'director_name', '') or '').strip()} )", "center"),
        (_director_office(school), "center"),
    ]])
    _p(doc, "วันที่.........................................", align="center", after=2)

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    fname = _safe(f"ขออนุมัติจำหน่ายครุภัณฑ์_{doc_no or thai_date(doc_date)}") + ".docx"
    out_path = out_dir / fname
    doc.save(str(out_path))
    return str(out_path)
