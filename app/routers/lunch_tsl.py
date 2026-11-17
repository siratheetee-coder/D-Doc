"""นำเข้าเมนู/วัตถุดิบจาก Thai School Lunch (วางตารางรายงาน -> หน้าตรวจ -> บันทึก)"""
import json
from datetime import datetime
from fastapi import APIRouter, Depends, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import LunchProgram
from app.templating import templates
from app.services import lunch_tsl
from app.thai_utils import be_date_input

router = APIRouter()


def _prog(db, pid):
    p = db.get(LunchProgram, pid)
    if not p:
        raise HTTPException(404, "ไม่พบโครงการอาหารกลางวัน")
    return p


def _safe(back):
    return back if (back or "").startswith("/lunch/") else ""


def _ctx(request, p, back, **kw):
    with_ings = p.operate_mode != "hire"
    return dict(request=request, p=p, back=_safe(back), with_ings=with_ings,
                be=be_date_input, preview=None, error="", **kw)


@router.get("/lunch/{pid}/tsl-import", response_class=HTMLResponse)
def tsl_page(pid: int, request: Request, db: Session = Depends(get_db), back: str = ""):
    p = _prog(db, pid)
    return templates.TemplateResponse("lunch_tsl_import.html", _ctx(request, p, back))


@router.post("/lunch/{pid}/tsl-import/preview", response_class=HTMLResponse)
def tsl_preview(pid: int, request: Request, db: Session = Depends(get_db),
                rows: str = Form("[]"), text: str = Form(""), back: str = Form("")):
    p = _prog(db, pid)
    ctx = _ctx(request, p, back)
    try:
        data = json.loads(rows or "[]")
    except ValueError:
        data = []
    if not data and text:
        data = [line.split("\t") for line in text.splitlines()]
    pv = lunch_tsl.build_preview(db, p, data, lunch_tsl.report_students(text), ctx["with_ings"])
    if not pv["days"]:
        ctx["error"] = "อ่านตารางไม่ได้ ลองคัดลอกใหม่จากหน้ารายงานวัตถุดิบและปริมาณการจัดซื้อ (กด Ctrl+A แล้ว Ctrl+C)"
    else:
        ctx["preview"] = pv
    return templates.TemplateResponse("lunch_tsl_import.html", ctx)


@router.post("/lunch/{pid}/tsl-import/save")
async def tsl_save(pid: int, request: Request, db: Session = Depends(get_db)):
    p = _prog(db, pid)
    f = await request.form()
    with_ings = p.operate_mode != "hire"
    on = set(f.getlist("d_on"))
    days = []
    dates, mains, desserts = f.getlist("d_date"), f.getlist("d_main"), f.getlist("d_dessert")
    i_day, i_name, i_qty = f.getlist("i_day"), f.getlist("i_name"), f.getlist("i_qty")
    i_unit, i_price = f.getlist("i_unit"), f.getlist("i_price")
    for k, ds in enumerate(dates):
        if str(k) not in on:
            continue
        try:
            dt = datetime.strptime(ds, "%Y-%m-%d")
        except ValueError:
            continue
        ings = [{"name": i_name[j].strip(), "unit": i_unit[j].strip(),
                 "qty": lunch_tsl._num(i_qty[j]) or 0.0, "price": lunch_tsl._num(i_price[j]) or 0.0}
                for j in range(len(i_day)) if i_day[j] == str(k)]
        days.append({"date": dt, "main": (mains[k] if k < len(mains) else "").strip(),
                     "dessert": (desserts[k] if k < len(desserts) else "").strip(), "ings": ings})
    n = lunch_tsl.save(db, p, days, f.get("replace") == "1", with_ings)
    if with_ings and n:
        from app.routers.lunch import resync_program_ledger
        resync_program_ledger(db, p); db.commit()
    back = _safe(f.get("back", ""))
    dest = back or (f"/lunch/{pid}/ingredients" if with_ings else f"/lunch/{pid}/menu")
    sep = "&" if "?" in dest else "?"
    from urllib.parse import quote
    return RedirectResponse(f"{dest}{sep}msg=" + quote(f"นำเข้าแล้ว {n} วัน"), status_code=303)
