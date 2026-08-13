# -*- coding: utf-8 -*-
"""
doc_page.py - ตั้งขนาดหน้ากระดาษ A4 ให้เอกสาร Word ทุกฉบับ

python-docx ใช้เทมเพลตปริยายเป็น Letter (21.59 x 27.94 ซม.) ซึ่งไม่ใช่ขนาดกระดาษราชการไทย
ทำให้สัดส่วนหัวกระดาษ/ระยะขอบเพี้ยนเวลาพิมพ์ลง A4 จริง - เรียก set_a4(doc) หลังสร้าง Document()
"""
from docx.shared import Cm
from docx.enum.section import WD_ORIENT

A4_W, A4_H = Cm(21.0), Cm(29.7)

# ระยะขอบมาตรฐานเอกสารราชการ: บน 1.5 · ล่าง 2 · ซ้าย 3 · ขวา 2.5 ซม.
MARGIN_TOP, MARGIN_BOTTOM, MARGIN_LEFT, MARGIN_RIGHT = Cm(1.5), Cm(2.0), Cm(3.0), Cm(2.5)


def set_margins(doc, *, top=MARGIN_TOP, bottom=MARGIN_BOTTOM,
                left=MARGIN_LEFT, right=MARGIN_RIGHT):
    """ตั้งระยะขอบทุก section (ค่าปริยาย = มาตรฐานราชการ)"""
    for sec in doc.sections:
        sec.top_margin = top
        sec.bottom_margin = bottom
        sec.left_margin = left
        sec.right_margin = right
    return doc


def set_a4(doc, landscape: bool = False, margins: bool = True):
    """ตั้งทุก section ของเอกสารเป็น A4 (แนวตั้ง/แนวนอน) + ระยะขอบมาตรฐาน
    margins=False : ไม่แตะระยะขอบ (ให้เอกสารที่ตั้งขอบเองจัดการต่อ)"""
    for sec in doc.sections:
        if landscape:
            sec.orientation = WD_ORIENT.LANDSCAPE
            sec.page_width, sec.page_height = A4_H, A4_W
        else:
            sec.orientation = WD_ORIENT.PORTRAIT
            sec.page_width, sec.page_height = A4_W, A4_H
    if margins:
        set_margins(doc)
    return doc
