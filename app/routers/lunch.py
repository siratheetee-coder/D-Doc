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
from fastapi.responses import HTMLResponse, RedirectResponse
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
def nutrition_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("lunch_nutrition.html",
                                      _nutrition_ctx(request, db, _nutrition_pool(db)))


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
    return templates.TemplateResponse("lunch_menu.html", {
        "request": request, "school": get_school(db), "p": prog,
        "menu_rows": menu_rows, "edit": edit_row, "past_menus": past, "desserts": desserts,
        "food_groups": FOOD_GROUPS, "std_menus": STD_MENUS,
        "edit_groups": [g for g in (edit_row.groups or "").split(",")] if edit_row else [],
        "today_be": be_date_input(datetime.now()),
    })


def _clean_groups(groups) -> str:
    return ",".join(g for g in FOOD_GROUPS if g in (groups or []))


@router.post("/lunch/{pid}/menu/add")
def menu_add(pid: int, db: Session = Depends(get_db),
             date: str = Form(""), main: str = Form(""), dessert: str = Form(""),
             note: str = Form(""), groups: list[str] = Form([])):
    if not db.get(LunchProgram, pid):
        return RedirectResponse("/lunch", status_code=303)
    db.add(LunchMenu(program_id=pid, date=parse_be_date(date), main=main.strip(),
                     dessert=dessert.strip(), note=note.strip(), groups=_clean_groups(groups)))
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
def menu_delete(mid: int, db: Session = Depends(get_db)):
    m = db.get(LunchMenu, mid)
    pid = m.program_id if m else None
    if m:
        db.delete(m)
        db.commit()
    return RedirectResponse(f"/lunch/{pid}/menu" if pid else "/lunch", status_code=303)


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
def _measure_result(stu, m):
    """จัดกลุ่มภาวะโภชนาการของการชั่ง 1 ครั้ง (คืน dict ผล + อายุ)"""
    if not m or not m.weight or not m.height:
        return None
    return classify_all(stu.sex, stu.birthdate, m.weight, m.height, m.date)


# น้ำหนักตามเกณฑ์ส่วนสูง: สมส่วน (index 2) = ดีที่สุด · ยิ่งห่างยิ่งเสี่ยง
_WH_ORDER = {lbl: i for i, lbl in enumerate(WH_LABELS)}
_WH_RISK = {"ผอม", "ค่อนข้างผอม", "เริ่มอ้วน", "อ้วน"}   # กลุ่มเฝ้าระวัง


def _wh_trend(res):
    """เทียบน้ำหนัก/ส่วนสูง เทอม 1 -> เทอม 2 : up=ดีขึ้น / down=แย่ลง / same=คงที่ / None=ข้อมูลไม่พอ"""
    r1, r2 = res.get(1), res.get(2)
    if not (r1 and r2 and r1.get("wh") in _WH_ORDER and r2.get("wh") in _WH_ORDER):
        return None
    d1 = abs(_WH_ORDER[r1["wh"]] - 2)
    d2 = abs(_WH_ORDER[r2["wh"]] - 2)
    return "up" if d2 < d1 else "down" if d2 > d1 else "same"


def _nutrition_ctx(request, db, prog):
    students = prog.students
    rows = []
    wh_count = {k: 0 for k in WH_LABELS}
    ha_count = {k: 0 for k in HA_LABELS}
    wa_count = {k: 0 for k in WA_LABELS}
    watch = []
    for s in students:
        ms = {m.term: m for m in s.measures}
        res = {t: _measure_result(s, ms.get(t)) for t in (1, 2)}
        trend = _wh_trend(res)
        rows.append({"s": s, "m": ms, "res": res, "trend": trend})
        latest = res.get(2) or res.get(1)
        if latest:
            if latest["wh"] in wh_count:
                wh_count[latest["wh"]] += 1
            if latest["ha"] in ha_count:
                ha_count[latest["ha"]] += 1
            if latest.get("wa") in wa_count:
                wa_count[latest["wa"]] += 1
            if latest.get("wh") in _WH_RISK:
                r1w = (res.get(1) or {}).get("wh")
                r2w = (res.get(2) or {}).get("wh")
                watch.append({"s": s, "wh": latest["wh"], "trend": trend,
                              "repeat": (r1w in _WH_RISK and r2w in _WH_RISK)})
    n = sum(wh_count.values())
    # จัดกลุ่มตามระดับชั้น (ตามลำดับมาตรฐาน)
    order = {lv: i for i, lv in enumerate(DEFAULT_LEVELS)}
    rows_sorted = sorted(rows, key=lambda r: (order.get((r["s"].level or "").strip(), 99),
                                              (r["s"].level or ""), r["s"].name or ""))
    by_class = []
    for r in rows_sorted:
        lv = (r["s"].level or "").strip() or "ไม่ระบุชั้น"
        if not by_class or by_class[-1]["level"] != lv:
            by_class.append({"level": lv, "rows": []})
        by_class[-1]["rows"].append(r)
    watch.sort(key=lambda w: (not w["repeat"], order.get((w["s"].level or "").strip(), 99)))
    return {
        "request": request, "school": get_school(db), "p": prog,
        "rows": rows, "by_class": by_class, "watch": watch,
        "wh_labels": WH_LABELS, "ha_labels": HA_LABELS, "wa_labels": WA_LABELS,
        "wh_count": wh_count, "ha_count": ha_count, "wa_count": wa_count, "assessed": n,
        "today_be": be_date_input(datetime.now()),
    }


def _nutrition_pool(db) -> LunchProgram:
    """โปรแกรมพิเศษ (ซ่อน) เก็บทะเบียนภาวะโภชนาการรวมของโรงเรียน - สร้างครั้งเดียว ใช้ตลอด
    ทำให้ภาวะโภชนาการเป็นเมนูของตัวเอง ไม่ผูกกับเรื่องจ้างเหมาแต่ละโครงการ"""
    pool = db.query(LunchProgram).filter(LunchProgram.pool == 1).first()
    if not pool:
        pool = LunchProgram(year=_current_academic_year(), pool=1, note="ทะเบียนภาวะโภชนาการ")
        db.add(pool); db.commit()
    return pool


def _nutrition_report_data(prog):
    """นับภาวะโภชนาการ (น้ำหนักตามเกณฑ์ส่วนสูง) จากผลเทอมล่าสุด แยกตามชั้นและเพศ"""
    cats = WH_LABELS
    order = {lv: i for i, lv in enumerate(DEFAULT_LEVELS)}
    students = sorted(prog.students, key=lambda s: (order.get((s.level or "").strip(), 99),
                                                    (s.level or ""), s.name or ""))
    totals = {c: 0 for c in cats}
    sex_counts = {"ชาย": {c: 0 for c in cats}, "หญิง": {c: 0 for c in cats}}
    class_counts, cur, assessed = [], None, 0
    for s in students:
        ms = {m.term: m for m in s.measures}
        res = _measure_result(s, ms.get(2)) or _measure_result(s, ms.get(1))
        if not res or res.get("wh") not in totals:
            continue
        cat = res["wh"]
        lv = (s.level or "").strip() or "ไม่ระบุชั้น"
        if cur is None or cur["level"] != lv:
            cur = {"level": lv, "counts": {c: 0 for c in cats}, "total": 0}
            class_counts.append(cur)
        cur["counts"][cat] += 1; cur["total"] += 1
        totals[cat] += 1; assessed += 1
        sx = "ชาย" if s.sex == "M" else "หญิง" if s.sex == "F" else None
        if sx:
            sex_counts[sx][cat] += 1
    return cats, class_counts, sex_counts, totals, assessed


@router.get("/lunch/nutrition/report.docx")
def nutrition_report_docx(db: Session = Depends(get_db)):
    from app.services.nutrition_report import render_nutrition_report
    cats, class_counts, sex_counts, totals, assessed = _nutrition_report_data(_nutrition_pool(db))
    path = render_nutrition_report(get_school(db), cats, class_counts, sex_counts, totals, assessed,
                                   as_of=datetime.now())
    return serve_generated(path, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


@router.post("/lunch/nutrition/student/add")
def student_add(db: Session = Depends(get_db), name: str = Form(""), sex: str = Form(""),
                birthdate: str = Form(""), level: str = Form("")):
    if name.strip():
        db.add(LunchStudent(program_id=_nutrition_pool(db).id, name=name.strip(), sex=sex,
                            birthdate=parse_be_date(birthdate), level=level.strip()))
        db.commit()
    return RedirectResponse("/lunch/nutrition", status_code=303)


@router.post("/lunch/nutrition/pull-roster")
def nutrition_pull_roster(db: Session = Depends(get_db), level: str = Form("")):
    """ดึงนักเรียนจากทะเบียนกลางเข้าทะเบียนภาวะโภชนาการ (ข้ามคนที่ดึงมาแล้ว/ชื่อซ้ำ)"""
    from app.models import Student
    pool = _nutrition_pool(db)
    have_ids = {s.student_id for s in pool.students if s.student_id}
    have_names = {(s.name or "").strip() for s in pool.students}
    q = db.query(Student)
    lv = (level or "").strip()
    if lv:
        q = q.filter(Student.level == lv)
    for st in q.order_by(Student.level, Student.name).all():
        if st.id in have_ids or (st.name or "").strip() in have_names:
            continue
        db.add(LunchStudent(program_id=pool.id, student_id=st.id, name=st.name,
                            sex=st.sex, birthdate=st.birthdate, level=st.level))
    db.commit()
    return RedirectResponse("/lunch/nutrition", status_code=303)


@router.post("/lunch/nutrition/students/bulk")
def students_bulk_add(db: Session = Depends(get_db), bulk: str = Form("")):
    """เพิ่มนักเรียนทีละหลายคน: 1 บรรทัด = ชื่อ, เพศ(ช/ญ), วันเกิด, ชั้น (คั่นจุลภาคหรือ Tab)"""
    pool = _nutrition_pool(db)
    for line in (bulk or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in re.split(r"[,\t]", line)]
        name = parts[0] if parts else ""
        if not name:
            continue
        sx = (parts[1] if len(parts) > 1 else "").strip()
        sex = "M" if sx in ("ช", "ชาย", "M", "m") else "F" if sx in ("ญ", "หญิง", "F", "f") else ""
        birth = parse_be_date(parts[2]) if len(parts) > 2 else None
        level = parts[3] if len(parts) > 3 else ""
        db.add(LunchStudent(program_id=pool.id, name=name, sex=sex, birthdate=birth, level=level))
    db.commit()
    return RedirectResponse("/lunch/nutrition", status_code=303)


@router.post("/lunch/student/{sid}/update")
def student_update(sid: int, db: Session = Depends(get_db),
                   name: str = Form(""), sex: str = Form(""),
                   birthdate: str = Form(""), level: str = Form("")):
    s = db.get(LunchStudent, sid)
    if not s:
        return RedirectResponse("/lunch", status_code=303)
    if name.strip():
        s.name = name.strip()
    s.sex = sex
    s.birthdate = parse_be_date(birthdate)
    s.level = level.strip()
    db.commit()
    return RedirectResponse("/lunch/nutrition", status_code=303)


@router.post("/lunch/student/{sid}/measure")
def student_measure(sid: int, db: Session = Depends(get_db),
                    term: str = Form("1"), date: str = Form(""),
                    weight: str = Form(""), height: str = Form("")):
    s = db.get(LunchStudent, sid)
    if not s:
        return RedirectResponse("/lunch", status_code=303)
    t = _to_int(term, 1)
    m = next((x for x in s.measures if x.term == t), None)
    if not m:
        m = LunchMeasure(student_id=sid, term=t)
        db.add(m)
    m.date = parse_be_date(date)
    m.weight = _to_float(weight, 0.0)
    m.height = _to_float(height, 0.0)
    db.commit()
    return RedirectResponse("/lunch/nutrition", status_code=303)


@router.post("/lunch/student/{sid}/delete")
def student_delete(sid: int, db: Session = Depends(get_db)):
    s = db.get(LunchStudent, sid)
    pid = s.program_id if s else None
    if s:
        db.delete(s)
        db.commit()
    return RedirectResponse("/lunch/nutrition", status_code=303)


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
    persons = db.query(Person).order_by(Person.name).all()
    sel_kind = request.query_params.get("kind")
    if sel_kind not in COMMITTEE_KINDS:
        sel_kind = "tor"
    return templates.TemplateResponse("lunch_contract.html", {
        "request": request, "school": get_school(db), "r": rnd, "p": rnd.program,
        "installments": rnd.installments, "paid": paid,
        "committed": sum(i.amount or 0 for i in rnd.installments),
        "committees": committees, "com_kinds": COMMITTEE_KINDS, "com_roles": COMMITTEE_ROLES,
        "persons": persons, "persons_pos": {p.name: p.position for p in persons},
        "sel_kind": sel_kind,
        "holidays": _lunch_holidays(rnd.program),
        "today_be": be_date_input(datetime.now()),
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


@router.post("/lunch/installment/{iid}/update")
def installment_update(iid: int, db: Session = Depends(get_db),
                       start_date: str = Form(""), end_date: str = Form(""),
                       days: str = Form(""), amount: str = Form(""),
                       deliver_date: str = Form(""), inspect_date: str = Form(""),
                       status: str = Form("ร่าง")):
    inst = db.get(LunchInstallment, iid)
    if not inst:
        return RedirectResponse("/lunch", status_code=303)
    inst.start_date = parse_be_date(start_date)
    inst.end_date = parse_be_date(end_date)
    inst.days = _to_int(days, 0)
    inst.amount = _to_float(amount, 0.0)
    inst.deliver_date = parse_be_date(deliver_date)
    inst.inspect_date = parse_be_date(inspect_date)
    inst.status = status
    _sync_installment_ledger(db, inst)
    db.commit()
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
