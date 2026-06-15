# -*- coding: utf-8 -*-
"""
office_doc.py
-------------
สร้างไฟล์ Word เอกสารงานธุรการจากข้อมูลจริง:
  - บันทึกข้อความ (OfficeMemo)
  - คำสั่งโรงเรียน (SchoolOrder)

ใช้ helper จัดรูปแบบร่วมกับ build_templates (ฟอนต์ TH Sarabun, ครุฑ, ตัวหนา complex script)
"""
from pathlib import Path

from docx import Document

from app.database import get_data_dir
from app.thai_utils import thai_date, thai_date_official
from app.services.build_templates import (
    _font, _p, _p_runs, _krut_and_title, _krut_center, _sign_table, THAI_FONT,
)


def _safe(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _school_office(school) -> str:
    parts = [school.name or "", school.address or ""]
    return "  ".join(p for p in parts if p).strip()


def _director_office(school) -> str:
    name = (school.name or "").strip()
    if name.startswith("โรงเรียน"):
        return "ผู้อำนวยการ" + name
    return school.director_position or "ผู้อำนวยการโรงเรียน"


def _body_paragraphs(doc, body: str):
    """แตกเนื้อหาเป็นย่อหน้า (เว้นบรรทัด = ย่อหน้าใหม่) จัดชิดขอบแบบไทย เยื้องบรรทัดแรก"""
    for line in (body or "").split("\n"):
        line = line.strip()
        if line:
            _p(doc, line, align="justify", indent=1.25, after=2)


def render_memo(memo, school) -> str:
    """สร้างไฟล์ .docx บันทึกข้อความ คืนค่าที่อยู่ไฟล์"""
    doc = Document()
    _font(doc)
    _krut_and_title(doc)   # ครุฑ + "บันทึกข้อความ"

    _p_runs(doc, [("ส่วนราชการ  ", True), (memo.from_dept or _school_office(school), False)])
    _p_runs(doc, [("ที่  ", True), (memo.memo_no or "", False),
                  ("\t", False), ("วันที่ ", True), (thai_date(memo.date), False)], tab_cm=7)
    _p_runs(doc, [("เรื่อง  ", True), (memo.subject or "", False)])
    _p_runs(doc, [("เรียน  ", True), (memo.to_person or _director_office(school), False)])

    _p(doc, "", after=4)
    _body_paragraphs(doc, memo.body)

    # ลงนาม
    _p(doc, "", after=12)
    signer = (memo.signer_name or school.director_name or "")
    position = (memo.signer_position or _director_office(school))
    _sign_table(doc, [[
        ("ลงชื่อ.........................................", "center"),
        (f"( {signer} )", "center"),
        (position, "center"),
    ]])

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    fname = _safe(f"บันทึกข้อความ_{memo.memo_no or memo.id}_{memo.subject}") + ".docx"
    out_path = out_dir / fname
    doc.save(str(out_path))
    return str(out_path)


def render_order(order, school) -> str:
    """สร้างไฟล์ .docx คำสั่งโรงเรียน คืนค่าที่อยู่ไฟล์"""
    doc = Document()
    _font(doc)
    _krut_center(doc, height_cm=1.8)
    _p(doc, "คำสั่ง" + (school.name or ""), align="center", bold=True, size=18, after=0)
    _p(doc, "ที่ " + (order.order_no or ""), align="center", bold=True, after=0)
    _p(doc, "เรื่อง " + (order.subject or ""), align="center", bold=True, after=0)
    _p(doc, "─────────────────────", align="center", after=6)

    _body_paragraphs(doc, order.body)

    _p(doc, "", after=6)
    _p(doc, "สั่ง ณ วันที่ " + thai_date_official(order.date), align="center", after=12)
    _p(doc, "(ลงชื่อ).........................................", align="center")
    _p(doc, f"( {school.director_name or ''} )", align="center")
    _p(doc, _director_office(school), align="center")

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    fname = _safe(f"คำสั่ง_{order.order_no or order.id}_{order.subject}") + ".docx"
    out_path = out_dir / fname
    doc.save(str(out_path))
    return str(out_path)
