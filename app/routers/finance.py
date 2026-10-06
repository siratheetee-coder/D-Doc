# -*- coding: utf-8 -*-
"""
finance.py - งานการเงิน
หน้าหลักการเงิน + ทะเบียนคุมเงินแยกบัญชี (รับ-จ่าย-คงเหลือ)
+ บันทึกขออนุมัติเบิกจ่าย (ออก Word, เชื่อมเรื่องพัสดุ) + ทะเบียนใบเสร็จ/ใบสำคัญ
+ รายงานการเงิน (Excel) + นำเข้าข้อมูลจาก Excel
เลขบันทึกขอเบิกจ่ายใช้ชุดเลขกลาง 'memo' ร่วมกับทุกงาน
"""
from pathlib import Path
from datetime import datetime, timedelta

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    FinanceAccount, FinanceTxn, DisburseMemo, Receipt, Procurement, AccountOpening,
    AccountItem, Project, MoneyLoan, LoanReturn, CheckPayment, BankRecon,
)
from app.services.budget import current_plan_year, plan_year_label
from app.thai_utils import SCHOOL_LEVELS
from app.services.ebudget_cat import EXPENSE as EB_EXPENSE, INCOME as EB_INCOME
from app.services.asset_utils import (
    account_balance, account_balance_year, opening_for, recon_sides,
    account_balance_asof, item_remaining_asof,
)
from app.services.cash_report import render_cash_report, DEPOSIT_TYPES
from app.services.fin_registers import (
    special_form, SPECIAL_LABEL, render_account_register,
    render_safe_custody, render_disburse_register,
    render_money_register, render_all_registers,
)
from app.services.ledger_book_doc import (
    render_cash_book, render_cash_book_fund, build_cash_book_xlsx, build_cash_book_fund_xlsx,
    render_general_ledger, build_ledger_xlsx,
)
from app.services.doc_number import suggest_doc_no, commit_doc_no, check_doc_no, parse_seq, remove_issued
from app.services.finance_doc import render_disburse
from app.services.finance_io import build_finance_template, import_finance_workbook
from app.services.finance_report import export_finance_report
from app.thai_utils import current_fiscal_year, parse_be_date, be_date_input, thai_date
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float, serve_generated

router = APIRouter()
from app.routers.subsidy import router as subsidy_router
router.include_router(subsidy_router)

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ประเภทเงินตามงบ (คอลัมน์สมุดเงินสดราชการ) - เก็บเป็นข้อความไทยตรงๆ
from app.services.finance_types import (FUND_TYPES, FUND_DEFAULT as _FUND_DEFAULT,
                                        resolve_fund_type, fund_color)

# ชุดหมวดสำเร็จรูป (กดปุ่มเดียวสร้างทั้งโครง) - (ชื่อหมวดแม่ | None, [รายการลูก])
PRESET_SETS = {
    "subsidy_head": {
        "label": "เงินอุดหนุนรายหัว (5 รายการมาตรฐาน)",
        "parent": "เงินอุดหนุนทั่วไป",
        "children": ["ค่าจัดการเรียนการสอน", "ค่าหนังสือเรียน", "ค่าอุปกรณ์การเรียน",
                     "ค่าเครื่องแบบนักเรียน", "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน"],
    },
    "state_interest": {
        "label": "ดอกเบี้ยรายได้แผ่นดิน",
        "parent": None,
        "children": ["ดอกเบี้ยเงินฝากธนาคาร", "ดอกเบี้ยเงินอุดหนุน", "ดอกเบี้ยเงินอาหารกลางวัน"],
    },
}


# ปีงบที่ให้เลือกได้เสมอ แม้ยังไม่มีข้อมูลสักรายการ
_YEARS_BACK = 2         # ย้อนหลังกี่ปี (ไว้ลงข้อมูลเก่าที่ยังไม่ได้บันทึก)
_YEARS_AHEAD = 1        # ล่วงหน้ากี่ปี (ไว้ตั้งงบปีหน้าก่อนขึ้นปีงบใหม่)


def _finance_years(db, fy: int) -> list:
    """รายชื่อปีงบให้เลือก เรียงใหม่ไปเก่า

    เดิมคืนเฉพาะปีที่ "มีข้อมูลอยู่แล้ว" + ปีปัจจุบัน ซึ่งทำให้โรงเรียนที่เพิ่งเริ่มใช้
    เห็นปีเดียว แล้วย้อนไปลงข้อมูลปีก่อนไม่ได้เลย (ไก่กับไข่: ไม่มีข้อมูลจึงไม่มีปีให้เลือก
    พอเลือกปีไม่ได้ก็ลงข้อมูลไม่ได้) จึงเปิดช่วงปีไว้ให้เสมอ
    """
    ys = {r[0] for r in db.query(FinanceTxn.fiscal_year).distinct()}
    ys |= {r[0] for r in db.query(AccountOpening.fiscal_year).distinct()}
    ys |= {r[0] for r in db.query(AccountItem.fiscal_year).distinct()}   # ตั้งงบไว้แต่ยังไม่มีรายการ
    ys |= set(range(fy - _YEARS_BACK, fy + _YEARS_AHEAD + 1))
    ys.discard(None)
    return sorted(ys, reverse=True)


# ---------------- Dashboard ----------------
@router.get("/finance", response_class=HTMLResponse)
def finance_dashboard(request: Request, db: Session = Depends(get_db), year: int | None = None):
    from app.services.dashboard_tasks import finance_tasks
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    total_bal = sum(account_balance_year(a, fy) for a in accounts)
    txns = db.query(FinanceTxn).filter_by(fiscal_year=fy).all()
    total_in = sum(t.amount or 0 for t in txns if t.kind == "in")
    total_out = sum(t.amount or 0 for t in txns if t.kind == "out")
    return templates.TemplateResponse("finance_dashboard.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy), "next_year": fy + 1,
        "accounts": accounts, "total_bal": total_bal,
        "total_in": total_in, "total_out": total_out,
        "n_disburse": db.query(DisburseMemo).filter_by(fiscal_year=fy).count(),
        "n_receipt": db.query(Receipt).filter_by(fiscal_year=fy).count(),
        "task_cards": finance_tasks(db, fy),
        "recent_disburse": db.query(DisburseMemo).order_by(DisburseMemo.id.desc()).limit(5).all(),
    })


# ---------------- ยกยอดคงเหลือไปปีงบถัดไป (ไม่ลบข้อมูลเก่า) ----------------
@router.post("/finance/carry-forward")
def carry_forward(db: Session = Depends(get_db), year: str = Form("")):
    """คัดลอกยอดคงเหลือสิ้นปีงบ {year} ไปตั้งเป็น 'ยอดยกมา' ของปีงบถัดไป
    ไม่ลบรายการเดิม (ปีเก่ายังกดกลับไปดูได้) - upsert จึงกดซ้ำได้ ค่าจะอัปเดตให้ตรงเสมอ"""
    src = _to_int(year, current_fiscal_year())
    nxt = src + 1
    from app.services.finance_openings import carry
    try:
        carry(db,src)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409,str(exc))
    return RedirectResponse(f"/finance?year={nxt}&carried={src}", status_code=303)



@router.get("/finance/receipts/register.docx")
def receipt_register_docx(db: Session = Depends(get_db), year: int | None = None):
    """ทะเบียนคุมใบเสร็จรับเงินและใบสำคัญรับเงิน (พิมพ์เก็บเป็นหลักฐาน)"""
    from app.models import Receipt
    from app.services.fin_registers import render_receipt_register
    fy = year or current_fiscal_year()
    names = {a.id: a.name for a in db.query(FinanceAccount).all()}
    rows = [(r, names.get(r.account_id, ""))
            for r in (db.query(Receipt).filter_by(fiscal_year=fy)
                      .order_by(Receipt.date, Receipt.id).all())]
    return serve_generated(render_receipt_register(get_school(db), fy, rows), _DOCX)


# ---------------- ทะเบียนคุมเงิน (บัญชี + ledger) ----------------
@router.get("/finance/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    # งบตามหมวด (รวมทุกหมวด/รายการย่อยของบัญชี ในปีงบนั้น) - โชว์ระดับบัญชี
    budget_by_acct = {}
    items_by_acct = {}
    all_items = (db.query(AccountItem).filter_by(fiscal_year=fy)
                 .order_by(AccountItem.account_id, AccountItem.id).all())
    for it in all_items:
        budget_by_acct[it.account_id] = budget_by_acct.get(it.account_id, 0.0) + (it.budget or 0.0)
        items_by_acct.setdefault(it.account_id, []).append(it)
    # รับ-จ่าย-คงเหลือ รายรายการย่อย (เงินอุดหนุนต้องดูระดับรายการย่อยได้ ไม่ใช่เห็นแต่ยอดรวม)
    flow = {}
    for t in db.query(FinanceTxn).filter_by(fiscal_year=fy).all():
        if not t.item_id:
            continue
        cur = flow.setdefault(t.item_id, {"in": 0.0, "out": 0.0})
        cur["in" if (t.kind or "in") == "in" else "out"] += float(t.amount or 0)
    item_rows = {}
    for aid_, rows_ in items_by_acct.items():
        kids = {}
        for it in rows_:
            if it.parent_id:
                kids.setdefault(it.parent_id, []).append(it)
        out = []
        for it in rows_:
            if it.parent_id:
                continue                       # ลูกจะถูกแทรกต่อท้ายแม่ของตัวเอง
            for lv, node in [(0, it)] + [(1, k) for k in kids.get(it.id, [])]:
                fam = [node] + kids.get(node.id, [])
                got = sum(flow.get(x.id, {}).get("in", 0.0) for x in fam)
                used = sum(flow.get(x.id, {}).get("out", 0.0) for x in fam)
                budget = sum(float(x.budget or 0) for x in kids.get(node.id, [])) if kids.get(node.id) else float(node.budget or 0)
                out.append({
                    "o": node, "level": lv, "budget": budget, "got": got, "used": used,
                    "opening": sum(float(x.opening_balance or 0) for x in fam),
                    "left": sum(float(x.opening_balance or 0) for x in fam) + got - used,
                    "pct": min(100, round(used / budget * 100)) if budget else 0,
                })
        item_rows[aid_] = out
        budget_by_acct[aid_] = sum(r["budget"] for r in out if r["level"]==0)
    # จัดกลุ่มตามหมวดเงิน (งบประมาณ -> รายได้แผ่นดิน -> นอกงบประมาณ) พร้อมยอดรวมรายกลุ่ม
    # ในกลุ่มเรียงตามที่เก็บเงิน (ธนาคาร/เงินสด/ส่วนราชการ) แล้วตามชื่อ
    dep_order = {"bank": 0, "cash": 1, "agency": 2}
    groups = []
    for fund in FUND_TYPES:
        rows = [a for a in accounts if (a.fund_type or _FUND_DEFAULT) == fund]
        if not rows:
            continue
        rows.sort(key=lambda a: (dep_order.get(a.deposit_type, 9), a.name or ""))
        groups.append({
            "fund": fund, "color": fund_color(fund), "accounts": rows,
            "budget": sum(budget_by_acct.get(a.id, 0.0) for a in rows),
            "opening": sum(opening_for(a, fy) for a in rows),
            "balance": sum(account_balance_year(a, fy) for a in rows),
        })
    return templates.TemplateResponse("finance_accounts.html", {
        "request": request, "accounts": accounts, "budget_by_acct": budget_by_acct,
        "groups": groups, "fiscal_year": fy, "years": _finance_years(db, fy),
        "item_rows": item_rows,
    })


@router.post("/finance/accounts")
def account_add(db: Session = Depends(get_db), name: str = Form(...),
                opening_balance: str = Form("0"), note: str = Form(""),
                deposit_type: str = Form("bank"), fund_type: str = Form("")):
    if name.strip():
        nm = name.strip()
        dt = deposit_type if deposit_type in DEPOSIT_TYPES else "bank"
        # ช่องเดียวรวมชื่อ+ประเภทเงิน: ถ้าชื่อตรง 3 งบ ใช้เป็น fund_type เลย · ชื่ออื่น = นอกงบฯ (ปรับได้ภายหลัง)
        ft = resolve_fund_type(nm, fund_type)
        db.add(FinanceAccount(name=nm,
                              opening_balance=_to_float(opening_balance, 0.0),
                              deposit_type=dt, fund_type=ft, note=note.strip()))
        db.commit()
    return RedirectResponse("/finance/accounts", status_code=303)


@router.post("/finance/accounts/{aid}/fund-type")
def account_set_fund_type(aid: int, db: Session = Depends(get_db),
                          fund_type: str = Form(_FUND_DEFAULT), year: str = Form("")):
    a = db.get(FinanceAccount, aid)
    if a and fund_type in FUND_TYPES:
        a.fund_type = fund_type
        db.commit()
    fy = _to_int(year, current_fiscal_year())
    return RedirectResponse(f"/finance/accounts/{aid}?year={fy}", status_code=303)


@router.post("/finance/accounts/{aid}/deposit-type")
def account_set_deposit_type(aid: int, db: Session = Depends(get_db),
                             deposit_type: str = Form("bank"), year: str = Form("")):
    a = db.get(FinanceAccount, aid)
    if a and deposit_type in DEPOSIT_TYPES:
        a.deposit_type = deposit_type
        db.commit()
    fy = _to_int(year, current_fiscal_year())
    return RedirectResponse(f"/finance/accounts?year={fy}", status_code=303)


@router.post("/finance/accounts/{aid}/delete")
def account_delete(aid: int, db: Session = Depends(get_db)):
    a = db.get(FinanceAccount, aid)
    if a:
        db.delete(a); db.commit()
    return RedirectResponse("/finance/accounts", status_code=303)


@router.get("/finance/accounts/{aid}", response_class=HTMLResponse)
def account_ledger(aid: int, request: Request, db: Session = Depends(get_db), year: int | None = None):
    a = db.get(FinanceAccount, aid)
    if not a:
        return RedirectResponse("/finance/accounts", status_code=303)
    fy = year or current_fiscal_year()
    opening = opening_for(a, fy)
    txns = [t for t in a.txns if t.fiscal_year == fy]
    rows = []
    bal = opening
    for t in sorted(txns, key=lambda x: (x.date or datetime.min, x.id)):
        bal += (t.amount or 0) if t.kind == "in" else -(t.amount or 0)
        rows.append({"t": t, "balance": round(bal, 2)})
    # สรุปงบรายหมวด (เฉพาะปีงบที่เลือก) - เป็นต้นไม้ซ้อน 2 ชั้น หมวดแม่รวมยอดลูก
    items = (db.query(AccountItem).filter_by(account_id=a.id, fiscal_year=fy)
             .order_by(AccountItem.id).all())

    def _self(it):
        tin = sum(t.amount or 0 for t in txns if t.item_id == it.id and t.kind == "in")
        tout = sum(t.amount or 0 for t in txns if t.item_id == it.id and t.kind == "out")
        return tin, tout

    parents = [it for it in items if it.parent_id is None]
    children_by = {}
    for it in items:
        if it.parent_id is not None:
            children_by.setdefault(it.parent_id, []).append(it)
    item_rows = []          # เรียงตามการแสดง (หมวดแม่ตามด้วยลูก) + level
    for p in parents:
        p_in, p_out = _self(p)
        p_bud = p.budget or 0
        kids = children_by.get(p.id, [])
        krows = []
        for k in kids:
            k_in, k_out = _self(k)
            krows.append({"it": k, "level": 1, "tin": k_in, "tout": k_out,
                          "opening": k.opening_balance or 0, "budget": k.budget or 0, "remain": round((k.opening_balance or 0) + k_in - k_out, 2)})
        # หมวดแม่: รับ-จ่ายรวมลูก (เงินลงหมวดแม่ตรงๆ ก็นับ) แต่ "งบ" ไม่บวกซ้ำ
        # ถ้ามีลูก งบ = ผลรวมงบลูกเท่านั้น (งบที่เคยตั้งบนหมวดแม่จะถูกแทนด้วยผลรวมลูก)
        tin = p_in + sum(r["tin"] for r in krows)
        tout = p_out + sum(r["tout"] for r in krows)
        budget = sum(r["budget"] for r in krows) if krows else p_bud
        item_rows.append({"it": p, "level": 0, "tin": tin, "tout": tout, "budget": budget,
                          "opening": (p.opening_balance or 0)+sum(r["opening"] for r in krows),
                          "remain": round((p.opening_balance or 0)+sum(r["opening"] for r in krows) + tin - tout, 2), "has_kids": bool(krows)})
        item_rows.extend(krows)
    from app.services.finance_openings import token as opening_token
    # แผนที่ รายการเงิน -> เลขใบเสร็จที่ออกผูกกัน (ไว้แสดงในประวัติ)
    receipt_map = {rc.txn_id: (rc.receipt_no or "(ไม่มีเลข)")
                   for rc in db.query(Receipt).filter(Receipt.txn_id.isnot(None)).all()
                   if rc.txn_id}
    return templates.TemplateResponse("finance_ledger.html", {
        "request": request, "account": a, "rows": rows, "balance": round(bal, 2),
        "opening": opening, "fiscal_year": fy, "years": _finance_years(db, fy),
        "items": items, "item_rows": item_rows, "receipt_map": receipt_map,
        "opening_token": opening_token(db,a,fy),
        "opening_sum": round(sum(i.opening_balance or 0 for i in items),2),
        "opening_gap": round(opening-sum(i.opening_balance or 0 for i in items),2),
        "parents": parents, "fund_types": FUND_TYPES, "presets": PRESET_SETS,
        "item_budget_total": sum(r["budget"] for r in item_rows if r["level"] == 0),
        "item_remain_total": sum(r["remain"] for r in item_rows if r["level"] == 0),
        "special_key": special_form(a), "special_label": SPECIAL_LABEL,
        "projects": _plan_projects(db, fy),
        "eb_expense": EB_EXPENSE, "eb_income": EB_INCOME[0][1],
        "fund_c": fund_color(a.fund_type),
    })


@router.post("/finance/accounts/{aid}/item")
def account_item_add(aid: int, db: Session = Depends(get_db), name: str = Form(...),
                     budget: str = Form("0"), note: str = Form(""), fiscal_year: str = Form(""),
                     deposit_type: str = Form("bank"), parent_id: str = Form("")):
    a = db.get(FinanceAccount, aid)
    fy = _to_int(fiscal_year, current_fiscal_year())
    if a and name.strip():
        dt = deposit_type if deposit_type in DEPOSIT_TYPES else "bank"
        # หมวดแม่ต้องอยู่บัญชี+ปีเดียวกัน และเป็นหมวดหลัก (ไม่ให้ซ้อนเกิน 2 ชั้น)
        pid = _to_int(parent_id, 0) or None
        if pid:
            par = db.get(AccountItem, pid)
            if not (par and par.account_id == a.id and par.fiscal_year == fy and par.parent_id is None):
                pid = None
        db.add(AccountItem(account_id=a.id, fiscal_year=fy, name=name.strip(), parent_id=pid,
                           budget=_to_float(budget, 0.0), deposit_type=dt, note=note.strip()))
        db.commit()
    return RedirectResponse(f"/finance/accounts/{aid}?year={fy}", status_code=303)


@router.post("/finance/accounts/{aid}/preset")
def account_add_preset(aid: int, db: Session = Depends(get_db),
                       preset: str = Form(""), fiscal_year: str = Form("")):
    """สร้างชุดหมวดสำเร็จรูป (หมวดแม่ + ลูก) ในคลิกเดียว - ข้ามชื่อที่มีอยู่แล้ว"""
    a = db.get(FinanceAccount, aid)
    fy = _to_int(fiscal_year, current_fiscal_year())
    spec = PRESET_SETS.get(preset)
    if a and spec:
        existing = {it.name.strip() for it in a.items if it.fiscal_year == fy}
        parent = None
        if spec["parent"]:
            parent = next((it for it in a.items if it.fiscal_year == fy
                           and it.name.strip() == spec["parent"] and it.parent_id is None), None)
            if not parent:
                parent = AccountItem(account_id=a.id, fiscal_year=fy, name=spec["parent"])
                db.add(parent); db.flush()
        for cname in spec["children"]:
            if cname not in existing:
                db.add(AccountItem(account_id=a.id, fiscal_year=fy, name=cname,
                                   parent_id=parent.id if parent else None))
        db.commit()
    return RedirectResponse(f"/finance/accounts/{aid}?year={fy}", status_code=303)


@router.post("/finance/accounts/{aid}/copy-items")
def account_copy_items(aid: int, db: Session = Depends(get_db), year: str = Form("")):
    """คัดลอกรายชื่อหมวด + งบที่ตั้งไว้ จากปีงบก่อนหน้า มายังปีงบที่เลือก
    (ข้ามหมวดชื่อซ้ำที่มีอยู่แล้วในปีนี้)"""
    a = db.get(FinanceAccount, aid)
    fy = _to_int(year, current_fiscal_year())
    if a:
        existing = {it.name.strip() for it in a.items if it.fiscal_year == fy}
        prev = [it for it in a.items if it.fiscal_year == fy - 1]
        id_map = {}  # old item id -> new AccountItem (คงโครงหมวดแม่-ลูก)
        # หมวดแม่ก่อน แล้วค่อยลูก (จะได้ผูก parent_id ได้ถูก)
        for it in sorted(prev, key=lambda x: (x.parent_id is not None, x.id)):
            if it.name.strip() in existing:
                continue
            pid = id_map[it.parent_id].id if (it.parent_id and it.parent_id in id_map) else None
            new = AccountItem(account_id=a.id, fiscal_year=fy, name=it.name, parent_id=pid,
                              budget=it.budget, deposit_type=it.deposit_type, note=it.note)
            db.add(new); db.flush()
            id_map[it.id] = new
            existing.add(it.name.strip())
        db.commit()
    return RedirectResponse(f"/finance/accounts/{aid}?year={fy}", status_code=303)


@router.post("/finance/items/{iid}/update")
def account_item_update(iid: int, db: Session = Depends(get_db), budget: str = Form(None),
                        name: str = Form(None), deposit_type: str = Form(None),
                        note: str = Form(None), year: str = Form("")):
    """แก้ไขหมวดในตาราง (งบ/ชื่อ/เก็บที่/หมายเหตุ) - บันทึกอินไลน์"""
    it = db.get(AccountItem, iid)
    if it:
        if budget is not None:
            it.budget = _to_float(budget, it.budget or 0.0)
        if name is not None and name.strip():
            it.name = name.strip()
        if deposit_type is not None and deposit_type in DEPOSIT_TYPES:
            it.deposit_type = deposit_type
        if note is not None:
            it.note = note.strip()
        db.commit()
    aid = it.account_id if it else None
    fy = _to_int(year, it.fiscal_year if it else current_fiscal_year())
    return RedirectResponse(f"/finance/accounts/{aid}?year={fy}" if aid else "/finance/accounts",
                            status_code=303)


@router.post("/finance/items/{iid}/delete")
def account_item_delete(iid: int, db: Session = Depends(get_db)):
    it = db.get(AccountItem, iid)
    aid = it.account_id if it else None
    fy = it.fiscal_year if it else current_fiscal_year()
    if it:
        # ปลดการผูกหมวดออกจากรายการที่อ้างถึง (ไม่ลบรายการเงิน)
        for t in db.query(FinanceTxn).filter_by(item_id=it.id).all():
            t.item_id = None
        db.delete(it); db.commit()
    return RedirectResponse(f"/finance/accounts/{aid}?year={fy}" if aid else "/finance/accounts", status_code=303)


@router.post("/finance/accounts/{aid}/txn")
def account_txn_add(aid: int, db: Session = Depends(get_db), kind: str = Form("in"),
                    amount: str = Form("0"), date: str = Form(""), category: str = Form(""),
                    ref: str = Form(""), note: str = Form(""), fiscal_year: str = Form(""),
                    item_id: str = Form(""), receipt_no: str = Form(""), party: str = Form(""),
                    due_date: str = Form(""), refund_date: str = Form(""),
                    project_id: str = Form(""), eb_code: str = Form("")):
    a = db.get(FinanceAccount, aid)
    fy = _to_int(fiscal_year, current_fiscal_year())
    if a:
        k = "out" if kind == "out" else "in"
        amt = _to_float(amount, 0.0)
        dt = parse_be_date(date) or datetime.now()
        t = FinanceTxn(
            account_id=a.id, fiscal_year=fy, item_id=_to_int(item_id, 0) or None,
            project_id=_to_int(project_id, 0) or None,
            eb_code=(eb_code or "").strip(),
            kind=k, amount=amt, date=dt,
            category=category.strip(), ref=ref.strip(), note=note.strip(),
            due_date=parse_be_date(due_date) if due_date else None,
            refund_date=parse_be_date(refund_date) if refund_date else None,
        )
        db.add(t); db.flush()
        # ถ้ากรอกเลขใบเสร็จ/ผู้รับเงิน -> สร้างรายการในทะเบียนใบเสร็จให้อัตโนมัติ (ผูกกัน)
        if receipt_no.strip() or party.strip():
            db.add(Receipt(
                fiscal_year=fy, receipt_no=receipt_no.strip(), date=dt,
                kind=("จ่าย" if k == "out" else "รับ"), party=party.strip(),
                amount=amt, account_id=a.id, txn_id=t.id, note=note.strip(),
            ))
        db.commit()
    return RedirectResponse(f"/finance/accounts/{aid}?year={fy}", status_code=303)


@router.post("/finance/txn/{tid}/delete")
def account_txn_delete(tid: int, db: Session = Depends(get_db),
                       return_to: str = "", year: int | None = None, account: int | None = None):
    t = db.get(FinanceTxn, tid)
    aid = t.account_id if t else None
    fy = t.fiscal_year if t else None
    if t:
        # ลบใบเสร็จที่ออกพร้อมรายการนี้ด้วย (กันยอดค้างในทะเบียนใบเสร็จ)
        for rc in db.query(Receipt).filter_by(txn_id=t.id).all():
            db.delete(rc)
        db.delete(t); db.commit()
    url = f"/finance/accounts/{aid}?year={fy}" if aid else "/finance/accounts"
    if return_to == "cashbook":
        url = f"/finance/cashbook?year={year or fy or current_fiscal_year()}"
        if account:
            url += f"&account={account}"
    return RedirectResponse(url, status_code=303)


# ---------------- บันทึกขออนุมัติเบิกจ่าย ----------------
def _items_map(db, fy) -> dict:
    """แผนที่ {account_id: [{id, name}]} ของหมวด/รายการย่อยในปีงบนั้น (ใช้ทำ dropdown หมวดตามบัญชี)"""
    out: dict = {}
    for it in (db.query(AccountItem).filter_by(fiscal_year=fy)
               .order_by(AccountItem.name).all()):
        out.setdefault(it.account_id, []).append({"id": it.id, "name": it.name})
    return out


@router.get("/finance/disburse", response_class=HTMLResponse)
def disburse_page(request: Request, db: Session = Depends(get_db), proc: int | None = None):
    fy = current_fiscal_year()
    query = db.query(DisburseMemo)
    if request.query_params.get('attention') == '1':
        fy = _to_int(request.query_params.get('year'), fy)
        query = query.filter(DisburseMemo.fiscal_year == fy, DisburseMemo.status.in_(['ร่าง', 'อนุมัติ']))
    rows = query.order_by(DisburseMemo.id.desc()).all()
    # prefill จากเรื่องจัดซื้อ/จัดจ้าง (ถ้าระบุ ?proc=<id>)
    prefill = None
    if proc:
        p = db.get(Procurement, proc)
        if p:
            prefill = {
                "subject": p.subject or "",
                "payee": p.vendor.name if p.vendor else "",
                "amount": p.total_amount or 0,
                "budget_source": p.budget_source or "",
                "procurement_id": p.id,
                "project_id": p.project_id,
                "proc_kind": "จัดจ้าง" if (p.proc_type or "") == "จ้าง" else "จัดซื้อ",
                # เลขบันทึก+วันที่ ดึงจากบันทึกขอเบิกจ่าย/รายงานขอซื้อของเรื่องนั้น
                "memo_no": p.inspect_memo_no or p.memo_no or "",
                "date": p.inspect_date or p.request_date,
                "item_id": None,
            }
    return templates.TemplateResponse("disburse_form.html", {
        "request": request, "rows": rows, "fiscal_year": fy,
        "sug_memo": suggest_doc_no(db, "memo", fy),
        "accounts": db.query(FinanceAccount).order_by(FinanceAccount.name).all(),
        "items_map": _items_map(db, fy),
        "procs": db.query(Procurement).filter_by(fiscal_year=fy).order_by(Procurement.id.desc()).all(),
        "projects": db.query(Project).filter_by(active=True).order_by(Project.name).all(),
        "prefill": prefill,
    })


@router.post("/finance/disburse")
def disburse_create(db: Session = Depends(get_db), fiscal_year: str = Form(""),
                    memo_no: str = Form(""), date: str = Form(""), subject: str = Form(""),
                    payee: str = Form(""), amount: str = Form("0"), budget_source: str = Form(""),
                    account_id: str = Form(""), procurement_id: str = Form(""), note: str = Form(""),
                    vat: str = Form("0"), wht: str = Form("0"), fine: str = Form("0"),
                    proc_kind: str = Form("จัดซื้อ"), project_id: str = Form(""),
                    item_id: str = Form("")):
    fy = _to_int(fiscal_year, current_fiscal_year())
    no = memo_no.strip() or suggest_doc_no(db, "memo", fy)
    m = DisburseMemo(
        fiscal_year=fy, memo_no=no, seq=parse_seq(no), date=parse_be_date(date),
        subject=subject.strip(), payee=payee.strip(), amount=_to_float(amount, 0.0),
        vat=_to_float(vat, 0.0), wht=_to_float(wht, 0.0), fine=_to_float(fine, 0.0),
        proc_kind=proc_kind.strip() or "จัดซื้อ",
        budget_source=budget_source.strip(), account_id=_to_int(account_id, 0) or None,
        item_id=_to_int(item_id, 0) or None,
        procurement_id=_to_int(procurement_id, 0) or None, note=note,
        project_id=_to_int(project_id, 0) or None,
    )
    db.add(m); db.flush()
    commit_doc_no(db, "memo", fy, no, source="finance", ref_id=m.id, date=m.date,
                  subject=((m.subject or "").strip() if (m.subject or "").strip().startswith("ขออนุมัติเบิกจ่าย")
                           else f"ขออนุมัติเบิกจ่าย {(m.subject or '').strip()}".strip()))
    db.commit(); db.refresh(m)
    return RedirectResponse(f"/finance/disburse/{m.id}", status_code=303)


@router.get("/finance/disburse/{mid}", response_class=HTMLResponse)
def disburse_detail(mid: int, request: Request, db: Session = Depends(get_db)):
    m = db.get(DisburseMemo, mid)
    if not m:
        return RedirectResponse("/finance/disburse", status_code=303)
    return templates.TemplateResponse("disburse_detail.html", {
        "request": request, "m": m, "school": get_school(db),
        "accounts": db.query(FinanceAccount).order_by(FinanceAccount.name).all(),
        "items_map": _items_map(db, m.fiscal_year),
        "projects": db.query(Project).filter_by(active=True).order_by(Project.name).all(),
        "proc": db.get(Procurement, m.procurement_id) if m.procurement_id else None,
    })


@router.post("/finance/disburse/{mid}/update")
def disburse_update(mid: int, db: Session = Depends(get_db), memo_no: str = Form(""),
                    date: str = Form(""), subject: str = Form(""), payee: str = Form(""),
                    amount: str = Form("0"), budget_source: str = Form(""),
                    account_id: str = Form(""), status: str = Form(""), note: str = Form(""),
                    vat: str = Form("0"), wht: str = Form("0"), fine: str = Form("0"),
                    proc_kind: str = Form("จัดซื้อ"), project_id: str = Form(""),
                    item_id: str = Form("")):
    m = db.get(DisburseMemo, mid)
    if m:
        m.memo_no = memo_no.strip(); m.seq = parse_seq(memo_no)
        m.date = parse_be_date(date); m.subject = subject.strip(); m.payee = payee.strip()
        m.amount = _to_float(amount, 0.0); m.budget_source = budget_source.strip()
        m.vat = _to_float(vat, 0.0); m.wht = _to_float(wht, 0.0); m.fine = _to_float(fine, 0.0)
        m.proc_kind = proc_kind.strip() or "จัดซื้อ"
        m.account_id = _to_int(account_id, 0) or None
        m.item_id = _to_int(item_id, 0) or None
        m.project_id = _to_int(project_id, 0) or None
        if status.strip():
            m.status = status.strip()
        m.note = note
        # ถ้าบันทึกนี้ลงจ่ายเข้าทะเบียนคุมเงินไปแล้ว ให้ปรับรายการในทะเบียนให้ตรงกัน
        # (แก้หมวด/บัญชี/จำนวน/วันที่ ย้อนหลังได้ ยอดคงเหลือรายหมวดจะอัปเดตตาม)
        txn = db.query(FinanceTxn).filter_by(disburse_id=m.id).first()
        if txn:
            if m.account_id:
                txn.account_id = m.account_id
            txn.item_id = m.item_id
            txn.amount = m.amount or 0
            txn.date = m.date or txn.date
            txn.ref = m.memo_no or txn.ref
        remove_issued(db, "finance", m.id, "memo")   # ล้างเลขเก่า (กันค้างเมื่อเปลี่ยนเลข)
        commit_doc_no(db, "memo", m.fiscal_year, m.memo_no, source="finance", ref_id=m.id, date=m.date,
                  subject=((m.subject or "").strip() if (m.subject or "").strip().startswith("ขออนุมัติเบิกจ่าย")
                           else f"ขออนุมัติเบิกจ่าย {(m.subject or '').strip()}".strip()))
        db.commit()
    return RedirectResponse(f"/finance/disburse/{mid}?saved=1", status_code=303)


@router.post("/finance/disburse/{mid}/post")
def disburse_post(mid: int, db: Session = Depends(get_db)):
    """ลงรายการจ่ายเงินจริงเข้าทะเบียนคุมเงิน (ตามบัญชีที่เลือก) + ตั้งสถานะจ่ายแล้ว"""
    m = db.get(DisburseMemo, mid)
    if m and m.account_id and not any(
            t.disburse_id == m.id for t in db.query(FinanceTxn).filter_by(disburse_id=m.id)):
        db.add(FinanceTxn(
            account_id=m.account_id, fiscal_year=m.fiscal_year, kind="out",
            item_id=m.item_id, amount=m.amount or 0, date=m.date or datetime.now(),
            category="เบิกจ่าย", ref=m.memo_no or "", note=f"จ่าย {m.payee}".strip(),
            disburse_id=m.id,
        ))
        m.status = "จ่ายแล้ว"
        db.commit()
    return RedirectResponse(f"/finance/disburse/{mid}?posted=1", status_code=303)


@router.post("/finance/disburse/{mid}/delete")
def disburse_delete(mid: int, db: Session = Depends(get_db)):
    m = db.get(DisburseMemo, mid)
    if m:
        # ลบรายการเงินที่ผูกกับบันทึกนี้ด้วย (ถ้ามี)
        for t in db.query(FinanceTxn).filter_by(disburse_id=m.id).all():
            db.delete(t)
        db.delete(m); db.commit()
    return RedirectResponse("/finance/disburse", status_code=303)


@router.get("/finance/disburse/{mid}/generate")
def disburse_generate(mid: int, db: Session = Depends(get_db)):
    m = db.get(DisburseMemo, mid)
    if not m:
        return RedirectResponse("/finance/disburse", status_code=303)
    path = render_disburse(m, get_school(db))
    return serve_generated(path, _DOCX)


# ---------------- ทะเบียนใบเสร็จ/ใบสำคัญ ----------------
@router.get("/finance/receipts", response_class=HTMLResponse)
def receipts_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    rows = (db.query(Receipt).filter_by(fiscal_year=fy)
            .order_by(Receipt.date, Receipt.id).all())
    years = sorted({r[0] for r in db.query(Receipt.fiscal_year).distinct()} | {fy}, reverse=True)
    return templates.TemplateResponse("receipts.html", {
        "request": request, "rows": rows, "fiscal_year": fy, "years": years,
        "accounts": db.query(FinanceAccount).order_by(FinanceAccount.name).all(),
    })


@router.post("/finance/receipts")
def receipt_add(db: Session = Depends(get_db), fiscal_year: str = Form(""),
                receipt_no: str = Form(""), date: str = Form(""), kind: str = Form("รับ"),
                party: str = Form(""), amount: str = Form("0"), account_id: str = Form(""),
                note: str = Form("")):
    fy = _to_int(fiscal_year, current_fiscal_year())
    db.add(Receipt(
        fiscal_year=fy, receipt_no=receipt_no.strip(), date=parse_be_date(date),
        kind=("จ่าย" if "จ่าย" in kind else "รับ"), party=party.strip(),
        amount=_to_float(amount, 0.0), account_id=_to_int(account_id, 0) or None,
        note=note.strip(),
    ))
    db.commit()
    return RedirectResponse("/finance/receipts", status_code=303)


@router.post("/finance/receipts/{rid}/delete")
def receipt_delete(rid: int, db: Session = Depends(get_db)):
    r = db.get(Receipt, rid)
    if r:
        db.delete(r); db.commit()
    return RedirectResponse("/finance/receipts", status_code=303)


# ---------------- รายงานการเงิน ----------------
@router.get("/finance/report", response_class=HTMLResponse)
def report_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    txns = db.query(FinanceTxn).filter_by(fiscal_year=fy).all()
    years = sorted({r[0] for r in db.query(FinanceTxn.fiscal_year).distinct()} | {fy}, reverse=True)
    # สรุปแยกบัญชี (เฉพาะปีงบที่เลือก)
    summary = []
    for a in accounts:
        tin = sum(t.amount or 0 for t in a.txns if t.kind == "in" and t.fiscal_year == fy)
        tout = sum(t.amount or 0 for t in a.txns if t.kind == "out" and t.fiscal_year == fy)
        summary.append({"name": a.name, "opening": opening_for(a, fy),
                        "tin": tin, "tout": tout, "bal": account_balance_year(a, fy)})
    return templates.TemplateResponse("finance_report.html", {
        "request": request, "fiscal_year": fy, "years": years, "summary": summary,
        "total_in": sum(s["tin"] for s in summary),
        "total_out": sum(s["tout"] for s in summary),
        "total_bal": sum(s["bal"] for s in summary),
    })


# ---------------- รายงานเงินคงเหลือประจำวัน ----------------
def _blank_amt():
    return {"cash": 0.0, "bank": 0.0, "agency": 0.0, "total": 0.0}


def _add_amt(dst, src):
    for k in ("cash", "bank", "agency", "total"):
        dst[k] += src[k]


def _build_cash_rows(accounts, fy, as_of):
    """สร้างแถวรายงานเงินคงเหลือแบบแบ่งชั้น: 3 งบใหญ่ → บัญชี → หมวดแม่ → หมวดย่อย
    แต่ละชั้นมียอดรวม แยกคอลัมน์ (เงินสด/ธนาคาร/ส่วนราชการผู้เบิก/รวม)
    row = {name, level(0-3), kind(group/sub/leaf), cash, bank, agency, total}"""
    rows = []
    tot = _blank_amt()

    def col_of(dt):
        return dt if dt in DEPOSIT_TYPES else "bank"

    def amt_of(col, val):
        a = _blank_amt(); a[col] = val; a["total"] = val
        return a

    for fund in FUND_TYPES:
        f_accts = [a for a in accounts if (a.fund_type or _FUND_DEFAULT) == fund]
        f_sub = _blank_amt()
        body = []
        for a in f_accts:
            acc_col = col_of(a.deposit_type)
            items = [it for it in a.items if it.fiscal_year == fy]
            # ชื่อบัญชี = ชื่อกลุ่มงบ -> ไม่แสดงแถวบัญชีซ้ำ เลื่อนหมวดขึ้นมาอยู่ใต้กลุ่มงบเลย
            redundant = a.name.strip() == fund
            off = 0 if redundant else 1
            if items:
                a_sub = _blank_amt()
                a_body = []
                parents = [it for it in items if it.parent_id is None]
                kids_by = {}
                for it in items:
                    if it.parent_id is not None:
                        kids_by.setdefault(it.parent_id, []).append(it)
                for p in parents:
                    p_col = col_of(p.deposit_type or acc_col)
                    kids = kids_by.get(p.id, [])
                    if kids:
                        # หมวดแม่มีลูก: ไม่นับงบตัวเอง (นับเฉพาะเงินที่ลงหมวดแม่ตรงๆ) + รวมลูก
                        p_own = item_remaining_asof(p, as_of)
                        p_roll = amt_of(p_col, p_own)
                        krows = []
                        for k in kids:
                            k_amt = amt_of(col_of(k.deposit_type or acc_col), item_remaining_asof(k, as_of))
                            krows.append({"name": k.name, "level": 2 + off, "kind": "leaf", **k_amt})
                            _add_amt(p_roll, k_amt)
                        a_body.append({"name": p.name, "level": 1 + off, "kind": "sub", **p_roll})
                        a_body.extend(krows)
                        _add_amt(a_sub, p_roll)
                    else:
                        p_amt = amt_of(p_col, item_remaining_asof(p, as_of))
                        a_body.append({"name": p.name, "level": 1 + off, "kind": "leaf", **p_amt})
                        _add_amt(a_sub, p_amt)
                residual=round(account_balance_asof(a,fy,as_of)-a_sub['total'],2)
                if residual:
                    amt=amt_of(acc_col,residual)
                    a_body.append({"name":"ยอดที่ยังไม่แยกหมวด / รายการไม่ระบุหมวด","level":1+off,"kind":"leaf",**amt})
                    _add_amt(a_sub,amt)
                if not redundant:
                    body.append({"name": a.name, "level": 1, "kind": "sub", **a_sub})
                body.extend(a_body)
                _add_amt(f_sub, a_sub)
            else:
                b_amt = amt_of(acc_col, account_balance_asof(a, fy, as_of))
                if not redundant:
                    body.append({"name": a.name, "level": 1, "kind": "leaf", **b_amt})
                _add_amt(f_sub, b_amt)
        rows.append({"name": fund, "level": 0, "kind": "group", **f_sub})
        rows.extend(body)
        _add_amt(tot, f_sub)
    return rows, {k: round(v, 2) for k, v in tot.items()}


@router.get("/finance/cash-report", response_class=HTMLResponse)
def cash_report_page(request: Request, db: Session = Depends(get_db),
                     year: int | None = None, date: str | None = None):
    as_of = parse_be_date(date) if date else datetime.now()
    fy = year or current_fiscal_year(as_of)   # ปีงบคิดจากวันที่ที่เลือก
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.id).all()
    rows, totals = _build_cash_rows(accounts, fy, as_of)
    return templates.TemplateResponse("cash_report.html", {
        "request": request, "fiscal_year": fy, "years": _finance_years(db, fy),
        "rows": rows, "totals": totals, "as_of": as_of,
        "as_of_be": be_date_input(as_of), "deposit_types": DEPOSIT_TYPES,
        "school": get_school(db),
    })


@router.get("/finance/cash-report.docx")
def cash_report_docx(db: Session = Depends(get_db),
                     year: int | None = None, date: str | None = None):
    as_of = parse_be_date(date) if date else datetime.now()
    fy = year or current_fiscal_year(as_of)
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.id).all()
    rows, totals = _build_cash_rows(accounts, fy, as_of)
    path = render_cash_report(get_school(db), rows, totals, as_of)
    return serve_generated(path, _DOCX)


# ---------------- สมุดเงินสด + บัญชีแยกประเภท (แบบ สตง.) ----------------
_MONTH_NAME = {1: "มกราคม", 2: "กุมภาพันธ์", 3: "มีนาคม", 4: "เมษายน", 5: "พฤษภาคม",
               6: "มิถุนายน", 7: "กรกฎาคม", 8: "สิงหาคม", 9: "กันยายน",
               10: "ตุลาคม", 11: "พฤศจิกายน", 12: "ธันวาคม"}


def _build_book_rows(txns, opening, *, acct_names=None, ledger=False):
    """สร้างแถวสมุดเงินสด/บัญชีแยกประเภท: เรียงตามวันที่ + ยอดคงเหลือสะสม + แถวรวมรายเดือน
    txns: FinanceTxn (in=เดบิต/รับ, out=เครดิต/จ่าย)
    acct_names: {account_id: ชื่อบัญชี} เพื่อใส่ชื่อบัญชีนำหน้ารายการ (โหมดรวมทุกบัญชี)
    ledger=True: เพิ่มคอลัมน์ 'ดุล' (เดบิต/เครดิต) จากยอดคงเหลือ"""
    rows = []
    bal = float(opening or 0)
    tot_d = tot_c = 0.0
    ordered = sorted(txns, key=lambda t: (t.date or datetime.min, t.id))
    cur_month = None
    m_d = m_c = 0.0

    def _side():
        return "เดบิต" if bal >= 0 else "เครดิต"

    def flush():
        nonlocal m_d, m_c
        if cur_month is not None:
            r = {"subtotal": True, "date": "", "ref": "",
                 "desc": f"รวมรับ-จ่ายเดือน{_MONTH_NAME.get(cur_month, '')}",
                 "debit": round(m_d, 2), "credit": round(m_c, 2), "balance": round(bal, 2)}
            if ledger:
                r["side"] = _side()
            rows.append(r)
        m_d = m_c = 0.0

    for t in ordered:
        m = t.date.month if t.date else None
        if cur_month is not None and m != cur_month:
            flush()
        cur_month = m
        debit = (t.amount or 0) if t.kind == "in" else 0.0
        credit = (t.amount or 0) if t.kind == "out" else 0.0
        bal += debit - credit
        m_d += debit; m_c += credit
        tot_d += debit; tot_c += credit
        desc = " ".join(x for x in [(t.category or "").strip(), (t.note or "").strip()] if x) or "-"
        if acct_names:
            nm = acct_names.get(t.account_id)
            if nm:
                desc = f"[{nm}] {desc}"
        r = {"date": thai_date(t.date) if t.date else "", "desc": desc, "ref": (t.ref or "").strip(),
             "debit": debit, "credit": credit, "balance": round(bal, 2)}
        if ledger:
            r["side"] = _side()
        rows.append(r)
    flush()
    return rows, {"debit": round(tot_d, 2), "credit": round(tot_c, 2), "balance": round(bal, 2)}


def _cashbook_data(db, fy, account_id=None):
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.id).all()
    if account_id:
        acc = db.get(FinanceAccount, account_id)
        scope = acc.name if acc else "ทุกบัญชี"
        opening = opening_for(acc, fy) if acc else 0.0
        txns = [t for t in (acc.txns if acc else []) if t.fiscal_year == fy]
        acct_names = None
    else:
        scope = "ทุกบัญชี"
        opening = sum(opening_for(a, fy) for a in accounts)
        txns = db.query(FinanceTxn).filter_by(fiscal_year=fy).all()
        acct_names = {a.id: a.name for a in accounts}
    rows, totals = _build_book_rows(txns, opening, acct_names=acct_names)
    return accounts, scope, opening, rows, totals


def _cashbook_fund_data(db, fy, account_id=None):
    """ข้อมูลสมุดเงินสดแบบราชการ (แยกด้านรับ/จ่าย + แยกประเภทเงินตามงบ)
    คืน (scope, open_by_fund{งบ:ยอดยกมา}, receipts[], payments[])
    แต่ละรายการ = {date, ref, desc, amount, fund}"""
    if account_id:
        acc = db.get(FinanceAccount, account_id)
        accts = [acc] if acc else []
        scope = acc.name if acc else "ทุกบัญชี"
        multi = False
    else:
        accts = db.query(FinanceAccount).order_by(FinanceAccount.id).all()
        scope = "ทุกบัญชี"
        multi = True
    fund_of = {a.id: (a.fund_type or _FUND_DEFAULT) for a in accts}
    name_of = {a.id: a.name for a in accts}
    open_by_fund = {f: 0.0 for f in FUND_TYPES}
    for a in accts:
        open_by_fund[fund_of[a.id]] = open_by_fund.get(fund_of[a.id], 0.0) + (opening_for(a, fy) or 0.0)
    aids = set(fund_of)
    txns = [t for t in db.query(FinanceTxn).filter_by(fiscal_year=fy).all() if t.account_id in aids]
    receipts, payments = [], []
    for t in sorted(txns, key=lambda x: (x.date or datetime.min, x.id)):
        desc = " ".join(x for x in [(t.category or "").strip(), (t.note or "").strip()] if x) or "-"
        if multi and name_of.get(t.account_id):
            desc = f"[{name_of[t.account_id]}] {desc}"
        row = {"id": t.id, "date": thai_date(t.date) if t.date else "", "ref": (t.ref or "").strip(),
               "desc": desc, "amount": t.amount or 0.0, "fund": fund_of.get(t.account_id, _FUND_DEFAULT)}
        (receipts if t.kind == "in" else payments).append(row)
    return scope, open_by_fund, receipts, payments


@router.get("/finance/cashbook", response_class=HTMLResponse)
def cashbook_page(request: Request, db: Session = Depends(get_db),
                  year: int | None = None, account: int | None = None):
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    scope, open_by_fund, receipts, payments = _cashbook_fund_data(db, fy, account)

    def _sect_tot(rows, opening=None):
        tot = {"cash": 0.0}
        for f in FUND_TYPES:
            tot[f] = 0.0
        if opening is not None:
            for f in FUND_TYPES:
                tot[f] += opening.get(f, 0.0); tot["cash"] += opening.get(f, 0.0)
        for r in rows:
            tot["cash"] += r["amount"]; tot[r["fund"]] = tot.get(r["fund"], 0.0) + r["amount"]
        return tot

    rin = _sect_tot(receipts, open_by_fund)
    rout = _sect_tot(payments)
    opening_cash = sum(open_by_fund.get(f, 0.0) for f in FUND_TYPES)
    recv_total = sum(r["amount"] for r in receipts)
    pay_total = sum(r["amount"] for r in payments)
    carry = {"cash": rin["cash"] - rout["cash"]}
    for f in FUND_TYPES:
        carry[f] = rin[f] - rout[f]
    sections = [
        {"title": "ด้านรับ  (เดบิต = เงินสด · เครดิตแยกตามประเภทเงิน)",
         "total_label": "รวมด้านรับ", "rows": receipts, "opening": open_by_fund, "tot": rin},
        {"title": "ด้านจ่าย  (เครดิต = เงินสด · เดบิตแยกตามประเภทเงิน)",
         "total_label": "รวมด้านจ่าย", "rows": payments, "opening": None, "tot": rout},
    ]
    return templates.TemplateResponse("finance_cashbook.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy), "accounts": accounts, "sel_account": account,
        "scope": scope, "funds": FUND_TYPES, "sections": sections, "carry": carry,
        "opening_cash": opening_cash, "recv_total": recv_total, "pay_total": pay_total,
    })


@router.get("/finance/cashbook.docx")
def cashbook_docx(db: Session = Depends(get_db), year: int | None = None, account: int | None = None):
    fy = year or current_fiscal_year()
    scope, open_by_fund, receipts, payments = _cashbook_fund_data(db, fy, account)
    path = render_cash_book_fund(get_school(db), fy, scope, open_by_fund, receipts, payments)
    return serve_generated(path, _DOCX)


@router.get("/finance/cashbook.xlsx")
def cashbook_xlsx(db: Session = Depends(get_db), year: int | None = None, account: int | None = None):
    fy = year or current_fiscal_year()
    scope, open_by_fund, receipts, payments = _cashbook_fund_data(db, fy, account)
    path = build_cash_book_fund_xlsx(fy, scope, open_by_fund, receipts, payments)
    return serve_generated(path, _XLSX)


def _ledger_data(db, aid, fy):
    a = db.get(FinanceAccount, aid)
    if not a:
        return None, 0.0, []
    opening = opening_for(a, fy)
    txns = [t for t in a.txns if t.fiscal_year == fy]
    rows, _totals = _build_book_rows(txns, opening, ledger=True)
    return a, opening, rows


@router.get("/finance/accounts/{aid}/ledger.docx")
def ledger_docx(aid: int, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    a, opening, rows = _ledger_data(db, aid, fy)
    if not a:
        return RedirectResponse("/finance/accounts", status_code=303)
    path = render_general_ledger(get_school(db), a, fy, rows, opening)
    return serve_generated(path, _DOCX)


@router.get("/finance/accounts/{aid}/ledger.xlsx")
def ledger_xlsx(aid: int, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    a, opening, rows = _ledger_data(db, aid, fy)
    if not a:
        return RedirectResponse("/finance/accounts", status_code=303)
    path = build_ledger_xlsx(a, fy, rows, opening)
    return serve_generated(path, _XLSX)


# ---------------- ศูนย์รายงานแบบ สตง. ----------------
@router.get("/finance/audit", response_class=HTMLResponse)
def audit_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    return templates.TemplateResponse("finance_audit.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy), "accounts": accounts,
        "today_be": be_date_input(datetime.now()),
    })


@router.get("/finance/report.xlsx")
def report_xlsx(db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    txns = db.query(FinanceTxn).filter_by(fiscal_year=fy).all()
    path = export_finance_report(accounts, txns, fy)
    return serve_generated(path, _XLSX)


# ---------------- นำเข้า Excel ----------------
@router.get("/finance/import", response_class=HTMLResponse)
def finance_import_page(request: Request, imported: str | None = None, import_err: str | None = None):
    lines = []
    if imported and imported != "none":
        for part in imported.split(","):
            if ":" in part:
                sheet, n = part.split(":", 1)
                lines.append(f"{sheet}: เพิ่ม {n} รายการ")
    err = {"type": "ไฟล์ต้องเป็น .xlsx เท่านั้น",
           "read": "อ่านไฟล์ไม่สำเร็จ ตรวจสอบว่าใช้เทมเพลตที่ถูกต้อง"}.get(import_err)
    return templates.TemplateResponse("finance_import.html", {
        "request": request, "import_lines": lines, "import_err": err,
    })


@router.get("/finance/template.xlsx")
def finance_template():
    path = build_finance_template()
    return serve_generated(path, _XLSX)


@router.post("/finance/import")
async def finance_import(db: Session = Depends(get_db), file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        return RedirectResponse("/finance/import?import_err=type", status_code=303)
    content = await file.read()
    try:
        summary = import_finance_workbook(content, db)
    except Exception:
        return RedirectResponse("/finance/import?import_err=read", status_code=303)
    q = ",".join(f"{k}:{v}" for k, v in summary.items()) or "none"
    return RedirectResponse(f"/finance/import?imported={q}", status_code=303)


# ==================== เงินยืม · เช็ค · กระทบยอด · 50 ทวิ · ไตรมาส ====================
def _fin_accounts(db):
    return db.query(FinanceAccount).order_by(FinanceAccount.name).all()


def _fin_persons(db):
    """รายชื่อบุคลากร (ใช้เลือกผู้ยืมในหน้าเงินยืม)"""
    from app.models import Person
    return db.query(Person).filter_by(active=True).order_by(Person.name).all()


# ---------------- ใบสำคัญรับเงิน (พิมพ์จากทะเบียนใบเสร็จ) ----------------
@router.get("/finance/receipts/{rid}/voucher")
def receipt_voucher_doc(rid: int, db: Session = Depends(get_db)):
    """พิมพ์ใบสำคัญรับเงินจากรายการในทะเบียนใบเสร็จ"""
    from app.services.receipt_voucher import render_receipt_voucher
    r = db.get(Receipt, rid)
    if not r:
        return RedirectResponse("/finance/receipts", status_code=303)
    path = render_receipt_voucher(
        get_school(db), payee=r.party or "", payee_address="",
        items=[((r.note or "").strip() or f"รับเงินตามใบเสร็จเลขที่ {r.receipt_no or '-'}",
                 float(r.amount or 0))],
        total=float(r.amount or 0), date=r.date,
        subject=f"ใบสำคัญรับเงิน_{r.receipt_no or r.id}")
    return serve_generated(path, _DOCX)


# ---------------- เงินยืม (สัญญาแบบ 8500 + ทะเบียนคุมลูกหนี้) ----------------
@router.get("/finance/loans", response_class=HTMLResponse)
def loans_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    from app.services.dashboard_tasks import loan_state
    from app.thai_utils import thai_today
    attention = request.query_params.get('attention')
    query = db.query(MoneyLoan)
    if attention not in ('overdue', 'soon', 'undated'):
        query = query.filter_by(fiscal_year=fy)
    loans = query.order_by(MoneyLoan.due_date, MoneyLoan.id).all()
    if attention in ('overdue', 'soon', 'undated'):
        today = thai_today()
        loans = [loan for loan in loans if loan_state(loan, today)[0] == attention]
    rows = []
    for ln in loans:
        paid = sum(float(r.amount or 0) for r in (ln.returns or []))
        rows.append({"o": ln, "paid": paid, "left": float(ln.amount or 0) - paid})
    return templates.TemplateResponse("finance_loans.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy), "rows": rows,
        "accounts": _fin_accounts(db), "today_be": be_date_input(datetime.now()),
        "persons": _fin_persons(db),
    })


@router.post("/finance/loans")
async def loan_add(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    fy = _to_int(form.get("fiscal_year"), current_fiscal_year())
    borrow_date = parse_be_date(form.get("date"))
    receive_date = parse_be_date(form.get("receive_date"))
    within_days = max(1, _to_int(form.get("within_days"), 15))
    # Match the contract: count from receipt of the money, falling back to borrowing date.
    base_date = receive_date or borrow_date
    due_date = base_date + timedelta(days=within_days) if base_date else None
    ln = MoneyLoan(
        fiscal_year=fy, contract_no=(form.get("contract_no") or "").strip(),
        date=borrow_date, receive_date=receive_date,
        due_date=due_date,
        borrower=(form.get("borrower") or "").strip(),
        position=(form.get("position") or "").strip(),
        submit_to=(form.get("submit_to") or "").strip(),
        fund_from=(form.get("fund_from") or "").strip(),
        purpose=(form.get("purpose") or "").strip(),
        amount=_to_float(form.get("amount"), 0.0),
        within_days=within_days,
        account_id=_to_int(form.get("account_id"), 0) or None,
        note=(form.get("note") or "").strip())
    db.add(ln); db.commit()
    return RedirectResponse(f"/finance/loans?year={fy}", status_code=303)


@router.post("/finance/loans/{lid}/return")
async def loan_return_add(lid: int, request: Request, db: Session = Depends(get_db)):
    """บันทึกการส่งใช้เงินยืม (เงินสดหรือใบสำคัญ)"""
    form = await request.form()
    ln = db.get(MoneyLoan, lid)
    if ln:
        db.add(LoanReturn(loan_id=lid, date=parse_be_date(form.get("date")),
                          kind=(form.get("kind") or "เงินสด").strip(),
                          amount=_to_float(form.get("amount"), 0.0),
                          receipt_no=(form.get("receipt_no") or "").strip(),
                          note=(form.get("note") or "").strip()))
        db.commit()
    return RedirectResponse(f"/finance/loans?year={ln.fiscal_year if ln else ''}", status_code=303)


@router.post("/finance/loans/{lid}/delete")
def loan_delete(lid: int, db: Session = Depends(get_db)):
    ln = db.get(MoneyLoan, lid)
    fy = ln.fiscal_year if ln else current_fiscal_year()
    if ln:
        db.delete(ln); db.commit()
    return RedirectResponse(f"/finance/loans?year={fy}", status_code=303)


@router.get("/finance/loans/{lid}/contract.docx")
def loan_contract_doc(lid: int, db: Session = Depends(get_db)):
    from app.services.finance_forms_doc import render_loan_contract
    ln = db.get(MoneyLoan, lid)
    if not ln:
        return RedirectResponse("/finance/loans", status_code=303)
    return serve_generated(render_loan_contract(get_school(db), ln), _DOCX)


@router.get("/finance/loans/{lid}/returns.docx")
def loan_returns_doc(lid: int, db: Session = Depends(get_db)):
    from app.services.finance_forms_doc import render_loan_returns
    ln = db.get(MoneyLoan, lid)
    if not ln or not ln.returns:
        return RedirectResponse("/finance/loans", status_code=303)
    return serve_generated(render_loan_returns(get_school(db), ln), _DOCX)


@router.get("/finance/loans/register.docx")
def loan_register_doc(request: Request, db: Session = Depends(get_db),
                      year: int | None = None):
    from app.services.finance_forms_doc import render_loan_register
    fy = year or current_fiscal_year()
    from app.services.dashboard_tasks import loan_state
    from app.thai_utils import thai_today
    attention = request.query_params.get('attention')
    query = db.query(MoneyLoan)
    if attention not in ('overdue', 'soon', 'undated'):
        query = query.filter_by(fiscal_year=fy)
    loans = query.order_by(MoneyLoan.due_date, MoneyLoan.id).all()
    if attention in ('overdue', 'soon', 'undated'):
        today = thai_today()
        loans = [loan for loan in loans if loan_state(loan, today)[0] == attention]
    return serve_generated(render_loan_register(get_school(db), fy, loans), _DOCX)


# ---------------- ทะเบียนคุมการจ่ายเช็ค ----------------
@router.get("/finance/checks", response_class=HTMLResponse)
def checks_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    rows = (db.query(CheckPayment).filter_by(fiscal_year=fy)
            .order_by(CheckPayment.date, CheckPayment.id).all())
    return templates.TemplateResponse("finance_checks.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy), "rows": rows, "accounts": _fin_accounts(db),
        "today_be": be_date_input(datetime.now()),
    })


@router.post("/finance/checks")
async def check_add(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    fy = _to_int(form.get("fiscal_year"), current_fiscal_year())
    db.add(CheckPayment(
        fiscal_year=fy, date=parse_be_date(form.get("date")),
        pay_method=(form.get("pay_method") or "โอน").strip(),
        check_no=(form.get("check_no") or "").strip(), bank=(form.get("bank") or "").strip(),
        payee=(form.get("payee") or "").strip(), amount=_to_float(form.get("amount"), 0.0),
        purpose=(form.get("purpose") or "").strip(),
        account_id=_to_int(form.get("account_id"), 0) or None,
        note=(form.get("note") or "").strip()))
    db.commit()
    return RedirectResponse(f"/finance/checks?year={fy}", status_code=303)


@router.post("/finance/checks/{cid}/toggle")
def check_toggle(cid: int, db: Session = Depends(get_db),
                 date: str = Form("", alias="cleared_date")):
    """สลับสถานะ 'เงินออกจากบัญชีแล้ว' พร้อมวันที่เงินออกจริง

    วันที่นี้ทำให้ย้อนไปทำงบกระทบยอดของเดือนก่อนได้ถูกต้อง เช็คที่เพิ่งขึ้นเงิน
    เดือนนี้ต้องยังนับเป็นรายการคงค้างของเดือนที่แล้ว ไม่ใช่หายไปทั้งแถว
    """
    ck = db.get(CheckPayment, cid)
    fy = ck.fiscal_year if ck else current_fiscal_year()
    if ck:
        ck.cleared = not bool(ck.cleared)
        ck.cleared_date = (parse_be_date(date) or datetime.now()) if ck.cleared else None
        db.commit()
    return RedirectResponse(f"/finance/checks?year={fy}", status_code=303)


@router.post("/finance/checks/{cid}/delete")
def check_delete(cid: int, db: Session = Depends(get_db)):
    ck = db.get(CheckPayment, cid)
    fy = ck.fiscal_year if ck else current_fiscal_year()
    if ck:
        db.delete(ck); db.commit()
    return RedirectResponse(f"/finance/checks?year={fy}", status_code=303)


@router.get("/finance/checks/register.docx")
def check_register_doc(db: Session = Depends(get_db), year: int | None = None):
    from app.services.finance_forms_doc import render_check_register
    fy = year or current_fiscal_year()
    rows = (db.query(CheckPayment).filter_by(fiscal_year=fy)
            .order_by(CheckPayment.date, CheckPayment.id).all())
    return serve_generated(render_check_register(get_school(db), fy, rows), _DOCX)


# ---------------- งบกระทบยอดเงินฝากธนาคาร ----------------
def _book_balance(db, fy, account_id, upto=None):
    """ยอดคงเหลือตามบัญชีของโรงเรียน = ยอดยกมาของปีงบนั้น + รับ - จ่าย

    upto = ตัดยอด ณ วันที่ (กระทบยอดสิ้นเดือนไหน ต้องใช้ยอดถึงวันนั้น
    ไม่ใช่ยอดทั้งปีที่รวมเดือนถัด ๆ ไปที่ลงบัญชีไปแล้ว)
    รายการที่ไม่มีวันที่ถือว่าอยู่ในช่วงเสมอ จะได้ไม่หายไปเงียบ ๆ
    """
    acc = db.get(FinanceAccount, account_id) if account_id else None
    if not acc:
        return 0.0
    bal = opening_for(acc, fy)      # ยอดยกมาของปีงบนั้น ไม่ใช่ยอดตั้งต้นของบัญชี
    for t in db.query(FinanceTxn).filter_by(account_id=acc.id, fiscal_year=fy).all():
        if upto is not None and t.date is not None and t.date.date() > upto.date():
            continue
        bal += float(t.amount or 0) if t.kind == "in" else -float(t.amount or 0)
    return round(bal, 2)


def _recon_rows(db, fy, account_id):
    """งบกระทบยอดที่ทำไว้ เฉพาะบัญชีที่กำลังดู ไม่ปนบัญชีอื่น"""
    q = db.query(BankRecon).filter_by(fiscal_year=fy)
    if account_id:
        q = q.filter(BankRecon.account_id == account_id)
    return q.order_by(BankRecon.as_of.desc(), BankRecon.id.desc()).all()


def _outstanding_checks(db, fy, account_id, as_of=None):
    """รายการจ่ายที่เงินยังไม่ออก -> (ของบัญชีนี้, ที่ยังไม่ได้ระบุบัญชี)

    ของเดิมถือว่ารายการที่ไม่ระบุบัญชีเป็นของบัญชีที่กำลังดู ทำให้โรงเรียน
    ที่มีหลายบัญชีเอายอดเดียวกันไปหักซ้ำทุกบัญชี · แยกออกมาเตือนให้ไประบุบัญชีแทน

    as_of = ตัดสิน ณ วันที่ทำงบ รายการที่เงินออกหลังวันนั้น ยังถือว่าคงค้างอยู่
    ติ๊กแล้วแต่ไม่มีวันที่ = ข้อมูลเก่าก่อนมีช่องนี้ ถือว่าออกไปแล้วตั้งแต่ต้น
    """
    def still_out(c):
        if not c.cleared:
            return True
        return bool(as_of and c.cleared_date and c.cleared_date.date() > as_of.date())

    rows = [c for c in db.query(CheckPayment).filter_by(fiscal_year=fy)
            .order_by(CheckPayment.date).all() if still_out(c)]
    mine = [c for c in rows if account_id and c.account_id == account_id]
    loose = [c for c in rows if not c.account_id]
    return mine, loose


@router.get("/finance/bank-recon", response_class=HTMLResponse)
def bank_recon_page(request: Request, db: Session = Depends(get_db),
                    year: int | None = None, account_id: int = 0):
    fy = year or current_fiscal_year()
    accounts = _fin_accounts(db)
    aid = account_id or (accounts[0].id if accounts else 0)
    outstanding, loose = _outstanding_checks(db, fy, aid)
    # ยอดตามบัญชีรายวัน ให้หน้าจอขยับตามวันที่ที่เลือกได้เองโดยไม่ต้องโหลดใหม่
    daily, run = {}, opening_for(db.get(FinanceAccount, aid), fy) if aid else 0.0
    if aid:
        txns = sorted(db.query(FinanceTxn).filter_by(account_id=aid, fiscal_year=fy).all(),
                      key=lambda t: (t.date or datetime.min))
        for t in txns:
            run += float(t.amount or 0) if t.kind == "in" else -float(t.amount or 0)
            if t.date:
                daily[t.date.strftime("%Y-%m-%d")] = round(run, 2)
    return templates.TemplateResponse("finance_bank_recon.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy),
        "rows": [(r, recon_sides(r)) for r in _recon_rows(db, fy, aid)],
        "accounts": accounts,
        "account_id": aid, "today_be": be_date_input(datetime.now()),
        "book_balance": _book_balance(db, fy, aid),
        "opening": opening_for(db.get(FinanceAccount, aid), fy) if aid else 0.0,
        "daily_balance": daily,
        "outstanding": outstanding, "loose_checks": loose,
        "outstanding_sum": sum(float(c.amount or 0) for c in outstanding),
        # ให้หน้าจอคิดรายการคงค้าง ณ วันที่ที่เลือกได้เอง ไม่ต้องโหลดหน้าใหม่
        "check_data": [{"amount": float(c.amount or 0), "cleared": bool(c.cleared),
                        "cleared_on": c.cleared_date.strftime("%Y-%m-%d") if c.cleared_date else "",
                        "payee": c.payee or "", "no": c.check_no or "",
                        "on": c.date.strftime("%Y-%m-%d") if c.date else ""}
                       for c in db.query(CheckPayment).filter_by(fiscal_year=fy)
                       .order_by(CheckPayment.date).all() if c.account_id == aid],
    })


@router.post("/finance/bank-recon")
async def bank_recon_add(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    fy = _to_int(form.get("fiscal_year"), current_fiscal_year())
    aid = _to_int(form.get("account_id"), 0) or None
    rec = BankRecon(
        fiscal_year=fy, account_id=aid, as_of=parse_be_date(form.get("as_of")),
        stmt_balance=_to_float(form.get("stmt_balance"), 0.0),
        in_transit=_to_float(form.get("in_transit"), 0.0),
        outstanding=_to_float(form.get("outstanding"), 0.0),
        bank_fee=_to_float(form.get("bank_fee"), 0.0),
        interest=_to_float(form.get("interest"), 0.0),
        other=_to_float(form.get("other"), 0.0),
        other_side=("book" if form.get("other_side") == "book" else "bank"),
        other_note=(form.get("other_note") or "").strip(),
        book_balance=_to_float(form.get("book_balance"), 0.0),
        note=(form.get("note") or "").strip())
    db.add(rec); db.commit()
    return RedirectResponse(f"/finance/bank-recon?year={fy}&account_id={aid or 0}",
                            status_code=303)


@router.post("/finance/bank-recon/{rid}/delete")
def bank_recon_delete(rid: int, db: Session = Depends(get_db)):
    rec = db.get(BankRecon, rid)
    fy = rec.fiscal_year if rec else current_fiscal_year()
    if rec:
        db.delete(rec); db.commit()
    return RedirectResponse(f"/finance/bank-recon?year={fy}", status_code=303)


@router.get("/finance/bank-recon/{rid}.docx")
def bank_recon_doc(rid: int, db: Session = Depends(get_db)):
    from app.services.finance_forms_doc import render_bank_recon
    rec = db.get(BankRecon, rid)
    if not rec:
        return RedirectResponse("/finance/bank-recon", status_code=303)
    acc = db.get(FinanceAccount, rec.account_id) if rec.account_id else None
    # รายการคงค้าง ณ วันที่ของงบใบนี้ ไม่ใช่ ณ วันที่กดพิมพ์
    checks, _ = _outstanding_checks(db, rec.fiscal_year, rec.account_id, as_of=rec.as_of)
    return serve_generated(
        render_bank_recon(get_school(db), rec, acc.name if acc else "", checks), _DOCX)


# ---------------- หนังสือรับรองการหักภาษี ณ ที่จ่าย (50 ทวิ) ----------------
def _payee_vendor(db, memo):
    """ผู้ขายของบันทึกขอเบิก: ผู้ขายของเรื่องจัดซื้อที่ผูกไว้ ก่อน · ไม่มีก็หาจากชื่อผู้รับเงินในทะเบียนผู้ขาย"""
    from app.models import Procurement, Vendor
    if memo.procurement_id:
        p = db.get(Procurement, memo.procurement_id)
        if p and p.vendor:
            return p.vendor
    name = (memo.payee or "").strip()
    if not name:
        return None
    # ชื่อต้องตรงกันเป๊ะ - เว้นว่างให้เขียนเองดีกว่าดึงเลขภาษีของร้านอื่นมาผิดคน
    return db.query(Vendor).filter(Vendor.name == name).first()


@router.get("/finance/disburse/{mid}/wht.docx")
def wht_certificate_doc(mid: int, db: Session = Depends(get_db),
                        tax_id: str = "", address: str = "",
                        pay_type: str = "ค่าจ้างทำของ"):
    from app.services.finance_forms_doc import render_wht_certificate
    memo = db.get(DisburseMemo, mid)
    if not memo:
        return RedirectResponse("/finance/disburse", status_code=303)
    # ผู้ถูกหักภาษี: ดึงเลขผู้เสียภาษี/ที่อยู่จากทะเบียนผู้ขาย (ส่งค่าใน URL มาเองได้ทับ)
    v = _payee_vendor(db, memo)
    from app.models import Procurement
    proc = db.get(Procurement, memo.procurement_id) if memo.procurement_id else None
    path = render_wht_certificate(
        get_school(db), memo,
        ref_no=((proc.order_no or "").strip() if proc else "") or (memo.memo_no or ""),
        payee_tax_id=tax_id.strip() or ((v.tax_id or "").strip() if v else ""),
        payee_address=address.strip() or ((v.address or "").strip() if v else ""),
        pay_type=pay_type)
    return serve_generated(path, _DOCX)


# ---------------- รายงานผลการใช้จ่ายงบประมาณรายไตรมาส ----------------
_Q_MONTHS = {1: (10, 11, 12), 2: (1, 2, 3), 3: (4, 5, 6), 4: (7, 8, 9)}


def _quarter_rows(db, fy, quarter):
    """ยอดยกมา (ก่อนไตรมาส) · รับ/จ่ายในไตรมาส · คงเหลือ แยกตามบัญชี"""
    months = _Q_MONTHS.get(quarter, ())
    rows = []
    tot = {"opening": 0.0, "income": 0.0, "expense": 0.0, "balance": 0.0}
    for acc in _fin_accounts(db):
        # ต้องใช้ opening_for ไม่ใช่ acc.opening_balance ไม่งั้นปีที่ยกยอดมา
        # จะกลับไปใช้ยอดตั้งต้นตอนสร้างบัญชี (ยอดยกมาที่ยกไว้หายทั้งก้อน)
        opening = opening_for(acc, fy)
        inc = exp = 0.0
        for t in db.query(FinanceTxn).filter_by(account_id=acc.id, fiscal_year=fy).all():
            mth = t.date.month if t.date else 0
            amt = float(t.amount or 0)
            if mth in months:
                if t.kind == "in":
                    inc += amt
                else:
                    exp += amt
            elif _before_quarter(mth, quarter):
                opening += amt if t.kind == "in" else -amt
        bal = opening + inc - exp
        rows.append({"account": acc.name, "opening": opening, "income": inc,
                     "expense": exp, "balance": bal})
        tot["opening"] += opening; tot["income"] += inc
        tot["expense"] += exp; tot["balance"] += bal
    return rows, tot


def _before_quarter(month, quarter) -> bool:
    """เดือนนี้อยู่ก่อนไตรมาสที่เลือกไหม (ปีงบเริ่ม ต.ค.)"""
    order = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    if month not in order:
        return False
    start = (quarter - 1) * 3
    return order.index(month) < start


@router.get("/finance/quarter", response_class=HTMLResponse)
def quarter_page(request: Request, db: Session = Depends(get_db),
                 year: int | None = None, q: int = 1):
    fy = year or current_fiscal_year()
    q = q if q in (1, 2, 3, 4) else 1
    rows, tot = _quarter_rows(db, fy, q)
    from app.services.finance_forms_doc import QUARTERS
    return templates.TemplateResponse("finance_quarter.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy), "rows": rows, "totals": tot,
        "quarter": q, "quarters": QUARTERS,
    })


@router.get("/finance/quarter.docx")
def quarter_doc(db: Session = Depends(get_db), year: int | None = None, q: int = 1):
    from app.services.finance_forms_doc import render_quarter_report
    fy = year or current_fiscal_year()
    q = q if q in (1, 2, 3, 4) else 1
    rows, tot = _quarter_rows(db, fy, q)
    return serve_generated(render_quarter_report(get_school(db), fy, q, rows, tot), _DOCX)


# ---------------- ทะเบียนคุมเงิน (ฟอร์มกลาง ใช้ได้ทุกบัญชีและทุกรายการย่อย) ----------------
def _register_rows(db, fy):
    """แถวสำหรับออกทะเบียนคุม: บัญชี + รายการย่อยที่มีงบหรือมีรายการเคลื่อนไหว

    บัญชีที่แบ่งเป็นรายการย่อย (เช่น เงินอุดหนุน) "ไม่มีทะเบียนคุมของตัวเอง"
    ของจริงคุมแยกทีละประเภทย่อย (ค่าจัดการเรียนการสอน, ค่าหนังสือเรียน, ...)
    จึงออกเฉพาะระดับรายการย่อย ตามที่แบบฟอร์มระบุ "ประเภทเงิน ..." ไว้ด้านบน
    """
    rows = []
    for a in db.query(FinanceAccount).order_by(FinanceAccount.name).all():
        txns = [t for t in a.txns if t.fiscal_year == fy]
        items = (db.query(AccountItem)
                 .filter_by(account_id=a.id, fiscal_year=fy)
                 .order_by(AccountItem.id).all())
        if not items:
            rows.append((a, None, txns, opening_for(a, fy)))
            continue
        for it in items:
            ids = _item_family(db, it)
            sub = [t for t in txns if t.item_id in ids]
            item_opening=sum(x.opening_balance or 0 for x in items if x.id in ids)
            if not sub and not item_opening and not (it.budget or 0):
                continue                       # รายการย่อยที่ยังไม่มีอะไรเลย ไม่ต้องพิมพ์
            rows.append((a, it, sub, item_opening))
        # Keep unclassified openings/transactions visible in the combined register.
        known={it.id for it in items}
        unclassified=[t for t in txns if t.item_id not in known]
        unallocated=round(opening_for(a,fy)-sum(it.opening_balance or 0 for it in items),2)
        if unallocated or unclassified:
            from types import SimpleNamespace
            label=SimpleNamespace(name='ยอดที่ยังไม่แยกหมวด / รายการไม่ระบุหมวด',deposit_type=a.deposit_type)
            rows.append((a,label,unclassified,unallocated))
    return rows


def _item_family(db, it):
    """id ของรายการย่อยนี้ + หมวดลูกทั้งหมด (หมวดหลักต้องคุมรวมของลูกด้วย)"""
    ids = {it.id}
    ids.update(x.id for x in db.query(AccountItem)
               .filter_by(parent_id=it.id, fiscal_year=it.fiscal_year).all())
    return ids


@router.get("/finance/accounts/{aid}/money-register.docx")
def account_money_register_docx(aid: int, db: Session = Depends(get_db),
                                year: int | None = None, item: int | None = None):
    """ทะเบียนคุมเงินของบัญชีนี้ (ใส่ item=<id> เพื่อออกเฉพาะรายการย่อยนั้น)"""
    fy = year or current_fiscal_year()
    a = db.get(FinanceAccount, aid)
    if not a:
        return RedirectResponse("/finance/accounts", status_code=303)
    txns = [t for t in a.txns if t.fiscal_year == fy]
    sub = None
    if item:
        sub = db.get(AccountItem, item)
        if not sub or sub.account_id != a.id or sub.fiscal_year != fy:
            raise HTTPException(status_code=404, detail="ไม่พบรายการย่อยนี้ในบัญชี")
        ids = _item_family(db, sub)
        txns = [t for t in txns if t.item_id in ids]
    path = render_money_register(get_school(db), a, txns,
                                 sum(i.opening_balance or 0 for i in a.items if i.id in ids) if sub else opening_for(a, fy), fy, item=sub)
    return serve_generated(path, _DOCX)


# ใช้ /finance/registers.docx ไม่ใช่ /finance/accounts/registers.docx
# เพราะจะไปชนกับ /finance/accounts/{aid} (aid เป็น int -> ได้ 422 แทนไฟล์)
@router.get("/finance/registers.docx")
def all_money_registers_docx(db: Session = Depends(get_db), year: int | None = None):
    """ออกทะเบียนคุมทุกบัญชีและทุกรายการย่อย รวมเป็นไฟล์เดียว"""
    fy = year or current_fiscal_year()
    try:
        path = render_all_registers(get_school(db), _register_rows(db, fy), fy)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return serve_generated(path, _DOCX)


# ---------------- ทะเบียนคุมเฉพาะประเภทเงิน (เกาะกับบัญชีที่ครูตั้งไว้) ----------------
@router.get("/finance/accounts/{aid}/register.docx")
def account_register_docx(aid: int, db: Session = Depends(get_db), year: int | None = None):
    """พิมพ์ทะเบียนคุมตามรูปแบบเฉพาะของประเภทบัญชี
    (เงินประกันสัญญา / เงินรายได้แผ่นดิน / เงินฝากส่วนราชการผู้เบิก)"""
    fy = year or current_fiscal_year()
    a = db.get(FinanceAccount, aid)
    key = special_form(a) if a else ""
    if not a or not key:
        return RedirectResponse(f"/finance/accounts/{aid}?year={fy}", status_code=303)
    txns = [t for t in a.txns if t.fiscal_year == fy]
    path = render_account_register(get_school(db), a, txns, opening_for(a, fy), fy, key)
    return serve_generated(path, _DOCX)


@router.get("/finance/safe-custody.docx")
def safe_custody_docx(db: Session = Depends(get_db),
                      year: int | None = None, date: str | None = None):
    """บันทึกการรับเงินเพื่อเก็บรักษา - คู่กับรายงานเงินคงเหลือประจำวัน
    นับเฉพาะ "เงินสด" เพราะเป็นเงินที่ต้องเก็บในตู้นิรภัย"""
    as_of = parse_be_date(date) if date else datetime.now()
    fy = year or current_fiscal_year(as_of)
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.id).all()
    rows, totals = _build_cash_rows(accounts, fy, as_of)
    cash_rows = [(r["name"], r.get("cash") or 0)
                 for r in rows if r.get("kind") != "group" and (r.get("cash") or 0)]
    path = render_safe_custody(get_school(db), cash_rows, totals.get("cash") or 0, as_of)
    return serve_generated(path, _DOCX)


@router.get("/finance/disburse-register.docx")
def disburse_register_docx(db: Session = Depends(get_db), year: int | None = None):
    """ทะเบียนคุมหลักฐานขอเบิก - สรุปบันทึกขอเบิกจ่ายทั้งปีงบ"""
    fy = year or current_fiscal_year()
    memos = (db.query(DisburseMemo).filter_by(fiscal_year=fy)
             .order_by(DisburseMemo.date, DisburseMemo.id).all())
    path = render_disburse_register(get_school(db), fy, memos)
    return serve_generated(path, _DOCX)


def _plan_projects(db, year=None):
    """โครงการให้เลือกตอนลงรับ-จ่าย

    เอาทั้งปีแผนปัจจุบันและปีที่กำลังดูอยู่ เพราะช่วงต้นปีงบ (1 ต.ค.)
    ปีแผนจะข้ามไปปีใหม่แล้ว แต่ครูยังลงรายการของปีเก่าค้างอยู่
    """
    from app.models import Project
    years = {current_plan_year(get_school(db))}
    if year:
        years.add(year)
    return (db.query(Project).filter(Project.plan_year.in_(years))
            .order_by(Project.plan_year.desc(), Project.name).all())


# ---------------- ทะเบียนคุมโครงการ (ผูกกับเงินที่จ่ายจริง) ----------------
def _project_register_rows(db, year):
    """โครงการของปีแผนนั้น + รายการใช้เงินจริงทุกทาง (จัดซื้อ · ขอเบิกจ่าย · จ่ายตรง)"""
    from app.models import Project
    from app.services.project_summary import build_rows
    projects = (db.query(Project).filter(Project.plan_year == year)
                .order_by(Project.name).all())
    return build_rows(db, projects)


def _plan_year_list(db, cur):
    from app.models import Project
    ys = {y for (y,) in db.query(Project.plan_year).distinct().all() if y}
    ys.add(cur)
    return sorted(ys, reverse=True)


@router.get("/finance/projects", response_class=HTMLResponse)
def finance_projects_page(request: Request, db: Session = Depends(get_db),
                          year: int | None = None):
    """ทะเบียนคุมโครงการ: งบที่ตั้งไว้ · ใช้ไปเท่าไร · เหลือเท่าไร · ใช้ไปกับอะไรบ้าง"""
    school = get_school(db)
    cur = year or current_plan_year(school)
    rows = _project_register_rows(db, cur)
    return templates.TemplateResponse("finance_projects.html", {
        "request": request, "rows": rows, "fiscal_year": cur,
        "year_label": plan_year_label(school), "years": _plan_year_list(db, cur),
        "total_budget": sum(r["budget"] for r in rows),
        "total_spent": sum(r["spent"] for r in rows),
        "total_left": sum(r["left"] for r in rows),
    })


@router.get("/finance/projects/register.docx")
def finance_projects_register_docx(db: Session = Depends(get_db),
                                   year: int | None = None, project: int | None = None):
    """ทะเบียนคุมโครงการเป็นไฟล์ Word (ใส่ project=<id> เพื่อออกเฉพาะโครงการนั้น)"""
    from app.services.project_register import render_project_register
    school = get_school(db)
    cur = year or current_plan_year(school)
    rows = _project_register_rows(db, cur)
    if project:
        rows = [r for r in rows if r["p"].id == project]
        if not rows:
            raise HTTPException(status_code=404, detail="ไม่พบโครงการนี้ในปีที่เลือก")
    path = render_project_register(school, cur, plan_year_label(school), rows)
    return serve_generated(path, _DOCX)


# ---------------- ช่วยกรอก e-Budget (ระบบบัญชีการศึกษาขั้นพื้นฐาน สนผ. สพฐ.) ----------------
@router.get("/finance/ebudget", response_class=HTMLResponse)
def ebudget_page(request: Request, db: Session = Depends(get_db),
                 year: int | None = None, round: int = 0):
    """คำนวณตัวเลขทุกส่วนของ e-Budget ให้ แล้วคัดลอกไปกรอกในเว็บ สพฐ. ทีละช่อง

    ไม่ได้ส่งข้อมูลไปที่ e-Budget · ครูยังต้องเปิดเว็บแล้ววางเอง (เหมือนหน้าช่วยกรอก e-GP)
    """
    from app.services.ebudget import ORDER, SOURCES, build, period
    fy = year or current_fiscal_year()
    rnd = 2 if round == 2 else (1 if round == 1 else _default_round(fy))
    data = build(db, fy, rnd)
    return templates.TemplateResponse("finance_ebudget.html", {
        "request": request, "d": data, "order": ORDER, "sources": SOURCES,
        "fiscal_year": fy, "round": rnd, "years": _finance_years(db, fy),
        "school": get_school(db),
    })


def _default_round(fy: int) -> int:
    """เดารอบรายงานจากวันที่วันนี้ · 1 ต.ค. เป็นต้นไป = ยื่นรอบที่ 2 ของปีงบที่เพิ่งจบ"""
    from app.thai_utils import thai_now
    now = thai_now()
    return 1 if 4 <= now.month <= 9 else 2


@router.get("/finance/ebudget/fill", response_class=HTMLResponse)
def ebudget_fill_page(request: Request, db: Session = Depends(get_db),
                      year: int | None = None, round: int = 0, all: int = 0):
    """ไล่เติมหมวด e-Budget ย้อนหลัง - ระบบเดาให้ก่อน ครูแค่ตรวจทานแล้วกดบันทึก

    all=1 แสดงทุกรายการในงวด (ไว้แก้ของที่เคยเติมไว้) · ปกติแสดงเฉพาะที่ยังว่าง
    """
    from app.models import AccountItem, FinanceAccount, FinanceTxn, Project
    from app.services.ebudget import period
    from app.services.ebudget_cat import EXPENSE, INCOME, guess
    fy = year or current_fiscal_year()
    rnd = 2 if round == 2 else (1 if round == 1 else _default_round(fy))
    start, end, label = period(fy, rnd)
    accts = {a.id: a for a in db.query(FinanceAccount).all()}
    items = {i.id: i for i in db.query(AccountItem).filter_by(fiscal_year=fy).all()}
    projs = {p.id: p for p in db.query(Project).all()}
    rows = []
    for t in db.query(FinanceTxn).filter_by(fiscal_year=fy).order_by(FinanceTxn.date).all():
        d = t.date
        if not d or not (start <= d <= end):
            continue
        if not all and (t.eb_code or "").strip():
            continue
        it = items.get(t.item_id)
        pj = projs.get(t.project_id)
        rows.append({
            "t": t, "account": (accts.get(t.account_id).name if accts.get(t.account_id) else ""),
            "item": it.name if it else "", "project": pj.name if pj else "",
            "current": (t.eb_code or "").strip(),
            "guess": guess(t, it.name if it else "", pj.name if pj else "",
                           accts.get(t.account_id).name if accts.get(t.account_id) else ""),
        })
    return templates.TemplateResponse("finance_ebudget_fill.html", {
        "request": request, "rows": rows, "fiscal_year": fy, "round": rnd,
        "label": label, "start": start, "end": end, "show_all": bool(all),
        "eb_expense": EXPENSE, "eb_income": INCOME[0][1],
    })


@router.post("/finance/ebudget/fill")
async def ebudget_fill_save(request: Request, db: Session = Depends(get_db)):
    """บันทึกหมวดที่ครูตรวจทานแล้ว (ส่งมาเป็น eb_<txn_id>)"""
    from app.models import FinanceTxn
    form = await request.form()
    fy = _to_int(form.get("year"), current_fiscal_year())
    rnd = _to_int(form.get("round"), 1)
    saved = 0
    for key, val in form.items():
        if not key.startswith("eb_"):
            continue
        t = db.get(FinanceTxn, _to_int(key[3:], 0))
        if t is None:
            continue
        new = (val or "").strip()
        if (t.eb_code or "") != new:
            t.eb_code = new
            saved += 1
    db.commit()
    return RedirectResponse(f"/finance/ebudget?year={fy}&round={rnd}&saved={saved}",
                            status_code=303)


@router.post('/finance/accounts/{aid}/openings')
async def save_account_openings(aid: int, request: Request, db: Session=Depends(get_db)):
    from app.services.finance_openings import save
    form=await request.form()
    a=db.get(FinanceAccount,aid)
    if not a:raise HTTPException(404,'ไม่พบบัญชี')
    try:
        fy=int(form.get('fiscal_year',0))
        if not 2500<=fy<=2700:raise ValueError('ปีงบไม่ถูกต้อง')
        save(db,a,fy,form)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409,str(exc))
    return RedirectResponse(f'/finance/accounts/{aid}?year={fy}',status_code=303)
