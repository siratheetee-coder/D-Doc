# -*- coding: utf-8 -*-
"""
project_register.py - ทะเบียนคุมโครงการ (งานการเงิน)

ต่างจาก "รายงานสรุปการใช้งบประมาณรายโครงการ" (project_summary.py) ตรงที่
เล่มนี้เป็น "ทะเบียนคุม" แบบที่ครูการเงินใช้จริง คือ 1 โครงการ = 1 หน้า
ลงรายการทีละบรรทัดตามวันที่ แล้วเดินยอดคงเหลือสะสมลงมาเรื่อย ๆ
เหมือนทะเบียนคุมเงิน จะได้ตอบได้ทันทีว่า "โครงการนี้เหลือเงินเท่าไร"

คอลัมน์: วัน เดือน ปี | ที่เอกสาร | รายการ | วิธีการ | จำนวนเงิน | คงเหลือ
"""
from datetime import datetime

from docx import Document
from docx.shared import Cm

from app.database import get_data_dir
from app.services.build_templates import _font, _p, _set_cell
from app.services.doc_page import set_a4, tidy
from app.services.page_fit import add_sign_space
from app.thai_utils import thai_date

_W = [Cm(2.9), Cm(2.1), Cm(4.9), Cm(2.4), Cm(2.1), Cm(2.1)]   # รวม 16.5 = พื้นที่พิมพ์ A4 ตั้ง
_HEAD = ["วัน เดือน ปี", "ที่เอกสาร", "รายการ", "วิธีการ", "จำนวนเงิน", "คงเหลือ"]


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _money(v) -> str:
    return f"{float(v or 0):,.2f}"


def _one(doc, school, row, year, year_label):
    """ทะเบียนคุมของโครงการเดียว (ขึ้นหน้าใหม่ทุกโครงการ)"""
    sname = (getattr(school, "name", "") or "โรงเรียน").strip()
    _p(doc, "ทะเบียนคุมโครงการ", align="center", bold=True, size=18, after=0)
    _p(doc, f"โครงการ {row['name']}", align="center", bold=True, size=16, after=0)
    _p(doc, sname, align="center", after=0)
    head = f"{year_label} {year}"
    if row.get("responsible"):
        head += f"   ผู้รับผิดชอบ {row['responsible']}"
    _p(doc, head, align="center", after=4)

    t = doc.add_table(rows=1, cols=len(_HEAD))
    t.style = "Table Grid"
    for c, v, w in zip(t.rows[0].cells, _HEAD, _W):
        _set_cell(c, v, size=14, align="center", bold=True)
        c.width = w

    budget = float(row["budget"] or 0)
    left = budget
    cells = t.add_row().cells
    for c, v, w, a in zip(cells, ["", "", "งบที่ได้รับอนุมัติ", "", _money(budget), _money(left)],
                          _W, ["center", "center", "left", "center", "right", "right"]):
        _set_cell(c, v, size=14, align=a)
        c.width = w
    for w in row["works"]:
        left -= float(w["amount"] or 0)
        vals = [thai_date(w["date"]) if w["date"] else "", w["no"] or "",
                w["subject"] or "", w["method"] or "", _money(w["amount"]), _money(left)]
        cells = t.add_row().cells
        for c, v, wd, a in zip(cells, vals, _W,
                               ["center", "center", "left", "center", "right", "right"]):
            _set_cell(c, v, size=14, align=a)
            c.width = wd
    cells = t.add_row().cells
    for c, v, w, a in zip(cells, ["", "", "รวมใช้ไป", "", _money(row["spent"]), _money(row["left"])],
                          _W, ["center", "center", "right", "center", "right", "right"]):
        _set_cell(c, v, size=14, align=a, bold=True)
        c.width = w

    _p(doc, "", after=4)
    _p(doc, "ลงชื่อ.....................................ผู้รับผิดชอบโครงการ", align="center", after=0)
    _p(doc, "ลงชื่อ.....................................เจ้าหน้าที่การเงิน", align="center", after=0)


def render_project_register(school, year, year_label, rows, *, as_of=None) -> str:
    """ทะเบียนคุมโครงการ · 1 โครงการ 1 หน้า · คืน path ไฟล์ .docx"""
    doc = Document()
    set_a4(doc)
    _font(doc)
    if not rows:
        _p(doc, "ทะเบียนคุมโครงการ", align="center", bold=True, size=18, after=4)
        _p(doc, f"ยังไม่มีโครงการใน{year_label} {year}", align="center")
    for i, row in enumerate(rows):
        if i:
            doc.add_page_break()
        _one(doc, school, row, year, year_label)
    _p(doc, "", after=0)
    _p(doc, f"ข้อมูล ณ วันที่ {thai_date(as_of or datetime.now())}", align="right", size=14)
    add_sign_space(doc)
    tidy(doc)
    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / (_safe(f"ทะเบียนคุมโครงการ_{year_label}{year}") + ".docx")
    doc.save(str(path))
    return str(path)
