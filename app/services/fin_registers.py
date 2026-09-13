# -*- coding: utf-8 -*-
"""
fin_registers.py - ทะเบียนคุมเงินเฉพาะประเภท + บันทึกการรับเงินเพื่อเก็บรักษา

ยึดตามชุดแบบฟอร์มการเงินของสถานศึกษา (สพป.เพชรบุรี เขต 2) ซึ่งมีทะเบียนคุม
แยกตาม "ประเภทเงิน" ไม่ใช่แยกเป็นระบบใหม่ ระบบเราจึงผูกไว้กับ "บัญชี" ที่ครูตั้งเอง
แล้วเลือกรูปแบบฟอร์มให้อัตโนมัติจากประเภทของบัญชีนั้น (special_form)

  - บัญชีชื่อ/ประเภทเป็นเงินประกันสัญญา  -> ทะเบียนคุมเงินฝาก (เงินประกันสัญญา)
  - บัญชี fund_type = เงินรายได้แผ่นดิน  -> ทะเบียนคุมการรับและนำส่งเงินรายได้แผ่นดิน
  - บัญชี deposit_type = agency          -> สมุดคู่ฝาก (ส่วนราชการผู้เบิก)

และอีก 2 ฟอร์มที่เกาะกับหน้าเดิม
  - บันทึกการรับเงินเพื่อเก็บรักษา  -> คู่กับรายงานเงินคงเหลือประจำวัน
  - ทะเบียนคุมหลักฐานขอเบิก        -> คู่กับหน้าบันทึกขอเบิกจ่าย
"""
from datetime import datetime

from docx.shared import Cm

from app.thai_utils import thai_date, bahttext
from app.services.build_templates import (
    _p, _set_cell, _repeat_header_row, _no_split_row, _fixed_cols, _sign_table,
)
from app.services.finance_forms_doc import _new, _save, _money, _grid, _row, _BLANK

# ---------------------------------------------------------------- ชนิดฟอร์มพิเศษ
SPECIAL_LABEL = {
    "guarantee": "ทะเบียนคุมเงินฝาก (เงินประกันสัญญา)",
    "revenue": "ทะเบียนคุมการรับและนำส่งเงินรายได้แผ่นดิน",
    "agency": "สมุดคู่ฝาก (ส่วนราชการผู้เบิก)",
}


def special_form(account) -> str:
    """บัญชีนี้ควรพิมพ์ทะเบียนคุมแบบไหน ('' = ใช้บัญชีแยกประเภทปกติ)"""
    name = (account.name or "")
    if "ประกัน" in name:
        return "guarantee"
    if (account.fund_type or "") == "เงินรายได้แผ่นดิน" or "รายได้แผ่นดิน" in name:
        return "revenue"
    if (account.deposit_type or "") == "agency":
        return "agency"
    return ""


def _head2(doc, groups, widths, *, size=12):
    """หัวตาราง 2 ชั้น - groups: list ของ (ชื่อ, [หัวย่อย...])
    หัวย่อยว่าง = คอลัมน์เดียวที่ผสานสองแถวเข้าด้วยกัน"""
    ncol = sum(max(1, len(g[1])) for g in groups)
    t = doc.add_table(rows=2, cols=ncol)
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _repeat_header_row(t.rows[1])
    _no_split_row(t.rows[0]); _no_split_row(t.rows[1])
    c = 0
    for label, subs in groups:
        if not subs:
            cell = t.cell(0, c).merge(t.cell(1, c))
            _set_cell(cell, label, bold=True, align="center", size=size)
            c += 1
        else:
            top = t.cell(0, c).merge(t.cell(0, c + len(subs) - 1))
            _set_cell(top, label, bold=True, align="center", size=size)
            for s in subs:
                _set_cell(t.cell(1, c), s, bold=True, align="center", size=size)
                c += 1
    for r in t.rows:
        for cell, w in zip(r.cells, widths):
            cell.width = w
    return t


def _blank_rows(t, n, widths, ncol):
    for _ in range(n):
        _row(t, [""] * ncol, widths, ["center"] * ncol)


def _sign_finance(doc, school):
    _p(doc, "", after=10)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................เจ้าหน้าที่การเงิน", "center"),
        ("(.......................................)", "center"),
    ], [
        ("ลงชื่อ.......................................", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
        ("ผู้อำนวยการโรงเรียน", "center"),
    ]])


def _school_only(school) -> str:
    """ชื่อโรงเรียนแบบตัดคำว่า "โรงเรียน" นำหน้าออก - กันข้อความซ้ำ เช่น "โรงเรียนโรงเรียนบ้าน..." """
    name = (school.name or "").strip()
    return name[len("โรงเรียน"):].strip() if name.startswith("โรงเรียน") else name


def _right_block(doc, lines, *, align="center", gap=True):
    """บล็อกข้อความชิดครึ่งขวาของหน้า โดยทุกบรรทัด "จัดตรงกันเอง" ในบล็อก
    ใช้ตารางไร้ขอบ 2 ช่อง (ซ้ายว่าง) แทนการสั่ง align=right ทีละบรรทัด
    ซึ่งทำให้บรรทัดยาวไม่เท่ากันไปเกาะขอบขวาแล้วดูเหลื่อมกัน"""
    _sign_table(doc, [[("", "center")], [(t, align) for t in lines]], gap=gap)


def _title(doc, school, title, fiscal_year, sub=""):
    _p(doc, title, align="center", bold=True, size=18, after=0)
    if sub:
        _p(doc, sub, align="center", size=14, after=0)
    _p(doc, (school.name or "").strip(), align="center", bold=True, size=15, after=0)
    _p(doc, f"ปีงบประมาณ {fiscal_year}", align="center", size=14, after=6)


# --------------------------------------- 1) บันทึกการรับเงินเพื่อเก็บรักษา
def render_safe_custody(school, rows, total, as_of) -> str:
    """rows: list ของ (ชื่อรายการ, จำนวนเงิน) - เฉพาะ "เงินสด" ที่ต้องเก็บในตู้นิรภัย
    ตามแบบฟอร์มจริง: ผอ. รับเงินไปเก็บรักษา แล้วคืนเจ้าหน้าที่การเงินในวันทำการถัดไป"""
    doc = _new()
    _p(doc, "บันทึกการรับเงินเพื่อเก็บรักษา", align="center", bold=True, size=18, after=6)
    _right_block(doc, [f"โรงเรียน{_school_only(school) or _BLANK}",
                       f"วันที่ {thai_date(as_of) if as_of else _BLANK}"], align="left", gap=False)
    _p(doc, "", after=4)
    _p(doc, "ข้าพเจ้าได้รับเงินคงเหลือตามรายการ ดังต่อไปนี้", indent=1.27, size=15, after=6)

    headers = ["รายการ", "จำนวนเงิน", "หมายเหตุ"]
    widths = [Cm(9.0), Cm(3.5), Cm(4.0)]
    t = _grid(doc, headers, widths, size=15)
    for name, amt in rows:
        _row(t, [name, _money(amt), ""], widths, ["left", "right", "left"], size=15)
    _blank_rows(t, max(0, 5 - len(rows)), widths, 3)
    _row(t, ["รวมทั้งสิ้น", _money(total), ""], widths,
         ["right", "right", "left"], size=15, bold=True)

    _p(doc, "", after=4)
    _p(doc, f"จำนวนเงิน  ({bahttext(total)})", indent=1.27, size=15, after=10)
    _p(doc, "ข้าพเจ้า จะรับผิดชอบในการเก็บรักษาเงินดังกล่าว และจะส่งคืนให้เจ้าหน้าที่การเงิน "
            "เพื่อจ่ายในวันทำการถัดไป", indent=1.27, size=15, after=10)

    _right_block(doc, ["ลงชื่อ..............................................",
                       f"( {(school.director_name or '').strip() or _BLANK} )",
                       f"ผู้อำนวยการโรงเรียน{_school_only(school)}"])
    _p(doc, "", after=6)

    got = _money(total) if total else "..............................."
    _p(doc, f"ข้าพเจ้าได้รับเงิน {got} บาท คืนจากผู้อำนวยการโรงเรียน"
            f"{_school_only(school) or _BLANK} ในวันที่ ........................................... "
            "เพื่อจะนำไปจ่ายตามระเบียบของทางราชการ", indent=1.27, size=15, after=12)
    _right_block(doc, ["ลงชื่อ..............................................",
                       "(..............................................)",
                       "เจ้าหน้าที่การเงิน"])
    _p(doc, "", after=6)

    _p(doc, "หมายเหตุ  บันทึกการรับเงินเพื่อเก็บรักษา ให้ถือเป็นหลักฐานแทนเงินสด "
            "ซึ่งจะต้องบันทึกไว้ทุกวันในวันที่เก็บรักษาเงินสด และจะต้องบันทึกไว้ในรายงานเงินคงเหลือประจำวัน",
       size=13, after=0)
    return _save(doc, f"บันทึกการรับเงินเพื่อเก็บรักษา_{thai_date(as_of) if as_of else ''}")


# --------------------------------------- 2) ทะเบียนคุมหลักฐานขอเบิก
def render_disburse_register(school, fiscal_year, memos) -> str:
    doc = _new(landscape=True)
    _title(doc, school, "ทะเบียนคุมหลักฐานขอเบิก", fiscal_year)
    headers = ["วัน เดือน ปี", "เจ้าหนี้หรือผู้ขอเบิก", "ประเภทรายจ่าย", "จำนวนเงิน",
               "ลายมือชื่อผู้รับหลักฐาน", "วัน เดือน ปี ที่ส่ง\nส่วนราชการผู้เบิก", "หมายเหตุ"]
    widths = [Cm(2.6), Cm(6.0), Cm(5.4), Cm(2.8), Cm(4.2), Cm(3.2), Cm(2.5)]
    t = _grid(doc, headers, widths)
    total = 0.0
    for m in memos:
        total += float(m.amount or 0)
        _row(t, [thai_date(m.date) if m.date else "", m.payee or "",
                 (m.budget_source or m.subject or "")[:48], _money(m.amount), "", "",
                 m.memo_no or ""],
             widths, ["center", "left", "left", "right", "center", "center", "center"])
    _blank_rows(t, max(0, 6 - len(memos)), widths, 7)
    _row(t, ["", "", "รวม", _money(total), "", "", ""], widths,
         ["center", "left", "right", "right", "center", "center", "center"], bold=True)
    _sign_finance(doc, school)
    return _save(doc, f"ทะเบียนคุมหลักฐานขอเบิก_ปีงบ{fiscal_year}")


# --------------------------------------- 3) ทะเบียนคุมเงินฝาก (เงินประกันสัญญา)
def render_guarantee_register(school, account, txns, fiscal_year) -> str:
    """แถวละ 1 รายการเงินประกันที่รับเข้ามา พร้อมวันครบกำหนดและวันที่คืนเงินให้ผู้มีสิทธิ์
    (ช่อง "การฝาก" เว้นไว้ให้กรอกวันที่นำเงินเข้าบัญชีธนาคารตามใบนำฝากจริง)"""
    doc = _new(landscape=True)
    _title(doc, school, "ทะเบียนคุมเงินนอกงบประมาณ",
           fiscal_year, sub=f"ประเภท เงินฝาก (เงินประกันสัญญา) · {account.name}")
    groups = [("ที่", []), ("รายการ", []), ("ประเภท", []),
              ("การรับ", ["วัน เดือน ปี", "ที่เอกสาร", "จำนวนเงิน"]),
              ("การฝาก", ["วัน เดือน ปี", "ที่เอกสาร", "จำนวนเงิน"]),
              ("วันครบกำหนด", []), ("วันที่เบิกจ่ายเงินคืน\nผู้มีสิทธิ์", []), ("หมายเหตุ", [])]
    widths = [Cm(1.2), Cm(3.8), Cm(2.2), Cm(2.2), Cm(2.0), Cm(2.2),
              Cm(2.2), Cm(2.0), Cm(2.2), Cm(2.2), Cm(2.4), Cm(2.0)]
    t = _head2(doc, groups, widths)
    total = 0.0
    ins = [x for x in txns if x.kind == "in"]
    for i, x in enumerate(ins, 1):
        total += float(x.amount or 0)
        _row(t, [str(i), x.note or x.category or "", "เงินประกันสัญญา",
                 thai_date(x.date) if x.date else "", x.ref or "", _money(x.amount),
                 "", "", "",
                 thai_date(x.due_date) if x.due_date else "",
                 thai_date(x.refund_date) if x.refund_date else "", ""],
             widths, ["center", "left", "center", "center", "center", "right",
                      "center", "center", "right", "center", "center", "left"])
    _blank_rows(t, max(0, 6 - len(ins)), widths, 12)
    _row(t, ["", "รวม", "", "", "", _money(total), "", "", "", "", "", ""], widths,
         ["center", "right", "center", "center", "center", "right",
          "center", "center", "right", "center", "center", "left"], bold=True)
    _sign_finance(doc, school)
    return _save(doc, f"ทะเบียนคุมเงินประกันสัญญา_ปีงบ{fiscal_year}")


# --------------------------------------- 4) ทะเบียนคุมการรับและนำส่งเงินรายได้แผ่นดิน
_REV_COLS = ["ดอกเบี้ยบัญชีเงินฝากธนาคาร", "เงินอุดหนุนเหลือจ่ายเกิน 2 ปี", "ค่าปรับอื่น ๆ"]


def _rev_bucket(txn) -> int:
    """จัดรายการเข้า 3 ช่องของฟอร์ม จากคำในหมวด/หมายเหตุ (ค่าเริ่มต้น = ค่าปรับอื่น ๆ)"""
    text = f"{txn.category or ''} {txn.note or ''}"
    if "ดอกเบี้ย" in text:
        return 0
    if "เหลือจ่าย" in text:
        return 1
    return 2


def render_revenue_register(school, account, txns, fiscal_year) -> str:
    doc = _new(landscape=True)
    _title(doc, school, "ทะเบียนคุมการรับและนำส่งเงินรายได้แผ่นดิน",
           fiscal_year, sub=account.name)
    groups = [("วัน เดือน ปี", []), ("ที่เอกสาร", []), ("รายการ", [])]
    for label in _REV_COLS:
        groups.append((label, ["รับ", "นำส่ง", "คงเหลือ"]))
    groups += [("รวมเงินคงเหลือ\nทุกประเภท", []), ("หมายเหตุ", [])]
    widths = [Cm(2.2), Cm(2.0), Cm(3.0)] + [Cm(1.65)] * 9 + [Cm(2.5), Cm(2.0)]
    t = _head2(doc, groups, widths)

    bal = [0.0, 0.0, 0.0]
    ordered = sorted(txns, key=lambda x: (x.date or datetime.min, x.id))
    for x in ordered:
        b = _rev_bucket(x)
        amt = float(x.amount or 0)
        got = amt if x.kind == "in" else 0.0
        sent = amt if x.kind == "out" else 0.0     # "นำส่ง" คลัง = จ่ายออก
        bal[b] += got - sent
        cells = ["", "", "", "", "", "", "", "", ""]
        cells[b * 3] = _money(got) if got else ""
        cells[b * 3 + 1] = _money(sent) if sent else ""
        cells[b * 3 + 2] = _money(bal[b])
        _row(t, [thai_date(x.date) if x.date else "", x.ref or "",
                 (x.note or x.category or "")[:30]] + cells + [_money(sum(bal)), ""],
             widths, ["center", "center", "left"] + ["right"] * 9 + ["right", "left"], size=12)
    _blank_rows(t, max(0, 6 - len(ordered)), widths, 14)
    _sign_finance(doc, school)
    return _save(doc, f"ทะเบียนคุมเงินรายได้แผ่นดิน_ปีงบ{fiscal_year}")


# --------------------------------------- 5) สมุดคู่ฝาก (ส่วนราชการผู้เบิก)
def render_agency_passbook(school, account, txns, opening, fiscal_year) -> str:
    doc = _new(landscape=True)
    _title(doc, school, "สมุดคู่ฝาก", fiscal_year, sub=f"(ส่วนราชการผู้เบิก) · {account.name}")
    groups = [("วัน เดือน ปี", []), ("ที่เอกสาร\nใบนำฝาก/ใบเบิกถอน", []),
              ("จำนวนเงิน", ["ฝาก", "ถอน", "คงเหลือ"]),
              ("ลายมือชื่อ\nผู้รับฝาก", []),
              ("ลายมือชื่อผู้นำฝาก\nหรือผู้เบิกถอน", []), ("หมายเหตุ", [])]
    widths = [Cm(2.6), Cm(4.0), Cm(2.8), Cm(2.8), Cm(3.0), Cm(4.0), Cm(4.5), Cm(3.0)]
    t = _head2(doc, groups, widths)
    bal = float(opening or 0)
    _row(t, ["", "ยอดยกมา", "", "", _money(bal), "", "", ""], widths,
         ["center", "left", "right", "right", "right", "center", "center", "left"], bold=True)
    ordered = sorted(txns, key=lambda x: (x.date or datetime.min, x.id))
    for x in ordered:
        amt = float(x.amount or 0)
        bal += amt if x.kind == "in" else -amt
        _row(t, [thai_date(x.date) if x.date else "", x.ref or (x.note or "")[:28],
                 _money(amt) if x.kind == "in" else "",
                 _money(amt) if x.kind == "out" else "", _money(bal), "", "", ""],
             widths, ["center", "left", "right", "right", "right", "center", "center", "left"])
    _blank_rows(t, max(0, 6 - len(ordered)), widths, 8)
    _sign_finance(doc, school)
    return _save(doc, f"สมุดคู่ฝาก_ปีงบ{fiscal_year}")


def render_account_register(school, account, txns, opening, fiscal_year, key) -> str:
    if key == "guarantee":
        return render_guarantee_register(school, account, txns, fiscal_year)
    if key == "revenue":
        return render_revenue_register(school, account, txns, fiscal_year)
    return render_agency_passbook(school, account, txns, opening, fiscal_year)
