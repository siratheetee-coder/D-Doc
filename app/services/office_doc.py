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
from docx.shared import Cm, Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH

from app.services.doc_page import set_a4

from app.database import get_data_dir
from app.thai_utils import thai_date, thai_date_official
from app.services.build_templates import (
    _font, _p, _p_runs, _krut_and_title, _krut_center, _sign_table, _hr,
    _no_borders, _set_cell, THAI_FONT,
)
from app.services.org_names import head_title


def _foot_line(par, text, size=15):
    """เพิ่มบรรทัดใน footer ด้วยฟอนต์ไทย (ชิดซ้าย)"""
    par.alignment = WD_ALIGN_PARAGRAPH.LEFT
    run = par.add_run(text)
    run.font.name = THAI_FONT
    run.font.size = Pt(size)
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(qn(a), THAI_FONT)


def _safe(text: str) -> str:
    from app.services.filenames import fit_name
    return fit_name(_safe_chars(text))


def _safe_chars(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _inline_to_anchor(inline, dy_emu):
    """แปลง <wp:inline> (รูปแบบไหลตามข้อความ) เป็น <wp:anchor> แบบ 'อยู่หน้าข้อความ'
    (behindDoc=0, wrapNone) จัดกึ่งกลางคอลัมน์ + เลื่อนแนวตั้ง dy_emu (ลบ = ขึ้น)"""
    drawing = inline.getparent()
    anchor = OxmlElement("wp:anchor")
    for k, v in (("distT", "0"), ("distB", "0"), ("distL", "0"), ("distR", "0"),
                 ("simplePos", "0"), ("relativeHeight", "251658240"), ("behindDoc", "0"),
                 ("locked", "0"), ("layoutInCell", "1"), ("allowOverlap", "1")):
        anchor.set(k, v)
    sp = OxmlElement("wp:simplePos"); sp.set("x", "0"); sp.set("y", "0"); anchor.append(sp)
    ph = OxmlElement("wp:positionH"); ph.set("relativeFrom", "column")
    al = OxmlElement("wp:align"); al.text = "center"; ph.append(al); anchor.append(ph)
    pv = OxmlElement("wp:positionV"); pv.set("relativeFrom", "paragraph")
    off = OxmlElement("wp:posOffset"); off.text = str(int(dy_emu)); pv.append(off); anchor.append(pv)
    # ย้ายลูก extent/effectExtent มาก่อน แล้วแทรก wrapNone ตามด้วย docPr/graphic (ลำดับตาม schema)
    for tag in ("wp:extent", "wp:effectExtent"):
        el = inline.find(qn(tag))
        if el is not None:
            anchor.append(el)
    anchor.append(OxmlElement("wp:wrapNone"))
    for tag in ("wp:docPr", "wp:cNvGraphicFramePr", "a:graphic"):
        el = inline.find(qn(tag))
        if el is not None:
            anchor.append(el)
    drawing.remove(inline)
    drawing.append(anchor)


def _float_signature(paragraph, signer_name, height_cm=1.45, dy_cm=-0.55):
    """ถ้าผู้ลงนามมีลายเซ็น -> วางรูปลายเซ็นแบบ 'อยู่หน้าข้อความ' ทับบนพารากราฟที่ระบุ
    (PNG โปร่งใส ลอยทับบรรทัด '(ลงชื่อ)' ไม่ดันข้อความ) คืน True ถ้าใส่แล้ว"""
    from app.services.signature import signature_path_for_current
    path = signature_path_for_current(signer_name)
    if not path:
        return False
    try:
        shape = paragraph.add_run().add_picture(path, height=Cm(height_cm))
        _inline_to_anchor(shape._inline, dy_cm * 360000)
        return True
    except Exception:
        return False


def _same(a, b) -> bool:
    return " ".join((a or "").split()) == " ".join((b or "").split()) and bool((a or "").strip())


def _sign_by(paragraph, signer, school, ap):
    """ลายเซ็นบนบรรทัดลงชื่อ: โรงเรียนที่เปิดส่ง ผอ. อนุมัติ ลายเซ็น ผอ. ขึ้นเฉพาะเมื่ออนุมัติแบบแปะลายเซ็นแล้ว
    (services/approval.py) ผู้ลงนามอื่น หรือโรงเรียนที่ไม่ได้เปิด ใช้แบบเดิม (แปะรูปจากทะเบียนบุคลากร)"""
    if ap["on"] and _same(signer, school.director_name):
        if ap["sig"]:
            from app.services.approval import _float_on_dots   # วางบนจุดไข่ปลา แบบเดียวกับเอกสารพัสดุ
            _float_on_dots(paragraph, ap["sig"])
        _acting_cell(paragraph, school, ap)
        return
    _float_signature(paragraph, signer)


def _acting_cell(paragraph, school, ap):
    """รักษาราชการแทน: ชื่อ/ตำแหน่งใต้ลายเซ็นในช่องเดียวกันเปลี่ยนเป็นผู้อนุมัติ"""
    from app.services.approval import _rewrite_acting, acting_name_for
    acting = acting_name_for(ap.get("a"))
    if not acting:
        return
    try:
        paras = paragraph._parent.paragraphs
    except AttributeError:
        return
    director = " ".join((school.director_name or "").split())
    for i, p in enumerate(paras):
        if _rewrite_acting(paras, i, p, director, acting):
            break


def _director_endorse(doc, school, ap):
    """บันทึกที่คนอื่นลงนามเสนอ ผอ.: อนุมัติในระบบแล้ว ต่อท้ายความเห็น ผอ. (☑ อนุมัติ + ลงนาม)"""
    from app.services.approval import acting_name_for
    a = ap["a"]
    _p(doc, f"ความเห็นของ{_director_office(school)}", after=2)
    _p(doc, "☑  อนุมัติ" + (f"   {a.comment}" if (a.comment or "").strip() else ""), after=8)
    tbl = _sign_table(doc, [[
        ("ลงชื่อ.........................................", "center"),
        (f"( {acting_name_for(a) or school.director_name or ''} )", "center"),
        (("รักษาราชการแทน" if acting_name_for(a) else "") + _director_office(school), "center"),
        (thai_date(a.decided_at) if a.decided_at else "", "center"),
    ]])
    if ap["sig"]:
        from app.services.approval import _float_on_dots
        _float_on_dots(tbl.rows[0].cells[0].paragraphs[0], ap["sig"])


def _ap(kind, rid):
    from app.services.approval import lookup_current
    return lookup_current(kind, rid)


def _save_doc(doc, fname: str) -> str:
    """บันทึก .docx ลง data/documents; ถ้าเขียนไม่ได้ (path/permission บนเซิร์ฟเวอร์)
    ใช้โฟลเดอร์ชั่วคราวของระบบแทน แล้วคืน path (เสิร์ฟจากหน่วยความจำภายหลัง)"""
    import tempfile
    try:
        out_dir = get_data_dir() / "documents"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / fname
        _finish_before_save(doc)
        doc.save(str(out_path))
        return str(out_path)
    except OSError:
        out_path = Path(tempfile.gettempdir()) / fname
        _finish_before_save(doc)
        doc.save(str(out_path))
        return str(out_path)


def _school_office(school) -> str:
    parts = [school.name or "", school.address or ""]
    return "  ".join(p for p in parts if p).strip()


def _director_office(school) -> str:
    return head_title(school)


def _body_paragraphs(doc, body: str, indent=1.25):
    """แตกเนื้อหาเป็นย่อหน้า (เว้นบรรทัด = ย่อหน้าใหม่) จัดชิดขอบแบบไทย เยื้องบรรทัดแรก"""
    for line in (body or "").split("\n"):
        line = line.strip()
        if line:
            _p(doc, line, align="justify", indent=indent, after=2)


# ---- ระยะแบบหนังสือราชการ (หนังสือภายนอก/คำสั่ง/หนังสือรับรอง) ----
GOV_INDENT = 2.5   # ย่อหน้า และระยะเยื้องขวาของบล็อกลงชื่อ


def _gov_page(doc):
    """ขอบซ้าย 3 ขวา 2 ซม. ขอบบนแคบให้ครุฑ (3 ซม.) อยู่ใกล้ขอบบน แบบหนังสือราชการตัวอย่าง"""
    for sec in doc.sections:
        sec.left_margin, sec.right_margin = Cm(3.0), Cm(2.0)
        sec.top_margin, sec.bottom_margin = Cm(1.5), Cm(2.0)


def _shift(p, cm=GOV_INDENT):
    """จัดกึ่งกลางแต่เยื้องขวา (ใส่ย่อหน้าบรรทัดแรกให้บรรทัดที่จัดกลาง) แบบคำลงท้าย/ลงชื่อในหนังสือราชการ"""
    p.paragraph_format.first_line_indent = Cm(cm)
    return p


def _shift_table(tbl, cm=GOV_INDENT):
    for row in tbl.rows:
        for c in row.cells:
            for p in c.paragraphs:
                _shift(p, cm)


def render_memo(memo, school) -> str:
    """สร้างไฟล์ .docx บันทึกข้อความ คืนค่าที่อยู่ไฟล์"""
    doc = Document(); set_a4(doc)
    _font(doc)
    _krut_and_title(doc)   # ครุฑ + "บันทึกข้อความ"

    _p_runs(doc, [("ส่วนราชการ  ", True), (memo.from_dept or _school_office(school), False)])
    _p_runs(doc, [("ที่  ", True), (memo.memo_no or "", False),
                  ("\t", False), ("วันที่ ", True), (thai_date(memo.date), False)], tab_cm=7)
    _p_runs(doc, [("เรื่อง  ", True), (memo.subject or "", False)])
    _p_runs(doc, [("เรียน  ", True), (memo.to_person or _director_office(school), False)])
    _hr(doc)
    _body_paragraphs(doc, memo.body)

    # ลงนาม
    _p(doc, "", after=12)
    signer = (memo.signer_name or school.director_name or "")
    position = (memo.signer_position or _director_office(school))
    tbl = _sign_table(doc, [[
        ("ลงชื่อ.........................................", "center"),
        (f"( {signer} )", "center"),
        (position, "center"),
    ]])
    ap = _ap("memo", memo.id)
    _sign_by(tbl.rows[0].cells[0].paragraphs[0], signer, school, ap)
    if ap["a"] and not _same(signer, school.director_name):
        _director_endorse(doc, school, ap)

    fname = _safe(f"บันทึกข้อความ_{memo.memo_no or memo.id}_{memo.subject}") + ".docx"
    return _save_doc(doc, fname)


def render_order(order, school) -> str:
    """สร้างไฟล์ .docx คำสั่งโรงเรียน คืนค่าที่อยู่ไฟล์"""
    doc = Document(); set_a4(doc)
    _font(doc)
    _gov_page(doc)
    _krut_center(doc, height_cm=3.0)
    _p(doc, "คำสั่ง" + (school.name or ""), align="center", bold=True, size=18, after=0)
    _p(doc, "ที่ " + (order.order_no or ""), align="center", bold=True, after=0)
    _p(doc, "เรื่อง " + (order.subject or ""), align="center", bold=True, after=0)
    _p(doc, "─────────────────────", align="center", after=6)

    _body_paragraphs(doc, order.body, indent=GOV_INDENT)

    _p(doc, "", after=6)
    _shift(_p(doc, "สั่ง ณ วันที่ " + thai_date_official(order.date), align="center", after=12))
    sign_p = _shift(_p(doc, "(ลงชื่อ).........................................", align="center"))
    _sign_by(sign_p, school.director_name, school, _ap("order", order.id))
    _shift(_p(doc, f"( {school.director_name or ''} )", align="center"))
    _shift(_p(doc, _director_office(school), align="center"))

    fname = _safe(f"คำสั่ง_{order.order_no or order.id}_{order.subject}") + ".docx"
    return _save_doc(doc, fname)


_BLANK = ".........................................."


def render_official_letter(letter, school) -> str:
    """สร้างไฟล์ .docx หนังสือราชการภายนอก (ครุฑกลาง + ขอแสดงความนับถือ) คืนค่าที่อยู่ไฟล์"""
    doc = Document(); set_a4(doc)
    _font(doc)
    _gov_page(doc)

    # ครุฑ 3 ซม. กลาง แล้วบรรทัด ที่ (ซ้าย) กับส่วนราชการ (ขวา) เริ่มระดับเดียวกันใต้ครุฑ
    # บล็อกส่วนราชการชิดซ้ายในตัวเอง ทุกบรรทัดเริ่มแนวเดียวกัน ยาวลงด้านล่างได้
    _krut_center(doc, height_cm=3.0)
    t = doc.add_table(rows=1, cols=2)
    _no_borders(t)
    t.autofit = False
    left, rightc = t.rows[0].cells
    left.width, rightc.width = Cm(10.0), Cm(6.0)
    _set_cell(left, "ที่  " + (letter.doc_no or _BLANK), align="left", size=16)
    lines = [school.name or ""] + [x for x in (school.address or "").split(chr(10)) if x.strip()]
    _set_cell(rightc, lines[0], align="left", size=16)
    for x in lines[1:]:
        p = rightc.add_paragraph(); r = p.add_run(x.strip()); r.font.size = Pt(16)
    for p in rightc.paragraphs:
        p.paragraph_format.space_after = Pt(0)

    _p(doc, "วันที่ " + thai_date_official(letter.date), align="center", after=4)
    # หัวเรื่องในตัวอย่างหนังสือราชการไม่เป็นตัวหนา
    _p_runs(doc, [("เรื่อง  ", False), (letter.subject or _BLANK, False)])
    _p_runs(doc, [("เรียน  ", False), (letter.to or _BLANK, False)])
    if (letter.ref or "").strip():
        _p_runs(doc, [("อ้างถึง  ", False), (letter.ref, False)])
    if (letter.enclosure or "").strip():
        _p_runs(doc, [("สิ่งที่ส่งมาด้วย  ", False), (letter.enclosure, False)])

    _p(doc, "", after=4)
    _body_paragraphs(doc, letter.body, indent=GOV_INDENT)

    # คำลงท้าย + ลงนาม: กึ่งกลางแต่เยื้องขวาตามย่อหน้า
    _p(doc, "", after=8)
    _shift(_p(doc, letter.closing or "ขอแสดงความนับถือ", align="center", after=10))
    signer = (letter.signer_name or school.director_name or "")
    position = (letter.signer_position or _director_office(school))
    tbl = _sign_table(doc, [[
        ("(ลงชื่อ).........................................", "center"),
        (f"( {signer} )", "center"),
        (position, "center"),
    ]])
    _shift_table(tbl)
    _sign_by(tbl.rows[0].cells[0].paragraphs[0], signer, school, _ap("letter", letter.id))

    # ส่วนราชการเจ้าของเรื่อง + เบอร์โทร -> ตรึงไว้ท้ายหน้า (footer)
    foot = doc.sections[0].footer
    foot.is_linked_to_previous = False
    _foot_line(foot.paragraphs[0] if foot.paragraphs else foot.add_paragraph(),
               school.name or "")
    _foot_line(foot.add_paragraph(), "โทร. ........................................")

    fname = _safe(f"หนังสือราชการ_{letter.doc_no or letter.id}_{letter.subject}") + ".docx"
    return _save_doc(doc, fname)


def _finish_before_save(doc):
    """เว้นที่ให้เซ็น + พยายามให้จบหน้าเดียว (ดู page_fit.finish_doc)"""
    try:
        from app.services.page_fit import finish_doc
        finish_doc(doc)
    except Exception:
        pass
    try:
        from app.services.approval import refit_signatures   # ระยะเว้นเปลี่ยนหลังวางลายเซ็น ผอ.
        refit_signatures(doc)
    except Exception:
        pass
