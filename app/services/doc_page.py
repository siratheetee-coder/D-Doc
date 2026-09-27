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
# ซ้าย 3.0 (ขอบเย็บเล่มราชการ) · ขวา/ล่างแคบลงให้พื้นที่พิมพ์กว้างขึ้น กันตัวอักษร/ตารางล้น
MARGIN_TOP, MARGIN_BOTTOM, MARGIN_LEFT, MARGIN_RIGHT = Cm(1.5), Cm(1.3), Cm(3.0), Cm(1.5)


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


def strip_tail(doc):
    """ตัดย่อหน้าว่างท้ายเอกสาร (บล็อกลงนามมักเติมบรรทัดว่างไว้) กันหน้าเปล่าท้ายไฟล์"""
    from docx.text.paragraph import Paragraph
    body = doc.element.body
    while True:
        kids = [e for e in body.iterchildren() if not e.tag.endswith('sectPr')]
        if not kids or not kids[-1].tag.endswith('}p'):
            return doc
        if Paragraph(kids[-1], doc).text.strip():
            return doc
        body.remove(kids[-1])


def fold_breaks(doc):
    """ย้าย page break ไปเป็นคุณสมบัติ "ขึ้นหน้าใหม่ก่อนย่อหน้านี้" ของย่อหน้าถัดไป

    ย่อหน้าที่มีแต่ page break กินที่ 1 บรรทัด ถ้าหน้าก่อนหน้าเต็มพอดี ย่อหน้านั้น
    จะตกไปอยู่หน้าใหม่แล้วดันเนื้อหาไปอีกหน้า -> เกิดหน้าเปล่าคั่น
    แปลงเป็น w:pageBreakBefore แทน ผลเหมือนกันแต่ไม่มีหน้าเปล่า
    """
    from docx.oxml.ns import qn
    body = doc.element.body
    for para in list(body.findall(qn('w:p'))):
        runs = para.findall(qn('w:r'))
        brs = [b for r in runs for b in r.findall(qn('w:br'))
               if b.get(qn('w:type')) == 'page']
        if not brs or any(r.findall(qn('w:t')) or r.findall(qn('w:drawing')) for r in runs):
            continue
        nxt = para.getnext()
        if nxt is None or nxt.tag != qn('w:p'):
            continue                      # ถัดไปเป็นตาราง/ท้ายเอกสาร -> คงไว้ตามเดิม
        pPr = nxt.get_or_add_pPr()
        if pPr.find(qn('w:pageBreakBefore')) is None:
            pPr.insert(0, pPr.makeelement(qn('w:pageBreakBefore'), {}))
        body.remove(para)
    return doc


def shrink_tail_after_table(doc):
    """ถ้าเอกสารจบด้วยตาราง ให้ปิดท้ายด้วยย่อหน้าเล็กจิ๋วแทน

    Word บังคับให้มีย่อหน้าต่อท้ายตารางเสมอ ถ้าปล่อยให้ใช้ขนาดปกติ (~16pt)
    แล้วตารางจบพอดีท้ายหน้า ย่อหน้านั้นจะตกไปอยู่หน้าใหม่ = ได้หน้าเปล่าปิดท้าย
    ย่อหน้าขนาด 1pt ไม่มีระยะห่าง แทรกได้เกือบทุกกรณีจึงไม่ดันหน้า
    """
    from docx.oxml.ns import qn
    from docx.shared import Pt
    body = doc.element.body
    kids = [e for e in body.iterchildren() if not e.tag.endswith('sectPr')]
    if not kids or kids[-1].tag != qn('w:tbl'):
        return doc
    par = doc.add_paragraph()
    pf = par.paragraph_format
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)
    pf.line_spacing = 1
    # ความสูงของย่อหน้าว่างมาจาก "เครื่องหมายย่อหน้า" (w:pPr/w:rPr) ไม่ใช่ run
    # ตั้งที่ run อย่างเดียวไม่มีผล ย่อหน้ายังสูงเท่าขนาดปกติและดันไปหน้าใหม่
    pPr = par._p.get_or_add_pPr()
    rPr = pPr.find(qn('w:rPr'))
    if rPr is None:
        rPr = pPr.makeelement(qn('w:rPr'), {})
        pPr.append(rPr)
    for tag in ('w:sz', 'w:szCs'):
        el = rPr.makeelement(qn(tag), {qn('w:val'): '2'})     # 2 half-points = 1pt
        rPr.append(el)
    return doc


def tidy(doc):
    """เก็บงานท้ายเอกสารก่อนเซฟ: ตัดย่อหน้าว่างท้ายไฟล์ + ยุบ page break
    + ปิดท้ายตารางด้วยย่อหน้าจิ๋ว (กันหน้าเปล่าปิดท้าย)"""
    return shrink_tail_after_table(fold_breaks(strip_tail(doc)))
