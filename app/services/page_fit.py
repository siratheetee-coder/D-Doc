# -*- coding: utf-8 -*-
"""
page_fit.py - บีบเอกสารให้ "ท่อนแรก" จบในหน้าเดียว โดยไม่ลดขนาดตัวอักษร

ทำไมต้องมี
  บันทึกข้อความราชการ (เช่น รายงานขอซื้อ/ขอจ้าง) ต้องอยู่หน้าเดียว และต้องเป็น 16 pt
  ตามระเบียบงานสารบรรณ แต่ความยาวจริงขึ้นกับข้อมูลของแต่ละโรงเรียน
  (ชื่อโรงเรียน/ที่อยู่ยาว · ชื่อโครงการยาว · กรรมการ 3-5 คน)
  ถ้าเนื้อหายาวขึ้นอีก 1-2 บรรทัด บล็อกลงนาม ผอ. จะหลุดไปหน้า 2 ทั้งบล็อก

วิธีทำ
  ประมาณความสูงของท่อนแรก (ก่อน page break แรก) แล้วถ้าเกินพื้นที่พิมพ์
  จึงค่อย ๆ บีบตามลำดับ "เสียรูปน้อยสุดก่อน"
    1) ตัดช่องไฟระหว่างย่อหน้า (space before/after) ให้เหลือ 0
    2) ลดระยะห่างบรรทัดเป็น 0.95 -> 0.92 -> 0.90 เท่า
  ขนาดตัวอักษรไม่ถูกแตะต้องเลย (คง 16 pt เสมอ)

การประมาณความสูง
  ไม่มี Word บนเซิร์ฟเวอร์ จึงประมาณเอง โดยเทียบค่ากับที่ Word วัดจริง
    - TH Sarabun New 16 pt ระยะบรรทัดเดี่ยว = 21.4 pt  -> LINE_FACTOR
    - พื้นที่พิมพ์กว้าง 16.5 ซม. ใส่อักษรไทยที่ "กินความกว้าง" ได้ ~76 ตัว/บรรทัด
      (สระบน/สระล่าง/วรรณยุกต์ ไม่กินความกว้าง จึงไม่นับ)
  ประมาณให้ "เผื่อสูงไว้ก่อน" เล็กน้อย ดีกว่าประมาณต่ำแล้วล้นหน้า
"""
import math

from docx.enum.text import WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Pt

LINE_FACTOR = 1.34          # ความสูงบรรทัด / ขนาดฟอนต์ (16 pt -> 21.4 pt ตามที่ Word วัด)
CHARS_PER_CM = 4.6          # อักษรไทยที่กินความกว้าง ต่อ 1 ซม. ที่ 16 pt (16.5 ซม. ~ 76 ตัว)
SAFETY_PT = 10.0            # กันชนท้ายหน้า เผื่อความคลาดเคลื่อน (ตัวประมาณเผื่อสูงไว้อีก ~1.5%)

# อักขระไทยที่วางซ้อนบน/ล่าง ไม่กินความกว้างบรรทัด
_ZERO_WIDTH = (set(range(0x0E31, 0x0E32)) | set(range(0x0E34, 0x0E3B))
               | set(range(0x0E47, 0x0E4F)) | {0x200B})

# ไล่บีบทีละน้อย หยุดทันทีที่พอดี (เอกสารส่วนใหญ่จบที่ขั้นแรก ๆ หน้าตาแทบไม่ต่างเดิม)
# (สัดส่วนช่องไฟที่เหลือ, ระยะห่างบรรทัด) · None = ไม่บีบบรรทัด
# ช่องว่างเหนือ "ลงชื่อ" (ที่ไว้เซ็นจริง) ถูกหวงไว้จนถึงขั้นท้าย ๆ จึงค่อยยอมลด
_STEPS = (
    (1.0, 0.98), (1.0, 0.96), (1.0, 0.94), (1.0, 0.92), (1.0, 0.90),
) + tuple((round(g / 10, 2), 0.90) for g in range(9, -1, -1))


def advance_len(text: str) -> int:
    """จำนวนอักขระที่กินความกว้างจริง (ตัดสระบน/ล่าง/วรรณยุกต์ออก)"""
    return sum(1 for ch in text or "" if ord(ch) not in _ZERO_WIDTH)


def _emu_to_pt(v) -> float:
    return float(v) / 12700.0


def _para_size_pt(par, default=16.0) -> float:
    sizes = [r.font.size.pt for r in par.runs if r.font.size is not None]
    return max(sizes) if sizes else default


def _para_lines(par, width_cm: float) -> int:
    """กี่บรรทัดเมื่อจัดลงความกว้าง width_cm (นับ line break ในย่อหน้าด้วย)"""
    text = par.text or ""
    hard = text.count("\n") + text.count("\v")
    per_line = max(8.0, width_cm * CHARS_PER_CM)
    return max(1, math.ceil(advance_len(text) / per_line)) + hard


def _para_height(par, width_cm: float) -> float:
    pf = par.paragraph_format
    size = _para_size_pt(par)
    # ย่อหน้าที่มีรูป (ตราครุฑ) สูงตามรูป ไม่ใช่ตามตัวอักษร
    pic = par._p.findall(".//" + qn("w:drawing")) + par._p.findall(".//" + qn("w:pict"))
    body = (max(_emu_to_pt(e.get("cy") or 0) for e in
                par._p.findall(".//" + qn("wp:extent"))) if pic and
            par._p.findall(".//" + qn("wp:extent")) else 0.0)
    line = size * LINE_FACTOR
    if pf.line_spacing is not None and not isinstance(pf.line_spacing, int):
        try:
            line *= float(pf.line_spacing)
        except (TypeError, ValueError):
            pass
    h = max(body, _para_lines(par, width_cm) * line)
    for gap in (pf.space_before, pf.space_after):
        if gap is not None:
            h += gap.pt
    return h


def _table_height(tbl, width_cm: float) -> float:
    """ความสูงตาราง = ผลรวมของแถว (แต่ละแถวสูงตามเซลล์ที่สูงสุด)"""
    total = 0.0
    cols = max(1, len(tbl.columns))
    cell_cm = width_cm / cols
    for row in tbl.rows:
        best = 0.0
        for cell in row.cells:
            h = sum(_para_height(p, cell_cm) for p in cell.paragraphs)
            best = max(best, h)
        total += best
    return total


def _is_break(el) -> bool:
    if el.tag != qn("w:p"):
        return False
    if el.findall(".//" + qn("w:br") + "[@" + qn("w:type") + "='page']"):
        return True
    pPr = el.find(qn("w:pPr"))
    return pPr is not None and pPr.find(qn("w:pageBreakBefore")) is not None


def first_block(doc):
    """elements ของท่อนแรก (ก่อน page break แรก) พร้อมคู่ object ของ python-docx"""
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    out = []
    for el in doc.element.body:
        if _is_break(el):
            break
        if el.tag == qn("w:p"):
            out.append(Paragraph(el, doc))
        elif el.tag == qn("w:tbl"):
            out.append(Table(el, doc))
    return out


def block_height(doc, blocks=None) -> float:
    """ความสูงโดยประมาณของท่อนแรก (pt)"""
    from docx.table import Table
    sec = doc.sections[0]
    width_cm = (sec.page_width - sec.left_margin - sec.right_margin) / 360000
    total = 0.0
    for b in (blocks if blocks is not None else first_block(doc)):
        total += (_table_height(b, width_cm) if isinstance(b, Table)
                  else _para_height(b, width_cm))
    return total


def page_budget(doc) -> float:
    sec = doc.sections[0]
    return (sec.page_height - sec.top_margin - sec.bottom_margin) / 12700.0 - SAFETY_PT


def _walk_paragraphs(blocks):
    from docx.table import Table
    for b in blocks:
        if isinstance(b, Table):
            for row in b.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        yield p
        else:
            yield b


def _has_picture(par) -> bool:
    return bool(par._p.findall(".//" + qn("w:drawing")) or par._p.findall(".//" + qn("w:pict")))


def _snapshot(blocks):
    """จำรูปแบบเดิมของทุกย่อหน้าไว้ - เพื่อบีบแบบ 'เทียบของเดิม' ไม่ใช่บีบทับซ้ำ ๆ
    และเพื่อคืนค่าเดิมได้ถ้าบีบจนสุดแล้วยังไม่จบหน้าเดียว"""
    out = []
    for p in _walk_paragraphs(blocks):
        pf = p.paragraph_format
        out.append((p, 0.0 if pf.space_before is None else pf.space_before.pt,
                    0.0 if pf.space_after is None else pf.space_after.pt,
                    pf.line_spacing, pf.line_spacing_rule))
    return out


def _restore(snap):
    """คืนรูปแบบเดิมทุกย่อหน้า (ใช้เมื่อบีบแล้วก็ยังไม่จบหน้าเดียวอยู่ดี)"""
    for p, before, after, spacing, rule in snap:
        pf = p.paragraph_format
        if before:
            pf.space_before = Pt(before)
        if after:
            pf.space_after = Pt(after)
        pf.line_spacing = spacing
        pf.line_spacing_rule = rule


def _apply(snap, gap_scale, spacing):
    """ตั้งช่องไฟเป็นสัดส่วนของค่าเดิม + (ถ้าระบุ) ลดระยะห่างบรรทัด

    ไม่บีบบรรทัดของย่อหน้าที่มีรูป (ตราครุฑ) หรือหัวเรื่องตัวใหญ่ ("บันทึกข้อความ" 29pt)
    เพราะกล่องบรรทัดจะเล็กกว่าตัวจริง ทำให้รูป/ตัวอักษรถูกตัดขอบ
    """
    for p, before, after, _sp, _rule in snap:
        pf = p.paragraph_format
        if before:
            pf.space_before = Pt(round(before * gap_scale, 1))
        if after:
            pf.space_after = Pt(round(after * gap_scale, 1))
        if spacing is not None and not _has_picture(p) and _para_size_pt(p) <= 18:
            pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
            pf.line_spacing = spacing


def fit_one_page(doc) -> dict:
    """บีบท่อนแรกให้จบหน้าเดียว (ไม่ลดขนาดตัวอักษร)

    คืนผลการทำงานไว้ตรวจสอบ/ทดสอบ: {'before', 'after', 'budget', 'spacing', 'fitted'}
    spacing = None แปลว่าไม่ต้องบีบบรรทัดเลย (พอดีอยู่แล้ว หรือแค่ตัดช่องไฟก็พอ)
    """
    blocks = first_block(doc)
    budget = page_budget(doc)
    before = block_height(doc, blocks)
    used = (1.0, None)
    if before > budget:
        snap = _snapshot(blocks)
        for step in _STEPS:
            _apply(snap, *step)
            used = step
            if block_height(doc, blocks) <= budget:
                break
        else:
            # บีบจนสุดแล้วก็ยังไม่จบหน้าเดียว = เนื้อหายาวเกินหน้าจริง ๆ
            # คืนรูปแบบเดิม ดีกว่าปล่อยให้เอกสารแน่นโดยไม่ได้อะไรกลับมา
            _restore(snap)
            used = (1.0, None)
    return {"before": round(before, 1), "after": round(block_height(doc, blocks), 1),
            "budget": round(budget, 1), "gap_scale": used[0], "spacing": used[1],
            "fitted": block_height(doc, blocks) <= budget}
