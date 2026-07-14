# -*- coding: utf-8 -*-
"""
finance.py — งานการเงิน
หน้าหลักการเงิน + ทะเบียนคุมเงินแยกบัญชี (รับ-จ่าย-คงเหลือ)
+ บันทึกขออนุมัติเบิกจ่าย (ออก Word, เชื่อมเรื่องพัสดุ) + ทะเบียนใบเสร็จ/ใบสำคัญ
+ รายงานการเงิน (Excel) + นำเข้าข้อมูลจาก Excel
เลขบันทึกขอเบิกจ่ายใช้ชุดเลขกลาง 'memo' ร่วมกับทุกงาน
"""
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, Request, Depends, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    FinanceAccount, FinanceTxn, DisburseMemo, Receipt, Procurement, AccountOpening,
    AccountItem, Project,
)
from app.services.budget import current_plan_year
from app.services.asset_utils import (
    account_balance, account_balance_year, opening_for,
    account_balance_asof, item_remaining_asof,
)
from app.services.cash_report import render_cash_report, DEPOSIT_TYPES
from app.services.ledger_book_doc import (
    render_cash_book, render_cash_book_fund, build_cash_book_xlsx,
    render_general_ledger, build_ledger_xlsx,
)
from app.services.doc_number import suggest_doc_no, commit_doc_no, check_doc_no, parse_seq
from app.services.finance_doc import render_disburse
from app.services.finance_io import build_finance_template, import_finance_workbook
from app.services.finance_report import export_finance_report
from app.thai_utils import current_fiscal_year, parse_be_date, be_date_input, thai_date
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float, serve_generated

router = APIRouter()

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# ประเภทเงินตามงบ (คอลัมน์สมุดเงินสดราชการ) — เก็บเป็นข้อความไทยตรงๆ
FUND_TYPES = ["เงินงบประมาณ", "เงินรายได้แผ่นดิน", "เงินนอกงบประมาณ"]
_FUND_DEFAULT = "เงินนอกงบประมาณ"

# ชุดหมวดสำเร็จรูป (กดปุ่มเดียวสร้างทั้งโครง) — (ชื่อหมวดแม่ | None, [รายการลูก])
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


def _finance_years(db, fy: int) -> list:
    """รายชื่อปีงบที่มีข้อมูลการเงิน (รายการ + ยอดยกมา) รวมปีปัจจุบัน เรียงใหม่ไปเก่า"""
    ys = {r[0] for r in db.query(FinanceTxn.fiscal_year).distinct()}
    ys |= {r[0] for r in db.query(AccountOpening.fiscal_year).distinct()}
    ys.add(fy)
    return sorted(ys, reverse=True)


# ---------------- Dashboard ----------------
@router.get("/finance", response_class=HTMLResponse)
def finance_dashboard(request: Request, db: Session = Depends(get_db), year: int | None = None):
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
        "recent_disburse": db.query(DisburseMemo).order_by(DisburseMemo.id.desc()).limit(5).all(),
    })


# ---------------- ยกยอดคงเหลือไปปีงบถัดไป (ไม่ลบข้อมูลเก่า) ----------------
@router.post("/finance/carry-forward")
def carry_forward(db: Session = Depends(get_db), year: str = Form("")):
    """คัดลอกยอดคงเหลือสิ้นปีงบ {year} ไปตั้งเป็น 'ยอดยกมา' ของปีงบถัดไป
    ไม่ลบรายการเดิม (ปีเก่ายังกดกลับไปดูได้) — upsert จึงกดซ้ำได้ ค่าจะอัปเดตให้ตรงเสมอ"""
    src = _to_int(year, current_fiscal_year())
    nxt = src + 1
    for a in db.query(FinanceAccount).all():
        closing = account_balance_year(a, src)
        row = (db.query(AccountOpening)
               .filter_by(account_id=a.id, fiscal_year=nxt).first())
        if row is None:
            row = AccountOpening(account_id=a.id, fiscal_year=nxt)
            db.add(row)
        row.amount = closing
    db.commit()
    return RedirectResponse(f"/finance?year={nxt}&carried={src}", status_code=303)


# ---------------- ทะเบียนคุมเงิน (บัญชี + ledger) ----------------
@router.get("/finance/accounts", response_class=HTMLResponse)
def accounts_page(request: Request, db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    return templates.TemplateResponse("finance_accounts.html", {
        "request": request, "accounts": accounts,
        "fiscal_year": fy, "years": _finance_years(db, fy),
    })


@router.post("/finance/accounts")
def account_add(db: Session = Depends(get_db), name: str = Form(...),
                opening_balance: str = Form("0"), note: str = Form(""),
                deposit_type: str = Form("bank"), fund_type: str = Form(_FUND_DEFAULT)):
    if name.strip():
        dt = deposit_type if deposit_type in DEPOSIT_TYPES else "bank"
        ft = fund_type if fund_type in FUND_TYPES else _FUND_DEFAULT
        db.add(FinanceAccount(name=name.strip(),
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
    # สรุปงบรายหมวด (เฉพาะปีงบที่เลือก) — เป็นต้นไม้ซ้อน 2 ชั้น หมวดแม่รวมยอดลูก
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
                          "budget": k.budget or 0, "remain": round((k.budget or 0) + k_in - k_out, 2)})
        # หมวดแม่ = ยอดของตัวเอง + รวมลูก
        tin = p_in + sum(r["tin"] for r in krows)
        tout = p_out + sum(r["tout"] for r in krows)
        budget = p_bud + sum(r["budget"] for r in krows)
        item_rows.append({"it": p, "level": 0, "tin": tin, "tout": tout, "budget": budget,
                          "remain": round(budget + tin - tout, 2), "has_kids": bool(krows)})
        item_rows.extend(krows)
    # แผนที่ รายการเงิน -> เลขใบเสร็จที่ออกผูกกัน (ไว้แสดงในประวัติ)
    receipt_map = {rc.txn_id: (rc.receipt_no or "(ไม่มีเลข)")
                   for rc in db.query(Receipt).filter(Receipt.txn_id.isnot(None)).all()
                   if rc.txn_id}
    return templates.TemplateResponse("finance_ledger.html", {
        "request": request, "account": a, "rows": rows, "balance": round(bal, 2),
        "opening": opening, "fiscal_year": fy, "years": _finance_years(db, fy),
        "items": items, "item_rows": item_rows, "receipt_map": receipt_map,
        "parents": parents, "fund_types": FUND_TYPES, "presets": PRESET_SETS,
        "item_budget_total": sum(r["budget"] for r in item_rows if r["level"] == 0),
        "item_remain_total": sum(r["remain"] for r in item_rows if r["level"] == 0),
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
    """สร้างชุดหมวดสำเร็จรูป (หมวดแม่ + ลูก) ในคลิกเดียว — ข้ามชื่อที่มีอยู่แล้ว"""
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
                    item_id: str = Form(""), receipt_no: str = Form(""), party: str = Form("")):
    a = db.get(FinanceAccount, aid)
    fy = _to_int(fiscal_year, current_fiscal_year())
    if a:
        k = "out" if kind == "out" else "in"
        amt = _to_float(amount, 0.0)
        dt = parse_be_date(date) or datetime.now()
        t = FinanceTxn(
            account_id=a.id, fiscal_year=fy, item_id=_to_int(item_id, 0) or None,
            kind=k, amount=amt, date=dt,
            category=category.strip(), ref=ref.strip(), note=note.strip(),
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
def account_txn_delete(tid: int, db: Session = Depends(get_db)):
    t = db.get(FinanceTxn, tid)
    aid = t.account_id if t else None
    fy = t.fiscal_year if t else None
    if t:
        # ลบใบเสร็จที่ออกพร้อมรายการนี้ด้วย (กันยอดค้างในทะเบียนใบเสร็จ)
        for rc in db.query(Receipt).filter_by(txn_id=t.id).all():
            db.delete(rc)
        db.delete(t); db.commit()
    url = f"/finance/accounts/{aid}?year={fy}" if aid else "/finance/accounts"
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
    rows = db.query(DisburseMemo).order_by(DisburseMemo.id.desc()).all()
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
    commit_doc_no(db, "memo", fy, no, source="finance", ref_id=m.id, subject=m.subject)
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
        commit_doc_no(db, "memo", m.fiscal_year, m.memo_no, source="finance", ref_id=m.id, subject=m.subject)
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
def _build_cash_rows(accounts, fy, as_of):
    """สร้างแถวรายงาน + ยอดรวมแต่ละคอลัมน์ (เงินสด/ธนาคาร/ส่วนราชการผู้เบิก/รวม)"""
    rows = []
    tot = {"cash": 0.0, "bank": 0.0, "agency": 0.0, "total": 0.0}

    def leaf(name, amt, col, indent):
        d = {"name": name, "header": False, "indent": indent,
             "cash": 0.0, "bank": 0.0, "agency": 0.0, "total": amt}
        d[col] = amt
        tot[col] += amt
        tot["total"] += amt
        return d

    for a in accounts:
        acc_col = a.deposit_type if a.deposit_type in DEPOSIT_TYPES else "bank"
        items = [it for it in a.items if it.fiscal_year == fy]
        if items:
            rows.append({"name": a.name, "header": True, "indent": False})
            for it in items:
                col = it.deposit_type if it.deposit_type in DEPOSIT_TYPES else acc_col
                rows.append(leaf(it.name, item_remaining_asof(it, as_of), col, True))
        else:
            rows.append(leaf(a.name, account_balance_asof(a, fy, as_of), acc_col, False))
    return rows, {k: round(v, 2) for k, v in tot.items()}


@router.get("/finance/cash-report", response_class=HTMLResponse)
def cash_report_page(request: Request, db: Session = Depends(get_db),
                     year: int | None = None, date: str | None = None):
    fy = year or current_fiscal_year()
    as_of = parse_be_date(date) if date else datetime.now()
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
    fy = year or current_fiscal_year()
    as_of = parse_be_date(date) if date else datetime.now()
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
        row = {"date": thai_date(t.date) if t.date else "", "ref": (t.ref or "").strip(),
               "desc": desc, "amount": t.amount or 0.0, "fund": fund_of.get(t.account_id, _FUND_DEFAULT)}
        (receipts if t.kind == "in" else payments).append(row)
    return scope, open_by_fund, receipts, payments


@router.get("/finance/cashbook", response_class=HTMLResponse)
def cashbook_page(request: Request, db: Session = Depends(get_db),
                  year: int | None = None, account: int | None = None):
    fy = year or current_fiscal_year()
    accounts, scope, opening, rows, totals = _cashbook_data(db, fy, account)
    return templates.TemplateResponse("finance_cashbook.html", {
        "request": request, "school": get_school(db), "fiscal_year": fy,
        "years": _finance_years(db, fy), "accounts": accounts, "sel_account": account,
        "scope": scope, "opening": opening, "rows": rows, "totals": totals,
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
    _a, scope, opening, rows, totals = _cashbook_data(db, fy, account)
    path = build_cash_book_xlsx(fy, rows, opening, totals, scope)
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
