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
from app.thai_utils import bahttext, thai_date

_DOT = "." * 110


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
    _p(doc, "รายงานผลการดำเนินงาน", align="center", bold=True, size=26, before=12, after=4)
    _p(doc, _act_name(rep), align="center", bold=True, size=22, after=2)
    if _txt(rep.title) and _txt(rep.title) != _txt(prj.name):
        _p(doc, f"ภายใต้{prj.name}", align="center", size=18, after=2)
    if prj.plan_year:
        _p(doc, f"{year_label} {prj.plan_year}", align="center", size=18, after=2)
    _p(doc, "", size=20, after=0)
    if _txt(rep.responsible):
        _p(doc, "ผู้รับผิดชอบ", align="center", size=17, after=2)
        _p(doc, rep.responsible, align="center", bold=True, size=18, after=1)
        if _txt(rep.responsible_pos):
            _p(doc, rep.responsible_pos, align="center", size=16, after=2)
    _p(doc, "", size=20, after=0)
    if _txt(school.name):
        _p(doc, _school_disp(school), align="center", bold=True, size=18, after=2)
    if _txt(getattr(school, "area_office", "")):
        _p(doc, school.area_office, align="center", size=16, after=1)


def _preface(doc, rep):
    if not _txt(rep.preface):
        return
    _p(doc, "คำนำ", align="center", bold=True, size=20, after=8)
    _para_block(doc, rep.preface)
    _p(doc, "", size=14, after=0)
    _p(doc, _txt(rep.responsible), align="right", after=1)
    if _txt(rep.responsible_pos):
        _p(doc, _txt(rep.responsible_pos), align="right", after=1)


def _contents(doc, heads):
    """สารบัญ - ไม่ใส่เลขหน้า (Word คำนวณให้ไม่ได้ตอนสร้าง) เว้นจุดไข่ปลาให้เขียนเอง"""
    _p(doc, "สารบัญ", align="center", bold=True, size=20, after=8)
    t = doc.add_table(rows=1, cols=2)
    t.style = "Table Grid"
    for cell, h, w in zip(t.rows[0].cells, ["เรื่อง", "หน้า"], [13.0, 3.0]):
        _set_cell(cell, h, size=16, align="center", bold=True)
        cell.width = Cm(w)
    for h in heads:
        c = t.add_row().cells
        _set_cell(c[0], h, size=16); c[0].width = Cm(13.0)
        _set_cell(c[1], "", size=16, align="center"); c[1].width = Cm(3.0)


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
    if _txt(rep.preface):
        doc.add_page_break()
        _preface(doc, rep)

    # ---- ประกอบสารบัญจากหัวข้อที่มีจริง แล้วค่อยพิมพ์เนื้อหาด้วยเลขชุดเดียวกัน ----
    # สารบัญต้องตรงกับหัวข้อที่พิมพ์จริง จึงประกอบรายชื่อจากเงื่อนไขชุดเดียวกับด้านล่าง
    plan = [t for cond, t in [
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

    doc.add_page_break()
    _contents(doc, plan)
    doc.add_page_break()

    _p(doc, f"รายงานผลการดำเนินงาน{_act_name(rep)}", align="center", bold=True, size=19, after=8)
    n = 0

    def head(title):
        nonlocal n
        n += 1
        _p(doc, f"{n}. {title}", bold=True, size=17, before=8, after=4)
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
        doc.add_page_break()
        _p(doc, "ภาคผนวก", align="center", bold=True, size=22, before=90, after=4)
        _p(doc, "ภาพกิจกรรม", align="center", bold=True, size=18, after=0)
        doc.add_page_break()
        _p(doc, f"ภาพกิจกรรม{_act_name(rep)}", align="center", bold=True, size=18, after=10)
        _photo_grid(doc, photos)

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
