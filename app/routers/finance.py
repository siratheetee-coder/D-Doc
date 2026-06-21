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
from app.services.doc_number import suggest_doc_no, commit_doc_no, check_doc_no, parse_seq
from app.services.finance_doc import render_disburse
from app.services.finance_io import build_finance_template, import_finance_workbook
from app.services.finance_report import export_finance_report
from app.thai_utils import current_fiscal_year, parse_be_date, be_date_input
from app.templating import templates
from app.routers.pages import get_school, _to_int, _to_float

router = APIRouter()

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


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
                deposit_type: str = Form("bank")):
    if name.strip():
        dt = deposit_type if deposit_type in DEPOSIT_TYPES else "bank"
        db.add(FinanceAccount(name=name.strip(),
                              opening_balance=_to_float(opening_balance, 0.0),
                              deposit_type=dt, note=note.strip()))
        db.commit()
    return RedirectResponse("/finance/accounts", status_code=303)


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
    # สรุปงบรายหมวด (เฉพาะปีงบที่เลือก)
    items = (db.query(AccountItem).filter_by(account_id=a.id, fiscal_year=fy)
             .order_by(AccountItem.id).all())
    item_rows = []
    for it in items:
        tin = sum(t.amount or 0 for t in txns if t.item_id == it.id and t.kind == "in")
        tout = sum(t.amount or 0 for t in txns if t.item_id == it.id and t.kind == "out")
        item_rows.append({"it": it, "tin": tin, "tout": tout,
                          "remain": round((it.budget or 0) + tin - tout, 2)})
    # แผนที่ รายการเงิน -> เลขใบเสร็จที่ออกผูกกัน (ไว้แสดงในประวัติ)
    receipt_map = {rc.txn_id: (rc.receipt_no or "(ไม่มีเลข)")
                   for rc in db.query(Receipt).filter(Receipt.txn_id.isnot(None)).all()
                   if rc.txn_id}
    return templates.TemplateResponse("finance_ledger.html", {
        "request": request, "account": a, "rows": rows, "balance": round(bal, 2),
        "opening": opening, "fiscal_year": fy, "years": _finance_years(db, fy),
        "items": items, "item_rows": item_rows, "receipt_map": receipt_map,
        "item_budget_total": sum(it.budget or 0 for it in items),
        "item_remain_total": sum(r["remain"] for r in item_rows),
    })


@router.post("/finance/accounts/{aid}/item")
def account_item_add(aid: int, db: Session = Depends(get_db), name: str = Form(...),
                     budget: str = Form("0"), note: str = Form(""), fiscal_year: str = Form(""),
                     deposit_type: str = Form("bank")):
    a = db.get(FinanceAccount, aid)
    fy = _to_int(fiscal_year, current_fiscal_year())
    if a and name.strip():
        dt = deposit_type if deposit_type in DEPOSIT_TYPES else "bank"
        db.add(AccountItem(account_id=a.id, fiscal_year=fy, name=name.strip(),
                           budget=_to_float(budget, 0.0), deposit_type=dt, note=note.strip()))
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
        for it in a.items:
            if it.fiscal_year == fy - 1 and it.name.strip() not in existing:
                db.add(AccountItem(account_id=a.id, fiscal_year=fy, name=it.name,
                                   budget=it.budget, deposit_type=it.deposit_type, note=it.note))
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
    return FileResponse(path, filename=Path(path).name, media_type=_DOCX)


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
    return FileResponse(path, filename=Path(path).name, media_type=_DOCX)


@router.get("/finance/report.xlsx")
def report_xlsx(db: Session = Depends(get_db), year: int | None = None):
    fy = year or current_fiscal_year()
    accounts = db.query(FinanceAccount).order_by(FinanceAccount.name).all()
    txns = db.query(FinanceTxn).filter_by(fiscal_year=fy).all()
    path = export_finance_report(accounts, txns, fy)
    return FileResponse(path, filename=Path(path).name, media_type=_XLSX)


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
    return FileResponse(path, filename=Path(path).name, media_type=_XLSX)


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
