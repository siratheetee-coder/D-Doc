# -*- coding: utf-8 -*-
"""ตรวจสุขภาพข้อมูลการเงิน: ไล่ตรวจข้อมูลแทนคน แล้วบอกเป็นข้อ ๆ ว่าตรงไหนน่าจะผิด พร้อมลิงก์ไปหน้าที่แก้ได้

แค่ตรวจและบอก ไม่แก้ข้อมูลเอง (คนแก้ต้องดูเอกสารจริงประกอบ)
แบ่ง 3 ระดับ: fix = สิ่งที่ควรแก้ (ข้อมูลผิดแน่) · check = สิ่งที่ควรเช็ค (อาจผิด/ใกล้ผิดระเบียบ)
notice = สิ่งที่ควรสังเกต (ไม่ผิด แค่ให้รู้)
ข้อตรวจแต่ละข้อมาจากปัญหาที่เจอจริง (บ้านหินลาด 2569-10: ยอดยกมากรอกเท่างบ, รายการปีก่อนเริ่มใช้ระบบ,
โครงการงบ 0 แต่มีเรื่องหักงบ, เรื่องพัสดุลงวันที่นอกปีของแผน)
"""
import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta

LEVELS = [
    ("fix", "สิ่งที่ควรแก้", "ข้อมูลผิดแน่นอน ทำให้ยอดเงินหรืองบในหน้าอื่นผิดตาม ควรแก้ก่อน"),
    ("check", "สิ่งที่ควรเช็ค", "อาจผิด หรือใกล้ผิดระเบียบ เปิดดูแล้วตัดสินใจว่าต้องแก้ไหม"),
    ("notice", "สิ่งที่ควรสังเกต", "ไม่ได้ผิด แค่ให้รู้ไว้ จะได้ไม่พลาด"),
]
MAX_ROWS = 6


def _fy_of(d) -> int:
    return d.year + 543 + (1 if d.month >= 10 else 0)


def _issue(title, why, rows, href, label="ไปดู"):
    # sig = ลายนิ้วมือของรายการทั้งหมด (ไม่ใช่แค่ที่แสดง) ใช้กับปุ่ม "ตรวจแล้ว ไม่ใช่ปัญหา": รายการเปลี่ยน = เตือนใหม่
    raw = "|".join(f"{r['href']}:{r['text']}:{r['amount']}" for r in rows)
    return dict(title=title, why=why, rows=rows[:MAX_ROWS], total=len(rows), href=href, label=label,
                sig=hashlib.sha256(raw.encode()).hexdigest()[:20])


def _row(text, href, sub="", amount=None, date=None, action=None):
    """action = ปุ่มแก้ในแถวนั้นเลย {url, label, confirm} (ส่งแบบ POST)"""
    return dict(text=text, href=href, sub=sub, amount=amount, date=date, action=action)


def _ledger(t):
    return f"/finance/accounts/{t.account_id}?year={t.fiscal_year}#t{t.id}"


def _txn_text(t):
    return ("รับ" if t.kind == "in" else "จ่าย") + (f" {t.note}" if t.note else (f" {t.ref}" if t.ref else ""))


def _plan(db):
    from app.models import School
    from app.services.budget import current_plan_year, plan_year_label
    school = db.query(School).first()
    year = current_plan_year(school)
    return year, plan_year_label(school, year)


def _plan_projects(db):
    from app.models import Project
    from app.services.budget import project_budget, project_spent
    year, label = _plan(db)
    rows = [(p, project_budget(p), project_spent(p))
            for p in db.query(Project).filter(Project.plan_year == year).order_by(Project.name)]
    return year, label, rows


def _joined(db, fy) -> bool:
    """เริ่มลงเงินในระบบที่ปีงบ fy (กรอกยอดยกมาปีนี้) และปีงบก่อนหน้าไม่เคยมีเงินเข้าหรือยอดยกมาเลย"""
    from app.models import AccountItem, AccountOpening, FinanceTxn
    has_open = (db.query(AccountOpening).filter(AccountOpening.fiscal_year == fy, AccountOpening.amount != 0).first()
                or db.query(AccountItem).filter(AccountItem.fiscal_year == fy, AccountItem.opening_balance != 0).first())
    if not has_open:
        return False
    prev = fy - 1
    return not (db.query(AccountOpening).filter(AccountOpening.fiscal_year == prev, AccountOpening.amount != 0).first()
                or db.query(AccountItem).filter(AccountItem.fiscal_year == prev, AccountItem.opening_balance != 0).first()
                or db.query(FinanceTxn).filter(FinanceTxn.fiscal_year == prev, FinanceTxn.kind == "in").first())


# ---------------------------------------------------------------- สิ่งที่ควรแก้
def opening_equals_budget(db, fy, today):
    from app.models import FinanceAccount
    rows = []
    for a in db.query(FinanceAccount).order_by(FinanceAccount.name):
        items = [i for i in a.items if i.fiscal_year == fy]
        parents = {i.parent_id for i in items if i.parent_id}
        cand = [i for i in items if i.id not in parents and (i.budget or 0) > 0]
        if len(cand) >= 2 and all(round(i.opening_balance or 0, 2) == round(i.budget, 2) for i in cand):
            rows.append(_row(a.name, f"/finance/accounts/{a.id}?year={fy}#opening-form",
                             sub=f"ยอดยกมาเท่ากับงบที่ตั้งไว้ทั้ง {len(cand)} หมวด",
                             amount=sum(i.opening_balance or 0 for i in cand)))
    if rows:
        return _issue("ยอดยกมาเท่ากับงบที่ตั้งไว้ทุกหมวด",
                      ["ยอดยกมาต้องเป็นเงินที่เหลือจริงในบัญชี ณ 1 ต.ค. ดูได้จากสมุดบัญชีธนาคาร",
                       "ไม่ใช่งบที่ได้รับจัดสรร ถ้ากรอกผิด ยอดคงเหลือทุกหน้าจะผิดตาม"],
                      rows, rows[0]["href"], "ไปแก้ยอดยกมา")


def txn_wrong_year(db, fy, today):
    from app.models import FinanceTxn
    rows = []
    for t in db.query(FinanceTxn).filter(FinanceTxn.date.isnot(None)).order_by(FinanceTxn.date):
        real = _fy_of(t.date)
        if real != t.fiscal_year:
            src = (" (มาจากบันทึกขอเบิกจ่าย)" if t.disburse_id else " (มาจากเงินยืม)" if (t.loan_id or t.loan_return_id)
                   else " (มาจากอาหารกลางวัน)" if t.lunch_year else "")
            rows.append(_row(_txn_text(t), _ledger(t), date=t.date, amount=t.amount,
                             sub=f"ลงไว้ในปีงบ {t.fiscal_year} แต่วันที่อยู่ในปีงบ {real}{src}",
                             action=dict(url=f"/finance/txn/{t.id}/move-year", label=f"ย้ายไปปีงบ {real}",
                                         confirm=f"ย้ายรายการนี้จากทะเบียนปีงบ {t.fiscal_year} ไปปีงบ {real} ตามวันที่?\n"
                                                 f"ยอดเงินและวันที่ไม่เปลี่ยน หมวดย้ายไปหมวดชื่อเดียวกันของปีงบ {real}")))
    if rows:
        return _issue("รายการเงินลงผิดปีงบ (วันที่ไม่อยู่ในปีงบที่ลงไว้)",
                      ["ถ้าวันที่ถูกแล้ว กดปุ่มสีเขียว \"ย้ายไปปีงบ ...\" ระบบย้ายให้ ยอดเงินและวันที่ไม่เปลี่ยน",
                       "ถ้าวันที่ผิด กด \"ไปดู\" แล้วลบรายการนั้น จากนั้นลงใหม่ให้ถูก"],
                      rows, rows[0]["href"])


def before_start(db, fy, today):
    from app.models import FinanceTxn
    if not _joined(db, fy):
        return None
    prev = fy - 1
    rows = [_row(_txn_text(t), f"/finance/disburse/{t.disburse_id}" if t.disburse_id else _ledger(t),
                 date=t.date, amount=t.amount,
                 sub="มาจากบันทึกขอเบิกจ่าย ลบที่บันทึกนั้น" if t.disburse_id else "")
            for t in db.query(FinanceTxn).filter(FinanceTxn.fiscal_year == prev).order_by(FinanceTxn.date)]
    if rows:
        return _issue(f"มีรายการเงินในปีงบ {prev} ซึ่งเป็นช่วงก่อนเริ่มใช้ระบบ",
                      [f"โรงเรียนเริ่มใช้ระบบปีงบ {fy} ด้วยยอดยกมา ซึ่งหักเงินที่จ่ายไปก่อนหน้าแล้ว",
                       f"รายการปีงบ {prev} จึงนับซ้ำ ให้ลบรายการเหล่านี้",
                       "อย่ากดยกยอด งบโครงการยังหักจากเรื่องพัสดุเหมือนเดิม"],
                      rows, rows[0]["href"])


def carry_mismatch(db, fy, today):
    from app.models import FinanceAccount
    from app.services.finance_openings import carry_status
    if _joined(db, fy):
        return None                                   # สาเหตุคือรายการก่อนเริ่มใช้ระบบ (ข้อด้านบน) ห้ามแนะนำให้ยกยอด
    ids = {a.name: a.id for a in db.query(FinanceAccount)}
    rows = [_row(r["name"], f"/finance/accounts/{ids.get(r['name'], 0)}?year={fy}",
                 sub=f"สิ้นปีงบ {fy - 1} เหลือ {r['want']:,.2f} แต่ยอดยกมาปีนี้ {r['got']:,.2f}")
            for r in carry_status(db, fy)]
    if rows:
        return _issue(f"ยอดยกมาปีงบ {fy} ไม่ตรงกับยอดคงเหลือสิ้นปีงบ {fy - 1}",
                      ["ถ้ามีข้อ \"รายการเงินลงผิดปีงบ\" ให้แก้ข้อนั้นก่อน",
                       "ตรวจรายการปีก่อนว่าครบและถูก",
                       "กด \"ไปดู\" แล้วกดปุ่มยกยอดในกล่องสีส้มด้านบน ข้อมูลปีเก่าไม่หาย"],
                      rows, rows[0]["href"])


def negative_balance(db, fy, today):
    from app.models import FinanceAccount
    from app.services.asset_utils import account_balance_year, item_remaining_asof
    rows = []
    for a in db.query(FinanceAccount).order_by(FinanceAccount.name):
        items = [i for i in a.items if i.fiscal_year == fy]
        href = f"/finance/accounts/{a.id}?year={fy}#txn-history"
        if not items:
            bal = account_balance_year(a, fy)
            if bal < -0.005:
                rows.append(_row(a.name, href, sub="เงินคงเหลือทั้งบัญชีติดลบ", amount=bal))
            continue
        for i in items:
            bal = item_remaining_asof(i)
            if bal < -0.005:
                rows.append(_row(f"{a.name} / {i.name}", href, sub="เงินคงเหลือในหมวดติดลบ", amount=bal))
    if rows:
        return _issue("เงินคงเหลือติดลบ",
                      ["ถ้ายังไม่ได้กรอกยอดยกมา ให้กรอกที่หน้าบัญชี",
                       "ถ้าลงรายการรับไม่ครบ ให้ลงให้ครบ",
                       "ถ้าลงจ่ายผิดหมวดหรือผิดบัญชี ให้ลบแล้วลงใหม่",
                       "ถ้ามีข้อ \"รายการเงินลงผิดปีงบ\" ให้แก้ข้อนั้นก่อน ยอดนี้อาจหายเอง"],
                      rows, rows[0]["href"])


def project_no_budget(db, fy, today):
    year, label, projects = _plan_projects(db)
    rows = [_row(p.name, f"/projects/{p.id}", sub=f"งบ 0 บาท แต่ใช้/กันงบไปแล้ว", amount=s)
            for p, b, s in projects if b <= 0 and s > 0.005]
    if rows:
        return _issue(f"โครงการ{label} {year} ยังไม่ได้ใส่งบ แต่มีเรื่องหักงบแล้ว",
                      ["ใส่งบตามแผนปฏิบัติการ ด้วยปุ่มแก้งบในหน้าโครงการ"],
                      rows, rows[0]["href"], "ไปใส่งบ")


def project_wrong_year(db, fy, today):
    from app.services.project_realign import find
    year, label = _plan(db)
    found = find(db, year)
    rows = [_row(r["title"] or r["no"], f"/projects/realign?year={year}", date=r["date"], amount=r["amount"],
                 sub=f"ลงวันที่นอกช่วง{label} {year} แต่หักงบ{r['project'].name}")
            for r in found]
    if rows:
        return _issue(f"เรื่องที่ลงวันที่นอกช่วง{label} {year} แต่หักงบโครงการปีนี้",
                      [("เช่น เรื่องพัสดุที่ทำตามปีงบ ซึ่งคาบเกี่ยวกับปีการศึกษาก่อน" if "การศึกษา" in label
                        else "เช่น เรื่องพัสดุของปีงบก่อนที่เลือกโครงการปีงบนี้ไว้"),
                       "ทำให้โครงการปีนี้ดูเหมือนใช้เงินเกิน",
                       "กดปุ่มแล้วตรวจรายการ ระบบย้ายไปโครงการชื่อเดียวกันของปีที่ถูกต้องให้"],
                      rows, f"/projects/realign?year={year}", "ไปตรวจและย้าย")


def memo_over_procurement(db, fy, today):
    from app.models import DisburseMemo, Procurement
    total = defaultdict(float)
    for m in db.query(DisburseMemo).filter(DisburseMemo.procurement_id.isnot(None)):
        total[m.procurement_id] += m.amount or 0
    rows = []
    for pid, paid in total.items():
        p = db.get(Procurement, pid)
        if p and paid > (p.total_amount or 0) + 0.005:
            rows.append(_row(f"เลขที่ {p.memo_no or '-'} {p.proc_type or ''}{p.subject or ''}", f"/procurement/{p.id}",
                             sub=f"ขอเบิกรวม {paid:,.2f} แต่ยอดเรื่อง {p.total_amount or 0:,.2f}",
                             amount=paid - (p.total_amount or 0)))
    if rows:
        return _issue("ขอเบิกเกินยอดของเรื่องพัสดุ",
                      ["บันทึกขอเบิกจ่ายของเรื่องเดียวกันรวมแล้วเกินยอดสั่งซื้อหรือสั่งจ้าง",
                       "อาจทำบันทึกซ้ำ หรือกรอกยอดผิด"],
                      rows, rows[0]["href"])


# ---------------------------------------------------------------- สิ่งที่ควรเช็ค
def project_over_budget(db, fy, today):
    year, label, projects = _plan_projects(db)
    rows = [_row(p.name, f"/projects/{p.id}", sub=f"งบ {b:,.2f} บาท ใช้หรือกันงบไปแล้ว {s:,.2f} บาท", amount=s - b)
            for p, b, s in projects if b > 0 and s > b + 0.005]
    if rows:
        return _issue(f"โครงการ{label} {year} ใช้เงินเกินงบ",
                      ["ตรวจว่าเรื่องที่หักงบเป็นของโครงการนี้จริง",
                       "ถ้าใช่ ให้ปรับงบโครงการ ถ้าไม่ใช่ ให้ย้ายเรื่องไปโครงการที่ถูก"],
                      rows, rows[0]["href"])


def plan_out_of_date(db, fy, today):
    from app.services import plan_funding as pf
    year, label = _plan(db)
    p = pf.plan(db, year)
    if not p:
        return None
    rows = [_row(r["source"].name, f"/plan-budget/{year}", amount=r["source"].amount,
                 sub="ยอดในทะเบียนคุมเงินเปลี่ยนไปหลังนำเข้าแผน")
            for r in pf.summary(db, p)["rows"] if r["changed"]]
    if rows:
        return _issue(f"เงินในแผน{label} {year} ไม่ตรงกับทะเบียนคุมเงินแล้ว",
                      ["ยอดในทะเบียนคุมเงินเปลี่ยนหลังนำเข้าแผน เช่น แก้ยอดยกมา",
                       "กดนำเข้าใหม่ในหน้างบที่ใช้จัดทำแผน ยอดที่จัดสรรจะได้ตรงกับเงินจริง"],
                      rows, f"/plan-budget/{year}", "ไปอัปเดตเงินในแผน")


def memo_unpaid_long(db, fy, today):
    from app.models import DisburseMemo
    cut = today - timedelta(days=30)
    rows = [_row(m.subject or m.memo_no or "บันทึกขอเบิกจ่าย", f"/finance/disburse/{m.id}", date=m.date, amount=m.amount,
                 sub=f"เลขที่ {m.memo_no or '-'} อนุมัติแล้วแต่ยังไม่ลงจ่าย")
            for m in db.query(DisburseMemo).filter(DisburseMemo.status == "อนุมัติ", DisburseMemo.date.isnot(None),
                                                   DisburseMemo.date < cut).order_by(DisburseMemo.date)]
    if rows:
        return _issue("บันทึกขอเบิกอนุมัติเกิน 30 วันแล้ว ยังไม่ลงจ่าย",
                      ["ถ้าจ่ายเงินแล้ว ให้กดลงจ่ายเข้าทะเบียนคุมเงิน หรือเชื่อมรายการจ่ายเดิม",
                       "ถ้ายังไม่จ่าย ตรวจว่ายังค้างจ่ายผู้ขายอยู่หรือไม่"],
                      rows, rows[0]["href"])


def loans_overdue(db, fy, today):
    from app.models import MoneyLoan
    from app.services.dashboard_tasks import loan_state
    rows = []
    for loan in db.query(MoneyLoan).order_by(MoneyLoan.due_date):
        state, left = loan_state(loan, today.date())
        if state == "overdue":
            rows.append(_row(loan.borrower or "ไม่ระบุผู้ยืม", f"/finance/loans?year={loan.fiscal_year}#loan-{loan.id}",
                             sub=f"สัญญา {loan.contract_no or '-'} ครบกำหนดแล้ว ยังค้างอยู่", amount=left,
                             date=loan.due_date))
    if rows:
        return _issue("เงินยืมเลยกำหนดส่งใช้",
                      ["ติดตามให้ผู้ยืมส่งใช้ใบสำคัญหรือเงินที่เหลือ",
                       "ถ้าส่งใช้แล้ว ให้บันทึกการส่งใช้ในหน้าเงินยืม"],
                      rows, "/finance/loans?attention=overdue")


def duplicate_payments(db, fy, today):
    from app.models import FinanceTxn
    groups = defaultdict(list)
    for t in db.query(FinanceTxn).filter(FinanceTxn.fiscal_year == fy, FinanceTxn.kind == "out",
                                         FinanceTxn.date.isnot(None)):
        if (t.amount or 0) > 0:
            groups[(t.account_id, t.date.date(), round(t.amount, 2))].append(t)
    rows = []
    for ts in groups.values():
        if len(ts) > 1:
            t = ts[0]
            rows.append(_row(_txn_text(t), _ledger(t), date=t.date, amount=t.amount,
                             sub=f"ยอดเท่ากัน วันเดียวกัน บัญชีเดียวกัน {len(ts)} รายการ"))
    if rows:
        return _issue("รายการจ่ายที่อาจลงซ้ำ",
                      ["ถ้าเป็นการจ่ายคนละเรื่องจริง ไม่ต้องแก้",
                       "ถ้าลงซ้ำ ให้ลบรายการที่เกิน"],
                      rows, rows[0]["href"])


def wht_vendor_no_tax_id(db, fy, today):
    from app.models import DisburseMemo, Procurement, Vendor
    by_name = {(v.name or "").strip(): v for v in db.query(Vendor)}
    seen, rows = set(), []
    for m in db.query(DisburseMemo).filter(DisburseMemo.fiscal_year == fy, DisburseMemo.wht > 0):
        p = db.get(Procurement, m.procurement_id) if m.procurement_id else None
        v = (p.vendor if p else None) or by_name.get((m.payee or "").strip())
        if v and not (v.tax_id or "").strip() and v.id not in seen:
            seen.add(v.id)
            rows.append(_row(v.name, "/vendors", sub=f"ถูกหักภาษี ณ ที่จ่าย (บันทึก {m.memo_no or '-'}) แต่ยังไม่มีเลขผู้เสียภาษี"))
    if rows:
        return _issue("ผู้ขายถูกหักภาษี ณ ที่จ่าย แต่ไม่มีเลขประจำตัวผู้เสียภาษี",
                      ["ไม่มีเลขผู้เสียภาษี จะออกหนังสือรับรองการหักภาษีให้ผู้ขายไม่ได้",
                       "เพิ่มเลขผู้เสียภาษีในข้อมูลผู้ขาย"],
                      rows, "/vendors", "ไปเพิ่มข้อมูลผู้ขาย")


def checks_not_cleared(db, fy, today):
    from app.models import CheckPayment
    cut = today - timedelta(days=150)
    rows = [_row(f"เช็คเลขที่ {c.check_no or '-'} จ่าย {c.payee or ''}", f"/finance/checks?year={c.fiscal_year}", date=c.date,
                 amount=c.amount, sub="สั่งจ่ายเกิน 5 เดือนแล้ว ยังไม่ขึ้นเงิน (เช็คขึ้นเงินได้ภายใน 6 เดือน)")
            for c in db.query(CheckPayment).filter(CheckPayment.pay_method == "เช็ค", CheckPayment.cleared.isnot(True),
                                                   CheckPayment.date.isnot(None), CheckPayment.date < cut)
            .order_by(CheckPayment.date)]
    if rows:
        return _issue("เช็คใกล้หมดอายุ ยังไม่ขึ้นเงิน",
                      ["ติดตามผู้รับเงินให้นำเช็คไปขึ้นเงิน",
                       "ถ้าขึ้นเงินแล้ว ให้ติ๊กว่าขึ้นเงินแล้วในทะเบียนคุมเช็ค"],
                      rows, rows[0]["href"])


def split_purchases(db, fy, today):
    """ซื้อ/จ้างร้านเดียวกัน ประเภทเดียวกัน ห่างกันไม่เกิน 15 วัน หลายเรื่อง = ลักษณะเหมือนแบ่งซื้อแบ่งจ้าง
    ไม่ฟันธงว่าผิด (ความต้องการคนละครั้งก็มี) จึงอยู่ระดับควรเช็ค และกดตรวจแล้วไม่ใช่ปัญหาได้
    ไม่นับงานจ้างเหมาอาหารกลางวัน (จ้างเป็นรอบตามปกติ)"""
    from app.models import Procurement, LunchHireRound
    lunch = {pid for (pid,) in db.query(LunchHireRound.procurement_id).filter(LunchHireRound.procurement_id.isnot(None))}
    groups = defaultdict(list)
    for p in db.query(Procurement).filter(Procurement.fiscal_year == fy, Procurement.vendor_id.isnot(None)):
        d = p.order_date or p.request_date
        if d and p.id not in lunch:
            groups[(p.vendor_id, p.proc_type or "ซื้อ")].append((d, p))
    rows = []
    for (_vid, kind), ps in groups.items():
        ps.sort(key=lambda x: (x[0], x[1].id))
        chains, cur = [], [ps[0]]
        for d, p in ps[1:]:
            if (d - cur[-1][0]).days <= 15:
                cur.append((d, p))
            else:
                chains.append(cur)
                cur = [(d, p)]
        chains.append(cur)
        for ch in chains:
            if len(ch) < 2:
                continue
            first, last = ch[0], ch[-1]
            vname = first[1].vendor.name if first[1].vendor else "ผู้ขาย"
            rows.append(_row(f"{vname} {kind} {len(ch)} เรื่อง ห่างกัน {(last[0] - first[0]).days} วัน",
                             f"/procurement/{first[1].id}", date=first[0],
                             amount=sum(x[1].total_amount or 0 for x in ch),
                             sub="เลขที่ " + ", ".join(x[1].memo_no or "-" for x in ch)))
    if rows:
        return _issue("ซื้อ/จ้างร้านเดียวกันหลายเรื่องในเวลาใกล้กัน (อาจเข้าข่ายแบ่งซื้อแบ่งจ้าง)",
                      ["ผู้ตรวจสอบมักทักข้อนี้",
                       "ถ้าเป็นความต้องการคนละครั้งจริง กด \"ตรวจแล้ว ไม่ใช่ปัญหา\"",
                       "ถ้าเป็นของที่ควรซื้อพร้อมกัน ครั้งหน้าให้รวมเป็นเรื่องเดียว"],
                      rows, rows[0]["href"])


def asset_not_registered(db, fy, today):
    from app.models import Procurement
    from app.services.register_import import import_history
    rows = []
    for p in db.query(Procurement).filter(Procurement.fiscal_year == fy, Procurement.proc_type == "ซื้อ",
                                          Procurement.inspect_date.isnot(None)).order_by(Procurement.inspect_date):
        big = [it for it in p.items if (it.unit_price or 0) >= 10000]
        if not big:
            continue
        done, suspected = import_history(db, p)
        miss = [it for it in big if it.id not in done and it.id not in suspected]
        if miss:
            rows.append(_row(f"เลขที่ {p.memo_no or '-'} {p.subject or ''}", f"/procurement/{p.id}/to-register",
                             date=p.inspect_date, amount=sum((it.unit_price or 0) * (it.quantity or 0) for it in miss),
                             sub="ยังไม่ขึ้นทะเบียน: " + ", ".join(it.name for it in miss[:3])))
    if rows:
        return _issue("ซื้อครุภัณฑ์ (ราคาต่อหน่วย 10,000 บาทขึ้นไป) ตรวจรับแล้ว แต่ยังไม่ขึ้นทะเบียน",
                      ["ขึ้นทะเบียนให้ครบ การตรวจนับประจำปีและค่าเสื่อมราคาจะได้ถูก",
                       "ถ้าเป็นวัสดุ เลือกส่งเข้าบัญชีวัสดุได้ในหน้าเดียวกัน"],
                      rows, rows[0]["href"], "ไปขึ้นทะเบียน")


def subsidy_over_received(db, fy, today):
    """รับเงินอุดหนุนรายหมวดเกินยอดที่คำนวณ/ได้รับจัดสรรไว้ (ฉบับล่าสุด) · รับไม่ครบเป็นเรื่องปกติ (ทยอยโอน) จึงไม่เตือน"""
    from app.models import SubsidySnapshot
    from app.services import subsidy as sub
    from app.thai_utils import current_academic_year
    ay0 = current_academic_year(today)
    rows = []
    for ay in (ay0 - 1, ay0):
        for term in (1, 2):
            snap = (db.query(SubsidySnapshot).filter_by(academic_year=ay, term=term)
                    .order_by(SubsidySnapshot.id.desc()).first())
            if not snap:
                continue
            want = {}
            for r in json.loads(snap.payload)["result"]["rows"]:
                v = r.get("allocated") if r.get("allocated") is not None else r.get("full")
                if v is not None:
                    want[r["key"]] = float(v)
            got, _, _ = sub.receipt_summary(db, ay, term)
            for key, amt in got.items():
                if key in want and amt > want[key] + 0.5:
                    rows.append(_row(f"{sub.NAMES.get(key, key)} ปีการศึกษา {ay} ภาคเรียนที่ {term}",
                                     f"/finance/subsidy?year={ay}&term={term}", amount=amt - want[key],
                                     sub=f"รับแล้ว {amt:,.2f} แต่คำนวณ/จัดสรรไว้ {want[key]:,.2f}"))
    if rows:
        return _issue("รับเงินอุดหนุนเกินยอดที่คำนวณไว้",
                      ["อาจผูกรายการรับซ้ำ หรือผูกผิดภาคเรียน",
                       "ตรวจรายการรับที่ผูกไว้ในหน้าคำนวณเงินอุดหนุน"],
                      rows, rows[0]["href"])


def lunch_round_over_rate(db, fy, today):
    """จ้างเหมาอาหารกลางวัน: วงเงินรอบเกิน จำนวนนักเรียน x อัตราต่อหัว x จำนวนวัน"""
    from app.models import LunchHireRound
    rows = []
    for r in db.query(LunchHireRound).filter(LunchHireRound.start_date.isnot(None)).order_by(LunchHireRound.start_date):
        p = r.program
        if _fy_of(r.start_date) != fy or not p or (p.operate_mode or "hire") != "hire":
            continue
        cap = float(p.total_students or 0) * float(p.rate_per_head or 0) * float(r.days or 0)
        if cap > 0 and (r.amount or 0) > cap + 0.5:
            rows.append(_row(f"รอบที่ {r.seq} ปีการศึกษา {p.year}", f"/lunch/round/{r.id}/edit", date=r.start_date,
                             amount=(r.amount or 0) - cap,
                             sub=f"วงเงิน {r.amount or 0:,.2f} แต่ {p.total_students} คน x {p.rate_per_head:,.2f} บาท x {r.days} วัน "
                                 f"= {cap:,.2f}"))
    if rows:
        return _issue("รอบจ้างเหมาอาหารกลางวัน วงเงินเกินอัตรารายหัว",
                      ["วงเงินต่อรอบไม่ควรเกิน จำนวนนักเรียน x อัตราต่อหัว x จำนวนวัน",
                       "ตรวจจำนวนนักเรียน จำนวนวัน หรือวงเงินของรอบนั้น"],
                      rows, rows[0]["href"])


def receipt_duplicate_no(db, fy, today):
    from app.models import Receipt
    groups = defaultdict(list)
    for r in db.query(Receipt).filter(Receipt.fiscal_year == fy, Receipt.kind == "รับ"):
        no = "".join((r.receipt_no or "").split())
        if no:
            groups[no].append(r)
    rows = [_row(f"ใบเสร็จเลขที่ {rs[0].receipt_no}", f"/finance/receipts?year={fy}", date=rs[0].date,
                 sub="ใช้ซ้ำ " + str(len(rs)) + " ใบ: " + ", ".join(r.party or "-" for r in rs[:3]))
            for rs in groups.values() if len(rs) > 1]
    if rows:
        return _issue("ใบเสร็จรับเงินเลขที่ซ้ำกัน",
                      ["ใบเสร็จแต่ละใบต้องมีเลขไม่ซ้ำ",
                       "ตรวจว่าพิมพ์เลขผิด หรือบันทึกใบเดียวกันซ้ำ"],
                      rows, rows[0]["href"])


_RC_BOOK = re.compile(r"เล่ม(?:ที่)?\s*([0-9A-Za-zก-ฮ]+)")
_RC_NO = re.compile(r"(?:เลขที่|เลข|no\.?)\s*(\d+)", re.I)
_RC_PLAIN = re.compile(r"^\s*(\d+)\s*(?:/\s*(\d{2,4}))?\s*$")


def _receipt_key(no: str):
    """แยกเลขใบเสร็จเป็น (ชุด, เลข) · "12/2570" -> ("/2570", 12) · "เล่มที่ 3 เลขที่ 15" -> ("เล่ม 3", 15)
    รูปแบบอื่นอ่านไม่ออก = None (ไม่ตรวจเลขข้าม)"""
    no = (no or "").strip()
    m = _RC_PLAIN.match(no)
    if m:
        return ("/" + m.group(2) if m.group(2) else ""), int(m.group(1))
    b, n = _RC_BOOK.search(no), _RC_NO.search(no)
    if b and n:
        return "เล่ม " + b.group(1), int(n.group(1))
    return None


def receipt_number_gap(db, fy, today):
    """ใบเสร็จรับเงินเลขที่ข้าม (ในชุดเดียวกัน) · ใบที่ยกเลิกต้องเก็บต้นฉบับไว้ จึงเป็นข้อควรเช็ค ไม่ใช่ข้อผิดแน่"""
    from app.models import Receipt
    sets = defaultdict(set)
    for r in db.query(Receipt).filter(Receipt.fiscal_year == fy, Receipt.kind == "รับ"):
        k = _receipt_key(r.receipt_no)
        if k:
            sets[k[0]].add(k[1])
    rows = []
    for book, nums in sorted(sets.items()):
        if len(nums) < 2:
            continue
        miss = sorted(set(range(min(nums), max(nums) + 1)) - nums)
        if miss and len(miss) <= 200:
            shown = ", ".join(str(n) for n in miss[:15]) + (f" และอีก {len(miss) - 15} เลข" if len(miss) > 15 else "")
            rows.append(_row(f"ใบเสร็จ{(' ' + book) if book.startswith('เล่ม') else (' ชุด ' + book.lstrip('/')) if book else ''}"
                             f" เลขที่ {min(nums)} ถึง {max(nums)}", f"/finance/receipts?year={fy}",
                             sub=f"เลขที่ข้ามไป: {shown}"))
    if rows:
        return _issue("ใบเสร็จรับเงินเลขที่ข้าม",
                      ["ถ้าเป็นใบที่ยกเลิก ให้เก็บต้นฉบับไว้ แล้วกด \"ตรวจแล้ว ไม่ใช่ปัญหา\"",
                       "ถ้าเป็นใบที่ออกจริงแต่ยังไม่ได้บันทึก ให้บันทึกให้ครบ"],
                      rows, rows[0]["href"])


# ---------------------------------------------------------------- สิ่งที่ควรสังเกต
def revenue_not_remitted(db, fy, today):
    """เงินรายได้แผ่นดินค้างนำส่งเกิน 10,000 บาท หรือค้างเกิน 30 วัน (ต้องนำส่งอย่างน้อยเดือนละครั้ง)"""
    from app.services.revenue_remit import summary, CASH_LIMIT
    from app.thai_utils import current_fiscal_year
    if fy != current_fiscal_year(today):
        return None
    rows = []
    for s in summary(db, today):
        for r in s["items"]:
            if r["pending"] > 0.005 and (s["pending"] > CASH_LIMIT or r["days"] > 30):
                rows.append(_row(f"{s['account'].name} / {r['name']}", "/finance/revenue", amount=r["pending"],
                                 sub=f"ค้างนำส่ง {r['days']} วัน"))
    if rows:
        return _issue("เงินรายได้แผ่นดินค้างนำส่งนานหรือมากเกินไป",
                      ["ต้องนำส่งอย่างน้อยเดือนละ 1 ครั้ง",
                       f"วันใดมีเกิน {CASH_LIMIT:,.0f} บาท ต้องนำส่งภายใน 3 วันทำการ",
                       "กดไปดู แล้วกด \"นำส่งยอดนี้\" ระบบออกบันทึก หนังสือนำส่ง และใบแจ้งการชำระเงินให้"],
                      rows, "/finance/revenue", "ไปนำส่ง")


def cash_on_hand(db, fy, today):
    """เงินสดที่เก็บไว้ที่โรงเรียน (ประเภทที่เก็บ = เงินสด) ค้างไว้เกิน 7 วันโดยไม่มีความเคลื่อนไหว"""
    from app.models import FinanceAccount
    from app.services.asset_utils import account_balance_year, item_remaining_asof
    from app.thai_utils import current_fiscal_year
    if fy != current_fiscal_year(today):
        return None
    cut = today - timedelta(days=7)
    rows = []
    for a in db.query(FinanceAccount).order_by(FinanceAccount.name):
        href = f"/finance/accounts/{a.id}?year={fy}#txn-history"
        targets = []
        if (a.deposit_type or "") == "cash":
            targets.append((a.name, account_balance_year(a, fy), [t for t in a.txns if t.fiscal_year == fy]))
        else:
            for i in a.items:
                if i.fiscal_year == fy and (i.deposit_type or "") == "cash":
                    targets.append((f"{a.name} / {i.name}", item_remaining_asof(i),
                                    [t for t in a.txns if t.item_id == i.id and t.fiscal_year == fy]))
        for name, bal, txns in targets:
            last = max((t.date for t in txns if t.date), default=None)
            if bal > 0.005 and (last is None or last < cut):
                rows.append(_row(name, href, amount=bal, date=last,
                                 sub="ไม่มีรับ-จ่ายเลยตั้งแต่ต้นปีงบ" if last is None else "ไม่มีรับ-จ่ายเกิน 7 วันแล้ว"))
    if rows:
        return _issue("มีเงินสดเก็บไว้ที่โรงเรียนนานเกิน 7 วัน",
                      ["เงินสดที่ยังไม่ใช้ควรนำฝากธนาคาร",
                       "ถ้านำฝากแล้ว ให้ลงรายการนำฝากในทะเบียนคุมเงิน"],
                      rows, rows[0]["href"])


def paid_before_pending(db, fy, today):
    """โรงเรียนที่เริ่มใช้ระบบกลางทาง: เรื่องพัสดุก่อนวันเริ่มใช้ระบบที่ยังขึ้นว่ารอจ่าย"""
    from app.services import paid_before as pb
    from app.thai_utils import current_fiscal_year
    cur = current_fiscal_year(today)
    if fy != cur or not any(_joined(db, y) for y in (cur, cur - 1, cur - 2)):
        return None
    cut = pb.default_cutoff(db)
    rows = [_row(f"เลขที่ {p.memo_no or '-'} {p.proc_type or ''}{p.subject or ''}", "/finance/paid-before",
                 date=pb.proc_date(p), amount=p.total_amount) for p in pb.candidates(db, cut)]
    if rows:
        return _issue("เรื่องพัสดุที่ทำก่อนเริ่มใช้ระบบและจ่ายไปแล้ว",
                      [f"{len(rows)} เรื่องที่ลงวันที่ก่อนเริ่มใช้ระบบ ยังขึ้นว่ารอจ่าย",
                       "ติ๊กเลือกเรื่องที่จ่ายเงินไปแล้ว แล้วทำเครื่องหมายได้ทีละหลายเรื่อง",
                       "ไม่สร้างรายการเงิน และงบโครงการที่ใช้ไปเท่าเดิม",
                       "ถ้ายังไม่ได้จ่ายจริง ให้ทำบันทึกขอเบิกจ่ายตามปกติ"],
                      rows, "/finance/paid-before", "ไปทำเครื่องหมาย")


def low_spend_year_end(db, fy, today):
    """ช่วง ก.ค. ถึง ก.ย. หมวดที่ตั้งงบไว้แต่ใช้ไปไม่ถึง 20% เตือนให้วางแผนใช้หรือกันเงินไว้เบิกเหลื่อมปี"""
    from app.models import AccountItem
    from app.thai_utils import current_fiscal_year
    if fy != current_fiscal_year(today) or today.month not in (7, 8, 9):
        return None
    rows = []
    for i in db.query(AccountItem).filter(AccountItem.fiscal_year == fy, AccountItem.budget > 0):
        spent = sum(t.amount or 0 for t in i.account.txns
                    if t.item_id == i.id and t.fiscal_year == fy and t.kind == "out")
        if spent < 0.2 * i.budget:
            rows.append(_row(f"{i.account.name} / {i.name}", f"/finance/accounts/{i.account_id}?year={fy}#txn-history",
                             sub=f"ตั้งงบ {i.budget:,.2f} บาท ใช้ไป {spent:,.2f} บาท ({spent / i.budget * 100:.0f}%)",
                             amount=i.budget - spent))
    if rows:
        return _issue(f"ใกล้สิ้นปีงบ {fy} แล้ว บางหมวดยังใช้เงินไม่ถึง 20% ของงบ",
                      ["วางแผนใช้ให้ทันก่อน 30 ก.ย.",
                       "ถ้าก่อหนี้ไว้แล้วแต่จ่ายไม่ทัน ให้ทำเรื่องกันเงินไว้เบิกเหลื่อมปี"],
                      rows, rows[0]["href"])


def plan_unallocated(db, fy, today):
    from app.services import plan_funding as pf
    year, label = _plan(db)
    p = pf.plan(db, year)
    if not p:
        return None
    s = pf.summary(db, p)
    if s["remaining"] > 0.005:
        rows = [_row(f"เงินในแผน{label} {year}", f"/projects?year={year}",
                     sub=f"นำเข้าแผน {s['total']:,.2f} บาท จัดสรรแล้ว {s['allocated']:,.2f} บาท", amount=s["remaining"])]
        return _issue("เงินในแผนยังไม่ได้จัดสรรให้โครงการ",
                      ["จัดสรรที่หน้าโครงการแต่ละโครงการ ส่วน \"โครงการนี้ใช้งบจากรายการใด\"",
                       "ใส่เท่ากับยอดงบเหลือทำเรื่องใหม่"],
                      rows, f"/projects?year={year}", "ไปจัดสรร")


def bank_recon_missing(db, fy, today):
    from app.models import BankRecon, FinanceAccount, FinanceTxn
    from app.thai_utils import current_fiscal_year
    if fy != current_fiscal_year(today):
        return None
    end = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(microseconds=1)
    start = end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for a in db.query(FinanceAccount).filter(FinanceAccount.deposit_type == "bank").order_by(FinanceAccount.name):
        if not db.query(FinanceTxn).filter(FinanceTxn.account_id == a.id, FinanceTxn.date <= end).first():
            continue
        done = db.query(BankRecon).filter(BankRecon.account_id == a.id, BankRecon.as_of >= start,
                                          BankRecon.as_of <= end + timedelta(days=1)).first()
        if not done:
            rows.append(_row(a.name, f"/finance/bank-recon?year={fy}", sub="ยังไม่ได้ทำงบกระทบยอดของเดือนที่แล้ว"))
    if rows:
        return _issue("ยังไม่ได้ทำงบกระทบยอดเงินฝากธนาคารของเดือนที่แล้ว",
                      ["เทียบยอดในทะเบียนคุมเงินกับ statement ธนาคารทุกสิ้นเดือน จะเจอรายการที่ลงขาดหรือลงซ้ำได้เร็ว"],
                      rows, f"/finance/bank-recon?year={fy}")


def txn_without_item(db, fy, today):
    from app.models import FinanceTxn
    rows = []
    for t in db.query(FinanceTxn).filter(FinanceTxn.fiscal_year == fy, FinanceTxn.item_id.is_(None)).order_by(FinanceTxn.date):
        if any(i.fiscal_year == fy for i in t.account.items):
            rows.append(_row(_txn_text(t), _ledger(t), date=t.date, amount=t.amount, sub=f"บัญชี {t.account.name}"))
    if rows:
        return _issue("รายการที่ยังไม่ได้ระบุหมวด",
                      ["บัญชีนี้แยกหมวดไว้ แต่รายการเหล่านี้ไม่ได้เลือกหมวด ยอดรายหมวดจึงไม่ครบ"],
                      rows, rows[0]["href"])


CHECKS = [
    ("fix", "ยอดยกมาเป็นเงินคงเหลือจริง ไม่ใช่งบที่ตั้งไว้", opening_equals_budget),
    ("fix", "ไม่มีรายการเงินในปีงบก่อนเริ่มใช้ระบบ", before_start),
    ("fix", "ยอดยกมาตรงกับยอดคงเหลือสิ้นปีก่อน", carry_mismatch),
    ("fix", "รายการเงินลงตรงปีงบ", txn_wrong_year),
    ("fix", "ไม่มีหมวดหรือบัญชีที่เงินคงเหลือติดลบ", negative_balance),
    ("fix", "โครงการที่มีเรื่องหักงบ ใส่งบไว้แล้ว", project_no_budget),
    ("fix", "เรื่องที่หักงบโครงการ ลงวันที่อยู่ในช่วงปีของแผน", project_wrong_year),
    ("fix", "บันทึกขอเบิกไม่เกินยอดเรื่องพัสดุ", memo_over_procurement),
    ("check", "โครงการใช้เงินไม่เกินงบ", project_over_budget),
    ("check", "เงินในแผนตรงกับทะเบียนคุมเงิน", plan_out_of_date),
    ("check", "บันทึกขอเบิกที่อนุมัติแล้ว ลงจ่ายครบ", memo_unpaid_long),
    ("check", "เงินยืมส่งใช้ตามกำหนด", loans_overdue),
    ("check", "เงินรายได้แผ่นดินนำส่งตามกำหนด", revenue_not_remitted),
    ("check", "ไม่มีรายการจ่ายที่อาจลงซ้ำ", duplicate_payments),
    ("check", "ผู้ขายที่ถูกหักภาษี ณ ที่จ่าย มีเลขผู้เสียภาษี", wht_vendor_no_tax_id),
    ("check", "เช็คที่สั่งจ่าย ขึ้นเงินแล้ว", checks_not_cleared),
    ("check", "ไม่มีการซื้อ/จ้างร้านเดียวกันหลายเรื่องในเวลาใกล้กัน", split_purchases),
    ("check", "ครุภัณฑ์ที่ตรวจรับแล้ว ขึ้นทะเบียนครบ", asset_not_registered),
    ("check", "รับเงินอุดหนุนไม่เกินยอดที่คำนวณไว้", subsidy_over_received),
    ("check", "รอบจ้างเหมาอาหารกลางวัน วงเงินไม่เกินอัตรารายหัว", lunch_round_over_rate),
    ("check", "ใบเสร็จรับเงินเลขที่ไม่ซ้ำ", receipt_duplicate_no),
    ("check", "ใบเสร็จรับเงินเลขที่เรียงต่อกันไม่ข้าม", receipt_number_gap),
    ("notice", "จัดสรรเงินในแผนให้โครงการครบ", plan_unallocated),
    ("notice", "ทำงบกระทบยอดเงินฝากธนาคารเดือนที่แล้ว", bank_recon_missing),
    ("notice", "รายการเงินระบุหมวดครบ", txn_without_item),
    ("notice", "ใกล้สิ้นปีงบ ทุกหมวดใช้เงินตามแผน", low_spend_year_end),
    ("notice", "เรื่องพัสดุที่ทำก่อนเริ่มใช้ระบบและจ่ายไปแล้ว ทำเครื่องหมายครบ", paid_before_pending),
    ("notice", "ไม่มีเงินสดค้างที่โรงเรียนนานเกิน 7 วัน", cash_on_hand),
]


def move_txn_year(db, tid) -> dict:
    """ย้ายรายการเงินที่ลงผิดปีงบ ไปปีงบตามวันที่ (ทะเบียนคุมเงินลงตามวันที่จ่าย/รับจริง)
    หมวดย้ายไปหมวดชื่อเดียวกันของปีงบใหม่ ถ้าไม่มีหมวดชื่อนั้น = ไม่ระบุหมวด · ใบเสร็จที่ผูกไว้ย้ายปีตาม
    ไม่แตะยอดเงิน วันที่ บันทึกขอเบิกจ่าย หรือเรื่องพัสดุ"""
    from app.models import FinanceTxn, AccountItem, Receipt
    t = db.get(FinanceTxn, tid)
    if not t or not t.date:
        raise ValueError("ไม่พบรายการ หรือรายการไม่มีวันที่")
    new = _fy_of(t.date)
    if new == t.fiscal_year:
        raise ValueError("รายการนี้อยู่ในปีงบที่ตรงกับวันที่แล้ว")
    old_item = db.get(AccountItem, t.item_id) if t.item_id else None
    item = None
    if old_item:
        item = (db.query(AccountItem).filter_by(account_id=t.account_id, fiscal_year=new, name=old_item.name)
                .order_by(AccountItem.id).first())
    old = t.fiscal_year
    t.fiscal_year, t.item_id = new, (item.id if item else None)
    for r in db.query(Receipt).filter_by(txn_id=t.id):
        r.fiscal_year = new
    db.commit()
    return dict(old=old, new=new, account_id=t.account_id, item_lost=bool(old_item and not item),
                item_name=old_item.name if old_item else "")


def acks(db) -> dict:
    from app.models import FinanceHealthAck
    return {a.key: a for a in db.query(FinanceHealthAck)}


def run(db, fy, today=None) -> dict:
    """{'fix': [issue], 'check': [...], 'notice': [...], 'dismissed': [...], 'passed': [ชื่อข้อที่ผ่าน], 'counts': {...}}
    dismissed = ข้อที่กด "ตรวจแล้ว ไม่ใช่ปัญหา" และรายการยังเหมือนตอนกด (ไม่นับเป็นปัญหา)"""
    today = today or datetime.now()
    out = {k: [] for k, _, _ in LEVELS}
    passed, dismissed = [], []
    try:
        ack = acks(db)
    except Exception as e:  # noqa: BLE001  อ่านไม่ได้ก็ยังตรวจได้ (แค่ไม่ซ่อนข้อที่กดข้ามไว้)
        print("[finance-health] acks", repr(e))
        ack = {}
    for level, ok_title, fn in CHECKS:
        try:
            res = fn(db, fy, today)
        except Exception as e:  # noqa: BLE001  ข้อตรวจข้อเดียวพัง ไม่ควรทำให้ทั้งหน้าพัง
            print("[finance-health]", fn.__name__, repr(e))
            continue
        if not res:
            passed.append(ok_title)
            continue
        res = dict(res, key=fn.__name__, level=level, can_ack=level != "fix")
        a = ack.get(fn.__name__)
        if res["can_ack"] and a and a.sig == res["sig"]:
            dismissed.append(dict(res, ack=a))
        else:
            out[level].append(res)
    counts = {k: len(v) for k, v in out.items()}
    counts["passed"] = len(passed)
    counts["dismissed"] = len(dismissed)
    return dict(out, passed=passed, dismissed=dismissed, counts=counts, fy=fy)


def set_ack(db, key, sig, by_name=""):
    """กด "ตรวจแล้ว ไม่ใช่ปัญหา" · ข้อระดับควรแก้กดไม่ได้ (ข้อมูลผิดแน่ ต้องแก้)"""
    from app.models import FinanceHealthAck
    lv = {fn.__name__: level for level, _, fn in CHECKS}
    if lv.get(key) not in ("check", "notice") or not sig:
        raise ValueError("ข้อนี้เป็นข้อมูลที่ผิดแน่นอน ต้องแก้ข้อมูล กดข้ามไม่ได้")
    row = db.query(FinanceHealthAck).filter_by(key=key).first() or FinanceHealthAck(key=key)
    row.sig, row.by_name, row.created_at = sig[:40], (by_name or "")[:100], datetime.now()
    db.add(row)
    db.commit()


def clear_ack(db, key):
    from app.models import FinanceHealthAck
    db.query(FinanceHealthAck).filter_by(key=key).delete()
    db.commit()


# ---------------------------------------------------------------- ภาพรวมทุกโรงเรียน (หน้าแอดมิน + cron ทุกคืน)
def _all_path():
    from app.database import get_data_dir
    return get_data_dir() / "finance-health-all.json"


def scan_all(today=None) -> dict:
    """ตรวจทุกโรงเรียน (ไม่รวมระบบตัวอย่าง/โรงเรียนสาธิต) เก็บสรุปไว้ที่ data/finance-health-all.json
    เปิดเฉพาะโรงเรียนที่มีไฟล์ฐานอยู่แล้ว (ไม่สร้างไฟล์ใหม่ให้โรงเรียนที่ยังไม่เคยใช้) · อ่านอย่างเดียว"""
    from app.accounts import acc_session, Tenant
    from app.database import get_data_dir
    from app.tenancy import session_for
    from app.thai_utils import current_fiscal_year
    today = today or datetime.now()
    fy = current_fiscal_year(today)
    adb = acc_session()
    try:
        tenants = [(t.id, t.name, bool(t.active)) for t in adb.query(Tenant)
                   .filter(Tenant.plan != "sandbox", Tenant.slug != "demo").order_by(Tenant.id)]
    finally:
        adb.close()
    rows = []
    for tid, name, active in tenants:
        if not (get_data_dir() / "schools" / str(tid) / "school.db").exists():
            continue
        db = session_for(tid)
        try:
            h = run(db, fy, today)
            rows.append(dict(id=tid, name=name, active=active, counts=h["counts"],
                             fix=[i["title"] for i in h["fix"]], check=[i["title"] for i in h["check"]],
                             notice=[i["title"] for i in h["notice"]]))
        except Exception as e:  # noqa: BLE001  โรงเรียนเดียวพัง ไม่ให้ทั้งรอบพัง
            rows.append(dict(id=tid, name=name, active=active, error=repr(e)[:200]))
        finally:
            db.close()
    rows.sort(key=lambda r: (-(r.get("counts") or {}).get("fix", 0), -(r.get("counts") or {}).get("check", 0),
                             r["name"] or ""))
    data = dict(at=today.strftime("%Y-%m-%d %H:%M"), fy=fy, schools=rows)
    p = _all_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)
    return data


def load_all():
    try:
        return json.loads(_all_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


if __name__ == "__main__":      # cron ทุกคืน: python -m app.services.finance_health
    d = scan_all()
    bad = [r for r in d["schools"] if (r.get("counts") or {}).get("fix")]
    print(f"[{d['at']}] ตรวจ {len(d['schools'])} โรงเรียน · มีสิ่งที่ควรแก้ {len(bad)} โรงเรียน")
    for r in bad:
        print(f"  - {r['name']}: ควรแก้ {r['counts']['fix']}")
