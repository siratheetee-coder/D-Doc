# -*- coding: utf-8 -*-
"""ตรวจสุขภาพข้อมูลการเงิน: ไล่ตรวจข้อมูลแทนคน แล้วบอกเป็นข้อ ๆ ว่าตรงไหนน่าจะผิด พร้อมลิงก์ไปหน้าที่แก้ได้

แค่ตรวจและบอก ไม่แก้ข้อมูลเอง (คนแก้ต้องดูเอกสารจริงประกอบ)
แบ่ง 3 ระดับ: fix = สิ่งที่ควรแก้ (ข้อมูลผิดแน่) · check = สิ่งที่ควรเช็ค (อาจผิด/ใกล้ผิดระเบียบ)
notice = สิ่งที่ควรสังเกต (ไม่ผิด แค่ให้รู้)
ข้อตรวจแต่ละข้อมาจากปัญหาที่เจอจริง (บ้านหินลาด 2569-10: ยอดยกมากรอกเท่างบ, รายการปีก่อนเริ่มใช้ระบบ,
โครงการงบ 0 แต่มีเรื่องหักงบ, เรื่องพัสดุลงวันที่นอกปีของแผน)
"""
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
    return dict(title=title, why=why, rows=rows[:MAX_ROWS], total=len(rows), href=href, label=label)


def _row(text, href, sub="", amount=None, date=None):
    return dict(text=text, href=href, sub=sub, amount=amount, date=date)


def _ledger(t):
    return f"/finance/accounts/{t.account_id}?year={t.fiscal_year}#t{t.id}"


def _txn_text(t):
    return ("รับ" if t.kind == "in" else "จ่าย") + (f" · {t.note}" if t.note else (f" · {t.ref}" if t.ref else ""))


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
                      f"ยอดยกมาต้องเป็นเงินที่เหลือจริงในบัญชี ณ 1 ต.ค. (ดูจากสมุดบัญชีธนาคารหรือทะเบียนคุมเงินเดิม) "
                      f"ไม่ใช่งบที่ได้รับจัดสรร ถ้ากรอกผิด ยอดคงเหลือทุกหน้าและเงินที่ใช้จัดสรรให้โครงการจะผิดตาม",
                      rows, rows[0]["href"], "ไปแก้ยอดยกมา")


def txn_wrong_year(db, fy, today):
    from app.models import FinanceTxn
    rows = []
    for t in db.query(FinanceTxn).filter(FinanceTxn.date.isnot(None)).order_by(FinanceTxn.date):
        real = _fy_of(t.date)
        if real != t.fiscal_year:
            rows.append(_row(_txn_text(t), _ledger(t), date=t.date, amount=t.amount,
                             sub=f"ลงไว้ในปีงบ {t.fiscal_year} แต่วันที่อยู่ในปีงบ {real}"))
    if rows:
        return _issue("รายการเงินลงผิดปีงบ (วันที่ไม่อยู่ในปีงบที่ลงไว้)",
                      "ยอดคงเหลือของทั้งสองปีงบจะเพี้ยน ให้แก้วันที่ให้ถูก หรือลบแล้วลงใหม่ในปีงบที่ตรงกับวันที่จ่ายจริง",
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
                      f"โรงเรียนเริ่มลงเงินในระบบที่ปีงบ {fy} ด้วยยอดยกมา ซึ่งหักเงินที่จ่ายไปก่อนหน้าแล้ว "
                      f"รายการปีงบ {prev} จึงนับซ้ำ และทำให้ระบบเตือนให้ยกยอดติดลบ ให้ลบรายการเหล่านี้ และอย่ากดยกยอด "
                      f"(งบโครงการยังหักจากเรื่องพัสดุเหมือนเดิม)",
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
                      "ยอดคงเหลือของปีนี้ในทุกหน้าจึงยังไม่ถูกต้อง ถ้าข้อมูลปีก่อนถูกแล้ว กดยกยอดที่กล่องสีส้มในหน้าบัญชี",
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
                      "จ่ายเกินเงินที่มี มักเกิดจากยอดยกมายังไม่ได้กรอก ลงรายการรับไม่ครบ หรือลงจ่ายผิดหมวด/ผิดบัญชี",
                      rows, rows[0]["href"])


def project_no_budget(db, fy, today):
    year, label, projects = _plan_projects(db)
    rows = [_row(p.name, f"/projects/{p.id}", sub=f"งบ 0 บาท แต่ใช้/กันงบไปแล้ว", amount=s)
            for p, b, s in projects if b <= 0 and s > 0.005]
    if rows:
        return _issue(f"โครงการ{label} {year} ยังไม่ได้ใส่งบ แต่มีเรื่องหักงบแล้ว",
                      "ใส่งบตามแผนปฏิบัติการ (ปุ่มแก้งบในหน้าโครงการ) ระบบถึงจะคำนวณงบเหลือได้ถูก",
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
                      "เช่น เรื่องพัสดุที่ทำตามปีงบ ซึ่งคาบเกี่ยวกับปีการศึกษาก่อน ทำให้โครงการปีนี้ดูเหมือนใช้เงินเกิน "
                      "ย้ายไปโครงการชื่อเดียวกันของปีที่ถูกต้องได้ในคลิกเดียว (ตรวจรายการก่อนยืนยัน)",
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
            rows.append(_row(f"{p.memo_no or '-'} · {p.proc_type or ''}{p.subject or ''}", f"/procurement/{p.id}",
                             sub=f"ขอเบิกรวม {paid:,.2f} แต่ยอดเรื่อง {p.total_amount or 0:,.2f}",
                             amount=paid - (p.total_amount or 0)))
    if rows:
        return _issue("ขอเบิกเกินยอดของเรื่องพัสดุ",
                      "บันทึกขอเบิกจ่ายที่ผูกกับเรื่องเดียวกันรวมแล้วเกินยอดสั่งซื้อ/สั่งจ้าง อาจทำบันทึกซ้ำ หรือกรอกยอดผิด",
                      rows, rows[0]["href"])


# ---------------------------------------------------------------- สิ่งที่ควรเช็ค
def project_over_budget(db, fy, today):
    year, label, projects = _plan_projects(db)
    rows = [_row(p.name, f"/projects/{p.id}", sub=f"งบ {b:,.2f} · ใช้/กันงบ {s:,.2f}", amount=s - b)
            for p, b, s in projects if b > 0 and s > b + 0.005]
    if rows:
        return _issue(f"โครงการ{label} {year} ใช้เงินเกินงบ",
                      "ตรวจว่าเรื่องที่หักงบเป็นของโครงการนี้จริง ถ้าใช่ ให้ปรับงบโครงการ (พร้อมเหตุผล) หรือย้ายบางเรื่องไปโครงการอื่น",
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
                      "เช่น แก้ยอดยกมาหรือยอดเงินอุดหนุนหลังนำเข้าแผน ให้กดนำเข้าใหม่ในหน้างบที่ใช้จัดทำแผน "
                      "ยอดที่ใช้จัดสรรให้โครงการจะได้ตรงกับเงินจริง",
                      rows, f"/plan-budget/{year}", "ไปอัปเดตเงินในแผน")


def memo_unpaid_long(db, fy, today):
    from app.models import DisburseMemo
    cut = today - timedelta(days=30)
    rows = [_row(m.subject or m.memo_no or "บันทึกขอเบิกจ่าย", f"/finance/disburse/{m.id}", date=m.date, amount=m.amount,
                 sub=f"เลขที่ {m.memo_no or '-'} · อนุมัติแล้วแต่ยังไม่ลงจ่าย")
            for m in db.query(DisburseMemo).filter(DisburseMemo.status == "อนุมัติ", DisburseMemo.date.isnot(None),
                                                   DisburseMemo.date < cut).order_by(DisburseMemo.date)]
    if rows:
        return _issue("บันทึกขอเบิกอนุมัติเกิน 30 วันแล้ว ยังไม่ลงจ่าย",
                      "ถ้าจ่ายเงินไปแล้ว ให้กดลงจ่ายเข้าทะเบียนคุมเงิน (หรือเชื่อมรายการจ่ายเดิม) ยอดคงเหลือจะได้ตรง "
                      "ถ้ายังไม่จ่าย ตรวจว่าค้างจ่ายผู้ขายอยู่หรือไม่",
                      rows, rows[0]["href"])


def loans_overdue(db, fy, today):
    from app.models import MoneyLoan
    from app.services.dashboard_tasks import loan_state
    rows = []
    for loan in db.query(MoneyLoan).order_by(MoneyLoan.due_date):
        state, left = loan_state(loan, today.date())
        if state == "overdue":
            rows.append(_row(loan.borrower or "ไม่ระบุผู้ยืม", f"/finance/loans?year={loan.fiscal_year}#loan-{loan.id}",
                             sub=f"สัญญา {loan.contract_no or '-'} · ครบกำหนดแล้ว ยังคงค้าง", amount=left,
                             date=loan.due_date))
    if rows:
        return _issue("เงินยืมเลยกำหนดส่งใช้",
                      "ติดตามให้ผู้ยืมส่งใช้ใบสำคัญหรือเงินสดที่เหลือ ถ้าส่งแล้วให้บันทึกการส่งใช้ในหน้าเงินยืม",
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
                      "ถ้าเป็นการจ่ายคนละเรื่องจริงก็ไม่ต้องแก้ ถ้าลงซ้ำ ให้ลบรายการที่เกิน "
                      "(ถ้ามาจากบันทึกขอเบิกจ่าย ใช้ปุ่มเชื่อมรายการจ่ายเดิมแทนการลงใหม่)",
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
                      "ออกหนังสือรับรองการหักภาษี ณ ที่จ่ายให้ผู้ขายไม่ได้ ให้เพิ่มเลขผู้เสียภาษีในข้อมูลผู้ขาย",
                      rows, "/vendors", "ไปเพิ่มข้อมูลผู้ขาย")


def checks_not_cleared(db, fy, today):
    from app.models import CheckPayment
    cut = today - timedelta(days=150)
    rows = [_row(f"เช็ค {c.check_no or '-'} · {c.payee or ''}", f"/finance/checks?year={c.fiscal_year}", date=c.date,
                 amount=c.amount, sub="สั่งจ่ายเกิน 5 เดือนแล้ว ยังไม่ขึ้นเงิน (เช็คขึ้นเงินได้ภายใน 6 เดือน)")
            for c in db.query(CheckPayment).filter(CheckPayment.pay_method == "เช็ค", CheckPayment.cleared.isnot(True),
                                                   CheckPayment.date.isnot(None), CheckPayment.date < cut)
            .order_by(CheckPayment.date)]
    if rows:
        return _issue("เช็คใกล้หมดอายุ ยังไม่ขึ้นเงิน",
                      "ติดตามผู้รับเงินให้นำเช็คไปขึ้นเงิน ถ้าขึ้นเงินแล้วให้ติ๊กขึ้นเงินแล้วในทะเบียนคุมเช็ค",
                      rows, rows[0]["href"])


# ---------------------------------------------------------------- สิ่งที่ควรสังเกต
def plan_unallocated(db, fy, today):
    from app.services import plan_funding as pf
    year, label = _plan(db)
    p = pf.plan(db, year)
    if not p:
        return None
    s = pf.summary(db, p)
    if s["remaining"] > 0.005:
        rows = [_row(f"เงินในแผน{label} {year}", f"/projects?year={year}",
                     sub=f"นำเข้าแผน {s['total']:,.2f} · จัดสรรแล้ว {s['allocated']:,.2f}", amount=s["remaining"])]
        return _issue("เงินในแผนยังไม่ได้จัดสรรให้โครงการ",
                      "จัดสรรในหน้าโครงการแต่ละโครงการ (ส่วน \"โครงการนี้ใช้งบจากรายการใด\") "
                      "ใส่เท่ายอดงบเหลือทำเรื่องใหม่ จะได้รู้ว่าโครงการไหนใช้เงินก้อนไหน",
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
                      "เทียบยอดในทะเบียนคุมเงินกับ statement ธนาคารทุกสิ้นเดือน จะเจอรายการที่ลงขาดหรือลงซ้ำได้เร็ว",
                      rows, f"/finance/bank-recon?year={fy}")


def txn_without_item(db, fy, today):
    from app.models import FinanceTxn
    rows = []
    for t in db.query(FinanceTxn).filter(FinanceTxn.fiscal_year == fy, FinanceTxn.item_id.is_(None)).order_by(FinanceTxn.date):
        if any(i.fiscal_year == fy for i in t.account.items):
            rows.append(_row(_txn_text(t), _ledger(t), date=t.date, amount=t.amount, sub=f"บัญชี {t.account.name}"))
    if rows:
        return _issue("รายการที่ยังไม่ได้ระบุหมวด",
                      "บัญชีนี้แยกหมวดไว้ แต่รายการเหล่านี้ไม่ได้เลือกหมวด ยอดคงเหลือรายหมวดจึงไม่ครบ",
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
    ("check", "ไม่มีรายการจ่ายที่อาจลงซ้ำ", duplicate_payments),
    ("check", "ผู้ขายที่ถูกหักภาษี ณ ที่จ่าย มีเลขผู้เสียภาษี", wht_vendor_no_tax_id),
    ("check", "เช็คที่สั่งจ่าย ขึ้นเงินแล้ว", checks_not_cleared),
    ("notice", "จัดสรรเงินในแผนให้โครงการครบ", plan_unallocated),
    ("notice", "ทำงบกระทบยอดเงินฝากธนาคารเดือนที่แล้ว", bank_recon_missing),
    ("notice", "รายการเงินระบุหมวดครบ", txn_without_item),
]


def run(db, fy, today=None) -> dict:
    """{'fix': [issue], 'check': [...], 'notice': [...], 'passed': [ชื่อข้อที่ผ่าน], 'counts': {...}}"""
    today = today or datetime.now()
    out = {k: [] for k, _, _ in LEVELS}
    passed = []
    for level, ok_title, fn in CHECKS:
        try:
            res = fn(db, fy, today)
        except Exception as e:  # noqa: BLE001  ข้อตรวจข้อเดียวพัง ไม่ควรทำให้ทั้งหน้าพัง
            print("[finance-health]", fn.__name__, repr(e))
            continue
        if res:
            out[level].append(dict(res, key=fn.__name__))
        else:
            passed.append(ok_title)
    counts = {k: len(v) for k, v in out.items()}
    counts["passed"] = len(passed)
    return dict(out, passed=passed, counts=counts, fy=fy)
