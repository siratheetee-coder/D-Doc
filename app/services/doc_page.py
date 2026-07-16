# -*- coding: utf-8 -*-
"""
doc_page.py — ตั้งขนาดหน้ากระดาษ A4 ให้เอกสาร Word ทุกฉบับ

python-docx ใช้เทมเพลตปริยายเป็น Letter (21.59 x 27.94 ซม.) ซึ่งไม่ใช่ขนาดกระดาษราชการไทย
ทำให้สัดส่วนหัวกระดาษ/ระยะขอบเพี้ยนเวลาพิมพ์ลง A4 จริง — เรียก set_a4(doc) หลังสร้าง Document()
"""
from docx.shared import Cm
from docx.enum.section import WD_ORIENT

A4_W, A4_H = Cm(21.0), Cm(29.7)


def set_a4(doc, landscape: bool = False):
    """ตั้งทุก section ของเอกสารเป็น A4 (แนวตั้ง หรือแนวนอน)"""
    for sec in doc.sections:
        if landscape:
            sec.orientation = WD_ORIENT.LANDSCAPE
            sec.page_width, sec.page_height = A4_H, A4_W
        else:
            sec.orientation = WD_ORIENT.PORTRAIT
            sec.page_width, sec.page_height = A4_W, A4_H
    return doc
