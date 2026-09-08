# -*- coding: utf-8 -*-
"""
project_report_doc.py - รายงานผลการดำเนินงานโครงการ/กิจกรรม (Word พร้อมพิมพ์)

โครงสร้างยึดตามแบบฟอร์มรายงานจริงที่โรงเรียนใช้:
  บันทึกข้อความนำส่ง (เสนอหัวหน้าฝ่าย -> ผอ.) · คำนำ · สารบัญ
  ๑ ความเป็นมา · ๒ วัตถุประสงค์ · ๓ เป้าหมาย (ปริมาณ/คุณภาพ)
  ๔ ขั้นตอนการดำเนินงาน (ตาราง) · ๕ งบประมาณ (ตาราง) · ๖ การประเมินผล (ตาราง)
  ๗ ผลที่คาดว่าจะได้รับ · แบบประเมินความพึงพอใจ (เกณฑ์)
  ๘ สรุปผลการประเมิน (ตารางแบบสอบถาม + ตารางบรรลุวัตถุประสงค์) · ๙ ข้อเสนอแนะ
  ลงนาม · ภาคผนวก ภาพกิจกรรม

หัวข้อไหนไม่ได้กรอก จะไม่ขึ้นในเอกสาร และเลขข้อไล่ใหม่ให้เอง
"""
import io
import os
import tempfile

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE
from docx.shared import Cm, Pt

from app.services.build_templates import (
    _csize, _font, _hr, _krut_and_title, _no_borders, _p, _p_runs, _set_cell,
    _sign_table, THAI_FONT,
)
from app.services.doc_page import set_a4
from app.services.lunch_doc import _money, _save
from docx.enum.section import WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

from app.thai_utils import bahttext, thai_date

_DOT = "." * 110

# ขนาดฟอนต์หน้าปก (ผู้ใช้ขอ 20-22 pt)
_COVER_BIG, _COVER_SUB = 22, 20


def _bookmark(paragraph, name: str, bid: int):
    """คั่นย่อหน้าด้วย bookmark เพื่อให้สารบัญอ้างเลขหน้าได้ด้วยฟิลด์ PAGEREF"""
    st = OxmlElement("w:bookmarkStart")
    st.set(qn("w:id"), str(bid)); st.set(qn("w:name"), name)
    en = OxmlElement("w:bookmarkEnd"); en.set(qn("w:id"), str(bid))
    paragraph._p.insert(0, st)
    paragraph._p.append(en)


def _pageref(paragraph, name: str, size=16):
    """ใส่ฟิลด์ PAGEREF (Word คำนวณเลขหน้าจริงให้เอง) · ก่อนอัปเดตจะโชว์ '-' ไว้ก่อน"""
    def _r():
        r = OxmlElement("w:r")
        rpr = OxmlElement("w:rPr")
        for tag in ("w:rFonts",):
            f = OxmlElement(tag)
            f.set(qn("w:ascii"), THAI_FONT); f.set(qn("w:hAnsi"), THAI_FONT)
            f.set(qn("w:cs"), THAI_FONT)
            rpr.append(f)
        for tag in ("w:sz", "w:szCs"):
            e = OxmlElement(tag); e.set(qn("w:val"), str(int(size * 2))); rpr.append(e)
        r.append(rpr)
        return r
    begin = _r(); fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), "begin"); begin.append(fc)
    instr = _r(); it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve")
    it.text = " PAGEREF " + name + " " + chr(92) + "h "
    instr.append(it)
    sep = _r(); fc2 = OxmlElement("w:fldChar"); fc2.set(qn("w:fldCharType"), "separate"); sep.append(fc2)
    val = _r(); t = OxmlElement("w:t"); t.text = "-"; val.append(t)
    end = _r(); fc3 = OxmlElement("w:fldChar"); fc3.set(qn("w:fldCharType"), "end"); end.append(fc3)
    for e in (begin, instr, sep, val, end):
        paragraph._p.append(e)


def _update_fields_on_open(doc):
    """สั่งให้ Word คำนวณฟิลด์ (เลขหน้าในสารบัญ) ใหม่ทันทีที่เปิดไฟล์"""
    try:
        st = doc.settings.element
        if st.find(qn("w:updateFields")) is None:
            e = OxmlElement("w:updateFields"); e.set(qn("w:val"), "true")
            st.append(e)
    except Exception:
        pass


def _vcenter(section, on: bool = True):
    """จัดเนื้อหาของ section นี้ให้อยู่กึ่งกลางหน้าในแนวตั้ง (ใช้กับหน้าคั่นภาคผนวก)
    on=False : ปลดออก - จำเป็นเพราะ add_section คัดลอกค่าเดิมของ section ก่อนหน้ามาให้"""
    sectPr = section._sectPr
    v = sectPr.find(qn("w:vAlign"))
    if not on:
        if v is not None:
            sectPr.remove(v)
        return
    if v is None:
        v = OxmlElement("w:vAlign"); sectPr.append(v)
    v.set(qn("w:val"), "center")


def _txt(v) -> str:
    return (str(v).strip() if v is not None else "")


def _lst(raw) -> list:
    from app.routers.project_report import load_list
    return load_list(raw)


def _school_disp(school) -> str:
    """ชื่อโรงเรียนที่มีคำว่า "โรงเรียน" นำหน้าเสมอ (ชื่อที่กรอกไว้มีทั้งแบบมีและไม่มี)"""
    n = _txt(getattr(school, "name", ""))
    if not n:
        return "โรงเรียน......................................."
    return n if n.startswith("โรงเรียน") else f"โรงเรียน{n}"


def _office(school) -> str:
    return _school_disp(school)


def _director(school) -> str:
    """เช่น "ผู้อำนวยการโรงเรียนบ้านหินลาด" - ต่อชื่อโรงเรียนโดยไม่ให้คำว่าโรงเรียนซ้ำ"""
    pos = _txt(getattr(school, "director_position", "")) or "ผู้อำนวยการโรงเรียน"
    name = _school_disp(school)
    if not _txt(getattr(school, "name", "")):
        return pos
    if pos.endswith("โรงเรียน"):
        return pos[:-len("โรงเรียน")] + name
    return f"{pos} {name}"


def _period(rep) -> str:
    a, b = rep.date_start, rep.date_end
    if a and b:
        return thai_date(a) if a.date() == b.date() else f"{thai_date(a)} ถึง {thai_date(b)}"
    return thai_date(a or b) if (a or b) else ""


def _act_name(rep) -> str:
    return _txt(rep.title) or _txt(rep.project.name)


def _para_block(doc, text: str, *, size=16):
    """ข้อความหลายบรรทัด -> ย่อหน้าละบรรทัด เว้นหน้า 1.25 ซม. ตามแบบราชการ"""
    for line in _txt(text).splitlines():
        if line.strip():
            _p(doc, line.strip(), align="justify", indent=1.25, after=3, size=size)


def _num_list(doc, items, prefix: str):
    """รายการเป็นข้อ ๆ พร้อมเลขข้อย่อย เช่น 2.1 / 3.1.1"""
    for i, it in enumerate(items, 1):
        _p(doc, f"{prefix}{i}  {_txt(it)}", indent=1.25, after=3, size=16)


def _grid(doc, headers, rows, widths, *, aligns=None):
    """ตารางมีเส้น + หัวตารางตัวหนา · rows = list ของ list ข้อความ"""
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    for cell, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(cell, h, size=15, align="center", bold=True)
        cell.width = Cm(w)
    for r in rows:
        cells = t.add_row().cells
        for i, (cell, val) in enumerate(zip(cells, r)):
            _set_cell(cell, _txt(val), size=15,
                      align=(aligns[i] if aligns else "left"))
            cell.width = Cm(widths[i])
    _p(doc, "", size=8, after=0)
    return t


# ---------------- ๐ บันทึกข้อความนำส่ง ----------------
def _memo(doc, rep, school):
    act = _act_name(rep)
    prj = rep.project
    _krut_and_title(doc)
    _p_runs(doc, [("ส่วนราชการ  ", True), (_office(school), False)])
    _p_runs(doc, [("ที่  ", True), ("." * 45, False), ("\t", False),
                  ("วันที่ ", True), (thai_date(rep.date_end or rep.date_start), False)],
            tab_cm=8)
    subject = f"รายงานผลการดำเนินงาน{prj.name}"
    if _txt(rep.title) and _txt(rep.title) != _txt(prj.name):
        subject += f" {rep.title}"
    if prj.plan_year:
        from app.services.budget import plan_year_label
        subject += f" ประจำ{plan_year_label(school)} {prj.plan_year}"
    _p_runs(doc, [("เรื่อง  ", True), (subject, False)])
    _p_runs(doc, [("เรียน  ", True), (_director(school), False)])
    _hr(doc)

    body = _txt(rep.memo_body)
    if body:
        _para_block(doc, body)
    else:
        who = _txt(rep.responsible) or "ผู้รับผิดชอบโครงการ"
        when = _period(rep)
        _p(doc, f"ด้วย {who} {_school_disp(school)} ได้ดำเนินการ{prj.name}"
                f"{(' ' + act) if act != _txt(prj.name) else ''}"
                f"{(' ระหว่าง' + when) if when else ''} เรียบร้อยแล้ว",
           align="justify", indent=1.25, after=3)
    _p(doc, f"ทั้งนี้ จึงขอรายงานผลการดำเนินงาน{act} รายละเอียดตามเอกสารที่แนบมาพร้อมนี้",
       align="justify", indent=1.25, after=3)
    _p(doc, "จึงเรียนมาเพื่อโปรดทราบและพิจารณา", indent=1.25, before=6, after=10)

    _sign_table(doc, [[
        ("ลงชื่อ ...............................................", "center"),
        (f"( {_txt(rep.responsible) or '............................................'} )", "center"),
        (f"ตำแหน่ง {_txt(rep.responsible_pos) or 'ครู'}", "center"),
    ]], after=6)

    head = _txt(getattr(school, "academic_head_name", ""))
    _p(doc, "เสนอ  หัวหน้าฝ่ายบริหารงานวิชาการ", bold=True, before=6, after=4)
    _p(doc, _DOT, after=2); _p(doc, _DOT, after=8)
    _sign_table(doc, [[
        ("ลงชื่อ ...............................................", "center"),
        (f"( {head or '............................................'} )", "center"),
        ("หัวหน้าฝ่ายบริหารงานวิชาการ", "center"),
    ]], after=6)

    _p(doc, f"เสนอ  {_director(school)}", bold=True, before=6, after=4)
    _p(doc, _DOT, after=2); _p(doc, _DOT, after=8)
    _sign_table(doc, [[
        ("ลงชื่อ ...............................................", "center"),
        (f"( {_txt(school.director_name) or '............................................'} )", "center"),
        (_txt(getattr(school, "director_position", "")) or "ผู้อำนวยการโรงเรียน", "center"),
    ]], after=2)


# ---------------- ปก / คำนำ / สารบัญ ----------------
def _logo_path(school):
    """คืน path ชั่วคราวของโลโก้โรงเรียน (python-docx รับเฉพาะไฟล์/สตรีม) หรือ None"""
    data = getattr(school, "logo", None)
    if not data:
        return None
    ext = (getattr(school, "logo_ext", "") or "png").lstrip(".")
    fd, path = tempfile.mkstemp(suffix=f".{ext}")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    return path


def _cover(doc, rep, school, year_label):
    prj = rep.project
    logo = _logo_path(school)
    if logo:
        try:
            p = doc.add_paragraph(); p.alignment = 1
            p.paragraph_format.space_after = Pt(6)
            p.add_run().add_picture(logo, height=Cm(3.0))
        except Exception:
            pass
        finally:
            try:
                os.unlink(logo)
            except OSError:
                pass
    else:
        _p(doc, "", size=28, after=0)
    _p(doc, "รายงานผลการดำเนินงาน", align="center", bold=True, size=_COVER_BIG, before=12, after=6)
    _p(doc, _act_name(rep), align="center", bold=True, size=_COVER_BIG, after=4)
    if _txt(rep.title) and _txt(rep.title) != _txt(prj.name):
        _p(doc, f"ภายใต้{prj.name}", align="center", size=_COVER_SUB, after=4)
    if prj.plan_year:
        _p(doc, f"{year_label} {prj.plan_year}", align="center", size=_COVER_SUB, after=4)
    for _ in range(3):
        _p(doc, "", size=_COVER_SUB, after=0)
    if _txt(rep.responsible):
        _p(doc, "ผู้รับผิดชอบ", align="center", size=_COVER_SUB, after=4)
        _p(doc, rep.responsible, align="center", bold=True, size=_COVER_SUB, after=2)
        if _txt(rep.responsible_pos):
            _p(doc, rep.responsible_pos, align="center", size=_COVER_SUB, after=4)
    # ดันชื่อโรงเรียนไปอยู่ช่วงล่างของหน้า (แบบหน้าปกรายงานราชการ)
    for _ in range(6):
        _p(doc, "", size=_COVER_SUB, after=0)
    if _txt(school.name):
        _p(doc, _school_disp(school), align="center", bold=True, size=_COVER_SUB, after=4)
    if _txt(getattr(school, "area_office", "")):
        _p(doc, school.area_office, align="center", size=_COVER_SUB, after=2)


def _auto_preface(rep) -> str:
    """คำนำมาตรฐาน - เขียนจากข้อมูลที่กรอกไว้ (ไม่มีช่องให้กรอกเองแล้ว)
    ถ้าอยากได้ถ้อยคำอื่น แก้ได้ในไฟล์ Word ที่ดาวน์โหลดไป"""
    act, prj = _act_name(rep), rep.project
    objs = _lst(rep.objectives)
    lines = []
    first = f"รายงานฉบับนี้จัดทำขึ้นเพื่อรายงานผลการดำเนินงาน{act}"
    if act != _txt(prj.name):
        first += f" ภายใต้{prj.name}"
    if _period(rep):
        first += f" ซึ่งดำเนินการ{_period(rep)}"
    if objs:
        lead = objs[0] if objs[0].startswith("เพื่อ") else "เพื่อ" + objs[0]
        first += f" โดยมีวัตถุประสงค์{lead}"
        if len(objs) > 1:
            first += " และวัตถุประสงค์อื่นตามที่ระบุไว้ในรายงาน"
    lines.append(first)
    lines.append("รายงานฉบับนี้ประกอบด้วยความเป็นมา วัตถุประสงค์ เป้าหมาย ขั้นตอนการดำเนินงาน "
                 "งบประมาณ การประเมินผล สรุปผลการประเมิน และข้อเสนอแนะ "
                 "เพื่อใช้เป็นข้อมูลในการพัฒนาการจัดกิจกรรมในครั้งต่อไป")
    lines.append("ผู้จัดทำหวังเป็นอย่างยิ่งว่ารายงานฉบับนี้จะเป็นประโยชน์ต่อผู้ที่เกี่ยวข้องต่อไป")
    return "\n".join(lines)


def _preface(doc, rep, mark_fn=None):
    par = _p(doc, "คำนำ", align="center", bold=True, size=20, after=8)
    if mark_fn:
        mark_fn(par)
    _para_block(doc, _txt(rep.preface) or _auto_preface(rep))
    _p(doc, "", size=14, after=0)
    _p(doc, _txt(rep.responsible), align="right", after=1)
    if _txt(rep.responsible_pos):
        _p(doc, _txt(rep.responsible_pos), align="right", after=1)


def _contents(doc, heads):
    """สารบัญ - ตารางไม่มีเส้น + เลขหน้าจริง (ฟิลด์ PAGEREF ชี้ไป bookmark ของแต่ละหัวข้อ
    Word คำนวณเลขหน้าให้เองตอนเปิดไฟล์ เพราะตั้ง updateFields ไว้แล้ว)"""
    _p(doc, "สารบัญ", align="center", bold=True, size=20, after=10)
    t = doc.add_table(rows=1, cols=2)
    _no_borders(t)
    for cell, h, w, al in zip(t.rows[0].cells, ["เรื่อง", "หน้า"], [13.0, 3.0],
                              ["center", "center"]):
        _set_cell(cell, h, size=16, align=al, bold=True)
        cell.width = Cm(w)
    for name, h in heads:
        c = t.add_row().cells
        _set_cell(c[0], h, size=16); c[0].width = Cm(13.0)
        c[1].width = Cm(3.0)
        c[1].text = ""
        pp = c[1].paragraphs[0]
        pp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pp.paragraph_format.space_after = Pt(2)
        _pageref(pp, name, size=16)


# ---------------- เอกสารหลัก ----------------
def render_project_report(rep, school, doc=None) -> str:
    from app.routers.project_report import survey_level, survey_percent
    from app.services.budget import plan_year_label

    own = doc is None
    if own:
        doc = Document(); set_a4(doc); _font(doc)
    elif doc.paragraphs or doc.tables:
        doc.add_page_break()

    prj = rep.project
    year_label = plan_year_label(school)
    objectives = _lst(rep.objectives)
    t_qty, t_qual = _lst(rep.target_qty), _lst(rep.target_qual)
    steps, budgets = _lst(rep.steps_items), _lst(rep.budget_items)
    evals, obj_rows = _lst(rep.eval_items), _lst(rep.obj_results)
    survey_rows = _lst(rep.survey_items)
    expected = _lst(rep.expected)

    _memo(doc, rep, school)
    doc.add_page_break()
    _cover(doc, rep, school, year_label)
    doc.add_page_break()
    _preface(doc, rep, mark_fn=lambda par: _bookmark(par, "_rpt1", 99))

    # ---- ประกอบสารบัญจากหัวข้อที่มีจริง แล้วค่อยพิมพ์เนื้อหาด้วยเลขชุดเดียวกัน ----
    # สารบัญต้องตรงกับหัวข้อที่พิมพ์จริง จึงประกอบรายชื่อจากเงื่อนไขชุดเดียวกับด้านล่าง
    plan_raw = ["คำนำ"] + [t for cond, t in [
        (_txt(rep.principles), "ความเป็นมา"),
        (objectives, "วัตถุประสงค์"),
        (t_qty or t_qual, "เป้าหมาย"),
        (steps, "ขั้นตอนการดำเนินงาน"),
        (budgets or float(rep.budget_used or 0) or float(rep.budget_planned or 0), "งบประมาณ"),
        (evals, "การประเมินผล"),
        (expected, "ผลที่คาดว่าจะได้รับ"),
        (survey_rows or obj_rows, "สรุปผลการประเมิน"),
        (_txt(rep.suggestions), "ข้อเสนอแนะ"),
        ([ph for ph in (rep.photos or []) if ph.image], "ภาคผนวก (ภาพกิจกรรม)"),
    ] if cond]
    # ชื่อ bookmark ต้องคงที่ตลอดไฟล์ (สารบัญกับหัวข้อจริงใช้ชุดเดียวกัน)
    plan = [(f"_rpt{i}", t) for i, t in enumerate(plan_raw, 1)]
    marks = {t: n for n, t in plan}
    bid = [100]

    def mark(par, title):
        """ผูก bookmark ให้หัวข้อ เพื่อให้สารบัญอ้างเลขหน้าได้"""
        if title in marks:
            bid[0] += 1
            _bookmark(par, marks[title], bid[0])

    doc.add_page_break()
    _contents(doc, plan)
    doc.add_page_break()

    _p(doc, f"รายงานผลการดำเนินงาน{_act_name(rep)}", align="center", bold=True, size=19, after=8)
    n = 0

    def head(title):
        nonlocal n
        n += 1
        mark(_p(doc, f"{n}. {title}", bold=True, size=17, before=8, after=4), title)
        return n

    if _txt(rep.principles):
        head("ความเป็นมา")
        _para_block(doc, rep.principles)

    if objectives:
        i = head("วัตถุประสงค์")
        _num_list(doc, objectives, f"{i}.")

    if t_qty or t_qual:
        i = head("เป้าหมาย")
        sub = 0
        if t_qty:
            sub += 1
            _p(doc, f"{i}.{sub}  เป้าหมายเชิงปริมาณ", bold=True, indent=1.25, after=3)
            _num_list(doc, t_qty, f"{i}.{sub}.")
        if t_qual:
            sub += 1
            _p(doc, f"{i}.{sub}  เป้าหมายเชิงคุณภาพ", bold=True, indent=1.25, after=3)
            _num_list(doc, t_qual, f"{i}.{sub}.")

    if steps:
        head("ขั้นตอนการดำเนินงาน")
        _grid(doc, ["ที่", "กิจกรรม", "ระยะเวลา", "ผู้รับผิดชอบ"],
              [[str(k), r.get("act", ""), r.get("period", ""), r.get("who", "")]
               for k, r in enumerate(steps, 1)],
              [1.3, 7.0, 4.0, 4.0], aligns=["center", "left", "center", "left"])

    used = float(rep.budget_used or 0)
    if budgets or used or float(rep.budget_planned or 0):
        head("งบประมาณ")
        total = sum(_num(r.get("pay")) + _num(r.get("use")) + _num(r.get("mat"))
                    for r in budgets) if budgets else used
        _p(doc, f"งบประมาณ  จำนวน  {_money(total)}  บาท"
                f"{('  (' + _txt(rep.budget_note) + ')') if _txt(rep.budget_note) else ''}"
                + ("  จำแนกการใช้งบประมาณ ดังนี้" if budgets else ""),
           indent=1.25, after=5)
        if budgets:
            rows = []
            for k, r in enumerate(budgets, 1):
                s = _num(r.get("pay")) + _num(r.get("use")) + _num(r.get("mat"))
                rows.append([str(k), r.get("item", ""), _money(s) if s else "-",
                             _cell_money(r.get("pay")), _cell_money(r.get("use")),
                             _cell_money(r.get("mat"))])
            t = _grid(doc, ["ที่", "รายการ", "งบประมาณ", "ค่าตอบแทน", "ค่าใช้สอย", "ค่าวัสดุ"],
                      rows, [1.3, 6.0, 2.6, 2.2, 2.2, 2.2],
                      aligns=["center", "left", "right", "right", "right", "right"])
            c = t.add_row().cells
            _set_cell(c[0], "รวม", size=15, align="center", bold=True)
            _set_cell(c[1], bahttext(total) if total else "-", size=15, align="center", bold=True)
            c[1].merge(c[5])

    if evals:
        head("การประเมินผล")
        _grid(doc, ["ตัวบ่งชี้ความสำเร็จ", "วิธีการประเมิน", "เครื่องมือ"],
              [[r.get("indicator", ""), r.get("method", ""), r.get("tool", "")] for r in evals],
              [7.5, 4.4, 4.4])

    if expected:
        i = head("ผลที่คาดว่าจะได้รับ")
        _num_list(doc, expected, f"{i}.")

    if survey_rows:
        _p(doc, "แบบประเมินความพึงพอใจ", align="center", bold=True, size=18, before=10, after=4)
        _p(doc, "คำชี้แจง  โปรดใส่เครื่องหมาย (/) ตามรายการที่เป็นจริงหรือเห็นว่าเหมาะสม",
           indent=1.25, after=3)
        _p(doc, "เกณฑ์การประเมิน", bold=True, indent=1.25, after=3)
        for lv, word, rng in [(4, "ดีเยี่ยม", "สูงกว่า 81%"), (3, "ดี", "61 - 80%"),
                              (2, "พอใช้", "41 - 60%"), (1, "ปรับปรุง", "ต่ำกว่า 40%")]:
            _p(doc, f"ระดับ {lv} หมายถึง  {word}  ประเมินอยู่ในระดับ {rng}", indent=2.0, after=2)

    if survey_rows or obj_rows:
        i = head("สรุปผลการประเมิน")
        if survey_rows:
            rows = [[str(k), r.get("item", ""), _cell_int(r.get("n4")), _cell_int(r.get("n3")),
                     _cell_int(r.get("n2")), _cell_int(r.get("n1"))]
                    for k, r in enumerate(survey_rows, 1)]
            t = _grid(doc, ["ลำดับที่", "รายการประเมิน", "ระดับ 4", "ระดับ 3", "ระดับ 2", "ระดับ 1"],
                      rows, [1.8, 7.2, 1.9, 1.9, 1.9, 1.9],
                      aligns=["center", "left", "center", "center", "center", "center"])
            pct = survey_percent(survey_rows)
            c = t.add_row().cells
            _set_cell(c[0], "ผลรวมเฉลี่ย", size=15, align="center", bold=True)
            c[0].merge(c[1])
            _set_cell(c[2], f"ร้อยละ  {pct:.2f}" if pct is not None else "-",
                      size=15, align="center", bold=True)
            c[2].merge(c[5])
            if pct is not None:
                _p(doc, f"{i}.1  ผลการประเมินหลังการดำเนินงานโดยเฉลี่ยรวมอยู่ในระดับ "
                        f"{survey_level(pct)} คิดเป็นร้อยละ {pct:.2f}", indent=1.25, after=4)
        if obj_rows:
            _p(doc, f"{i}.{2 if survey_rows else 1}  สรุปผลการดำเนินงานตามวัตถุประสงค์",
               indent=1.25, after=4)
            t = doc.add_table(rows=1, cols=4)
            t.style = "Table Grid"
            for cell, h, w in zip(t.rows[0].cells, ["ที่", "วัตถุประสงค์", "บรรลุ", "ไม่บรรลุ"],
                                  [1.3, 10.4, 2.2, 2.2]):
                _set_cell(cell, h, size=15, align="center", bold=True)
                cell.width = Cm(w)
            for k, r in enumerate(obj_rows, 1):
                c = t.add_row().cells
                ok = bool(r.get("ok"))
                for cell, val, w, al in zip(c, [str(k), r.get("obj", ""), "/" if ok else "",
                                                "" if ok else "/"],
                                            [1.3, 10.4, 2.2, 2.2],
                                            ["center", "left", "center", "center"]):
                    _set_cell(cell, val, size=15, align=al)
                    cell.width = Cm(w)
            _p(doc, "", size=8, after=0)
        if _txt(rep.summary_note):
            _para_block(doc, rep.summary_note)

    if _txt(rep.suggestions):
        head("ข้อเสนอแนะ")
        _para_block(doc, rep.suggestions)

    # ---------------- ลงนาม ----------------
    _p(doc, "", size=14, after=0)
    _sign_table(doc, [
        [("ลงชื่อ ...............................................", "center"),
         (f"( {_txt(rep.responsible) or '..........................................'} )", "center"),
         ("ผู้รายงาน", "center")],
        [("ลงชื่อ ...............................................", "center"),
         (f"( {_txt(school.director_name) or '..........................................'} )", "center"),
         (_txt(getattr(school, "director_position", "")) or "ผู้อำนวยการโรงเรียน", "center")],
    ], after=2)

    # ---------------- ภาคผนวก ----------------
    photos = [ph for ph in (rep.photos or []) if ph.image]
    if photos:
        # หน้าคั่น "ภาคผนวก" = section ใหม่ที่จัดกลางหน้าในแนวตั้ง (vAlign=center)
        sec = doc.add_section(WD_SECTION.NEW_PAGE)
        _vcenter(sec)
        par = _p(doc, "ภาคผนวก", align="center", bold=True, size=40, after=8)
        mark(par, "ภาคผนวก (ภาพกิจกรรม)")
        _p(doc, "ภาพกิจกรรม", align="center", size=24, after=0)
        # หน้าถัดไปกลับมาชิดบนตามปกติ
        _vcenter(doc.add_section(WD_SECTION.NEW_PAGE), on=False)
        _p(doc, f"ภาพกิจกรรม{_act_name(rep)}", align="center", bold=True, size=18, after=10)
        _photo_grid(doc, photos)

    _update_fields_on_open(doc)

    return _save(doc, f"รายงานผลการดำเนินงาน_{_act_name(rep)}") if own else doc


def _num(v) -> float:
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _cell_money(v) -> str:
    return _money(_num(v)) if _num(v) else "-"


def _cell_int(v) -> str:
    n = _num(v)
    return str(int(n)) if n else "-"


def _photo_grid(doc, photos):
    """ตารางภาพ 2 คอลัมน์ · แต่ละภาพมีคำบรรยายใต้ภาพ (ภาพเสียข้ามไป ไม่ทำเอกสารพัง)"""
    t = doc.add_table(rows=0, cols=2)
    _no_borders(t)
    for i in range(0, len(photos), 2):
        pair = photos[i:i + 2]
        row = t.add_row()
        row.height = Cm(6.4)
        row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
        for j, cell in enumerate(row.cells):
            cell.width = Cm(8.0)
            cell.text = ""
            if j >= len(pair):
                continue
            ph = pair[j]
            p = cell.paragraphs[0]
            p.alignment = 1
            p.paragraph_format.space_after = Pt(2)
            try:
                p.add_run().add_picture(io.BytesIO(ph.image), width=Cm(7.4))
            except Exception:
                continue
            cap = _txt(ph.caption)
            if cap:
                cp = cell.add_paragraph()
                cp.alignment = 1
                cp.paragraph_format.space_after = Pt(10)
                r = cp.add_run(cap)
                _csize(r, 14)
                r.font.name = THAI_FONT
