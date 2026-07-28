# -*- coding: utf-8 -*-
"""
proc_plan_doc.py - ประกาศเผยแพร่แผนการจัดซื้อจัดจ้างประจำปีงบประมาณ (Word)
ตามพระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 มาตรา 11
"""
from docx import Document
from docx.shared import Cm
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services.doc_page import set_a4

from app.database import get_data_dir
from app.thai_utils import thai_date, bahttext
from app.services.build_templates import (
    _font, _p, _krut_center, _set_cell, _repeat_header_row, _no_split_row,
)

_BLANK = "............................"


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*\n\r\t':
        text = text.replace(ch, "_")
    return text.strip()[:80]


def _fixed_layout(table, widths):
    """บังคับตารางเป็น layout คงที่ + ตั้ง gridCol/tblW ตามความกว้างที่กำหนด
    กัน Word ขยายคอลัมน์ตามเนื้อหาจนตารางเกินขอบกระดาษ"""
    tbl = table._tbl
    tblPr = tbl.tblPr
    layout = tblPr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout"); tblPr.append(layout)
    layout.set(qn("w:type"), "fixed")
    total = sum(int(w.twips) for w in widths)
    tblW = tblPr.find(qn("w:tblW"))
    if tblW is None:
        tblW = OxmlElement("w:tblW"); tblPr.append(tblW)
    tblW.set(qn("w:w"), str(total)); tblW.set(qn("w:type"), "dxa")
    grid = tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for gc, w in zip(grid.findall(qn("w:gridCol")), widths):
            gc.set(qn("w:w"), str(int(w.twips)))


def render_plan_announcement(school, fiscal_year, rows, announce_date=None) -> str:
    """rows = list ของ ProcurementPlan (เรียงแล้ว)"""
    doc = Document(); set_a4(doc)
    _font(doc)
    # ขอบกระดาษ: ซ้าย 2.0 / ขวา 1.5 / บน 1.5 / ล่าง 1.2 ซม. -> พื้นที่พิมพ์กว้าง 17.5 ซม.
    sec = doc.sections[0]
    sec.left_margin = Cm(2.0); sec.right_margin = Cm(1.5)
    sec.top_margin = Cm(1.5); sec.bottom_margin = Cm(1.2)
    sname = (school.name or "โรงเรียน").strip()
    total = sum(float(r.budget or 0) for r in rows)

    _krut_center(doc)
    _p(doc, f"ประกาศโรงเรียน{sname}", align="center", bold=True, size=18, after=0)
    _p(doc, f"เรื่อง เผยแพร่แผนการจัดซื้อจัดจ้าง ประจำปีงบประมาณ พ.ศ. {fiscal_year}",
       align="center", bold=True, after=0)
    _p(doc, "-----------------------------------", align="center", after=6)
    _p(doc, "ตามพระราชบัญญัติการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560 มาตรา 11 ให้หน่วยงาน"
            "ของรัฐจัดทำแผนการจัดซื้อจัดจ้างประจำปี และประกาศเผยแพร่ในระบบเครือข่ายสารสนเทศของ"
            "กรมบัญชีกลางและของหน่วยงานของรัฐตามที่กรมบัญชีกลางกำหนด และให้ปิดประกาศโดยเปิดเผย "
            "ณ สถานที่ปิดประกาศของหน่วยงานของรัฐ นั้น", align="justify", indent=1.25, after=2)
    _p(doc, f"โรงเรียน{sname} ขอประกาศเผยแพร่แผนการจัดซื้อจัดจ้าง ประจำปีงบประมาณ พ.ศ. {fiscal_year} "
            "ตามเอกสารแนบท้ายประกาศนี้", align="justify", indent=1.25, after=8)

    headers = ["ลำดับ", "รายการ/โครงการที่จะจัดซื้อจัดจ้าง", "งบประมาณโครงการ\n(บาท)",
               "ระยะเวลาที่คาดว่าจะ\nประกาศจัดซื้อจัดจ้าง"]
    widths = [Cm(1.4), Cm(9.5), Cm(3.2), Cm(3.3)]   # รวม 17.4 <= พื้นที่พิมพ์ 17.5 ซม. (สัดส่วนตามไฟล์จริง)
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"; t.autofit = False; t.allow_autofit = False
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _fixed_layout(t, widths)   # บังคับ layout คงที่ + gridCol ตามที่กำหนด (กัน Word ขยายคอลัมน์เกินขอบ)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14); c.width = w
    if not rows:
        r = t.add_row(); _set_cell(r.cells[0], "-", align="center", size=14)
    for i, p in enumerate(rows, start=1):
        r = t.add_row(); _no_split_row(r)
        vals = [str(i), p.name, f"{float(p.budget or 0):,.2f}", p.expected_period or "-"]
        aligns = ["center", "left", "right", "center"]
        for c, v, w, al in zip(r.cells, vals, widths, aligns):
            _set_cell(c, v, align=al, size=14); c.width = w
    r = t.add_row(); _no_split_row(r)
    _set_cell(r.cells[0], "", align="center", size=14)
    _set_cell(r.cells[1], "รวมทั้งสิ้น", bold=True, align="right", size=14)
    _set_cell(r.cells[2], f"{total:,.2f}", bold=True, align="right", size=14)
    _set_cell(r.cells[3], "", align="center", size=14)

    _p(doc, f"รวมงบประมาณทั้งสิ้น {total:,.2f} บาท ({bahttext(total)})", bold=True, before=6, after=12)
    _p(doc, f"ประกาศ ณ วันที่ {thai_date(announce_date) if announce_date else _BLANK}",
       align="center", after=14)
    _p(doc, "(ลงชื่อ)...........................................", align="center", after=0)
    _p(doc, f"( {(school.director_name or '').strip() or _BLANK} )", align="center", after=0)
    _p(doc, f"ผู้อำนวยการโรงเรียน{sname}", align="center", after=0)

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    path = out_dir / (_safe(f"ประกาศเผยแพร่แผนจัดซื้อจัดจ้าง_ปีงบ{fiscal_year}") + ".docx")
    doc.save(str(path))
    return str(path)
