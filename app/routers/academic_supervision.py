"""Academic internal supervision; existing records remain in the same tables."""
from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Person, ClassroomVisit, Supervision
from app.thai_utils import parse_be_date, be_date_input, current_academic_year
from app.templating import templates
from app.routers.pages import get_school, _to_int, serve_generated

def require_supervision_manager(request: Request):
    session = request.session
    if session.get('person_id') and not session.get('owner') and not session.get('director'):
        raise HTTPException(status_code=403, detail='งานนิเทศภายในสำหรับผู้บริหารและเจ้าหน้าที่วิชาการ')


router = APIRouter(dependencies=[Depends(require_supervision_manager)])
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

async def legacy_supervision(request: Request):
    path = request.url.path.replace('/hr/', '/academic/', 1)
    if request.url.query:
        path += '?' + request.url.query
    return RedirectResponse(path, status_code=307)

for path, methods in [
    ('supervision', ['GET']), ('classroom-visit', ['GET']),
    ('classroom-visit/save', ['POST']), ('classroom-visit/{vid}/delete', ['POST']),
    ('classroom-visit/{vid}/print.docx', ['GET']), ('supervision-form', ['GET']),
    ('supervision-form/save', ['POST']), ('supervision-form/{vid}/delete', ['POST']),
    ('supervision-form/{vid}/print.docx', ['GET']),
]:
    router.add_api_route('/hr/' + path, legacy_supervision, methods=methods, include_in_schema=False)

# ==================== การนิเทศภายในสถานศึกษา ====================
def _active_persons(db):
    return db.query(Person).filter(Person.active == True).order_by(Person.name).all()  # noqa: E712


def _director_name(school):
    return (getattr(school, "director_name", "") or "").strip()


@router.get("/academic/supervision", response_class=HTMLResponse)
def supervision_home(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("hr_supervision_home.html", {
        "request": request, "school": get_school(db),
        "n_visit": db.query(ClassroomVisit).count(),
        "n_sup": db.query(Supervision).count(),
    })


# ---------------- แบบการเยี่ยมชั้นเรียน ----------------
@router.get("/academic/classroom-visit", response_class=HTMLResponse)
def cv_page(request: Request, db: Session = Depends(get_db), edit: int | None = None, msg: str = "",
            year: int | None = None):
    from app.services.super_doc import VISIT_ITEMS
    rec = db.get(ClassroomVisit, edit) if edit else None
    _ay = get_school(db).academic_year or current_academic_year()   # ปีการศึกษาที่โรงเรียนตั้ง/คำนวณ
    years = sorted({y for (y,) in db.query(ClassroomVisit.year).distinct() if y} | {_ay}, reverse=True)
    q = db.query(ClassroomVisit)
    if year:
        q = q.filter(ClassroomVisit.year == year)
    return templates.TemplateResponse("hr_classroom_visit.html", {
        "request": request, "school": get_school(db), "msg": msg,
        "rows": q.order_by(ClassroomVisit.id.desc()).all(),
        "persons": _active_persons(db), "rec": rec, "items": VISIT_ITEMS,
        "years": years, "sel_year": year or 0, "default_year": _ay,
        "scores": (rec.scores.split(",") if rec and rec.scores else []),
        "be_date": be_date_input, "director": _director_name(get_school(db)),
    })


@router.post("/academic/classroom-visit/save")
async def cv_save(request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    vid = _to_int(f.get("id"), 0)
    r = db.get(ClassroomVisit, vid) if vid else ClassroomVisit()
    r.person_id = _to_int(f.get("person_id"), 0) or None
    r.term = _to_int(f.get("term"), 1)
    r.year = _to_int(f.get("year"), 0) or None
    r.subject_group = (f.get("subject_group") or "").strip()
    r.topic = (f.get("topic") or "").strip()
    r.grade_level = (f.get("grade_level") or "").strip()
    r.period = (f.get("period") or "").strip()
    r.visit_time = (f.get("visit_time") or "").strip()
    r.visit_date = parse_be_date(f.get("visit_date") or "")
    r.visitor_name = (f.get("visitor_name") or "").strip()
    r.suggestion = (f.get("suggestion") or "").strip()
    r.scores = ",".join((f.get(f"score_{i}") or "").strip() for i in range(1, 11))
    if not vid:
        db.add(r)
    db.commit()
    return RedirectResponse(f"/academic/classroom-visit?edit={r.id}&msg=บันทึกแบบการเยี่ยมชั้นเรียนแล้ว",
                            status_code=303)


@router.post("/academic/classroom-visit/{vid}/delete")
def cv_delete(vid: int, db: Session = Depends(get_db)):
    r = db.get(ClassroomVisit, vid)
    if r:
        db.delete(r); db.commit()
    return RedirectResponse("/academic/classroom-visit", status_code=303)


@router.get("/academic/classroom-visit/{vid}/print.docx")
def cv_print(vid: int, db: Session = Depends(get_db)):
    from app.services.super_doc import render_classroom_visit
    r = db.get(ClassroomVisit, vid)
    if not r:
        return RedirectResponse("/academic/classroom-visit", status_code=303)
    return serve_generated(render_classroom_visit(get_school(db), r), _DOCX)


# ---------------- แบบบันทึกการนิเทศการจัดการเรียนรู้ ----------------
@router.get("/academic/supervision-form", response_class=HTMLResponse)
def sup_page(request: Request, db: Session = Depends(get_db), edit: int | None = None, msg: str = ""):
    from app.services.super_doc import SUP_DOMAINS
    rec = db.get(Supervision, edit) if edit else None
    return templates.TemplateResponse("hr_supervision_form.html", {
        "request": request, "school": get_school(db), "msg": msg,
        "rows": db.query(Supervision).order_by(Supervision.id.desc()).all(),
        "persons": _active_persons(db), "rec": rec, "domains": SUP_DOMAINS,
        "scores": (rec.scores.split(",") if rec and rec.scores else []),
        "be_date": be_date_input, "director": _director_name(get_school(db)),
    })


@router.post("/academic/supervision-form/save")
async def sup_save(request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    vid = _to_int(f.get("id"), 0)
    r = db.get(Supervision, vid) if vid else Supervision()
    r.person_id = _to_int(f.get("person_id"), 0) or None
    r.subject_group = (f.get("subject_group") or "").strip()
    r.subject_taught = (f.get("subject_taught") or "").strip()
    r.subject_code = (f.get("subject_code") or "").strip()
    r.grade_class = (f.get("grade_class") or "").strip()
    r.round_no = _to_int(f.get("round_no"), 1)
    r.sup_date = parse_be_date(f.get("sup_date") or "")
    r.supervisor_name = (f.get("supervisor_name") or "").strip()
    r.note_found = (f.get("note_found") or "").strip()
    r.note_reflect = (f.get("note_reflect") or "").strip()
    r.note_impress = (f.get("note_impress") or "").strip()
    r.note_improve = (f.get("note_improve") or "").strip()
    r.scores = ",".join((f.get(f"score_{i}") or "").strip() for i in range(1, 26))
    if not vid:
        db.add(r)
    db.commit()
    return RedirectResponse(f"/academic/supervision-form?edit={r.id}&msg=บันทึกแบบนิเทศการจัดการเรียนรู้แล้ว",
                            status_code=303)


@router.post("/academic/supervision-form/{vid}/delete")
def sup_delete(vid: int, db: Session = Depends(get_db)):
    r = db.get(Supervision, vid)
    if r:
        db.delete(r); db.commit()
    return RedirectResponse("/academic/supervision-form", status_code=303)


@router.get("/academic/supervision-form/{vid}/print.docx")
def sup_print(vid: int, db: Session = Depends(get_db)):
    from app.services.super_doc import render_supervision
    r = db.get(Supervision, vid)
    if not r:
        return RedirectResponse("/academic/supervision-form", status_code=303)
    return serve_generated(render_supervision(get_school(db), r), _DOCX)
