# -*- coding: utf-8 -*-
"""
finance_doc.py
--------------
สร้างไฟล์ Word "บันทึกข้อความ ขออนุมัติเบิกจ่ายเงินนอกงบประมาณ" (DisburseMemo)
ตามแบบมาตรฐานราชการ: เนื้อความ + รายละเอียดการคำนวณเงิน + บล็อกอนุมัติของผู้อำนวยการ
ใช้ helper จัดรูปแบบร่วมกับ build_templates (ฟอนต์ TH Sarabun, ครุฑ, ตัวหนา complex script)
"""
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from app.services.doc_page import set_a4

from app.database import get_data_dir
from app.thai_utils import thai_date, bahttext
from app.services.build_templates import (
    _font, _p, _p_runs, _krut_and_title, _sign_table, _hr,
)
from app.services.org_names import head_title


def _safe(text: str) -> str:
    from app.services.filenames import fit_name
    return fit_name(_safe_chars(text))


def _safe_chars(text: str) -> str:
    for ch in '<>:"/\\|?*':
        text = text.replace(ch, "_")
    return text.strip()


def _school_office(school) -> str:
    parts = [school.name or "", school.address or ""]
    return "  ".join(p for p in parts if p).strip()


def _director_office(school) -> str:
    return head_title(school)


_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
           "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def _fmt(v) -> str:
    return "{:,.2f}".format(float(v or 0))


def _no_borders(table):
    tbl = table._tbl
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), "none")
        borders.append(e)
    tbl.tblPr.append(borders)


def _set_cell(cell, text, *, bold=False, align="left", size=16):
    cell.text = ""
    p = cell.paragraphs[0]
    p.alignment = {"left": WD_ALIGN_PARAGRAPH.LEFT, "center": WD_ALIGN_PARAGRAPH.CENTER,
                   "right": WD_ALIGN_PARAGRAPH.RIGHT}[align]
    p.paragraph_format.space_after = Pt(1)
    r = p.add_run(text)
    r.bold = bold
    r.font.size = Pt(size)
    r.font.name = "TH Sarabun New"
    r._element.rPr.rFonts.set(qn("w:cs"), "TH Sarabun New")


def _amt(v) -> str:
    """ตัวเลขในตารางบันทึกขอเบิก ตามแบบที่โรงเรียนใช้: ศูนย์เป็น - จำนวนเต็มไม่มีทศนิยม"""
    v = round(float(v or 0), 2)
    if not v:
        return "-"
    return "{:,.0f}".format(v) if v == int(v) else "{:,.2f}".format(v)


def _money_breakdown(doc, lines, bold_last=True, indent_cm=0):
    """ตารางไร้เส้น 3 คอลัมน์: ป้ายกำกับ | จำนวนเงิน(ชิดขวา) | บาท/คำอ่าน"""
    table = doc.add_table(rows=len(lines), cols=3)
    _no_borders(table)
    table.autofit = False
    widths = [Cm(6.5), Cm(3.5), Cm(6.5)]
    if indent_cm:      # ย่อเข้ามาแบบบันทึกขอเบิกของโรงเรียน
        widths = [Cm(6.5), Cm(3.0), Cm(2.0)]
        ind = OxmlElement("w:tblInd")
        ind.set(qn("w:w"), str(int(indent_cm * 567))); ind.set(qn("w:type"), "dxa")
        table._tbl.tblPr.append(ind)
    for i, (label, amount, tail) in enumerate(lines):
        cells = table.rows[i].cells
        bold = bold_last and (i == len(lines) - 1)
        _set_cell(cells[0], label, bold=bold, align="left")
        _set_cell(cells[1], amount, bold=bold, align="right")
        _set_cell(cells[2], tail, bold=bold, align="left")
        for c, w in zip(cells, widths):
            c.width = w
    return table


def _disburse_project_name(memo):
    """Resolve the selected project, then the linked procurement's project."""
    from sqlalchemy.orm import object_session
    from app.models import Project, Procurement
    db = object_session(memo)
    if db is not None:
        project = db.get(Project, memo.project_id) if memo.project_id else None
        if project and (project.name or '').strip():
            return project.name.strip()
        procurement = db.get(Procurement, memo.procurement_id) if memo.procurement_id else None
        if procurement:
            project = db.get(Project, procurement.project_id) if procurement.project_id else None
            name = (project.name if project else '') or procurement.project_name
            if (name or '').strip():
                return name.strip()
    # Preserve the previous free-text behavior for unlinked legacy memos.
    return (memo.note or '').strip()


def render_disburse(memo, school) -> str:
    """สร้างไฟล์ .docx บันทึกข้อความขออนุมัติเบิกจ่ายเงินนอกงบประมาณ คืนค่าที่อยู่ไฟล์
    ผอ. อนุมัติในระบบแล้ว ติ๊ก ☑ อนุมัติ + แปะลายเซ็น (services/approval.py)"""
    from app.services.staff import school_for
    school = school_for(memo, school)
    path = _render_disburse(memo, school)
    from app.services.approval import stamp_current
    stamp_current("disburse", memo.id, path, school.director_name or "")
    return path


def _render_disburse(memo, school) -> str:
    doc = Document(); set_a4(doc)
    _font(doc)
    _krut_and_title(doc)   # ครุฑ + "บันทึกข้อความ"

    amount = float(memo.amount or 0)
    vat = float(memo.vat or 0)
    wht = float(memo.wht or 0)
    fine = float(memo.fine or 0)
    goods = round(amount - vat, 2)
    net = round(amount - wht - fine, 2)
    from sqlalchemy.orm import object_session
    from app.services import disburse_split as splits
    db = object_session(memo)
    split_rows = splits.rows_of(db, memo) if db is not None and splits.is_split(memo) else []
    src = (memo.budget_source or " และ ".join(r["account_name"] for r in split_rows)
           or (memo.account.name if memo.account else "") or "เงินอุดหนุน")
    kind = memo.proc_kind or "จัดซื้อ"
    payee = memo.payee or "..............................."
    project_name = _disburse_project_name(memo)

    office = " ".join(x for x in [(school.name or "").strip(), (getattr(school, "area_office", "") or "").strip()] if x)
    _p_runs(doc, [("ส่วนราชการ  ", True), (office or _school_office(school), False)])
    _p_runs(doc, [("ที่  ", True), (memo.memo_no or "....................................", False),
                  ("\t", False), ("วันที่ ", True), (thai_date(memo.date), False)], tab_cm=8)
    _p_runs(doc, [("เรื่อง  ", True),
                  (f"ขออนุมัติเบิกจ่ายเงิน ประเภท{src}", False)])
    _p_runs(doc, [("เรียน  ", True), (_director_office(school), False)])
    _hr(doc)

    if kind == "ค่าใช้จ่ายอื่น":
        # ค่าเดินทาง ค่าตอบแทน ค่าอาหาร ฯลฯ ไม่ใช่การจัดซื้อจัดจ้าง: ไม่อ้างผู้ขาย/ใบกำกับภาษี/ระเบียบพัสดุ
        _p(doc,
           f"ตามที่{school.name or 'โรงเรียน'} ได้ดำเนินการโครงการ/กิจกรรม"
           f"{(' ' + project_name) if project_name else '..............................'} "
           f"โดยมีค่าใช้จ่ายเป็น{memo.subject or '..............................'} "
           f"จ่ายให้ {payee} จำนวนเงิน {_fmt(amount)} บาท ({bahttext(amount)}) "
           f"(รายละเอียดตามหลักฐานการจ่ายที่แนบ) และในการนี้โรงเรียนขอใช้เงินประเภท{src} นั้น",
           align="justify", indent=1.25, after=2)
        _p(doc, "เห็นสมควรเบิกจ่ายให้แก่ผู้มีสิทธิ์รับเงิน ตามหลักฐานที่แนบ โดยมีรายละเอียดดังนี้",
           align="justify", indent=1.25, after=2)
        _money_breakdown(doc, [
            ("จำนวนเงินขอเบิก", _amt(amount), "บาท"),
            ("หัก ภาษี ณ ที่จ่าย", _amt(wht), "บาท"),
            ("คงเหลือจ่ายจริง", _amt(net), "บาท"),
        ], bold_last=False, indent_cm=2.5)
    else:
        _disburse_purchase_body(doc, school, memo, kind, project_name, payee, src,
                                amount, vat, goods, wht, fine, net)
    if split_rows:
        _split_sources(doc, split_rows, wht, fine)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติ", indent=2.5, before=4, after=6)
    _disburse_tail(doc, school, memo, net)
    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    fname = _safe(f"ขออนุมัติเบิกจ่าย_{memo.memo_no or memo.id}_{memo.subject}") + ".docx"
    out_path = out_dir / fname
    doc.save(str(out_path))
    return str(out_path)


def _split_sources(doc, rows, wht, fine):
    """แหล่งเงินเมื่อแยกจ่ายหลายบัญชี บอกแต่ละบัญชีจ่ายเท่าไร หักภาษีเท่าไร (แบ่งตามสัดส่วนยอดเงิน)"""
    _p(doc, "โดยเบิกจ่ายจากแหล่งเงิน ดังนี้", indent=1.25, before=4, after=2)
    for i, r in enumerate(rows, 1):
        text = f"{i}. {r['name']} จำนวน {_fmt(r['amount'])} บาท"
        if wht:
            text += f" หักภาษี ณ ที่จ่าย {_fmt(r['wht'])} บาท"
        if fine:
            text += f" ค่าปรับ {_fmt(r['fine'])} บาท"
        if wht or fine:
            text += f" คงเหลือจ่ายจริง {_fmt(r['net'])} บาท"
        _p(doc, text, indent=1.25, after=0)


def _disburse_purchase_body(doc, school, memo, kind, project_name, payee, src, amount, vat, goods, wht, fine, net):
    # ย่อหน้านำตามแบบโรงเรียน: ด้วยฝ่าย... จัดซื้อ/จัดจ้าง ... เพื่อใช้โครงการ... กิจกรรม... ราคา...
    hire = kind == "จัดจ้าง"
    dept, activity = _disburse_dept_activity(memo)
    runs = [("ด้วย", False), (dept or "ฝ่าย..............................", bool(dept)),
            (f"  {kind}{(memo.subject or '').strip()}  เพื่อใช้", False),
            (project_name or "โครงการ..............................", bool(project_name))]
    if activity:
        runs += [(" กิจกรรม", False), (activity, True)]
    runs.append((f"  ราคา {_amt(amount)} บาท ({bahttext(amount)})", False))
    _p_runs(doc, runs, indent=1.25, align="justify", after=2)
    _p(doc,
       f"บัดนี้ {'ผู้รับจ้าง' if hire else 'ผู้ขาย'}  ได้ส่งมอบ{'งาน' if hire else 'พัสดุ'}ถูกต้องครบถ้วนแล้ว  "
       "ตามระเบียบกระทรวงการคลังว่าด้วยการจัดซื้อจัดจ้างและการบริหารพัสดุภาครัฐ พ.ศ. 2560",
       align="justify", indent=1.25, after=2)
    _p(doc, (f"เห็นสมควรเบิกจ่ายให้แก่{'ผู้รับจ้าง' if hire else 'ผู้ขาย'}  "
             f"ตาม{'ใบสั่งจ้างหรือสัญญาจ้าง' if hire else 'ใบสั่งซื้อหรือสัญญาซื้อขาย'}  โดยมีรายละเอียดดังนี้"),
       align="justify", indent=1.25, after=2)

    _money_breakdown(doc, [
        ("จำนวนเงินขอเบิก", _amt(amount), "บาท"),
        ("รวมราคา", _amt(goods), "บาท"),
        ("ค่าภาษีมูลค่าเพิ่ม", _amt(vat), "บาท"),
        ("จำนวนเงินรวมทั้งสิ้น", _amt(amount), "บาท"),
        ("หัก ภาษี ณ ที่จ่าย", _amt(wht), "บาท"),
        ("ค่าปรับ", _amt(fine), "บาท"),
        ("คงเหลือจ่ายจริง", _amt(net), "บาท"),
    ], bold_last=False, indent_cm=2.5)


def _disburse_dept_activity(memo):
    """ฝ่ายที่ขอ (จากเรื่องจัดซื้อ หรือผู้รับผิดชอบโครงการ) และชื่อกิจกรรม"""
    from sqlalchemy.orm import object_session
    from app.models import Procurement, Project, ProjectActivity
    db = object_session(memo)
    if db is None:
        return "", ""
    proc = db.get(Procurement, memo.procurement_id) if memo.procurement_id else None
    project = db.get(Project, memo.project_id) if memo.project_id else None
    if project is None and proc is not None and proc.project_id:
        project = db.get(Project, proc.project_id)
    dept = ((proc.department if proc else "") or (project.responsible if project else "") or "").strip()
    act_id = memo.activity_id or (proc.activity_id if proc else None)
    act = db.get(ProjectActivity, act_id) if act_id else None
    return dept, ((act.name if act else "") or "").strip()


def _disburse_tail(doc, school, memo, net):
    # ลงนามเจ้าหน้าที่การเงิน
    fin = (school.finance_officer_name or school.officer_name or "").strip()
    d = memo.date
    when = f"{d.day}/{_MONTHS[d.month]}/{d.year + 543}" if d else "......../................/........"
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ......................................", "center"),
        (f"({fin})" if fin else "(......................................)", "center"),
        ("เจ้าหน้าที่การเงิน", "center"),
        (when, "center"),
    ]], gap=False)

    # ความเห็นของผู้อำนวยการ
    _p(doc, f"ความเห็นของ{_director_office(school)}", indent=0.5, before=6, after=2)
    _p(doc, "☐  อนุมัติ          ☐  ไม่อนุมัติ", indent=1.0, after=4)
    director = (school.director_name or "").strip()
    _sign_table(doc, [[("", "center")], [
        ("ลงชื่อ ......................................", "center"),
        (f"({director})" if director else "(......................................)", "center"),
        (_director_office(school), "center"),
        (when, "center"),
    ]], gap=False)
