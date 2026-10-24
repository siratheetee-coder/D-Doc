"""นำส่งเงินรายได้แผ่นดิน (หน้า /finance/revenue)

ตามระบบควบคุมการเงินของหน่วยงานย่อย พ.ศ. 2544 และระเบียบกระทรวงการคลังว่าด้วยการเบิกเงินจากคลัง
การรับเงิน การจ่ายเงิน การเก็บรักษาเงิน และการนำเงินส่งคลัง พ.ศ. 2562
- เงินรายได้แผ่นดินเก็บเป็นเงินสดได้ไม่เกิน 10,000 บาท นำส่งอย่างน้อยเดือนละ 1 ครั้ง
  วันใดเกิน 10,000 บาท นำส่งภายใน 3 วันทำการ
- สถานศึกษาที่ไม่ได้เป็นหน่วยเบิกจ่าย นำส่งผ่านสำนักงานเขตพื้นที่ ด้วยใบแจ้งการชำระเงินของธนาคารกรุงไทย
  (Company Code ของเขต, Ref.1 = รหัสโรงเรียน, Ref.2 = รหัสรายได้)

เอกสาร: บันทึกขออนุมัตินำส่ง, หนังสือนำส่งถึงเขต, ใบแจ้งการชำระเงิน (2 ส่วน), รายงานประจำเดือน
"""
from datetime import datetime

from docx.shared import Cm

from app.models import FinanceAccount, FinanceTxn, RevenueRemit
from app.thai_utils import bahttext, current_fiscal_year, thai_date
from app.services.asset_dispose_set import (_BLANK, _d, _director_line, _letter_header, _memo_header,
                                            _new, _save, _break, _sname)
from app.services.build_templates import _p, _sign_table
from app.services.finance_forms_doc import _grid, _row
from app.services.org_names import parent_office

# (คีย์, ชื่อประเภท, รหัสรายได้ที่ใช้กันทั่วไป, คำที่ใช้จัดรายการรับเข้าประเภท)
TYPES = [
    ("interest", "ดอกเบี้ยเงินฝากสถาบันการเงิน", "821", ("ดอกเบี้ย",)),
    ("old_return", "เงินเหลือจ่ายปีเก่าส่งคืน", "811", ("เหลือจ่าย", "ปีเก่า")),
    ("sale", "ค่าขายของเบ็ดเตล็ด", "642", ("ขาย", "ทอดตลาด", "เบ็ดเตล็ด")),
    ("fine", "ค่าปรับ", "", ("ปรับ",)),
    ("other", "รายได้แผ่นดินอื่น ๆ", "", ()),
]
NAMES = {k: n for k, n, _, _ in TYPES}
CODES = {k: c for k, _, c, _ in TYPES}
METHODS = ["เงินสด", "เงินโอน", "เช็ค"]
CASH_LIMIT = 10000


def is_revenue(account) -> bool:
    return (account.fund_type or "") == "เงินรายได้แผ่นดิน" or "รายได้แผ่นดิน" in (account.name or "")


def classify(txn) -> str:
    text = f"{txn.category or ''} {txn.note or ''}"
    for key, name, _, words in TYPES:
        if name in text or any(w in text for w in words):
            return key
    return "other"


def accounts(db):
    return [a for a in db.query(FinanceAccount).order_by(FinanceAccount.name) if is_revenue(a)]


def summary(db, today=None):
    """ยอดค้างนำส่งของแต่ละบัญชี/ประเภท (นับทุกปี เพราะรับปลายปีงบแล้วนำส่งต้นปีงบใหม่ได้)"""
    today = today or datetime.now()
    out = []
    for a in accounts(db):
        rows = {k: {"key": k, "name": n, "got": 0.0, "sent": 0.0, "since": None} for k, n, _, _ in TYPES}
        for t in sorted(a.txns, key=lambda x: (x.date or datetime.min, x.id)):
            r = rows[classify(t)]
            amt = float(t.amount or 0)
            if t.kind == "in":
                r["got"] += amt
                if r["got"] - r["sent"] > 0.004 and r["since"] is None:
                    r["since"] = t.date
            else:
                r["sent"] += amt
                if r["got"] - r["sent"] <= 0.004:
                    r["since"] = None          # นำส่งครบแล้ว นับวันค้างใหม่
        items = []
        for r in rows.values():
            r["pending"] = round(r["got"] - r["sent"], 2)
            r["days"] = (today - r["since"]).days if r["since"] and r["pending"] > 0 else 0
            if r["got"] or r["sent"]:
                items.append(r)
        pending = round(sum(r["pending"] for r in items), 2)
        out.append({"account": a, "items": items, "pending": pending,
                    "urgent": pending > CASH_LIMIT or any(r["days"] > 30 for r in items)})
    return out


def defaults(db, school):
    """ค่าที่ใช้ครั้งก่อน (Company Code / รหัสโรงเรียน / ผู้นำฝาก) ไม่ต้องกรอกซ้ำทุกครั้ง"""
    last = db.query(RevenueRemit).order_by(RevenueRemit.id.desc()).first()
    office = parent_office(school, "")
    return {"send_to": (last.send_to if last else "") or office, "company_code": last.company_code if last else "",
            "ref1": last.ref1 if last else "", "payer": (last.payer if last else "") or (school.finance_officer_name or ""),
            "phone": last.phone if last else "", "method": last.method if last else "เงินสด"}


def create(db, *, account_id, rtype, amount, date, **fields):
    a = db.get(FinanceAccount, account_id)
    if not a or not is_revenue(a):
        raise ValueError("เลือกบัญชีเงินรายได้แผ่นดิน")
    if rtype not in NAMES:
        raise ValueError("เลือกประเภทเงินที่จะนำส่ง")
    if not amount or amount <= 0:
        raise ValueError("จำนวนเงินต้องมากกว่า 0")
    if not date:
        raise ValueError("ใส่วันที่นำส่ง")
    pend = next((r["pending"] for s in summary(db) if s["account"].id == a.id for r in s["items"] if r["key"] == rtype), 0)
    if amount - pend > 0.004:
        raise ValueError(f"นำส่งได้ไม่เกินยอดค้างนำส่งของประเภทนี้ ({pend:,.2f} บาท) ถ้ายังไม่ได้ลงรับเงิน ให้ลงรับในทะเบียนคุมเงินก่อน")
    fy = current_fiscal_year(date)
    r = RevenueRemit(fiscal_year=fy, date=date, account_id=a.id, rtype=rtype, amount=round(amount, 2),
                     **{k: (str(v or "").strip())[:200] for k, v in fields.items()})
    txn = FinanceTxn(account_id=a.id, fiscal_year=fy, date=date, kind="out", amount=r.amount,
                     category=NAMES[rtype], ref=r.letter_no or r.memo_no,
                     note=f"นำส่งเงินรายได้แผ่นดิน ({NAMES[rtype]}) ผ่าน{r.send_to or 'สำนักงานเขตพื้นที่'}")
    db.add(txn); db.flush()
    r.txn_id = txn.id
    db.add(r); db.flush()
    return r


def delete(db, remit):
    if remit.txn_id:
        t = db.get(FinanceTxn, remit.txn_id)
        if t:
            db.delete(t)
    db.delete(remit)


# ------------------------------------------------------------------ เอกสาร
def _sign_officer(doc, school, role="เจ้าหน้าที่การเงิน"):
    nm = (school.finance_officer_name or school.officer_name or "").strip() or _BLANK
    _sign_table(doc, [[("ลงชื่อ ......................................", "center"), (f"( {nm} )", "center"),
                       (role, "center")]])


def _render_memo(doc, school, r):
    amt = float(r.amount or 0)
    _memo_header(doc, school, "ขออนุมัตินำส่งเงินรายได้แผ่นดิน", r.memo_no, _d(r.date))
    to = r.send_to or parent_office(school, "") or "สำนักงานเขตพื้นที่การศึกษา"
    _p(doc, f"ด้วย{_sname(school)} มีเงินรายได้แผ่นดิน ประเภท {NAMES[r.rtype]} "
            f"จำนวน {amt:,.2f} บาท ({bahttext(amt)}) ซึ่งเป็นเงินที่ต้องนำส่งคลัง "
            "ตามระเบียบกระทรวงการคลังว่าด้วยการเบิกเงินจากคลัง การรับเงิน การจ่ายเงิน "
            "การเก็บรักษาเงิน และการนำเงินส่งคลัง พ.ศ. 2562", align="justify", indent=1.25, after=2)
    how = {"เงินสด": "เป็นเงินสด", "เงินโอน": "โดยการโอนเงิน", "เช็ค": "เป็นเช็ค"}.get(r.method, "")
    codes = "  ".join(x for x in [f"Company Code {r.company_code}" if r.company_code else "",
                                   f"Ref.1 {r.ref1}" if r.ref1 else "", f"Ref.2 {r.ref2}" if r.ref2 else ""] if x)
    _p(doc, f"จึงขออนุมัตินำเงินจำนวนดังกล่าวส่งคลังผ่าน{to} {how} "
            "โดยชำระผ่านธนาคารกรุงไทยตามใบแจ้งการชำระเงินรายได้แผ่นดิน"
            + (f" ({codes})" if codes else ""), align="justify", indent=1.25, after=2)
    _p(doc, "จึงเรียนมาเพื่อโปรดพิจารณาอนุมัติ", align="justify", indent=1.25, after=10)
    _sign_officer(doc, school)
    _p(doc, "", after=6)
    _p(doc, "(   )  อนุมัติ          (   )  ไม่อนุมัติ", indent=1.25, after=10)
    _sign_table(doc, [[("ลงชื่อ ......................................", "center"),
                       (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
                       (_director_line(school), "center")]])
    _p(doc, "วันที่ ........./............./..................", align="center", after=2)


def _render_letter(doc, school, r):
    amt = float(r.amount or 0)
    to = r.send_to or parent_office(school, "") or _BLANK
    _letter_header(doc, school, r.letter_no, _d(r.date), "การนำส่งเงินรายได้แผ่นดิน",
                   "ผู้อำนวยการ" + to if to != _BLANK else _BLANK,
                   "ใบแจ้งการชำระเงินรายได้แผ่นดิน (ส่วนของผู้ชำระเงิน) จำนวน 1 ฉบับ")
    _p(doc, f"ด้วย{_sname(school)} ได้นำส่งเงินรายได้แผ่นดิน ประเภท {NAMES[r.rtype]}"
            + (f" รหัสรายได้ {r.ref2}" if r.ref2 else "")
            + f" จำนวน {amt:,.2f} บาท ({bahttext(amt)}) โดยชำระผ่านธนาคารกรุงไทย"
            f" เมื่อวันที่ {_d(r.date)} เข้าบัญชีของ{to} เรียบร้อยแล้ว "
            "รายละเอียดตามสิ่งที่ส่งมาด้วยพร้อมนี้", align="justify", indent=1.25, after=2)
    _p(doc, "จึงเรียนมาเพื่อโปรดทราบ และออกใบเสร็จรับเงินให้โรงเรียนเพื่อเป็นหลักฐานต่อไป",
       align="justify", indent=1.25, after=8)
    _p(doc, "ขอแสดงความนับถือ", align="center", after=12)
    _sign_table(doc, [[("", "center"), (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
                       (_director_line(school), "center")]])
    _p(doc, "งานการเงิน", size=14, before=8, after=0)
    _p(doc, f"โทร. {r.phone or _BLANK}", size=14, after=6)


def _render_slip(doc, school, r):
    """ใบแจ้งการชำระเงินรายได้แผ่นดิน 2 ส่วน (ผู้ชำระเงิน / ธนาคาร) ตามแบบที่เขตพื้นที่ใช้"""
    amt = float(r.amount or 0)
    to = r.send_to or parent_office(school, "") or _BLANK
    for part in ("ส่วนของผู้ชำระเงิน", "ส่วนของธนาคาร"):
        _p(doc, part, bold=True, size=14, after=2)
        widths = [Cm(9.0), Cm(8.0)]
        t = _grid(doc, ["ใบแจ้งการชำระเงิน รายได้แผ่นดิน", f"วันที่ / Date  {thai_date(r.date)}"], widths, size=15)
        rows = [
            (f"ให้แก่ {to}", f"Company Code  {r.company_code or _BLANK}"),
            (f"โรงเรียน  {_sname(school)}", f"Ref.1 รหัสโรงเรียน  {r.ref1 or _BLANK}"),
            ("", f"Ref.2 รหัสรายได้  {r.ref2 or _BLANK}"),
            ("  ".join(("☑ " if r.method == m else "☐ ") + m for m in METHODS), "ธนาคารกรุงไทย  สาขา ......................"),
            (f"จำนวนเงินเป็นตัวอักษร  ({bahttext(amt)})", f"จำนวนเงินเป็นตัวเลข  {amt:,.2f}  บาท"),
            (f"ผู้นำฝาก  {r.payer or _BLANK}   โทร. {r.phone or _BLANK}", "เจ้าหน้าที่ธนาคาร (ประทับตรา)"),
        ]
        for a, b in rows:
            _row(t, [a, b], widths, ["left", "left"], size=14)
        _p(doc, "", after=4)
        if part == "ส่วนของผู้ชำระเงิน":
            _p(doc, "-" * 60 + "  ตัดตามรอยนี้  " + "-" * 60, align="center", size=10, after=8)


RENDERERS = {"memo": ("บันทึกขออนุมัตินำส่งเงินรายได้แผ่นดิน", _render_memo),
             "letter": ("หนังสือนำส่งเงินรายได้แผ่นดิน", _render_letter),
             "slip": ("ใบแจ้งการชำระเงินรายได้แผ่นดิน", _render_slip)}


def render(school, r, which) -> str:
    doc = _new()
    keys = list(RENDERERS) if which == "all" else [which]
    for k in keys:
        _break(doc)
        RENDERERS[k][1](doc, school, r)
    name = "ชุดนำส่งเงินรายได้แผ่นดิน" if which == "all" else RENDERERS[which][0]
    return _save(doc, f"{name}_{r.id}_{r.date.strftime('%d-%m-')}{r.date.year + 543}")


_TH_MONTHS = ["", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม",
              "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def month_rows(db, year, month):
    """แต่ละประเภท: ยกมา / รับ / นำส่ง / คงเหลือ ของเดือนนั้น (ปี ค.ศ.)"""
    start = datetime(year, month, 1)
    end = datetime(year + (month == 12), (month % 12) + 1, 1)
    rows = {k: {"name": n, "carry": 0.0, "got": 0.0, "sent": 0.0} for k, n, _, _ in TYPES}
    for a in accounts(db):
        for t in a.txns:
            if not t.date or t.date >= end:
                continue
            r = rows[classify(t)]
            amt = float(t.amount or 0) * (1 if t.kind == "in" else -1)
            if t.date < start:
                r["carry"] += amt
            elif amt > 0:
                r["got"] += amt
            else:
                r["sent"] -= amt
    out = [dict(r, left=round(r["carry"] + r["got"] - r["sent"], 2)) for r in rows.values()
           if r["carry"] or r["got"] or r["sent"]]
    return out, start, end


def render_month_report(db, school, year, month) -> str:
    rows, start, end = month_rows(db, year, month)
    doc = _new()
    label = f"{_TH_MONTHS[month]} พ.ศ. {year + 543}"
    _p(doc, "รายงานการรับและนำส่งเงินรายได้แผ่นดิน", align="center", bold=True, size=18, after=0)
    _p(doc, f"{_sname(school)}  ประจำเดือน {label}", align="center", after=8)
    widths = [Cm(5.6), Cm(2.8), Cm(2.8), Cm(2.8), Cm(2.8)]
    t = _grid(doc, ["ประเภทเงินรายได้แผ่นดิน", "ยกมา", "รับ", "นำส่ง", "คงเหลือ"], widths, size=14)
    tot = [0.0] * 4
    for r in rows:
        vals = [r["carry"], r["got"], r["sent"], r["left"]]
        tot = [a + b for a, b in zip(tot, vals)]
        _row(t, [r["name"]] + [f"{v:,.2f}" for v in vals], widths, ["left"] + ["right"] * 4, size=14)
    if not rows:
        _row(t, ["ไม่มีรายการรับหรือนำส่งในเดือนนี้", "", "", "", ""], widths, ["left"] + ["right"] * 4, size=14)
    _row(t, ["รวม"] + [f"{v:,.2f}" for v in tot], widths, ["center"] + ["right"] * 4, size=14, bold=True)
    remits = (db.query(RevenueRemit).filter(RevenueRemit.date >= start, RevenueRemit.date < end)
              .order_by(RevenueRemit.date).all())
    if remits:
        _p(doc, "", after=4)
        _p(doc, "รายละเอียดการนำส่ง", bold=True, after=2)
        w2 = [Cm(3.0), Cm(5.4), Cm(3.4), Cm(2.0), Cm(3.0)]
        t2 = _grid(doc, ["วันที่", "ประเภท", "หนังสือนำส่ง", "รหัส", "จำนวนเงิน"], w2, size=14)
        for x in remits:
            _row(t2, [thai_date(x.date), NAMES[x.rtype], x.letter_no or "-", x.ref2 or "-", f"{x.amount:,.2f}"],
                 w2, ["center", "left", "center", "center", "right"], size=14)
    _p(doc, "", after=10)
    _sign_table(doc, [[("ลงชื่อ ......................................", "center"),
                       (f"( {(school.finance_officer_name or school.officer_name or '').strip() or _BLANK} )", "center"),
                       ("เจ้าหน้าที่การเงิน", "center")],
                      [("ลงชื่อ ......................................", "center"),
                       (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
                       (_director_line(school), "center")]])
    return _save(doc, f"รายงานการรับและนำส่งเงินรายได้แผ่นดิน_{label}")
