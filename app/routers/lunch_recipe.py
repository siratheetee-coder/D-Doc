"""สูตรอาหาร + คำนวณวัตถุดิบตามจำนวนนักเรียน + ใบซื้อของรายสัปดาห์"""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import LunchProgram, LunchRecipe, LunchRecipeItem, LunchIngredient
from app.services import lunch_recipe as svc
from app.templating import templates
from app.thai_utils import parse_be_date, be_date_input, thai_date
from app.routers.pages import get_school, _to_float

router = APIRouter()


def _back(v):
    v = v or ""
    return v if v.startswith("/lunch/") and "//" not in v else ""


@router.get("/lunch/{pid}/recipes", response_class=HTMLResponse)
def recipes_page(pid: int, request: Request, db: Session = Depends(get_db), back: str = "", edit: int = 0):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    recipes = db.query(LunchRecipe).order_by(LunchRecipe.name).all()
    menu_names = sorted({(m.main or "").strip() for m in prog.menus if (m.main or "").strip()})
    cur = db.get(LunchRecipe, edit) if edit else None
    return templates.TemplateResponse("lunch_recipes.html", {
        "request": request, "school": get_school(db), "p": prog, "recipes": recipes, "cur": cur,
        "menu_names": menu_names, "tiers": svc.tiers(prog), "back": _back(back)})


@router.post("/lunch/{pid}/recipes/save")
async def recipe_save(pid: int, request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    name = (form.get("name") or "").strip()
    back = _back(form.get("back") or "")
    if not name:
        return RedirectResponse(f"/lunch/{pid}/recipes", status_code=303)
    rid = int(form.get("rid") or 0)
    r = db.get(LunchRecipe, rid) if rid else None
    if not r:
        r = LunchRecipe(name=name); db.add(r)
    r.name = name
    r.items.clear(); db.flush()
    names, units = form.getlist("i_name"), form.getlist("i_unit")
    qk, qp, qm = form.getlist("i_k"), form.getlist("i_p"), form.getlist("i_m")
    locked = set(form.getlist("i_lock"))
    seq = 0
    for i, n in enumerate(names):
        n = (n or "").strip()
        if not n:
            continue
        seq += 1
        r.items.append(LunchRecipeItem(seq=seq, name=n, unit=(units[i] if i < len(units) else "").strip(),
                                       q_k=_to_float(qk[i] if i < len(qk) else 0, 0.0),
                                       q_p=_to_float(qp[i] if i < len(qp) else 0, 0.0),
                                       q_m=_to_float(qm[i] if i < len(qm) else 0, 0.0),
                                       locked=1 if str(i) in locked else 0))
    db.commit()
    q = f"?back={back}" if back else ""
    return RedirectResponse(f"/lunch/{pid}/recipes{q}", status_code=303)


@router.post("/lunch/{pid}/recipes/{rid}/delete")
def recipe_delete(pid: int, rid: int, db: Session = Depends(get_db), back: str = Form("")):
    r = db.get(LunchRecipe, rid)
    if r:
        db.delete(r); db.commit()
    back = _back(back)
    return RedirectResponse(f"/lunch/{pid}/recipes" + (f"?back={back}" if back else ""), status_code=303)


@router.get("/lunch/{pid}/recipes/calc")
def recipe_calc(pid: int, db: Session = Depends(get_db), d: str = "", recipe: int = 0, back: str = ""):
    """คำนวณวัตถุดิบของวัน d (พ.ศ.) จากสูตรที่จับคู่กับเมนูวันนั้น หรือสูตรที่เลือก"""
    prog = db.get(LunchProgram, pid)
    if not prog:
        return JSONResponse({"ok": False}, status_code=404)
    day = parse_be_date(d)
    menu = next((m.main for m in prog.menus if m.date and day and m.date.date() == day.date()), "")
    r = db.get(LunchRecipe, recipe) if recipe else svc.match(db, menu)
    t = svc.tiers(prog)
    rnd = svc.current_round(prog, back)
    have = {(x.name or "").strip() for x in prog.ingredients if x.date and day and x.date.date() == day.date()}
    spent = sum((x.quantity or 0) * (x.unit_price or 0) for x in prog.ingredients
                if x.date and day and x.date.date() == day.date())
    return JSONResponse({
        "ok": True, "menu": menu, "recipe": {"id": r.id, "name": r.name} if r else None,
        "recipes": [{"id": x.id, "name": x.name} for x in db.query(LunchRecipe).order_by(LunchRecipe.name)],
        "tiers": t, "budget": svc.daily_budget(prog, rnd), "spent": round(spent, 2),
        "rows": [dict(x, have=x["name"] in have) for x in (svc.calc(r, t, svc.last_prices(prog)) if r else [])]})


@router.post("/lunch/{pid}/recipes/fill")
def recipe_fill(pid: int, db: Session = Depends(get_db), date: str = Form(""), rows: str = Form("[]"),
                back: str = Form("")):
    """เติมวัตถุดิบที่คำนวณแล้วลงวันนั้น ไม่ทับรายการชื่อเดียวกันที่กรอกไว้แล้ว"""
    from app.routers.lunch import resync_program_ledger
    prog = db.get(LunchProgram, pid)
    day = parse_be_date(date)
    added = 0
    if prog and day:
        have = {(x.name or "").strip() for x in prog.ingredients if x.date and x.date.date() == day.date()}
        seq = max([x.seq for x in prog.ingredients if x.date and x.date.date() == day.date()], default=0)
        try:
            data = json.loads(rows or "[]")
        except ValueError:
            data = []
        for row in data[:200]:
            n = str(row.get("name") or "").strip()
            q = _to_float(row.get("qty"), 0.0)
            if not n or n in have or q <= 0:
                continue
            seq += 1; added += 1; have.add(n)
            db.add(LunchIngredient(program_id=pid, date=day, seq=seq, name=n, quantity=q,
                                   unit=str(row.get("unit") or "").strip()[:40],
                                   unit_price=max(_to_float(row.get("price"), 0.0), 0.0)))
        db.commit()
        resync_program_ledger(db, prog); db.commit()
    from urllib.parse import quote
    back = _back(back)
    url = f"/lunch/{pid}/ingredients?" + (f"back={quote(back)}&" if back else "") + "d=" + quote(date) + f"&added={added}"
    return RedirectResponse(url, status_code=303)


@router.get("/lunch/{pid}/shopping", response_class=HTMLResponse)
def shopping(pid: int, request: Request, db: Session = Depends(get_db), w: str = "", back: str = ""):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    base = parse_be_date(w) or datetime.now()
    monday = datetime(base.year, base.month, base.day) - timedelta(days=base.weekday())
    data = svc.week_list(db, prog, monday)
    rnd = svc.current_round(prog, back)
    budget = round(svc.daily_budget(prog, rnd) * len(data["days"]), 2)
    return templates.TemplateResponse("lunch_shopping.html", {
        "request": request, "school": get_school(db), "p": prog, "d": data, "budget": budget,
        "monday": monday, "friday": monday + timedelta(days=4), "thai_date": thai_date,
        "prev": be_date_input(monday - timedelta(days=7)), "next": be_date_input(monday + timedelta(days=7)),
        "back": _back(back)})
