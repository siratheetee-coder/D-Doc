# -*- coding: utf-8 -*-
"""
lunch.py - งานอาหารกลางวัน
โครงการอาหารกลางวันต่อปีการศึกษา: คำนวณงบ (นักเรียน x อัตรา/หัว/วัน x จำนวนวัน)
+ บัญชีรับ-จ่ายเงินอาหารกลางวัน + เชื่อมไปเรื่องจ้างเหมา (โมดูลจัดซื้อ)
ตารางใหม่สร้างอัตโนมัติด้วย init_school_db (ไม่ต้อง ALTER)
"""
import re
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (LunchProgram, LunchClass, LunchLedger, LunchHireRound,
                        LunchInstallment, LunchMenu, LunchStudent, LunchMeasure, Vendor,
                        FinanceAccount, FinanceTxn, Procurement)
from app.services.growth_ref import (classify_all, age_months,
                                     WH_LABELS, HA_LABELS, WA_LABELS)
from app.thai_utils import parse_be_date, be_date_input, current_fiscal_year, SCHOOL_LEVELS
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float, serve_generated

router = APIRouter()

PERIOD_TYPES = {"day": "รายวัน", "week": "รายสัปดาห์", "month": "รายเดือน"}

# ระดับชั้นมาตรฐาน (เติม 0 ได้ถ้าไม่มีชั้นนั้น)
DEFAULT_LEVELS = SCHOOL_LEVELS         # ใช้ลิสต์ร่วมจาก thai_utils (แหล่งความจริงเดียว)

OPERATE_MODES = {
    "hire": "จ้างเหมาประกอบอาหาร (ปรุงสำเร็จ)",
    "person": "จ้างบุคคลประกอบอาหาร (แม่ครัว)",
    "ingredient": "ซื้อวัตถุดิบเพื่อประกอบอาหาร (ยืมเงิน)",
    "self": "โรงเรียนดำเนินการเอง",
}

# อาหารหลัก 5 หมู่ (ตามหลักโภชนาการ)
FOOD_GROUPS = {
    "1": "โปรตีน (เนื้อ/ไข่/นม/ถั่ว)",
    "2": "ข้าว-แป้ง (คาร์โบไฮเดรต)",
    "3": "ผัก (เกลือแร่)",
    "4": "ผลไม้ (วิตามิน)",
    "5": "ไขมัน",
}

# เมนูแนะนำมาตรฐาน (ครบ 5 หมู่) - กดเพิ่มเข้าตารางได้เลย ไว้หมุนเวียนรายสัปดาห์
STD_MENUS = [
    {"main": "ข้าว + ผัดกะเพราไก่ ไข่ดาว", "dessert": "กล้วยน้ำว้า"},
    {"main": "ข้าว + แกงจืดเต้าหู้หมูสับ", "dessert": "ส้ม"},
    {"main": "ข้าว + ไข่พะโล้ + ผักลวก", "dessert": "มะละกอสุก"},
    {"main": "ข้าว + ผัดผักรวมใส่หมู", "dessert": "แตงโม"},
    {"main": "ก๋วยเตี๋ยวหมูตุ๋น ใส่ผัก", "dessert": "ฝรั่ง"},
    {"main": "ข้าว + ไก่ทอด + ต้มจืดผัก", "dessert": "สับปะรด"},
    {"main": "ข้าว + แกงเขียวหวานไก่", "dessert": "กล้วยบวชชี"},
    {"main": "ข้าว + หมูผัดขิง + ผักลวก", "dessert": "มะม่วงสุก"},
    {"main": "ข้าวผัดหมู/ไก่ ใส่ผัก", "dessert": "นมจืด + กล้วย"},
    {"main": "ข้าว + ปลาทอด + ต้มจืดฟัก", "dessert": "องุ่น"},
]


def lunch_rate(total: int) -> float:
    """อัตราเงินอุดหนุนต่อหัว/วัน ตามขนาดโรงเรียน (มติ ครม. 8 พ.ย. 2565)"""
    if total <= 0:
        return 0.0
    if total <= 40:
        return 36.0
    if total <= 100:
        return 27.0
    if total <= 120:
        return 24.0
    return 22.0


def _current_academic_year() -> int:
    """ปีการศึกษาปัจจุบัน (พ.ศ.) - เปิดเทอม พ.ค. ถึง มี.ค."""
    now = datetime.now()
    y = now.year + 543
    return y if now.month >= 4 else y - 1


def _ledger_totals(prog: LunchProgram) -> dict:
    rin = sum(l.amount or 0 for l in prog.ledger if l.kind == "in")
    rout = sum(l.amount or 0 for l in prog.ledger if l.kind == "out")
    return {"in": rin, "out": rout, "balance": rin - rout}


# ---------------- หน้าหลัก ----------------
@router.get("/lunch", response_class=HTMLResponse)
def lunch_home(request: Request, db: Session = Depends(get_db)):
    progs = (db.query(LunchProgram)
             .filter((LunchProgram.pool == 0) | (LunchProgram.pool.is_(None)))
             .order_by(LunchProgram.year.desc(), LunchProgram.id.desc()).all())
    rows = [{"p": p, "totals": _ledger_totals(p)} for p in progs]
    return templates.TemplateResponse("lunch_home.html", {
        "request": request, "school": get_school(db), "rows": rows,
        "modes": OPERATE_MODES,
    })


# ---------------- ตั้งค่า/แก้ไขโครงการ ----------------
@router.get("/lunch/setup", response_class=HTMLResponse)
def lunch_setup_new(request: Request, db: Session = Depends(get_db)):
    return _setup_form(request, db, None)


@router.get("/lunch/{pid}/edit", response_class=HTMLResponse)
def lunch_setup_edit(pid: int, request: Request, db: Session = Depends(get_db)):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    return _setup_form(request, db, prog)


def _setup_form(request, db, prog):
    from_roster = False
    if prog and prog.classes:
        levels = [{"level": c.level, "num": c.num_students or 0} for c in prog.classes]
    else:
        # โครงการใหม่: ดึงจำนวนนักเรียนแต่ละชั้นจากทะเบียนนักเรียนกลางให้อัตโนมัติ
        from app.models import Student
        from collections import Counter
        counts = Counter((s.level or "").strip() for s in db.query(Student).all()
                         if (s.level or "").strip())
        ordered = list(DEFAULT_LEVELS) + [lv for lv in counts if lv not in DEFAULT_LEVELS]
        levels = [{"level": lv, "num": counts.get(lv, 0)} for lv in ordered]
        from_roster = bool(counts)
    return templates.TemplateResponse("lunch_setup.html", {
        "request": request, "school": get_school(db), "p": prog,
        "levels": levels, "modes": OPERATE_MODES, "from_roster": from_roster,
        "default_year": prog.year if prog else _current_academic_year(),
    })


@router.post("/lunch/save")
async def lunch_save(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    pid = _to_int(form.get("pid"), 0)
    prog = db.get(LunchProgram, pid) if pid else None
    if not prog:
        prog = LunchProgram()
        db.add(prog)
    prog.year = _to_int(form.get("year"), _current_academic_year())
    prog.days = _to_int(form.get("days"), 200)
    prog.operate_mode = form.get("operate_mode") or "hire"
    prog.funding_org = (form.get("funding_org") or "").strip()
    prog.note = (form.get("note") or "").strip()

    # ระดับชั้น (ล้างของเดิม สร้างใหม่ตามที่กรอก)
    prog.classes.clear()
    db.flush()
    levels = form.getlist("level")
    nums = form.getlist("num")
    total = 0
    for i, lv in enumerate(levels):
        lv = (lv or "").strip()
        n = _to_int(nums[i] if i < len(nums) else 0, 0)
        if not lv:
            continue
        prog.classes.append(LunchClass(seq=i, level=lv, num_students=n))
        total += n

    # อัตราต่อหัว: ถ้ากรอกมาใช้ตามนั้น ไม่งั้นเลือกอัตโนมัติตามขนาด
    rate = _to_float(form.get("rate_per_head"), 0.0)
    prog.rate_per_head = rate if rate > 0 else lunch_rate(total)

    db.commit()
    return RedirectResponse(f"/lunch/{prog.id}", status_code=303)


@router.post("/lunch/{pid}/delete")
def lunch_delete(pid: int, db: Session = Depends(get_db)):
    prog = db.get(LunchProgram, pid)
    if prog:
        # ลบรายการคู่ในการเงินก่อน (cascade ลบ LunchLedger แต่ไม่ลบ FinanceTxn ให้)
        for l in list(prog.ledger):
            _unmirror_finance(db, l)
        db.delete(prog)
        db.commit()
    return RedirectResponse("/lunch", status_code=303)


# ---------------- ภาวะโภชนาการ (เมนูของตัวเอง - ต้องมาก่อน /lunch/{pid}) ----------------
@router.get("/lunch/nutrition", response_class=HTMLResponse)
def nutrition_page(request: Request, db: Session = Depends(get_db), year: str = ""):
    """หน้าภาวะโภชนาการ (อ่าน/เขียนทะเบียนกลางร่วมกับหน้าทะเบียนนักเรียนและสมุดพก ปพ.6)"""
    from app.services import growth
    yr = _to_int(year, 0) or growth.current_academic_year()
    ctx = growth.build_ctx(db, yr)
    ctx.update({"request": request, "school": get_school(db),
                "years": growth.available_years(db), "today_be": be_date_input(datetime.now()),
                "page_title": "ภาวะโภชนาการนักเรียน", "page_url": "/lunch/nutrition",
                "report_url": "/lunch/nutrition/report.docx"})
    return templates.TemplateResponse("growth.html", ctx)


# ---------------- รายละเอียดโครงการ + บัญชีรับ-จ่าย ----------------
@router.get("/lunch/{pid}", response_class=HTMLResponse)
def lunch_detail(pid: int, request: Request, db: Session = Depends(get_db)):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    ledger = sorted(prog.ledger, key=lambda l: (l.date or datetime.min, l.id))
    # ยอดคงเหลือสะสมต่อรายการ
    running = 0.0
    rows = []
    for l in ledger:
        running += (l.amount or 0) if l.kind == "in" else -(l.amount or 0)
        rows.append({"l": l, "running": running})
    return templates.TemplateResponse("lunch_detail.html", {
        "request": request, "school": get_school(db), "p": prog,
        "rows": rows, "totals": _ledger_totals(prog),
        "modes": OPERATE_MODES, "auto_rate": lunch_rate(prog.total_students),
    })


@router.post("/lunch/{pid}/ledger/add")
def lunch_ledger_add(pid: int, db: Session = Depends(get_db),
                     date: str = Form(""), kind: str = Form("in"),
                     detail: str = Form(""), amount: str = Form(""),
                     ref: str = Form("")):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    led = LunchLedger(
        program_id=pid, date=parse_be_date(date) or datetime.now(),
        kind=("out" if kind == "out" else "in"), detail=detail.strip(),
        amount=_to_float(amount, 0.0), ref=ref.strip(),
    )
    db.add(led)
    db.flush()
    _mirror_finance(db, led)     # สะท้อนเข้าบัญชีการเงินหลัก
    db.commit()
    return RedirectResponse(f"/lunch/{pid}", status_code=303)


@router.post("/lunch/ledger/{lid}/delete")
def lunch_ledger_delete(lid: int, db: Session = Depends(get_db)):
    row = db.get(LunchLedger, lid)
    pid = row.program_id if row else None
    if row:
        _delete_ledger(db, row)
        db.commit()
    return RedirectResponse(f"/lunch/{pid}" if pid else "/lunch", status_code=303)


@router.get("/lunch/ledger/{lid}/receipt.docx")
def lunch_receipt_docx(lid: int, db: Session = Depends(get_db)):
    """ใบสำคัญรับเงิน (จากรายการ 'รับ' ในบัญชีอาหารกลางวัน)"""
    from app.services.lunch_receipt import render_lunch_receipt
    led = db.get(LunchLedger, lid)
    if not led:
        return RedirectResponse("/lunch", status_code=303)
    path = render_lunch_receipt(get_school(db), led.program, led)
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ---------------- จ้างเหมารายรอบ ----------------
def _weekday_count(start, end) -> int:
    """นับวันจันทร์-ศุกร์ระหว่างสองวันที่ (รวมปลายทาง) ใช้เสนอจำนวนวันทำการ"""
    if not start or not end or end < start:
        return 0
    n, cur = 0, start
    while cur <= end:
        if cur.weekday() < 5:
            n += 1
        cur = cur.fromordinal(cur.toordinal() + 1)
    return n


LUNCH_ACCOUNT_NAME = "อาหารกลางวัน"


def _ensure_lunch_account(db: Session) -> FinanceAccount:
    """หา/สร้างบัญชี 'อาหารกลางวัน' ในโมดูลการเงิน (ปลายทางที่รายการอาหารกลางวันไปสะท้อน)"""
    acc = db.query(FinanceAccount).filter_by(name=LUNCH_ACCOUNT_NAME).first()
    if not acc:
        acc = FinanceAccount(name=LUNCH_ACCOUNT_NAME, deposit_type="agency",
                             note="เชื่อมอัตโนมัติจากงานอาหารกลางวัน")
        db.add(acc)
        db.flush()
    return acc


def _mirror_finance(db: Session, ledger: LunchLedger) -> None:
    """สร้าง/อัปเดตรายการคู่ใน FinanceTxn (บัญชีอาหารกลางวัน) ให้ตรงกับรายการบัญชีอาหารกลางวัน 1 แถว
    -> ยอดรับ-จ่ายอาหารกลางวันไปโผล่ในงบการเงินรวม/รายงานเงินคงเหลือ"""
    acc = _ensure_lunch_account(db)
    d = ledger.date or datetime.now()
    txn = db.get(FinanceTxn, ledger.finance_txn_id) if ledger.finance_txn_id else None
    if not txn:
        txn = FinanceTxn(account_id=acc.id, fiscal_year=current_fiscal_year(d))
        db.add(txn)
    txn.account_id = acc.id
    txn.fiscal_year = current_fiscal_year(d)
    txn.date = d
    txn.kind = ledger.kind
    txn.amount = ledger.amount or 0
    txn.category = LUNCH_ACCOUNT_NAME
    txn.ref = ledger.ref or ""
    txn.note = ledger.detail or ""
    db.flush()
    ledger.finance_txn_id = txn.id


def _unmirror_finance(db: Session, ledger: LunchLedger) -> None:
    """ลบรายการคู่ในการเงินเมื่อรายการบัญชีอาหารกลางวันถูกลบ"""
    if ledger.finance_txn_id:
        t = db.get(FinanceTxn, ledger.finance_txn_id)
        if t:
            db.delete(t)
        ledger.finance_txn_id = None


def _delete_ledger(db: Session, ledger: LunchLedger) -> None:
    """ลบรายการบัญชีอาหารกลางวัน + รายการคู่ในการเงิน"""
    _unmirror_finance(db, ledger)
    db.delete(ledger)


def _sync_round_procurement(db: Session, rnd: LunchHireRound) -> None:
    """ผูกใบสั่งจ้างของรอบกับ 'เรื่องจัดจ้าง' ในงานพัสดุ เมื่อกรอกเลขที่ใบสั่งจ้างแล้ว
    -> เลขที่ใบสั่งจ้างไปโผล่ในทะเบียนคุมการจัดจ้างอัตโนมัติ (ไม่ต้องสร้างเรื่องเอง)"""
    if not (rnd.order_no or "").strip():
        return   # ยังไม่ออกใบสั่งจ้าง -> ไม่สร้างเรื่อง (กันทะเบียนรก)
    prog = rnd.program
    fy = current_fiscal_year(rnd.order_date) if rnd.order_date else (prog.year or current_fiscal_year())
    subject = f"จ้างเหมาประกอบอาหารกลางวัน รอบที่ {rnd.seq} ปีการศึกษา {prog.year}"
    proc = db.get(Procurement, rnd.procurement_id) if rnd.procurement_id else None
    if not proc:
        proc = Procurement(fiscal_year=fy, subject=subject, proc_type="จ้าง",
                           method="เฉพาะเจาะจง", proc_case="w119t2",
                           budget_source=prog.funding_org or "เงินอุดหนุนอาหารกลางวัน")
        db.add(proc)
        db.flush()
        rnd.procurement_id = proc.id
    proc.fiscal_year = fy
    proc.proc_type = "จ้าง"
    proc.subject = subject
    proc.order_no = (rnd.order_no or "").strip()
    proc.order_date = rnd.order_date
    proc.total_amount = rnd.amount or 0
    proc.vendor_id = rnd.vendor_id
    proc.status = ("เบิกจ่ายแล้ว" if rnd.status == "จ่ายแล้ว"
                   else "อนุมัติ" if rnd.status == "จ้างแล้ว" else "ร่าง")


def _sync_round_ledger(db: Session, rnd: LunchHireRound) -> None:
    """ผูกบัญชีอัตโนมัติ: รอบที่ 'จ่ายแล้ว' -> มีรายการจ่ายในบัญชี (1 รอบ = 1 รายการ)
    ถ้ายังไม่จ่าย/ลบรอบ -> ลบรายการบัญชีที่ผูกไว้"""
    existing = db.query(LunchLedger).filter_by(round_id=rnd.id).first()
    if rnd.status == "จ่ายแล้ว" and (rnd.amount or 0) > 0:
        detail = f"ค่าจ้างเหมาอาหารกลางวัน รอบที่ {rnd.seq}"
        if rnd.start_date and rnd.end_date:
            detail += f" ({be_date_input(rnd.start_date)}-{be_date_input(rnd.end_date)})"
        d = rnd.end_date or rnd.start_date or datetime.now()
        if existing:
            existing.amount = rnd.amount
            existing.detail = detail
            existing.date = d
            existing.procurement_id = rnd.procurement_id
            led = existing
        else:
            led = LunchLedger(program_id=rnd.program_id, round_id=rnd.id, kind="out",
                              detail=detail, amount=rnd.amount, date=d,
                              procurement_id=rnd.procurement_id)
            db.add(led)
        db.flush()
        _mirror_finance(db, led)
    elif existing:
        _delete_ledger(db, existing)


def _lunch_holidays(prog) -> dict:
    """วันหยุดราชการ (ISO ค.ศ.) ครอบคลุมปีการศึกษาของโครงการ (พ.ค.-มี.ค.) เผื่อ +/-1"""
    from app.services.thai_holidays import holiday_map
    base = (prog.year or 2568) - 543
    return holiday_map([base - 1, base, base + 1])


def _rounds_page(request, db, prog, edit=None):
    vendors = db.query(Vendor).order_by(Vendor.name).all()
    paid = sum(r.amount or 0 for r in prog.rounds if r.status == "จ่ายแล้ว")
    committed = sum(r.amount or 0 for r in prog.rounds)
    return templates.TemplateResponse("lunch_rounds.html", {
        "request": request, "school": get_school(db), "p": prog,
        "rounds": prog.rounds, "vendors": vendors, "periods": PERIOD_TYPES,
        "edit": edit, "paid": paid, "committed": committed,
        "default_period": "month", "holidays": _lunch_holidays(prog),
    })


@router.get("/lunch/{pid}/rounds", response_class=HTMLResponse)
def rounds_page(pid: int, request: Request, db: Session = Depends(get_db)):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    return _rounds_page(request, db, prog)


@router.get("/lunch/round/{rid}/edit", response_class=HTMLResponse)
def round_edit(rid: int, request: Request, db: Session = Depends(get_db)):
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    return _rounds_page(request, db, rnd.program, edit=rnd)


def _maybe_new_vendor(db, form):
    """ถ้ากรอกชื่อผู้รับจ้างใหม่ในฟอร์ม -> สร้าง Vendor แล้วคืน id (ไม่งั้นคืน None)"""
    name = (form.get("nv_name") or "").strip()
    if not name:
        return None
    v = Vendor(
        name=name,
        owner_name=(form.get("nv_owner") or "").strip(),
        tax_id=(form.get("nv_tax") or "").strip(),
        phone=(form.get("nv_phone") or "").strip(),
        address=(form.get("nv_address") or "").strip(),
        bank_account=(form.get("nv_bank") or "").strip(),
    )
    db.add(v)
    db.flush()
    return v.id


def _populate_round(rnd, form, db):
    rnd.period_type = form.get("period_type") or "month"
    rnd.start_date = parse_be_date(form.get("start_date") or "")
    rnd.end_date = parse_be_date(form.get("end_date") or "")
    rnd.days = _to_int(form.get("days"), 0)
    new_vid = _maybe_new_vendor(db, form)
    rnd.vendor_id = new_vid or (_to_int(form.get("vendor_id"), 0) or None)
    rnd.amount = _to_float(form.get("amount"), 0.0)
    rnd.procurement_id = _to_int(form.get("procurement_id"), 0) or None
    rnd.order_no = (form.get("order_no") or "").strip()
    rnd.order_date = parse_be_date(form.get("order_date") or "")
    rnd.status = form.get("status") or "ร่าง"
    rnd.note = (form.get("note") or "").strip()


@router.post("/lunch/{pid}/rounds/add")
async def round_add(pid: int, request: Request, db: Session = Depends(get_db)):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    form = await request.form()
    seq = max([r.seq for r in prog.rounds], default=0) + 1
    rnd = LunchHireRound(program_id=pid, seq=seq)
    _populate_round(rnd, form, db)
    db.add(rnd)
    db.flush()
    _sync_round_procurement(db, rnd)   # ผูกเรื่องจัดจ้าง (ถ้ามีเลขใบสั่งจ้าง)
    _sync_round_ledger(db, rnd)
    db.commit()
    return RedirectResponse(f"/lunch/{pid}/rounds", status_code=303)


@router.post("/lunch/round/{rid}/update")
async def round_update(rid: int, request: Request, db: Session = Depends(get_db)):
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    form = await request.form()
    _populate_round(rnd, form, db)
    _sync_round_procurement(db, rnd)   # ผูก/อัปเดตเรื่องจัดจ้าง (ถ้ามีเลขใบสั่งจ้าง)
    _sync_round_ledger(db, rnd)
    db.commit()
    return RedirectResponse(f"/lunch/{rnd.program_id}/rounds", status_code=303)


@router.post("/lunch/round/{rid}/status")
async def round_set_status(rid: int, request: Request, db: Session = Depends(get_db),
                           status: str = Form("")):
    """เปลี่ยนสถานะรอบตรงจากตาราง (ร่าง/จ้างแล้ว/จ่ายแล้ว) - เปลี่ยนกลับไปมาได้
    ซิงก์เรื่องจัดจ้าง + บัญชีให้อัตโนมัติ (จ่ายแล้ว->ลงบัญชี, ถอย->ลบรายการบัญชี)"""
    rnd = db.get(LunchHireRound, rid)
    ok = False
    if rnd and status.strip() in ("ร่าง", "จ้างแล้ว", "จ่ายแล้ว"):
        rnd.status = status.strip()
        _sync_round_procurement(db, rnd)
        _sync_round_ledger(db, rnd)
        db.commit()
        ok = True
    if request.headers.get("X-Requested-With") == "fetch":
        return JSONResponse({"ok": ok})
    return RedirectResponse(f"/lunch/{rnd.program_id}/rounds" if rnd else "/lunch", status_code=303)


@router.post("/lunch/round/{rid}/delete")
def round_delete(rid: int, db: Session = Depends(get_db)):
    rnd = db.get(LunchHireRound, rid)
    pid = rnd.program_id if rnd else None
    if rnd:
        # ลบรายการบัญชี (+ รายการคู่ในการเงิน) ที่ผูกกับรอบนี้ รวมงวดย่อยด้วย
        insts = {i.id for i in rnd.installments}
        for l in db.query(LunchLedger).filter_by(round_id=rnd.id).all():
            _delete_ledger(db, l)
        for iid in insts:
            for l in db.query(LunchLedger).filter_by(installment_id=iid).all():
                _delete_ledger(db, l)
        # ลบเรื่องจัดจ้างที่ระบบผูกให้อัตโนมัติ (เฉพาะที่เราสร้างเอง = w119t2 อาหารกลางวัน)
        if rnd.procurement_id:
            proc = db.get(Procurement, rnd.procurement_id)
            if proc and proc.proc_case == "w119t2" and "อาหารกลางวัน" in (proc.subject or ""):
                db.delete(proc)
        db.delete(rnd)
        db.commit()
    return RedirectResponse(f"/lunch/{pid}/rounds" if pid else "/lunch", status_code=303)


# ---------------- เมนู/สำรับ ----------------
@router.get("/lunch/{pid}/menu", response_class=HTMLResponse)
def menu_page(pid: int, request: Request, db: Session = Depends(get_db),
              edit: int | None = None):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    edit_row = db.get(LunchMenu, edit) if edit else None
    if edit_row and edit_row.program_id != pid:
        edit_row = None
    # คลังเมนูที่เคยใช้ (ทุกโครงการของโรงเรียน) เลือกใช้ซ้ำได้ ไม่ต้องพิมพ์ใหม่
    seen, past = set(), []
    for mm in db.query(LunchMenu).order_by(LunchMenu.id.desc()).all():
        key = (mm.main or "").strip()
        if key and key not in seen:
            seen.add(key)
            past.append({"main": key, "dessert": (mm.dessert or "").strip()})
    desserts = sorted({(mm.dessert or "").strip() for mm in db.query(LunchMenu).all() if (mm.dessert or "").strip()})
    # แต่ละเมนู: หมู่ที่ครบ + หมู่ที่ขาด (ตาม 5 หมู่)
    menu_rows = []
    for m in prog.menus:
        got = [g for g in (m.groups or "").split(",") if g in FOOD_GROUPS]
        missing = [FOOD_GROUPS[g] for g in FOOD_GROUPS if g not in got]
        menu_rows.append({"m": m, "got": got, "missing": missing})
    # prefill ช่วงวันจาก "รอบจ้างล่าสุด" (รอบที่เริ่มช้าสุด = รอบที่กำลังทำอยู่)
    # ไม่ใช้รอบแรกสุด เพราะจะย้อนไปสร้างเมนูรอบเก่าที่ผ่านไปแล้ว
    rounds_with_start = [r for r in prog.rounds if r.start_date]
    latest_round = max(rounds_with_start, key=lambda r: r.start_date) if rounds_with_start else None
    term_start = latest_round.start_date if latest_round else None
    term_end = latest_round.end_date if latest_round else None
    # วันที่ตั้งต้นในฟอร์มเพิ่มเมนู: วันเปิดเรียนถัดจากเมนูล่าสุด (กรอกไล่วันได้เลย ไม่ต้องแก้)
    # ถ้ายังไม่มีเมนู -> วันเริ่มรอบล่าสุด · ถ้าไม่มีรอบ -> วันนี้
    from app.services.thai_holidays import next_workday
    from datetime import timedelta
    menu_dates = [m.date for m in prog.menus if m.date]
    if menu_dates:
        base = (max(menu_dates) + timedelta(days=1)).date()
    elif term_start:
        base = term_start.date()
    else:
        base = datetime.now().date()
    nd = next_workday(base, None)
    default_menu_date = datetime(nd.year, nd.month, nd.day)
    return templates.TemplateResponse("lunch_menu.html", {
        "request": request, "school": get_school(db), "p": prog,
        "menu_rows": menu_rows, "edit": edit_row, "past_menus": past, "desserts": desserts,
        "food_groups": FOOD_GROUPS,
        "edit_groups": [g for g in (edit_row.groups or "").split(",")] if edit_row else [],
        "today_be": be_date_input(default_menu_date),
        "term_start_be": be_date_input(term_start) if term_start else "",
        "term_end_be": be_date_input(term_end) if term_end else "",
        "menu_count": len(menu_rows),
        "filled": request.query_params.get("filled"),
    })


def _clean_groups(groups) -> str:
    return ",".join(g for g in FOOD_GROUPS if g in (groups or []))


def _safe_back(back: str, default: str) -> str:
    """คืน path ภายในระบบเท่านั้น (กัน open-redirect)"""
    b = (back or "").strip()
    return b if b.startswith("/") and not b.startswith("//") else default


@router.post("/lunch/{pid}/menu/add")
def menu_add(pid: int, db: Session = Depends(get_db),
             date: str = Form(""), main: str = Form(""), dessert: str = Form(""),
             note: str = Form(""), groups: list[str] = Form([]), back: str = Form("")):
    if not db.get(LunchProgram, pid):
        return RedirectResponse("/lunch", status_code=303)
    db.add(LunchMenu(program_id=pid, date=parse_be_date(date), main=main.strip(),
                     dessert=dessert.strip(), note=note.strip(), groups=_clean_groups(groups)))
    db.commit()
    return RedirectResponse(_safe_back(back, f"/lunch/{pid}/menu"), status_code=303)


@router.post("/lunch/{pid}/menu/fill-term")
def menu_fill_term(pid: int, db: Session = Depends(get_db),
                   cycle_size: str = Form("5"), start_date: str = Form(""),
                   end_date: str = Form(""), skip_holiday: str = Form("")):
    """สร้างเมนูทั้งสัญญาแบบหมุนเวียนรายสัปดาห์:
    เอา N เมนูแรกเป็นชุดหมุนเวียน ไล่ใส่ทุกวันเปิดเรียน (ข้ามเสาร์-อาทิตย์ + วันหยุดถ้าเลือก)
    ผูกเมนูกับ 'ลำดับวันเปิดเรียน' -> วันจันทร์ทุกสัปดาห์ได้เมนูเดียวกัน (เมื่อชุด=5)
    ข้ามวันที่ที่มีเมนูอยู่แล้ว (ไม่ทับ)"""
    from datetime import timedelta
    from app.services.thai_holidays import is_workday
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    n = max(1, _to_int(cycle_size, 5))
    # ชุดหมุนเวียน = เมนูตั้งต้นที่ยังไม่มีวันที่ (ที่ผู้ใช้เพิ่มไว้เป็นชุด) ถ้าไม่มีค่อยใช้เมนูที่มีวันที่
    dateless = sorted((m for m in prog.menus if not m.date), key=lambda m: m.id)
    dated = sorted((m for m in prog.menus if m.date), key=lambda m: (m.date, m.id))
    source = dateless or dated
    cycle = [(m.main, m.dessert, m.groups) for m in source[:n]]
    s = parse_be_date(start_date)
    e = parse_be_date(end_date)
    if not cycle or not s or not e or e < s:
        return RedirectResponse(f"/lunch/{pid}/menu?filled=0", status_code=303)
    hol = _lunch_holidays(prog) if skip_holiday else None
    existing = {m.date.date() for m in prog.menus if m.date}
    d, end = s.date(), e.date()
    ordinal, created = 0, 0
    while d <= end:
        weekend = d.weekday() >= 5
        holiday = bool(hol) and d.isoformat() in hol
        if not weekend and not holiday:
            if d not in existing:
                main, dessert, groups = cycle[ordinal % len(cycle)]
                db.add(LunchMenu(program_id=pid, date=datetime(d.year, d.month, d.day),
                                 main=main, dessert=dessert, groups=groups))
                existing.add(d)
                created += 1
            ordinal += 1
        d += timedelta(days=1)
    # เมนูตั้งต้นที่ไม่มีวันที่ = แค่ชุดตั้งต้นสำหรับหมุนเวียน เมื่อกระจายลงวันแล้วลบทิ้งให้อัตโนมัติ
    if created:
        db.query(LunchMenu).filter(LunchMenu.program_id == pid,
                                   LunchMenu.date.is_(None)).delete(synchronize_session=False)
    db.commit()
    return RedirectResponse(f"/lunch/{pid}/menu?filled={created}", status_code=303)


@router.post("/lunch/{pid}/menu/delete-all")
def menu_delete_all(pid: int, db: Session = Depends(get_db)):
    """ลบเมนูทั้งหมดของโครงการทีเดียว (เช่น สร้างวนผิดช่วง อยากเริ่มใหม่)"""
    if db.get(LunchProgram, pid):
        db.query(LunchMenu).filter_by(program_id=pid).delete(synchronize_session=False)
        db.commit()
    return RedirectResponse(f"/lunch/{pid}/menu", status_code=303)


@router.post("/lunch/menu/{mid}/update")
def menu_update(mid: int, db: Session = Depends(get_db),
                date: str = Form(""), main: str = Form(""), dessert: str = Form(""),
                note: str = Form(""), groups: list[str] = Form([])):
    m = db.get(LunchMenu, mid)
    if not m:
        return RedirectResponse("/lunch", status_code=303)
    m.date = parse_be_date(date)
    m.main = main.strip()
    m.dessert = dessert.strip()
    m.note = note.strip()
    m.groups = _clean_groups(groups)
    db.commit()
    return RedirectResponse(f"/lunch/{m.program_id}/menu", status_code=303)


@router.post("/lunch/menu/{mid}/delete")
def menu_delete(mid: int, db: Session = Depends(get_db), back: str = Form("")):
    m = db.get(LunchMenu, mid)
    pid = m.program_id if m else None
    if m:
        db.delete(m)
        db.commit()
    return RedirectResponse(_safe_back(back, f"/lunch/{pid}/menu" if pid else "/lunch"), status_code=303)


@router.get("/lunch/{pid}/menu/print", response_class=HTMLResponse)
def menu_print(pid: int, request: Request, db: Session = Depends(get_db)):
    prog = db.get(LunchProgram, pid)
    if not prog:
        return RedirectResponse("/lunch", status_code=303)
    return templates.TemplateResponse("lunch_menu_print.html", {
        "request": request, "school": get_school(db), "p": prog,
        "menus": sorted(prog.menus, key=lambda m: (m.date or datetime.min)),
    })


# ---------------- ภาวะโภชนาการ ----------------
# ตรรกะภาวะโภชนาการย้ายไป app/services/growth.py (เก็บข้อมูลที่ทะเบียนนักเรียนกลาง
# ใช้ร่วมกับหน้าทะเบียนนักเรียนและสมุดพก ปพ.6) · หน้านี้เป็นเพียงมุมมองของงานอาหารกลางวัน


@router.get("/lunch/nutrition/report.docx")
def nutrition_report_docx(db: Session = Depends(get_db), year: str = ""):
    from app.services.nutrition_report import render_nutrition_report
    from app.services import growth
    yr = _to_int(year, 0) or growth.current_academic_year()
    cats, class_counts, sex_counts, totals, assessed = growth.report_data(db, yr)
    path = render_nutrition_report(get_school(db), cats, class_counts, sex_counts, totals, assessed,
                                   as_of=datetime.now())
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# หมายเหตุ: การเพิ่ม/แก้ไข/ลบนักเรียน และบันทึกการชั่ง ย้ายไปหน้าทะเบียนนักเรียนกลาง
# (/students, /students/{id}/measure) แล้ว · หน้าอาหารกลางวันแสดงข้อมูลชุดเดียวกัน


# ---------------- งวดงานย่อยในสัญญา ----------------
def _sync_installment_ledger(db: Session, inst: LunchInstallment) -> None:
    """ผูกบัญชีอัตโนมัติรายงวด: งวด 'จ่ายแล้ว' -> รายการจ่ายในบัญชี ; ไม่งั้นลบ"""
    existing = db.query(LunchLedger).filter_by(installment_id=inst.id).first()
    if inst.status == "จ่ายแล้ว" and (inst.amount or 0) > 0:
        detail = f"ค่าจ้างเหมาอาหารกลางวัน งวดที่ {inst.seq}"
        if inst.start_date and inst.end_date:
            detail += f" ({be_date_input(inst.start_date)}-{be_date_input(inst.end_date)})"
        d = inst.inspect_date or inst.end_date or datetime.now()
        rnd = inst.round
        if existing:
            existing.amount = inst.amount
            existing.detail = detail
            existing.date = d
            existing.procurement_id = rnd.procurement_id if rnd else None
            led = existing
        else:
            led = LunchLedger(program_id=inst.round.program_id, installment_id=inst.id,
                              kind="out", detail=detail, amount=inst.amount, date=d,
                              procurement_id=inst.round.procurement_id)
            db.add(led)
        db.flush()
        _mirror_finance(db, led)
    elif existing:
        _delete_ledger(db, existing)


@router.get("/lunch/round/{rid}/plan", response_class=HTMLResponse)
def contract_plan(rid: int, request: Request, db: Session = Depends(get_db)):
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    from app.models import Person
    paid = sum(i.amount or 0 for i in rnd.installments if i.status == "จ่ายแล้ว")
    committees = {k: [m for m in rnd.committees if m.kind == k] for k in COMMITTEE_KINDS}
    # รอบอื่นในโครงการเดียวกันที่มีกรรมการอยู่แล้ว (ไว้ดึงมาใช้ ไม่ต้องกรอกใหม่)
    other_rounds = [{"id": r2.id, "seq": r2.seq, "count": len(r2.committees)}
                    for r2 in sorted(rnd.program.rounds, key=lambda x: x.seq)
                    if r2.id != rnd.id and r2.committees]
    persons = db.query(Person).order_by(Person.name).all()
    sel_kind = request.query_params.get("kind")
    if sel_kind not in COMMITTEE_KINDS:
        sel_kind = "tor"

    # ---- เมนูอาหารในช่วงสัญญา (ให้สร้างเมนูต่อจากงวดในหน้าเดียว + เลือกวันจาก dropdown) ----
    from datetime import timedelta
    from app.services.thai_holidays import is_workday
    prog = rnd.program
    holset = set(_lunch_holidays(prog).keys())
    have = {m.date.date().isoformat(): m for m in prog.menus if m.date}
    menu_days = []
    if rnd.start_date and rnd.end_date:
        d, end = rnd.start_date.date(), rnd.end_date.date()
        while d <= end:
            if is_workday(d, holset):
                menu_days.append({"be": be_date_input(datetime(d.year, d.month, d.day)),
                                  "has": d.isoformat() in have})
            d += timedelta(days=1)
    round_menus = sorted(
        [m for m in prog.menus if m.date and rnd.start_date and rnd.end_date
         and rnd.start_date <= m.date <= rnd.end_date],
        key=lambda m: (m.date or datetime.min))
    past_mains = sorted({(m.main or "").strip() for m in prog.menus if (m.main or "").strip()})
    past_desserts = sorted({(m.dessert or "").strip() for m in prog.menus if (m.dessert or "").strip()})

    return templates.TemplateResponse("lunch_contract.html", {
        "request": request, "school": get_school(db), "r": rnd, "p": rnd.program,
        "installments": rnd.installments, "paid": paid,
        "committed": sum(i.amount or 0 for i in rnd.installments),
        "committees": committees, "com_kinds": COMMITTEE_KINDS, "com_roles": COMMITTEE_ROLES,
        "other_rounds": other_rounds,
        "persons": persons, "persons_pos": {p.name: p.position for p in persons},
        "sel_kind": sel_kind,
        "holidays": _lunch_holidays(rnd.program),
        "today_be": be_date_input(datetime.now()),
        "menu_days": menu_days, "round_menus": round_menus,
        "past_mains": past_mains, "past_desserts": past_desserts,
    })


@router.post("/lunch/round/{rid}/installment/add")
def installment_add(rid: int, db: Session = Depends(get_db),
                    start_date: str = Form(""), end_date: str = Form(""),
                    days: str = Form(""), amount: str = Form(""),
                    deliver_date: str = Form(""), inspect_date: str = Form(""),
                    status: str = Form("ร่าง")):
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    seq = max([i.seq for i in rnd.installments], default=0) + 1
    inst = LunchInstallment(
        round_id=rid, seq=seq, start_date=parse_be_date(start_date),
        end_date=parse_be_date(end_date), days=_to_int(days, 0),
        amount=_to_float(amount, 0.0), deliver_date=parse_be_date(deliver_date),
        inspect_date=parse_be_date(inspect_date), status=status)
    db.add(inst)
    db.flush()
    _sync_installment_ledger(db, inst)
    db.commit()
    return RedirectResponse(f"/lunch/round/{rid}/plan", status_code=303)


@router.post("/lunch/round/{rid}/installments/auto")
def installments_auto(rid: int, db: Session = Depends(get_db),
                      start_date: str = Form(""), n_inst: str = Form(""), days_each: str = Form("")):
    """แบ่งงวดอัตโนมัติ: กรอกจำนวนงวด + จำนวนวันต่องวด -> สร้างงวดพร้อมช่วงวัน (ไม่นับวันหยุด)"""
    from app.services.thai_holidays import generate_installment_ranges
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    start = parse_be_date(start_date) or rnd.start_date
    n = _to_int(n_inst, 0)
    de = _to_int(days_each, 0)
    if start and n > 0 and de > 0:
        hol = set(_lunch_holidays(rnd.program).keys())
        ranges = generate_installment_ranges(start, n, de, hol)
        seq0 = max([i.seq for i in rnd.installments], default=0)
        prog = rnd.program
        rate = float(prog.rate_per_head or 0)
        students = int(prog.total_students or 0)
        for k, (s, e) in enumerate(ranges):
            end_dt = datetime(e.year, e.month, e.day)
            inst = LunchInstallment(
                round_id=rid, seq=seq0 + k + 1,
                start_date=datetime(s.year, s.month, s.day), end_date=end_dt,
                days=de, amount=round(de * students * rate, 2), status="ร่าง",
                deliver_date=end_dt, inspect_date=end_dt)   # ปกติส่งมอบ/ตรวจรับวันสุดท้ายของงวด (แก้ได้)
            db.add(inst)
        db.commit()
    return RedirectResponse(f"/lunch/round/{rid}/plan", status_code=303)


@router.post("/lunch/installment/{iid}/update")
async def installment_update(iid: int, request: Request, db: Session = Depends(get_db)):
    """อัปเดตงวด - เติมเฉพาะช่องที่ส่งมา (รองรับทั้งฟอร์มเต็มและแก้เฉพาะสถานะ/วันในตาราง)"""
    form = await request.form()
    inst = db.get(LunchInstallment, iid)
    if not inst:
        return RedirectResponse("/lunch", status_code=303)

    def has(k):
        return k in form

    def val(k):
        return (form.get(k) or "").strip()

    if has("start_date"):
        inst.start_date = parse_be_date(val("start_date"))
    if has("end_date"):
        inst.end_date = parse_be_date(val("end_date"))
    if has("days"):
        inst.days = _to_int(val("days"), 0)
    if has("amount"):
        inst.amount = _to_float(val("amount"), 0.0)
    if has("deliver_date"):
        inst.deliver_date = parse_be_date(val("deliver_date"))
    if has("inspect_date"):
        inst.inspect_date = parse_be_date(val("inspect_date"))
    if has("status"):
        inst.status = val("status")
    _sync_installment_ledger(db, inst)
    db.commit()
    if request.headers.get("x-requested-with") == "fetch":
        return JSONResponse({"ok": True})
    return RedirectResponse(f"/lunch/round/{inst.round_id}/plan", status_code=303)


@router.post("/lunch/installment/{iid}/delete")
def installment_delete(iid: int, db: Session = Depends(get_db)):
    inst = db.get(LunchInstallment, iid)
    rid = inst.round_id if inst else None
    if inst:
        for l in db.query(LunchLedger).filter_by(installment_id=inst.id).all():
            _delete_ledger(db, l)
        db.delete(inst)
        db.commit()
    return RedirectResponse(f"/lunch/round/{rid}/plan" if rid else "/lunch", status_code=303)


@router.get("/lunch/installment/{iid}/doc")
def installment_doc(iid: int, db: Session = Depends(get_db)):
    """ออกเอกสาร 'งวด X' (ควบคุม+ส่งมอบ+ตรวจรับ) พร้อมเมนูรายวันในช่วงงวด"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.lunch_doc import render_installment_doc
    inst = db.get(LunchInstallment, iid)
    if not inst:
        return RedirectResponse("/lunch", status_code=303)
    prog = inst.round.program
    menus = [m for m in prog.menus
             if m.date and inst.start_date and inst.end_date
             and inst.start_date <= m.date <= inst.end_date]
    menus.sort(key=lambda m: m.date)
    if prog.operate_mode == "person":
        from app.services.lunch_person_doc import render_p_installment
        path = render_p_installment(inst, get_school(db), menus)
    else:
        path = render_installment_doc(inst, get_school(db), menus)
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/lunch/installment/{iid}/disburse-doc")
def installment_disburse_doc(iid: int, db: Session = Depends(get_db)):
    """ออกเอกสารขอเบิกจ่ายรายงวด (บันทึก+ใบสำคัญรับเงิน+หนังสือรับรองหักภาษี)"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.lunch_doc import render_disburse_lunch_doc
    inst = db.get(LunchInstallment, iid)
    if not inst:
        return RedirectResponse("/lunch", status_code=303)
    if inst.round.program.operate_mode == "person":
        from app.services.lunch_person_doc import render_p_disburse
        path = render_p_disburse(inst, get_school(db))
    else:
        path = render_disburse_lunch_doc(inst, get_school(db))
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/lunch/round/{rid}/order-doc")
def contract_order_doc(rid: int, db: Session = Depends(get_db)):
    """ออกใบสั่งจ้าง (สัญญาต่อรอบ)"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.lunch_doc import render_order_doc
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    path = render_order_doc(rnd, get_school(db))
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# ---------------- คณะกรรมการในสัญญา ----------------
COMMITTEE_KINDS = {"tor": "จัดทำขอบเขตของงาน (TOR)", "control": "ควบคุมงาน", "inspect": "ตรวจรับ"}
COMMITTEE_ROLES = ["ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"]


@router.post("/lunch/round/{rid}/committee/add")
def committee_add(rid: int, db: Session = Depends(get_db),
                  kind: str = Form("inspect"), name: str = Form(""),
                  position: str = Form("ครู"), role: str = Form("กรรมการ")):
    from app.models import LunchCommittee
    rnd = db.get(LunchHireRound, rid)
    if not rnd or not name.strip():
        return RedirectResponse(f"/lunch/round/{rid}/plan", status_code=303)
    seq = max([m.seq for m in rnd.committees if m.kind == kind], default=0) + 1
    db.add(LunchCommittee(round_id=rid, kind=kind, seq=seq, name=name.strip(),
                          position=position.strip() or "ครู", role=role or "กรรมการ"))
    db.commit()
    return RedirectResponse(f"/lunch/round/{rid}/plan?kind={kind}#committee", status_code=303)


@router.post("/lunch/round/{rid}/committee/pull")
def committee_pull(rid: int, db: Session = Depends(get_db), src_round: str = Form("")):
    """คัดลอกกรรมการทุกชุด (TOR/ควบคุมงาน/ตรวจรับ) จากรอบอื่นในโครงการเดียวกันมาใส่รอบนี้
    ข้ามชื่อที่ซ้ำ (kind เดียวกัน) ไม่ให้เพิ่มซ้ำ"""
    from app.models import LunchCommittee
    rnd = db.get(LunchHireRound, rid)
    src = db.get(LunchHireRound, _to_int(src_round, 0))
    if not rnd or not src or src.id == rnd.id or src.program_id != rnd.program_id:
        return RedirectResponse(f"/lunch/round/{rid}/plan#committee", status_code=303)
    existing = {(m.kind, (m.name or "").strip()) for m in rnd.committees}
    seq_by_kind = {}
    for c in rnd.committees:
        seq_by_kind[c.kind] = max(seq_by_kind.get(c.kind, 0), c.seq)
    for m in sorted(src.committees, key=lambda x: (x.kind, x.seq)):
        key = (m.kind, (m.name or "").strip())
        if not key[1] or key in existing:
            continue
        seq_by_kind[m.kind] = seq_by_kind.get(m.kind, 0) + 1
        db.add(LunchCommittee(round_id=rid, kind=m.kind, seq=seq_by_kind[m.kind],
                              name=m.name, position=m.position, role=m.role))
        existing.add(key)
    db.commit()
    return RedirectResponse(f"/lunch/round/{rid}/plan#committee", status_code=303)


@router.post("/lunch/committee/{cid}/delete")
def committee_delete(cid: int, db: Session = Depends(get_db)):
    from app.models import LunchCommittee
    m = db.get(LunchCommittee, cid)
    rid = m.round_id if m else None
    kind = m.kind if m else ""
    if m:
        db.delete(m)
        db.commit()
    return RedirectResponse(f"/lunch/round/{rid}/plan?kind={kind}#committee" if rid else "/lunch",
                           status_code=303)


@router.get("/lunch/round/{rid}/committee-doc")
def committee_order_doc(rid: int, db: Session = Depends(get_db)):
    """ออกคำสั่งแต่งตั้งคณะกรรมการ (3 คำสั่ง: TOR/ควบคุมงาน/ตรวจรับ)"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.lunch_doc import render_committee_order_doc
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    path = render_committee_order_doc(rnd, get_school(db))
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/lunch/round/{rid}/hire-report-doc")
def contract_hire_report_doc(rid: int, db: Session = Depends(get_db)):
    """ออกรายงานขอจ้าง (บันทึกข้อความเปิดเรื่อง)"""
    from pathlib import Path
    from fastapi.responses import FileResponse
    from app.services.lunch_doc import render_hire_report_doc
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    path = render_hire_report_doc(rnd, get_school(db))
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _round_docfile(rid, db, render_name):
    from pathlib import Path
    from fastapi.responses import FileResponse
    import app.services.lunch_doc as ld
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    path = getattr(ld, render_name)(rnd, get_school(db))
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.get("/lunch/round/{rid}/winner-doc")
def contract_winner_doc(rid: int, db: Session = Depends(get_db)):
    return _round_docfile(rid, db, "render_winner_doc")


@router.get("/lunch/round/{rid}/result-doc")
def contract_result_doc(rid: int, db: Session = Depends(get_db)):
    return _round_docfile(rid, db, "render_result_doc")


@router.get("/lunch/round/{rid}/tor-request-doc")
def contract_tor_request_doc(rid: int, db: Session = Depends(get_db)):
    return _round_docfile(rid, db, "render_tor_request_doc")


@router.get("/lunch/round/{rid}/tor-doc")
def contract_tor_doc(rid: int, db: Session = Depends(get_db)):
    return _round_docfile(rid, db, "render_tor_doc")


@router.get("/lunch/round/{rid}/quotation-doc")
def contract_quotation_doc(rid: int, db: Session = Depends(get_db)):
    return _round_docfile(rid, db, "render_quotation_doc")


@router.get("/lunch/round/{rid}/bundle-doc")
def contract_bundle_doc(rid: int, db: Session = Depends(get_db)):
    """ออกเอกสารต่อรอบทั้งชุดเป็นไฟล์เดียว"""
    return _round_docfile(rid, db, "render_contract_bundle")


# ---------------- เอกสารรูปแบบ 1: ซื้อวัตถุดิบ (ยืมเงิน->ส่งใช้) ----------------
def _round_ingredient_doc(rid, db, render_name):
    from pathlib import Path
    from fastapi.responses import FileResponse
    import app.services.lunch_ingredient_doc as ig
    rnd = db.get(LunchHireRound, rid)
    if not rnd:
        return RedirectResponse("/lunch", status_code=303)
    path = getattr(ig, render_name)(rnd, get_school(db))
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# kind -> ฟังก์ชัน สำหรับเอกสารซื้อวัตถุดิบ
_INGREDIENT_DOCS = {
    "borrow": "render_borrow_memo", "estimate": "render_estimate",
    "purchase": "render_purchase_form", "material": "render_material_report_form",
    "receipt": "render_receipt_form", "control": "render_control_report",
    "repay": "render_repay_memo", "bundle": "render_ingredient_bundle",
}


@router.get("/lunch/round/{rid}/ingredient-doc/{kind}")
def contract_ingredient_doc(rid: int, kind: str, db: Session = Depends(get_db)):
    render_name = _INGREDIENT_DOCS.get(kind)
    if not render_name:
        return RedirectResponse(f"/lunch/round/{rid}/plan", status_code=303)
    return _round_ingredient_doc(rid, db, render_name)


# ---------------- เอกสารรูปแบบ 2: จ้างบุคคล (แม่ครัว) ----------------
_PERSON_DOCS = {
    "tor": "render_p_tor", "hire-report": "render_p_hire_report",
    "quotation": "render_p_quotation", "result": "render_p_result",
    "winner": "render_p_winner", "order": "render_p_order",
    "bundle": "render_person_bundle",
}


@router.get("/lunch/round/{rid}/person-doc/{kind}")
def contract_person_doc(rid: int, kind: str, db: Session = Depends(get_db)):
    from pathlib import Path
    from fastapi.responses import FileResponse
    import app.services.lunch_person_doc as pd
    render_name = _PERSON_DOCS.get(kind)
    rnd = db.get(LunchHireRound, rid)
    if not render_name or not rnd:
        return RedirectResponse(f"/lunch/round/{rid}/plan", status_code=303)
    path = getattr(pd, render_name)(rnd, get_school(db))
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
