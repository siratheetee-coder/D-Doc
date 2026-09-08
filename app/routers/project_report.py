# -*- coding: utf-8 -*-
"""
project_report.py - รายงานผลการดำเนินงานโครงการ/กิจกรรม

ผูกกับหน้า "โครงการ/แผนงบ" (/projects) · 1 โครงการรายงานได้หลายครั้ง (แยกรายกิจกรรม)
เส้นทางรายงานใช้ /project-reports/... แยกจาก /projects/{pid:int}
เพราะ path param เป็น int ถ้าใช้ /projects/reports จะกลายเป็น 422 ไม่ตกมาที่ route นี้
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Project, ProjectReport, ProjectReportPhoto, Person
from app.templating import templates
from app.thai_utils import parse_be_date

router = APIRouter()

MAX_PHOTOS = 24                      # กันเอกสารบวมจนดาวน์โหลดช้า
PHOTO_MAX_PX = 1100                  # ด้านยาวสุดหลังย่อ (พิมพ์ A4 ครึ่งหน้ากว้างพอ)

# ช่องข้อความยาวทั้งหมด - ใช้ทั้งตอนบันทึกและตอนแสดงผล (เพิ่มหัวข้อใหม่แก้ที่เดียว)
TEXT_FIELDS = ["std_ref", "principles", "objectives", "target_qty", "target_qual",
               "methods", "results", "satisfaction", "problems", "suggestions"]


def _to_float(v, d=0.0):
    try:
        return float(str(v).replace(",", "").strip())
    except (TypeError, ValueError):
        return d


def _shrink(data: bytes):
    """ย่อรูปเป็น JPEG · คืน None ถ้าไม่ใช่ไฟล์รูป (ผู้ใช้เผลอเลือกไฟล์อื่น)"""
    import io as _io
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(_io.BytesIO(data))).convert("RGB")
    except Exception:
        return None
    m = PHOTO_MAX_PX
    if max(img.width, img.height) > m:
        if img.width >= img.height:
            img = img.resize((m, round(img.height * m / img.width)), Image.LANCZOS)
        else:
            img = img.resize((round(img.width * m / img.height), m), Image.LANCZOS)
    buf = _io.BytesIO()
    img.save(buf, "JPEG", quality=80, optimize=True)
    return buf.getvalue()


def _get(db, rid):
    return db.get(ProjectReport, rid)


# ---------------- สร้าง / ลบ ----------------
@router.post("/projects/{pid}/report/new")
def report_new(pid: int, request: Request, db: Session = Depends(get_db)):
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
    from app.services.budget import plan_year_label
    from app.routers.pages import get_school
    return templates.TemplateResponse("project_report_form.html", {
        "request": request, "school": get_school(db), "rep": rep, "p": rep.project,
        "year_label": plan_year_label(get_school(db)), "saved": saved, "err": err,
        "persons": db.query(Person).filter_by(active=True).order_by(Person.name).all(),
        "max_photos": MAX_PHOTOS,
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
    # คำบรรยายภาพ (ส่งมาพร้อมฟอร์มเดียวกัน จะได้ไม่ต้องกดบันทึกสองที)
    for ph in rep.photos:
        cap = f.get(f"cap_{ph.id}", None)
        if cap is not None:
            ph.caption = cap.strip()
    db.commit()
    return RedirectResponse(f"/project-reports/{rid}?saved=1", status_code=303)


# ---------------- ภาพกิจกรรม ----------------
@router.post("/project-reports/{rid}/photos")
async def photos_add(rid: int, db: Session = Depends(get_db),
                     files: list[UploadFile] = File(default=[])):
    rep = _get(db, rid)
    if not rep:
        return RedirectResponse("/projects", status_code=303)
    room = MAX_PHOTOS - len(rep.photos)
    if room <= 0:
        return RedirectResponse(f"/project-reports/{rid}?err=full", status_code=303)
    seq = max([p.seq or 0 for p in rep.photos], default=0)
    added = bad = 0
    for uf in (files or [])[:room]:
        img = _shrink(await uf.read())
        if not img:
            bad += 1
            continue
        seq += 1
        db.add(ProjectReportPhoto(report_id=rid, seq=seq, image=img, caption=""))
        added += 1
    db.commit()
    q = "?added=%d" % added + ("&err=notimg" if bad else "")
    return RedirectResponse(f"/project-reports/{rid}{q}", status_code=303)


@router.post("/project-reports/{rid}/photos/{phid}/delete")
def photo_delete(rid: int, phid: int, db: Session = Depends(get_db)):
    ph = db.get(ProjectReportPhoto, phid)
    if ph and ph.report_id == rid:
        db.delete(ph); db.commit()
    return RedirectResponse(f"/project-reports/{rid}", status_code=303)


@router.post("/project-reports/{rid}/photos/{phid}/move")
def photo_move(rid: int, phid: int, db: Session = Depends(get_db), dir: str = Form("up")):
    """สลับลำดับกับภาพข้างเคียง (ลำดับนี้คือลำดับที่ขึ้นในเอกสาร)"""
    rep = _get(db, rid)
    if not rep:
        return RedirectResponse("/projects", status_code=303)
    items = list(rep.photos)
    for i, ph in enumerate(items):          # เขียนลำดับให้ต่อเนื่องก่อน กันข้อมูลเก่าที่ seq ซ้ำ/ว่าง
        ph.seq = i + 1
    idx = next((i for i, ph in enumerate(items) if ph.id == phid), None)
    j = None if idx is None else (idx - 1 if dir == "up" else idx + 1)
    if idx is not None and j is not None and 0 <= j < len(items):
        items[idx].seq, items[j].seq = items[j].seq, items[idx].seq
    db.commit()
    return RedirectResponse(f"/project-reports/{rid}", status_code=303)


@router.get("/project-reports/{rid}/photo/{phid}")
def photo_view(rid: int, phid: int, db: Session = Depends(get_db)):
    ph = db.get(ProjectReportPhoto, phid)
    if not ph or ph.report_id != rid or not ph.image:
        return Response(status_code=404)
    return Response(content=ph.image, media_type="image/jpeg",
                    headers={"Cache-Control": "private, max-age=86400"})


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
