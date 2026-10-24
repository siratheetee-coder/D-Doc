# -*- coding: utf-8 -*-
"""
finance_io.py - นำเข้าข้อมูลการเงินจาก Excel (สำหรับโรงเรียนที่มีทะเบียนเดิม)
ไฟล์เดียว 3 ชีต: บัญชีเงิน / รายการรับ-จ่าย / ใบเสร็จ-ใบสำคัญ
(แถว 1 = คำอธิบาย, แถว 2 = หัวตาราง, แถว 3+ = ข้อมูล)
"""
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

from app.database import get_data_dir
from app.models import FinanceAccount, FinanceTxn, Receipt
from app.thai_utils import current_fiscal_year, parse_be_date, thai_date_short

THAI_FONT = "TH Sarabun New"
_thin = Side(style="thin")
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_HEAD = PatternFill("solid", fgColor="DCFCE7")     # เขียวอ่อน (ธีมการเงิน)
_NOTE = PatternFill("solid", fgColor="FFF2CC")

SHEETS = {
    "บัญชีเงิน": {
        "headers": ["ชื่อบัญชี", "ยอดยกมา", "หมายเหตุ", "หมวดเงิน", "ยอดยกมาของปีงบ (พ.ศ.)"],
        "note": "กรอกรายการบัญชี/ประเภทเงินตั้งแต่แถวที่ 3 (เช่น เงินอุดหนุน, รายได้สถานศึกษา)",
        "widths": [30, 16, 36, 25, 18],
    },
    "รายการรับ-จ่าย": {
        "headers": ["บัญชี (ชื่อ)", "วันที่", "ประเภท (รับ/จ่าย)", "จำนวนเงิน", "หมวด", "อ้างอิง", "หมายเหตุ"],
        "note": "กรอกการเคลื่อนไหวเงินตั้งแต่แถวที่ 3 (วันที่ พ.ศ. เช่น 09/06/2569 · ประเภทใส่ รับ หรือ จ่าย)",
        "widths": [26, 16, 18, 16, 20, 20, 26],
    },
    "ใบเสร็จ-ใบสำคัญ": {
        "headers": ["เลขที่", "วันที่", "ประเภท (รับ/จ่าย)", "คู่สัญญา/ผู้รับเงิน", "จำนวนเงิน", "บัญชี (ชื่อ)", "หมายเหตุ"],
        "note": "กรอกทะเบียนใบเสร็จ/ใบสำคัญตั้งแต่แถวที่ 3",
        "widths": [16, 16, 18, 28, 16, 24, 24],
    },
}


def _style_head(c):
    c.font = Font(name=THAI_FONT, bold=True, size=14)
    c.alignment = Alignment(horizontal="center", vertical="center")
    c.border = _BORDER; c.fill = _HEAD


def build_finance_template() -> str:
    wb = Workbook(); wb.remove(wb.active)
    for title, spec in SHEETS.items():
        ws = wb.create_sheet(title)
        last = chr(64 + len(spec["headers"]))
        ws.merge_cells(f"A1:{last}1")
        ws["A1"] = spec["note"]
        ws["A1"].font = Font(name=THAI_FONT, bold=True, size=12, color="9C6500")
        ws["A1"].fill = _NOTE
        ws["A1"].alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        for col, h in enumerate(spec["headers"], start=1):
            _style_head(ws.cell(row=2, column=col, value=h))
        for i, w in enumerate(spec["widths"], start=1):
            ws.column_dimensions[chr(64 + i)].width = w
        ws.row_dimensions[1].height = 30
        ws.freeze_panes = "A3"
    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    path = out_dir / "เทมเพลตนำเข้าข้อมูลการเงิน.xlsx"
    wb.save(str(path))
    return str(path)


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _f(v) -> float:
    s = _s(v).replace(",", "")
    try:
        return float(s) if s else 0.0
    except ValueError:
        return 0.0


def _kind(v) -> str:
    return "out" if ("จ่าย" in _s(v) or _s(v).lower() == "out") else "in"


from app.services.finance_types import resolve_fund_type


def _date(v):
    """วันที่จากช่อง Excel: ข้อความ พ.ศ. หรือช่องวันที่ของ Excel (ถ้าพิมพ์ปี พ.ศ. ลงช่องวันที่ ปีจะเกิน 2400)"""
    from datetime import datetime, date
    if isinstance(v, (datetime, date)):
        d = v if isinstance(v, datetime) else datetime(v.year, v.month, v.day)
        return d.replace(year=d.year - 543) if d.year > 2400 else d
    return parse_be_date(_s(v)) if _s(v) else None


def _norm(s) -> str:
    return "".join(_s(s).split()).lower()


def _rows(wb, title):
    if title not in wb.sheetnames:
        return []
    return [(n, r) for n, r in enumerate(wb[title].iter_rows(min_row=3, values_only=True), 3)
            if r and any(v not in (None, "") for v in r)]


def parse_finance_workbook(file_bytes: bytes, db) -> dict:
    """อ่านไฟล์แล้วบอกว่าแต่ละแถวจะทำอะไร (ยังไม่บันทึก) ใช้แสดงหน้าตรวจก่อนนำเข้า

    - ปีงบตามวันที่ของแต่ละแถว
    - จับคู่ "หมวด" กับหมวดในทะเบียนคุมเงินของบัญชีและปีงบนั้น (ไม่สร้างหมวดใหม่ให้เอง)
    - รายการที่มีในระบบแล้ว (บัญชี วันที่ รับ/จ่าย จำนวนเงิน อ้างอิง ตรงกัน) หรือซ้ำในไฟล์ = ข้าม
    """
    from app.models import AccountItem
    wb = load_workbook(BytesIO(file_bytes), data_only=True)
    fy_now = current_fiscal_year()
    accounts = {_norm(a.name): a for a in db.query(FinanceAccount).all()}
    items = {}
    for it in db.query(AccountItem).all():
        items.setdefault((it.account_id, it.fiscal_year), {})[_norm(it.name)] = it
    out = {"accounts": [], "txns": [], "receipts": [], "new_accounts": set()}

    for n, row in _rows(wb, "บัญชีเงิน"):
        name = _s(row[0])
        if not name:
            continue
        r = {"line": n, "name": name, "opening": _f(row[1]) if len(row) > 1 else 0.0,
             "note": _s(row[2]) if len(row) > 2 else "", "fund": _s(row[3]) if len(row) > 3 else "",
             "opening_fy": None, "errors": [], "warnings": [], "exists": _norm(name) in accounts}
        if len(row) > 4 and _s(row[4]):
            try:
                y = int(float(_s(row[4])))
                if not 2500 <= y <= 2700:
                    raise ValueError
                r["opening_fy"] = y
            except ValueError:
                r["errors"].append("ปีงบของยอดยกมาต้องเป็น พ.ศ. เช่น 2569")
        out["accounts"].append(r)
    planned = {_norm(r["name"]) for r in out["accounts"] if not r["errors"]}

    def account_of(name, r):
        if not name:
            r["errors"].append("ไม่ได้ระบุบัญชี")
            return None
        a = accounts.get(_norm(name))
        if a is None and _norm(name) not in planned:
            out["new_accounts"].add(name)
            r["warnings"].append(f"บัญชี {name} ยังไม่มี ระบบจะสร้างให้")
        return a

    seen = set()
    for n, row in _rows(wb, "รายการรับ-จ่าย"):
        g = lambda i: row[i] if len(row) > i else None  # noqa: E731
        r = {"line": n, "account": _s(g(0)), "kind": _kind(g(2)), "amount": _f(g(3)),
             "category": _s(g(4)), "ref": _s(g(5)), "note": _s(g(6)), "errors": [], "warnings": [],
             "item_id": None, "item_name": ""}
        try:
            d = _date(g(1))
        except Exception:  # noqa: BLE001
            d = None
        if d is None:
            r["errors"].append("ไม่มีวันที่ หรืออ่านวันที่ไม่ได้")
        r["date"] = d.strftime("%Y-%m-%d") if d else ""
        r["date_th"] = thai_date_short(d) if d else ""
        r["fy"] = current_fiscal_year(d) if d else fy_now
        if r["amount"] <= 0:
            r["errors"].append("จำนวนเงินต้องมากกว่า 0")
        acc = account_of(r["account"], r)
        if acc is not None and r["category"]:
            it = items.get((acc.id, r["fy"]), {}).get(_norm(r["category"]))
            if it:
                r["item_id"], r["item_name"] = it.id, it.name
            else:
                r["warnings"].append(f"ไม่พบหมวด {r['category']} ในปีงบ {r['fy']} จะลงแบบไม่ระบุหมวด")
        key = (_norm(r["account"]), r["date"], r["kind"], round(r["amount"], 2), _norm(r["ref"]))
        if key in seen:
            r["errors"].append("ซ้ำกับแถวก่อนหน้าในไฟล์")
        elif acc is not None and d is not None and db.query(FinanceTxn).filter(
                FinanceTxn.account_id == acc.id, FinanceTxn.kind == r["kind"], FinanceTxn.date == d,
                FinanceTxn.amount.between(r["amount"] - 0.005, r["amount"] + 0.005),
                FinanceTxn.ref == r["ref"]).first():
            r["errors"].append("มีรายการนี้ในระบบแล้ว")
        seen.add(key)
        out["txns"].append(r)

    seen = set()
    for n, row in _rows(wb, "ใบเสร็จ-ใบสำคัญ"):
        g = lambda i: row[i] if len(row) > i else None  # noqa: E731
        r = {"line": n, "receipt_no": _s(g(0)), "kind": "จ่าย" if "จ่าย" in _s(g(2)) else "รับ",
             "party": _s(g(3)), "amount": _f(g(4)), "account": _s(g(5)), "note": _s(g(6)),
             "errors": [], "warnings": []}
        if not (r["receipt_no"] or r["party"]):
            continue
        try:
            d = _date(g(1))
        except Exception:  # noqa: BLE001
            d = None
        r["date"] = d.strftime("%Y-%m-%d") if d else ""
        r["date_th"] = thai_date_short(d) if d else ""
        r["fy"] = current_fiscal_year(d) if d else fy_now
        if d is None:
            r["warnings"].append(f"ไม่มีวันที่ ลงในปีงบ {fy_now}")
        if r["account"]:
            account_of(r["account"], r)
        key = (r["fy"], r["kind"], r["receipt_no"])
        if r["receipt_no"] and (key in seen or db.query(Receipt).filter_by(
                fiscal_year=r["fy"], kind=r["kind"], receipt_no=r["receipt_no"]).first()):
            r["errors"].append("เลขที่นี้มีแล้วในปีงบเดียวกัน")
        seen.add(key)
        out["receipts"].append(r)
    out["new_accounts"] = sorted(out["new_accounts"])
    for k in ("accounts", "txns", "receipts"):
        out[k + "_ok"] = sum(1 for r in out[k] if not r["errors"])
        out[k + "_bad"] = len(out[k]) - out[k + "_ok"]
    return out


def apply_finance_import(plan: dict, db) -> dict:
    """บันทึกแถวที่ผ่านการตรวจ (แถวที่มีข้อผิดพลาดข้าม)"""
    from datetime import datetime
    from app.models import AccountItem, AccountOpening
    accounts = {_norm(a.name): a for a in db.query(FinanceAccount).all()}

    def get_account(name):
        a = accounts.get(_norm(name))
        if a is None and _s(name):
            a = FinanceAccount(name=_s(name), fund_type=resolve_fund_type(_s(name)))
            db.add(a); db.flush()
            accounts[_norm(name)] = a
        return a

    summary = {}
    n = 0
    for r in plan["accounts"]:
        if r["errors"]:
            continue
        a = get_account(r["name"])
        if r["fund"]:
            a.fund_type = resolve_fund_type(a.name, r["fund"])
        if r["opening_fy"]:
            o = db.query(AccountOpening).filter_by(account_id=a.id, fiscal_year=r["opening_fy"]).first()
            if o is None:
                o = AccountOpening(account_id=a.id, fiscal_year=r["opening_fy"])
                db.add(o)
            o.amount = r["opening"]
        else:
            a.opening_balance = r["opening"]
        if r["note"]:
            a.note = r["note"]
        n += 1
    if n:
        summary["บัญชีเงิน"] = n
    n = 0
    for r in plan["txns"]:
        if r["errors"]:
            continue
        a = get_account(r["account"])
        item = db.get(AccountItem, r["item_id"]) if r.get("item_id") else None
        if item and (item.account_id != a.id or item.fiscal_year != r["fy"]):
            item = None
        db.add(FinanceTxn(account_id=a.id, fiscal_year=r["fy"], date=datetime.strptime(r["date"], "%Y-%m-%d"),
                          kind=r["kind"], amount=r["amount"], category=item.name if item else r["category"],
                          item_id=item.id if item else None, ref=r["ref"], note=r["note"]))
        n += 1
    if n:
        summary["รายการรับ-จ่าย"] = n
    n = 0
    for r in plan["receipts"]:
        if r["errors"]:
            continue
        a = get_account(r["account"]) if r["account"] else None
        db.add(Receipt(fiscal_year=r["fy"], receipt_no=r["receipt_no"],
                       date=datetime.strptime(r["date"], "%Y-%m-%d") if r["date"] else None,
                       kind=r["kind"], party=r["party"], amount=r["amount"],
                       account_id=a.id if a else None, note=r["note"]))
        n += 1
    if n:
        summary["ใบเสร็จ-ใบสำคัญ"] = n
    db.commit()
    return summary


def import_finance_workbook(file_bytes: bytes, db) -> dict:
    """ตรวจแล้วบันทึกในครั้งเดียว (ใช้ในชุดทดสอบ/สคริปต์) หน้าเว็บใช้ parse แล้วให้ผู้ใช้ยืนยันก่อน"""
    return apply_finance_import(parse_finance_workbook(file_bytes, db), db)
