# -*- coding: utf-8 -*-
"""
savings.py - ธนาคารโรงเรียน (เงินออมนักเรียน) แบบโรงเรียนเก็บเงินเอง อยู่ในงานบริหารทั่วไป (ฟรี)
ครูประจำชั้นบันทึกได้เฉพาะห้องตัวเอง เจ้าหน้าที่/ไอดีหลักเห็นทุกห้อง
ปิดยอดเดือนได้เฉพาะเจ้าหน้าที่ เปิดยอดคืนได้เฉพาะไอดีหลัก
"""
from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Student, SavingsTxn, SavingsLock
from app.templating import templates
from app.routers.pages import get_school
from app.routers.general import (_is_teacher, _my_homerooms, _class_students, _valid_date, _be_input,
                                 _be, _today_iso, _class_label, _bh_who)
from app.services import savings as sv

router = APIRouter()
BASE = "/general/savings"


def _staff(request) -> bool:
    return not _is_teacher(request)


def _my_sids(request, db):
    """None = ทุกคน (เจ้าหน้าที่)  set = นักเรียนในห้องที่ครูประจำชั้น"""
    if _staff(request):
        return None
    out = set()
    for c in _my_homerooms(request, db):
        out |= {s.student_id for s in c.students if s.student_id}
    return out


def _can(request, db, sid) -> bool:
    mine = _my_sids(request, db)
    return mine is None or sid in mine


def _back(url, msg):
    url = url if (url or "").startswith(BASE) else BASE
    return RedirectResponse(url + ("&" if "?" in url else "?") + "msg=" + msg, status_code=303)


def _class_rows(db, c, day):
    studs, missing = _class_students(c)
    ids = [s.student_id for s in studs]
    bal = sv.balances(db, ids)
    today = sv.day_totals(db, day, ids)
    rows = [{"sid": s.student_id, "seq": s.seq or "", "name": s.name, "bal": bal.get(s.student_id, 0.0),
             "dep": today.get(s.student_id, {}).get("dep", 0.0), "wd": today.get(s.student_id, {}).get("wd", 0.0)}
            for s in studs]
    return rows, missing


@router.get(BASE, response_class=HTMLResponse)
def savings_page(request: Request, db: Session = Depends(get_db), cid: int = 0, date: str = "", msg: str = ""):
    from app.routers.academic import _class_label as acad_label
    day = _valid_date(date)
    classes = _my_homerooms(request, db)
    c = next((x for x in classes if x.id == cid), classes[0] if classes else None)
    if c and any(not s.student_id for s in c.students):
        from app.routers.student_portal import _link_registry
        _link_registry(db, c)
        db.refresh(c)
    rows, missing = _class_rows(db, c, day) if c else ([], 0)
    staff = _staff(request)
    return templates.TemplateResponse("general_savings.html", {
        "request": request, "school": get_school(db), "classes": classes, "c": c, "class_label": acad_label,
        "rows": rows, "missing": missing, "day": day, "day_be": _be(day), "day_input": _be_input(day),
        "locked": sv.is_locked(db, day), "is_staff": staff, "msg": msg,
        "room_bal": round(sum(r["bal"] for r in rows), 2),
        "room_dep": round(sum(r["dep"] for r in rows), 2), "room_wd": round(sum(r["wd"] for r in rows), 2),
        "school_bal": sv.total_balance(db) if staff else None,
    })


@router.post(BASE + "/save")
async def savings_save(request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    day = _valid_date(f.get("date", ""))
    back = f.get("back") or BASE
    who, pid = _bh_who(request)
    mine = _my_sids(request, db)
    items, bad = [], False
    for k in f.keys():
        if not (k.startswith("dep_") or k.startswith("wd_")):
            continue
        kind, _, sid = k.partition("_")
        if not sid.isdigit():
            continue
        amt = sv.parse_amount(f.get(k))
        if amt is None:
            bad = True
            continue
        if amt:
            items.append((int(sid), kind, amt))
    if bad:
        return _back(back, "มีช่องที่กรอกจำนวนเงินไม่ถูกต้อง ยังไม่ได้บันทึก")
    if not items:
        return _back(back, "ยังไม่ได้กรอกจำนวนเงิน")
    if sv.is_locked(db, day):
        return _back(back, "เดือนนี้ปิดยอดแล้ว บันทึกเพิ่มไม่ได้")
    ids = {i[0] for i in items}
    if mine is not None and not ids <= mine:
        return _back(back, "บันทึกได้เฉพาะนักเรียนในห้องที่ท่านเป็นครูประจำชั้น")
    names = {s.id: s.name for s in db.query(Student).filter(Student.id.in_(ids))}
    bal = sv.balances(db, list(ids))
    items.sort(key=lambda x: x[1] != "dep")        # วันเดียวกัน ลงฝากก่อนถอน
    n = 0
    for sid, kind, amt in items:
        if sid not in names:
            continue
        _t, err = sv.add(db, student_id=sid, kind=kind, amount=amt, day=day, note=f.get("note", ""),
                         by_name=who, by_pid=pid, balance=bal[sid])
        if err:
            db.rollback()
            return _back(back, f"{names[sid]} {err} ยังไม่ได้บันทึกทั้งชุด")
        bal[sid] = round(bal[sid] + (amt if kind == "dep" else -amt), 2)
        n += 1
    db.commit()
    return _back(back, f"บันทึกแล้ว {n} รายการ")


@router.get(BASE + "/s/{sid}", response_class=HTMLResponse)
def savings_student(sid: int, request: Request, db: Session = Depends(get_db), msg: str = ""):
    stu = db.get(Student, sid)
    if not stu or not _can(request, db, sid):
        return RedirectResponse(BASE, status_code=303)
    hist = sv.history(db, sid)
    locked = {m.month for m in db.query(SavingsLock).all()}
    return templates.TemplateResponse("general_savings_student.html", {
        "request": request, "school": get_school(db), "stu": stu, "cls": _class_label(stu),
        "hist": list(reversed(hist)), "bal": hist[-1]["bal"] if hist else 0.0, "msg": msg, "be": _be,
        "kinds": sv.KIND_LABEL, "is_staff": _staff(request), "me": _bh_who(request)[0], "locked": locked,
    })


@router.post(BASE + "/t/{tid}/void")
async def savings_void(tid: int, request: Request, db: Session = Depends(get_db)):
    f = await request.form()
    t = db.get(SavingsTxn, tid)
    if not t or not _can(request, db, t.student_id):
        return RedirectResponse(BASE, status_code=303)
    who, _pid = _bh_who(request)
    if not _staff(request) and t.by_name != who:
        return _back(f"{BASE}/s/{t.student_id}", "ยกเลิกได้เฉพาะรายการที่ท่านบันทึกเอง")
    err = sv.void(db, t, reason=f.get("reason", ""), by_name=who)
    if err:
        return _back(f"{BASE}/s/{t.student_id}", err)
    db.commit()
    return _back(f"{BASE}/s/{t.student_id}", "ยกเลิกรายการแล้ว")


@router.get(BASE + "/s/{sid}/print", response_class=HTMLResponse)
def savings_passbook(sid: int, request: Request, db: Session = Depends(get_db)):
    stu = db.get(Student, sid)
    if not stu or not _can(request, db, sid):
        return RedirectResponse(BASE, status_code=303)
    hist = [h for h in sv.history(db, sid) if not h["t"].void]
    return templates.TemplateResponse("general_savings_print.html", {
        "request": request, "school": get_school(db), "mode": "book", "stu": stu, "cls": _class_label(stu),
        "hist": hist, "be": _be, "kinds": sv.KIND_LABEL,
    })


@router.get(BASE + "/daily", response_class=HTMLResponse)
def savings_daily(request: Request, db: Session = Depends(get_db), date: str = ""):
    """สรุปรับ/จ่ายประจำวันแยกห้อง (ครูเห็นเฉพาะห้องตัวเอง) ใช้ส่งเงินให้ผู้รับผิดชอบ"""
    from app.routers.academic import _class_label as acad_label
    day = _valid_date(date)
    rows = []
    for c in _my_homerooms(request, db):
        studs, _ = _class_students(c)
        tot = sv.day_totals(db, day, [s.student_id for s in studs])
        dep = round(sum(v["dep"] for v in tot.values()), 2)
        wd = round(sum(v["wd"] for v in tot.values()), 2)
        if dep or wd:
            rows.append({"label": acad_label(c), "teacher": c.homeroom.name if getattr(c, "homeroom", None) else "",
                         "n": len(tot), "dep": dep, "wd": wd})
    dep = round(sum(r["dep"] for r in rows), 2)
    wd = round(sum(r["wd"] for r in rows), 2)
    return templates.TemplateResponse("general_savings_print.html", {
        "request": request, "school": get_school(db), "mode": "daily", "rows": rows, "day_be": _be(day),
        "dep": dep, "wd": wd, "net": round(dep - wd, 2),
    })


@router.get(BASE + "/months", response_class=HTMLResponse)
def savings_months(request: Request, db: Session = Depends(get_db), msg: str = ""):
    if not _staff(request):
        return RedirectResponse(BASE, status_code=303)
    from app.thai_utils import _THAI_MONTHS
    months = sorted({d[:7] for (d,) in db.query(SavingsTxn.date).distinct()} | {_today_iso()[:7]}, reverse=True)
    locks = {x.month: x for x in db.query(SavingsLock).all()}
    rows = []
    for m in months:
        y, mo = int(m[:4]), int(m[5:7])
        rows.append({"m": m, "label": f"{_THAI_MONTHS[mo]} {y + 543}", **sv.month_summary(db, m),
                     "lock": locks.get(m), "end": sv.total_balance(db, upto=m + "-31")})
    return templates.TemplateResponse("general_savings_months.html", {
        "request": request, "school": get_school(db), "rows": rows, "msg": msg,
        "is_owner": bool(request.session.get("owner")),
    })


def _month_ok(m: str) -> bool:
    return len(m) == 7 and m[4] == "-" and m[:4].isdigit() and m[5:].isdigit()


@router.post(BASE + "/months/{month}/lock")
def savings_lock(month: str, request: Request, db: Session = Depends(get_db)):
    if not _staff(request) or not _month_ok(month):
        return RedirectResponse(BASE, status_code=303)
    if not db.query(SavingsLock).filter_by(month=month).first():
        db.add(SavingsLock(month=month, by_name=_bh_who(request)[0]))
        db.commit()
    return _back(BASE + "/months", "ปิดยอดเดือนแล้ว")


@router.post(BASE + "/months/{month}/unlock")
def savings_unlock(month: str, request: Request, db: Session = Depends(get_db)):
    if not request.session.get("owner"):
        return _back(BASE + "/months", "เปิดยอดคืนได้เฉพาะไอดีหลักของโรงเรียน")
    db.query(SavingsLock).filter_by(month=month).delete()
    db.commit()
    return _back(BASE + "/months", "เปิดยอดเดือนคืนแล้ว")
