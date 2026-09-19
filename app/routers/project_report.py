# -*- coding: utf-8 -*-
"""
project_report.py - รายงานผลการดำเนินงานโครงการ/กิจกรรม

ผูกกับหน้า "โครงการ/แผนงบ" (/projects) · 1 โครงการรายงานได้หลายครั้ง (แยกรายกิจกรรม)
โครงสร้างหัวข้อยึดตามแบบฟอร์มรายงานจริงของโรงเรียน (บันทึกข้อความนำส่ง -> คำนำ -> สารบัญ
-> ๑ ความเป็นมา ... ๙ ข้อเสนอแนะ -> ภาคผนวกภาพกิจกรรม)

เส้นทางรายงานใช้ /project-reports/... แยกจาก /projects/{pid:int}
เพราะ path param เป็น int ถ้าใช้ /projects/reports จะกลายเป็น 422 ไม่ตกมาที่ route นี้
"""
import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Person, Project, ProjectReport
from app.templating import templates
from app.thai_utils import parse_be_date

router = APIRouter()

# ช่องข้อความยาว (textarea เดี่ยว)
# memo_body / preface ไม่มีช่องกรอกในฟอร์มแล้ว - เอกสารเขียนให้อัตโนมัติ
TEXT_FIELDS = ["principles", "suggestions", "summary_note", "std_ref"]

# รายการเป็นข้อ ๆ : ชื่อคอลัมน์ -> ชื่อ input ในฟอร์ม (ส่งมาหลายค่าชื่อเดียวกัน)
LIST_FIELDS = ["objectives", "target_qty", "target_qual", "expected"]

# ตาราง: คอลัมน์ในโมเดล -> คีย์ของแต่ละแถว (ชื่อ input = "<field>_<key>")
TABLE_FIELDS = {
    "steps_items":  ["act", "period", "who"],
    "budget_items": ["item", "pay", "use", "mat"],
    "eval_items":   ["indicator", "method", "tool"],
    "survey_items": ["item", "n4", "n3", "n2", "n1"],
    "obj_results":  ["obj", "ok"],
}


# ---------------- helper อ่าน/เขียน JSON ----------------
def load_list(raw) -> list:
    """อ่านคอลัมน์ JSON · ถ้าเป็นข้อความเก่าจากเวอร์ชันก่อน ให้ตัดเป็นบรรทัด (ข้อมูลไม่หาย)"""
    raw = (raw or "").strip()
    if not raw:
        return []
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else []
    except (ValueError, TypeError):
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]


def _dump(v) -> str:
    return json.dumps(v, ensure_ascii=False)


def _to_float(v, d=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return d


def survey_percent(rows) -> float | None:
    """ร้อยละความพึงพอใจ = คะแนนที่ได้ / คะแนนเต็ม (4 x จำนวนผู้ตอบทั้งหมด) x 100
    คืน None ถ้ายังไม่มีใครตอบ (จะได้ไม่โชว์ 0.00% ให้เข้าใจผิด)"""
    got = full = 0.0
    for r in rows:
        n = [_to_float(r.get(f"n{k}", 0)) for k in (4, 3, 2, 1)]
        got += n[0] * 4 + n[1] * 3 + n[2] * 2 + n[3] * 1
        full += sum(n) * 4
    return round(got * 100.0 / full, 2) if full else None


def survey_level(pct) -> str:
    """ระดับตามเกณฑ์ 4 ระดับในแบบประเมิน (>81 ดีเยี่ยม · 61-80 ดี · 41-60 พอใช้ · ต่ำกว่า 40 ปรับปรุง)"""
    if pct is None:
        return ""
    return ("ดีเยี่ยม" if pct > 80 else "ดี" if pct > 60 else "พอใช้" if pct > 40 else "ปรับปรุง")


def _get(db, rid):
    return db.get(ProjectReport, rid)


# ---------------- สร้าง / ลบ ----------------
@router.post("/projects/{pid}/report/new")
def report_new(pid: int, db: Session = Depends(get_db)):
    p = db.get(Project, pid)
    if not p:
        return RedirectResponse("/projects", status_code=303)
    # เดาค่าเริ่มต้นให้จากโครงการ (ครูแก้ทีหลังได้) - ลดการพิมพ์ซ้ำ
    rep = ProjectReport(project_id=pid, title=p.name or "",
                        responsible=(p.responsible or ""),
                        budget_planned=_to_float(getattr(p, "budget", 0)))
    db.add(rep); db.commit()
    return RedirectResponse(f"/project-reports/{rep.id}", status_code=303)


@router.post("/project-reports/{rid}/delete")
def report_delete(rid: int, db: Session = Depends(get_db)):
    rep = _get(db, rid)
    pid = rep.project_id if rep else None
    if rep:
        db.delete(rep); db.commit()
    return RedirectResponse(f"/projects/{pid}" if pid else "/projects", status_code=303)


# ---------------- ฟอร์มกรอก ----------------
@router.get("/project-reports/{rid}", response_class=HTMLResponse)
def report_form(rid: int, request: Request, db: Session = Depends(get_db),
                saved: str = "", err: str = ""):
    rep = _get(db, rid)
    if not rep:
        return RedirectResponse("/projects", status_code=303)
    from app.routers.pages import get_school
    from app.services.budget import plan_year_label
    school = get_school(db)
    survey = load_list(rep.survey_items)
    pct = survey_percent(survey)
    return templates.TemplateResponse("project_report_form.html", {
        "request": request, "school": school, "rep": rep, "p": rep.project,
        "year_label": plan_year_label(school), "saved": saved, "err": err,
        "persons": db.query(Person).filter_by(active=True).order_by(Person.name).all(),
        "load_list": load_list,
        "survey": survey, "pct": pct, "level": survey_level(pct),
    })


@router.post("/project-reports/{rid}/save")
async def report_save(rid: int, request: Request, db: Session = Depends(get_db)):
    rep = _get(db, rid)
    if not rep:
        return RedirectResponse("/projects", status_code=303)
    f = await request.form()

    rep.title = (f.get("title", "") or "").strip()
    rep.location = (f.get("location", "") or "").strip()
    rep.responsible = (f.get("responsible", "") or "").strip()
    rep.responsible_pos = (f.get("responsible_pos", "") or "").strip()
    rep.date_start = parse_be_date(f.get("date_start", ""))
    rep.date_end = parse_be_date(f.get("date_end", ""))
    rep.budget_planned = _to_float(f.get("budget_planned", "0"))
    rep.budget_used = _to_float(f.get("budget_used", "0"))
    rep.budget_note = (f.get("budget_note", "") or "").strip()
    for k in TEXT_FIELDS:
        setattr(rep, k, (f.get(k, "") or "").strip())

    # รายการเป็นข้อ ๆ : ตัดข้อที่เว้นว่างทิ้ง (ผู้ใช้กดเพิ่มแถวแล้วไม่ได้พิมพ์)
    for k in LIST_FIELDS:
        setattr(rep, k, _dump([v.strip() for v in f.getlist(k) if str(v).strip()]))

    # ตาราง: ประกอบแถวจากคอลัมน์ที่ส่งมาขนานกัน แล้วทิ้งแถวที่ว่างทั้งแถว
    for field, keys in TABLE_FIELDS.items():
        cols = {k: f.getlist(f"{field}_{k}") for k in keys}
        n = max((len(v) for v in cols.values()), default=0)
        rows = []
        for i in range(n):
            row = {k: (cols[k][i].strip() if i < len(cols[k]) else "") for k in keys}
            if field == "obj_results":                 # ติ๊ก "บรรลุ" ส่งมาเป็นค่า on/ว่าง
                row["ok"] = row.get("ok") == "1"
                if not row.get("obj"):
                    continue
            elif not any(row.values()):
                continue
            rows.append(row)
        setattr(rep, field, _dump(rows))

    db.commit()
    return RedirectResponse(f"/project-reports/{rid}?saved=1", status_code=303)


# ---------------- AI อ่านเอกสารโครงการ แล้วเติมให้ ----------------
_AI_ERR = {
    "no_key": "ฟีเจอร์ AI ใช้ได้เฉพาะโรงเรียนที่เป็นสมาชิก",
    "no_text": "อ่านข้อความจากไฟล์ไม่ได้ (ไฟล์อาจเป็นภาพสแกน) ลองใช้ไฟล์ Word หรือ PDF ที่คัดลอกข้อความได้",
    "bad_type": "รองรับไฟล์ PDF, Word (.docx) หรือรูปภาพ",
}


@router.post("/project-reports/{rid}/ai-fill")
async def report_ai_fill(rid: int, request: Request, db: Session = Depends(get_db)):
    """อัปโหลดเอกสารโครงการ -> AI ดึงหลักการ วัตถุประสงค์ เป้าหมาย ขั้นตอน ฯลฯ มาเติม
    เติมเฉพาะช่องที่ยังว่าง ไม่ทับสิ่งที่ครูกรอกไว้แล้ว"""
    import os
    import tempfile
    from urllib.parse import quote
    from app.routers.pages import _ai_key
    from app.services.ai_extract import read_project_doc
    from app.services.pdf_extract import extract_text_any
    rep = _get(db, rid)
    if not rep:
        return RedirectResponse("/projects", status_code=303)
    back = f"/project-reports/{rid}"
    f = await request.form()
    up = f.get("file")
    name = (getattr(up, "filename", "") or "").lower()
    ext = os.path.splitext(name)[1]
    if not up or ext not in (".pdf", ".docx", ".png", ".jpg", ".jpeg"):
        return RedirectResponse(f"{back}?err={quote(_AI_ERR['bad_type'])}", status_code=303)
    key = _ai_key()
    if not key:
        return RedirectResponse(f"{back}?err={quote(_AI_ERR['no_key'])}", status_code=303)
    data = await up.read()
    fd, path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        try:
            text = extract_text_any(path)
        except Exception:
            text = ""
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    res = read_project_doc(text, key)
    if not res.get("ok"):
        msg = _AI_ERR.get(res.get("error"), "AI อ่านไม่สำเร็จ ลองใหม่อีกครั้ง")
        return RedirectResponse(f"{back}?err={quote(msg)}", status_code=303)
    filled = []
    for k in ("title", "location", "responsible", "std_ref", "principles"):
        v = str(res.get(k) or "").strip()
        if v and not (getattr(rep, k) or "").strip():
            setattr(rep, k, v); filled.append(k)
    for k in LIST_FIELDS:
        v = [str(x).strip() for x in (res.get(k) or []) if str(x).strip()]
        if v and not load_list(getattr(rep, k)):
            setattr(rep, k, _dump(v)); filled.append(k)
    for k in ("steps_items", "eval_items"):
        keys = TABLE_FIELDS[k]
        v = [{kk: str((r or {}).get(kk) or "").strip() for kk in keys} for r in (res.get(k) or [])
             if isinstance(r, dict)]
        v = [r for r in v if any(r.values())]
        if v and not load_list(getattr(rep, k)):
            setattr(rep, k, _dump(v)); filled.append(k)
    bp = _to_float(res.get("budget_planned"), 0)
    if bp and not rep.budget_planned:
        rep.budget_planned = bp; filled.append("budget_planned")
    db.commit()
    return RedirectResponse(f"{back}?saved=ai{len(filled)}", status_code=303)


# ---------------- ออกเอกสาร ----------------
@router.get("/project-reports/{rid}/doc.docx")
def report_docx(rid: int, db: Session = Depends(get_db)):
    rep = _get(db, rid)
    if not rep:
        return RedirectResponse("/projects", status_code=303)
    from app.routers.pages import get_school, serve_generated
    from app.services.project_report_doc import render_project_report
    path = render_project_report(rep, get_school(db))
    return serve_generated(
        path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
