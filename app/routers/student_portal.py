"""บัญชีนักเรียน: หน้าของนักเรียน (/student) + หน้าครูจัดการบัญชีและเผยแพร่คะแนน"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import accounts as acc
from app.database import get_db
from app.models import AcadClass, AcadStudent, AcadSubject, AcadTeaching, AcadScorePublish
from app.services import student_portal as sp
from app.templating import templates
from app.routers.pages import get_school

router = APIRouter()


# ---------------- ฝั่งนักเรียน ----------------
def _me(request, db):
    from app.routers.academic import _acad_year
    sid = request.session.get("student_id")
    if not sid:
        return None, None, None
    school = get_school(db)
    row = sp.current_row(db, int(sid), _acad_year(db))
    return school, row, (db.get(AcadClass, row.class_id) if row else None)


def _student_page(request, db, tab):
    school, row, klass = _me(request, db)
    if school is None:
        return RedirectResponse("/login", status_code=303)
    ctx = {"request": request, "school": school, "row": row, "klass": klass, "tab": tab,
           "name": request.session.get("name", ""), "off": not getattr(school, "student_portal", False)}
    if row and not ctx["off"]:
        if tab in ("home", "attendance"):
            ctx["att"] = sp.attendance(db, row)
        if tab in ("home", "timetable"):
            ctx["tt"] = sp.timetable(db, klass)
        if tab in ("home", "grades"):
            ctx["grades"] = sp.grades(db, row)
        if tab == "home":
            # คะแนนความประพฤติ (งานบริหารทั่วไป) ดูอย่างเดียว อ้างจาก student_id ในบัญชีเท่านั้น
            try:
                from app.routers.academic import _acad_year
                from app.services import behavior
                y = _acad_year(db)
                st = behavior.setting(db)
                sc = behavior.scores(db, y, [row.student_id])[row.student_id]
                ctx["bh"] = {"score": sc, "full": st.full, "level": behavior.level(sc, st),
                             "label": behavior.LEVEL_LABEL[behavior.level(sc, st)],
                             "hist": behavior.history(db, y, row.student_id)[:5]}
            except Exception:  # noqa: BLE001
                ctx["bh"] = None
            # เงินออมธนาคารโรงเรียน ดูอย่างเดียว (แสดงเมื่อมีรายการ)
            try:
                from app.services import savings
                h = [x for x in savings.history(db, row.student_id) if not x["t"].void]
                ctx["sv"] = {"bal": h[-1]["bal"], "hist": list(reversed(h))[:5]} if h else None
            except Exception:  # noqa: BLE001
                ctx["sv"] = None
    ctx["mark_label"] = sp.MARK_LABEL
    return templates.TemplateResponse("student_home.html", ctx)


@router.get("/student", response_class=HTMLResponse)
def student_home(request: Request, db: Session = Depends(get_db)):
    if not request.session.get("student_id"):
        return RedirectResponse("/", status_code=303)
    return _student_page(request, db, "home")


@router.get("/student/{tab}", response_class=HTMLResponse)
def student_tab(tab: str, request: Request, db: Session = Depends(get_db)):
    if not request.session.get("student_id") or tab not in ("attendance", "timetable", "grades"):
        return RedirectResponse("/student", status_code=303)
    return _student_page(request, db, tab)


# ---------------- ฝั่งครู/เจ้าหน้าที่ ----------------
def _staff(request, db):
    from app.routers.academic import _scope
    return _scope(request, db)


def _class_students(db, cid):
    return db.query(AcadStudent).filter_by(class_id=cid).order_by(AcadStudent.seq, AcadStudent.id).all()


@router.get("/academic/student-accounts", response_class=HTMLResponse)
def manage(request: Request, db: Session = Depends(get_db), cid: int = 0, msg: str = ""):
    from app.routers.academic import _acad_year, _sorted_classes, _class_label
    sc = _staff(request, db)
    tid = request.session.get("tid")
    allowed = acc.student_portal_allowed(tid)
    school = get_school(db)
    year = _acad_year(db)
    classes = [c for c in _sorted_classes(db.query(AcadClass).filter_by(year=year).all())
               if sc.can_class(c.id)]
    ctx = {"request": request, "school": school, "allowed": allowed, "classes": classes,
           "label": _class_label, "owner": bool(request.session.get("owner")), "msg": msg,
           "on": bool(getattr(school, "student_portal", False)), "klass": None}
    if cid:
        k = db.get(AcadClass, cid)
        if not k or not sc.can_class(cid):
            return RedirectResponse("/academic/student-accounts", status_code=303)
        accs = acc.student_accounts(tid)
        studs = _class_students(db, cid)
        subj_ids = {t.subject_id for t in db.query(AcadTeaching).filter_by(class_id=cid).all()}
        subjects = (db.query(AcadSubject).filter(AcadSubject.id.in_(list(subj_ids) or [0]))
                    .order_by(AcadSubject.seq, AcadSubject.code).all())
        pubs = {(p.subject_id, p.term or 0) for p in db.query(AcadScorePublish).filter_by(class_id=cid).all()}
        ctx.update(klass=k, students=studs, accs=accs, subjects=subjects, pubs=pubs,
                   can_manage=sc.can_homeroom(cid), can_pub=lambda sid: sc.can_teach(cid, sid))
    return templates.TemplateResponse("student_accounts.html", ctx)


@router.post("/academic/student-accounts/toggle")
def toggle(request: Request, db: Session = Depends(get_db), on: str = Form("")):
    if not request.session.get("owner") or not acc.student_portal_allowed(request.session.get("tid")):
        return RedirectResponse("/academic/student-accounts", status_code=303)
    school = get_school(db)
    school.student_portal = on == "1"
    db.commit()
    return RedirectResponse("/academic/student-accounts?msg=" + ("เปิดบัญชีนักเรียนแล้ว" if school.student_portal
                                                                  else "ปิดบัญชีนักเรียนแล้ว"), status_code=303)


def _link_registry(db, k):
    """นักเรียนที่ครูเพิ่มตรงในห้อง (ยังไม่ผูกทะเบียนกลาง) -> ผูกกับทะเบียน
    จับคู่ด้วยเลขประจำตัวก่อน ถ้าไม่มีเลข จับด้วยชื่อ+ชั้น ไม่เจอค่อยเพิ่มเข้าทะเบียนให้
    (บัญชีนักเรียนอ้าง Student.id ซึ่งคงที่ข้ามปีการศึกษา)"""
    from app.models import Student
    taken = {s.student_id for s in db.query(AcadStudent).filter(AcadStudent.student_id.isnot(None)).all()}
    changed = False
    for s in _class_students(db, k.id):
        if s.student_id:
            continue
        no, name = (s.student_no or "").strip(), (s.name or "").strip()
        st = None
        if no:
            st = db.query(Student).filter(Student.student_no == no).first()
        if not st and name:
            st = db.query(Student).filter(Student.name == name, Student.level == k.level).first()
        if st and st.id in taken:
            st = None if (no and st.student_no != no) or not no else st
        if not st:
            st = Student(name=name or "-", student_no=no, sex=s.sex or "", level=k.level, room=k.room or "")
            db.add(st); db.flush()
        s.student_id = st.id
        taken.add(st.id)
        changed = True
    if changed:
        db.commit()


def _cards(request, db, k, cards):
    import base64
    from urllib.parse import quote
    from app.routers.academic import _class_label
    from app.services import totp as _t
    base = str(request.base_url).rstrip("/") + "/login?u="
    for c in cards:
        png = _t.qr_png(base + quote(c["username"]))
        c["qr"] = ("data:image/png;base64," + base64.b64encode(png).decode()) if png else ""
    return templates.TemplateResponse("student_cards.html", {
        "request": request, "school": get_school(db), "klass": k, "label": _class_label,
        "cards": cards, "login_url": str(request.base_url).rstrip("/") + "/login"})


@router.post("/academic/student-accounts/{cid}/create", response_class=HTMLResponse)
def create(cid: int, request: Request, db: Session = Depends(get_db)):
    sc = _staff(request, db)
    tid = request.session.get("tid")
    k = db.get(AcadClass, cid)
    if not k or not sc.can_homeroom(cid) or not acc.student_portal_allowed(tid):
        return RedirectResponse("/academic/student-accounts", status_code=303)
    _link_registry(db, k)
    studs = [{"student_id": s.student_id, "student_no": s.student_no, "name": s.name, "level": k.level}
             for s in _class_students(db, cid) if s.student_id]
    cards = acc.create_student_accounts(tid, studs)
    if not cards:
        return RedirectResponse(f"/academic/student-accounts?cid={cid}&msg=นักเรียนทุกคนมีบัญชีแล้ว", status_code=303)
    return _cards(request, db, k, cards)


@router.post("/academic/student-accounts/{cid}/reset", response_class=HTMLResponse)
def reset(cid: int, request: Request, db: Session = Depends(get_db), student_id: int = Form(0)):
    sc = _staff(request, db)
    tid = request.session.get("tid")
    k = db.get(AcadClass, cid)
    ok = k and sc.can_homeroom(cid) and any(s.student_id == student_id for s in _class_students(db, cid))
    if not ok or not acc.student_portal_allowed(tid):
        return RedirectResponse("/academic/student-accounts", status_code=303)
    card = acc.reset_student_password(tid, student_id, k.level)
    if not card:
        return RedirectResponse(f"/academic/student-accounts?cid={cid}", status_code=303)
    return _cards(request, db, k, [card])


@router.post("/academic/student-accounts/{cid}/active")
def active(cid: int, request: Request, db: Session = Depends(get_db), student_id: int = Form(0),
           on: str = Form("")):
    sc = _staff(request, db)
    tid = request.session.get("tid")
    if sc.can_homeroom(cid) and any(s.student_id == student_id for s in _class_students(db, cid)):
        acc.set_student_active(tid, student_id, on == "1")
    return RedirectResponse(f"/academic/student-accounts?cid={cid}", status_code=303)


@router.post("/academic/student-accounts/{cid}/publish")
def publish(cid: int, request: Request, db: Session = Depends(get_db), subject_id: int = Form(0),
            term: int = Form(0), on: str = Form("")):
    sc = _staff(request, db)
    if db.get(AcadClass, cid) and db.get(AcadSubject, subject_id) and sc.can_teach(cid, subject_id):
        q = db.query(AcadScorePublish).filter_by(class_id=cid, subject_id=subject_id, term=term)
        if on == "1" and not q.first():
            db.add(AcadScorePublish(class_id=cid, subject_id=subject_id, term=term))
        elif on != "1":
            q.delete(synchronize_session=False)
        db.commit()
    return RedirectResponse(f"/academic/student-accounts?cid={cid}#pub", status_code=303)
