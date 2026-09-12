# -*- coding: utf-8 -*-
"""
finance_forms_doc.py - แบบฟอร์มการเงินที่ยังขาด (ยืมเงิน / เช็ค / กระทบยอด / 50 ทวิ)

ยึดตามแบบฟอร์มราชการจริง:
  - สัญญาการยืมเงิน "แบบ 8500" ของกรมบัญชีกลาง (หน้า = สัญญา · หลัง = รายการส่งใช้เงินยืม)
  - ทะเบียนคุมลูกหนี้เงินยืม และ ทะเบียนคุมการจ่ายเช็ค (แบบฟอร์มทะเบียนคุมของสถานศึกษา)
  - งบกระทบยอดเงินฝากธนาคาร (ยอดตาม statement +/- รายการคงค้าง = ยอดตามบัญชี)
  - หนังสือรับรองการหักภาษี ณ ที่จ่าย ตามมาตรา 50 ทวิ แห่งประมวลรัษฎากร
"""
import json

from docx import Document
from docx.shared import Cm

from app.services.doc_page import set_a4
from app.database import get_data_dir
from app.thai_utils import thai_date, bahttext
from app.services.book_receipt_doc import _safe
from app.services.build_templates import (
    _font, _p, _set_cell, _repeat_header_row, _no_split_row, _no_borders, _fixed_cols,
    _sign_table,
)

_BLANK = "................................"
_LINE = "." * 34


def _money(v) -> str:
    return f"{float(v or 0):,.2f}"


def _new(landscape: bool = False):
    doc = Document(); set_a4(doc, landscape=landscape); _font(doc)
    return doc


def _save(doc, name: str) -> str:
    out = get_data_dir() / "documents"
    out.mkdir(exist_ok=True)
    path = out / (_safe(name) + ".docx")
    doc.save(str(path))
    return str(path)


def _grid(doc, headers, widths, *, size=13):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=size)
        c.width = w
    return t


def _row(t, vals, widths, aligns, *, size=13, bold=False):
    r = t.add_row(); _no_split_row(r)
    for c, v, w, al in zip(r.cells, vals, widths, aligns):
        _set_cell(c, v, align=al, size=size, bold=bold)
        c.width = w
    return r


def _school_line(school) -> str:
    return " ".join(x for x in [(school.name or "").strip(), (school.address or "").strip()] if x)


# ------------------------------------------------- สัญญาการยืมเงิน (แบบ 8500)
def render_loan_contract(school, loan) -> str:
    """หน้า = สัญญาการยืมเงินตามแบบ 8500 · หลัง = รายการส่งใช้เงินยืม"""
    doc = _new()
    try:
        items = json.loads(loan.items or "[]")
    except Exception:
        items = []
    _p(doc, "แบบ 8500", align="right", size=13, after=0)
    _p(doc, "สัญญาการยืมเงิน", align="center", bold=True, size=18, after=4)
    _p(doc, f"ยื่นต่อ {(loan.submit_to or '').strip() or _LINE * 2}", size=15, after=1)
    _p(doc, f"เลขที่ {(loan.contract_no or '').strip() or _LINE}"
            f"          วันครบกำหนด {thai_date(loan.due_date) if loan.due_date else _LINE}",
       size=15, after=3)
    _p(doc, f"ข้าพเจ้า {(loan.borrower or '').strip() or _LINE}"
            f"  ตำแหน่ง {(loan.position or '').strip() or _LINE}", size=15, after=1)
    _p(doc, f"สังกัด {_school_line(school) or _LINE}", size=15, after=1)
    _p(doc, f"มีความประสงค์ขอยืมเงินจาก {(loan.fund_from or '').strip() or _LINE * 2}",
       size=15, after=1)
    _p(doc, f"เพื่อเป็นค่าใช้จ่ายในการ {(loan.purpose or '').strip() or _LINE * 2} "
            "ดังรายละเอียดต่อไปนี้", align="justify", size=15, after=3)

    widths = [Cm(11.5), Cm(5.0)]
    t = doc.add_table(rows=1, cols=2)
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _set_cell(t.rows[0].cells[0], "รายการ", bold=True, align="center", size=14)
    _set_cell(t.rows[0].cells[1], "จำนวนเงิน (บาท)", bold=True, align="center", size=14)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    total = 0.0
    rows = items or [{"name": "", "amount": 0}] * 3
    for it in rows:
        amt = float(it.get("amount") or 0)
        total += amt
        _row(t, [it.get("name") or "", _money(amt) if amt else ""], widths,
             ["left", "right"], size=14)
    total = total or float(loan.amount or 0)
    _row(t, [f"(ตัวอักษร {bahttext(total)})", _money(total)], widths,
         ["right", "right"], size=14, bold=True)

    _p(doc, "", after=4)
    _p(doc, f"ข้าพเจ้าสัญญาว่าจะปฏิบัติตามระเบียบของทางราชการทุกประการ และจะนำใบสำคัญคู่จ่าย"
            "ที่ถูกต้องพร้อมทั้งเงินเหลือจ่าย (ถ้ามี) ส่งใช้ภายในกำหนดไว้ในระเบียบการเบิกจ่ายเงิน"
            f"จากคลัง คือ ภายใน {loan.within_days or 15} วัน นับแต่วันที่ได้รับเงินนี้ "
            "ถ้าข้าพเจ้าไม่ส่งตามกำหนด ข้าพเจ้ายินยอมให้หักเงินเดือน ค่าจ้าง เบี้ยหวัด บำเหน็จ "
            "บำนาญ หรือเงินอื่นใดที่ข้าพเจ้าพึงได้รับจากทางราชการ ชดใช้จำนวนเงินที่ยืมไปจนครบถ้วนได้ทันที",
       align="justify", indent=1.25, size=15, after=8)
    _p(doc, f"ลายมือชื่อ...............................................ผู้ยืม"
            f"        วันที่ {thai_date(loan.date) if loan.date else _LINE}",
       align="right", size=15, after=8)

    _p(doc, f"เสนอ {(loan.submit_to or '').strip() or _LINE}", size=15, after=1)
    _p(doc, f"ได้ตรวจสอบแล้ว เห็นสมควรอนุมัติให้ยืมตามใบยืมฉบับนี้ได้ จำนวน {_money(total)} บาท "
            f"({bahttext(total)})", align="justify", indent=1.25, size=15, after=6)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................", "center"),
        ("(.......................................)", "center"),
        ("เจ้าหน้าที่การเงิน", "center"),
    ]])
    _p(doc, "คำอนุมัติ", bold=True, size=15, after=1)
    _p(doc, f"อนุมัติให้ยืมตามเงื่อนไขข้างต้นได้ เป็นเงิน {_money(total)} บาท ({bahttext(total)})",
       indent=1.25, size=15, after=8)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................ผู้อนุมัติ", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
        (f"วันที่ {_LINE}", "center"),
    ]])
    _p(doc, "ใบรับเงิน", bold=True, size=15, before=6, after=1)
    _p(doc, f"ข้าพเจ้าได้รับเงินยืม จำนวน {_money(total)} บาท ({bahttext(total)}) "
            "ไปเป็นการถูกต้องแล้ว", indent=1.25, size=15, after=8)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................ผู้รับเงิน", "center"),
        (f"( {(loan.borrower or '').strip() or _BLANK} )", "center"),
        (f"วันที่ {thai_date(loan.receive_date) if loan.receive_date else _LINE}", "center"),
    ]])

    # ---------------- ด้านหลัง: รายการส่งใช้เงินยืม ----------------
    doc.add_page_break()
    _p(doc, "รายการส่งใช้เงินยืม", align="center", bold=True, size=17, after=4)
    headers = ["ครั้งที่", "วัน เดือน ปี", "เงินสดหรือใบสำคัญ", "จำนวนเงิน", "คงค้าง",
               "ใบรับเลขที่", "ลายมือชื่อผู้รับ"]
    widths = [Cm(1.4), Cm(2.6), Cm(3.0), Cm(2.4), Cm(2.4), Cm(2.0), Cm(2.7)]
    t = _grid(doc, headers, widths, size=13)
    left = float(loan.amount or total or 0)
    rets = list(loan.returns or [])
    for i in range(max(len(rets), 10)):
        r = rets[i] if i < len(rets) else None
        if r:
            left -= float(r.amount or 0)
            vals = [str(i + 1), thai_date(r.date) if r.date else "", r.kind or "",
                    _money(r.amount), _money(left), r.receipt_no or "", ""]
        else:
            vals = [""] * 7
        _row(t, vals, widths, ["center", "center", "center", "right", "right", "center", "center"])
    _p(doc, f"ยอดเงินยืมทั้งสิ้น {_money(loan.amount or total)} บาท · "
            f"ส่งใช้แล้ว {_money(float(loan.amount or total) - left)} บาท · "
            f"คงค้าง {_money(left)} บาท", bold=True, before=6, after=10)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................เจ้าหน้าที่การเงิน", "center"),
        ("(.......................................)", "center"),
    ], [
        ("ลงชื่อ.......................................ผู้ยืม", "center"),
        (f"( {(loan.borrower or '').strip() or _BLANK} )", "center"),
    ]])
    return _save(doc, f"สัญญาการยืมเงิน_{(loan.contract_no or loan.id)}")


# --------------------------------------------- ทะเบียนคุมลูกหนี้เงินยืม
def render_loan_register(school, fiscal_year, loans) -> str:
    doc = _new(landscape=True)
    _p(doc, "ทะเบียนคุมลูกหนี้เงินยืม", align="center", bold=True, size=18, after=0)
    _p(doc, (school.name or "").strip(), align="center", bold=True, size=15, after=0)
    _p(doc, f"ปีงบประมาณ {fiscal_year}", align="center", size=14, after=6)
    headers = ["วัน เดือน ปี", "เลขที่สัญญา", "ชื่อผู้ยืม", "วัตถุประสงค์", "จำนวนเงินยืม",
               "วันครบกำหนด", "ส่งใช้แล้ว", "คงค้าง", "หมายเหตุ"]
    widths = [Cm(2.4), Cm(2.4), Cm(4.0), Cm(5.0), Cm(2.6), Cm(2.4), Cm(2.6), Cm(2.4), Cm(2.7)]
    t = _grid(doc, headers, widths)
    tot_loan = tot_ret = 0.0
    for ln in loans:
        paid = sum(float(r.amount or 0) for r in (ln.returns or []))
        left = float(ln.amount or 0) - paid
        tot_loan += float(ln.amount or 0); tot_ret += paid
        _row(t, [thai_date(ln.date) if ln.date else "", ln.contract_no or "",
                 ln.borrower or "", (ln.purpose or "")[:60], _money(ln.amount),
                 thai_date(ln.due_date) if ln.due_date else "", _money(paid), _money(left),
                 ln.note or ""],
             widths, ["center", "center", "left", "left", "right", "center", "right",
                      "right", "left"])
    _row(t, ["", "", "", "รวม", _money(tot_loan), "", _money(tot_ret),
             _money(tot_loan - tot_ret), ""], widths,
        ["center", "center", "left", "right", "right", "center", "right", "right", "left"],
        bold=True)
    _p(doc, "", after=10)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................เจ้าหน้าที่การเงิน", "center"),
        ("(.......................................)", "center"),
    ], [
        ("ลงชื่อ.......................................", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
    ]])
    return _save(doc, f"ทะเบียนคุมลูกหนี้เงินยืม_ปีงบ{fiscal_year}")


# ------------------------------------------------ ทะเบียนคุมการจ่ายเช็ค
def render_check_register(school, fiscal_year, checks) -> str:
    doc = _new(landscape=True)
    _p(doc, "ทะเบียนคุมการจ่ายเช็ค", align="center", bold=True, size=18, after=0)
    _p(doc, (school.name or "").strip(), align="center", bold=True, size=15, after=0)
    _p(doc, f"ปีงบประมาณ {fiscal_year}", align="center", size=14, after=6)
    headers = ["วัน เดือน ปี", "เลขที่เช็ค", "ธนาคาร", "จ่ายให้", "รายการ", "จำนวนเงิน",
               "ลงชื่อผู้รับเช็ค", "ลงชื่อผู้อนุมัติจ่ายเช็ค"]
    widths = [Cm(2.4), Cm(2.4), Cm(3.0), Cm(4.4), Cm(4.4), Cm(2.6), Cm(3.4), Cm(3.9)]
    t = _grid(doc, headers, widths)
    total = 0.0
    for ck in checks:
        total += float(ck.amount or 0)
        _row(t, [thai_date(ck.date) if ck.date else "", ck.check_no or "", ck.bank or "",
                 ck.payee or "", (ck.purpose or "")[:50], _money(ck.amount), "", ""],
             widths, ["center", "center", "left", "left", "left", "right", "center", "center"])
    for _ in range(max(0, 8 - len(checks))):
        _row(t, [""] * 8, widths, ["center"] * 8)
    _row(t, ["", "", "", "", "รวม", _money(total), "", ""], widths,
         ["center", "center", "left", "left", "right", "right", "center", "center"], bold=True)
    _p(doc, "", after=10)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................เจ้าหน้าที่การเงิน", "center"),
        ("(.......................................)", "center"),
    ], [
        ("ลงชื่อ.......................................", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
    ]])
    return _save(doc, f"ทะเบียนคุมการจ่ายเช็ค_ปีงบ{fiscal_year}")


# ------------------------------------------- งบกระทบยอดเงินฝากธนาคาร
def render_bank_recon(school, rec, account_name="", checks=None) -> str:
    """checks = เช็คที่ยังไม่ขึ้นเงิน (แนบรายตัวท้ายงบ ถ้ามี)"""
    doc = _new()
    _p(doc, "งบกระทบยอดเงินฝากธนาคาร", align="center", bold=True, size=18, after=0)
    _p(doc, (school.name or "").strip(), align="center", bold=True, size=15, after=0)
    _p(doc, f"บัญชี {account_name or _BLANK}", align="center", size=14, after=0)
    _p(doc, f"ณ วันที่ {thai_date(rec.as_of) if rec.as_of else _BLANK}",
       align="center", size=14, after=8)

    widths = [Cm(11.5), Cm(5.0)]
    t = doc.add_table(rows=0, cols=2)
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    add = float(rec.stmt_balance or 0)
    _row(t, ["ยอดเงินคงเหลือตามใบแจ้งยอดธนาคาร (Statement)", _money(rec.stmt_balance)],
         widths, ["left", "right"], size=14, bold=True)
    _row(t, ["บวก  เงินฝากระหว่างทาง (ฝากแล้วธนาคารยังไม่บันทึก)", _money(rec.in_transit)],
         widths, ["left", "right"], size=14)
    _row(t, ["บวก  ดอกเบี้ยรับที่ยังไม่ได้บันทึกบัญชี", _money(rec.interest)],
         widths, ["left", "right"], size=14)
    _row(t, ["หัก  เช็คที่ผู้รับยังไม่นำไปขึ้นเงิน", _money(rec.outstanding)],
         widths, ["left", "right"], size=14)
    _row(t, ["หัก  ค่าธรรมเนียมธนาคารที่ยังไม่ได้บันทึกบัญชี", _money(rec.bank_fee)],
         widths, ["left", "right"], size=14)
    other = float(rec.other or 0)
    if other:
        _row(t, [f"รายการอื่น {(rec.other_note or '').strip()}", _money(other)],
             widths, ["left", "right"], size=14)
    calc = (add + float(rec.in_transit or 0) + float(rec.interest or 0)
            - float(rec.outstanding or 0) - float(rec.bank_fee or 0) + other)
    _row(t, ["ยอดคงเหลือที่กระทบแล้ว", _money(calc)], widths, ["right", "right"],
         size=14, bold=True)
    _row(t, ["ยอดคงเหลือตามบัญชีเงินฝากธนาคารของสถานศึกษา", _money(rec.book_balance)],
         widths, ["left", "right"], size=14, bold=True)
    diff = calc - float(rec.book_balance or 0)
    _row(t, ["ผลต่าง", _money(diff)], widths, ["right", "right"], size=14, bold=True)

    if abs(diff) > 0.005:
        _p(doc, f"** ยอดยังไม่ตรงกัน ผลต่าง {_money(diff)} บาท ต้องตรวจสอบรายการเพิ่มเติม **",
           bold=True, before=4, after=2)
    else:
        _p(doc, "ยอดตรงกัน", bold=True, before=4, after=2)
    if (rec.note or "").strip():
        _p(doc, f"หมายเหตุ  {rec.note.strip()}", align="justify", after=2)

    if checks:
        _p(doc, "รายละเอียดเช็คที่ผู้รับยังไม่นำไปขึ้นเงิน", bold=True, before=6, after=2)
        hw = [Cm(2.6), Cm(2.6), Cm(6.3), Cm(3.0)]
        ct = _grid(doc, ["วัน เดือน ปี", "เลขที่เช็ค", "จ่ายให้", "จำนวนเงิน"], hw)
        s = 0.0
        for ck in checks:
            s += float(ck.amount or 0)
            _row(ct, [thai_date(ck.date) if ck.date else "", ck.check_no or "",
                      ck.payee or "", _money(ck.amount)], hw,
                 ["center", "center", "left", "right"], size=14)
        _row(ct, ["", "", "รวม", _money(s)], hw, ["center", "center", "right", "right"],
             size=14, bold=True)
    _p(doc, "", after=12)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................ผู้จัดทำ", "center"),
        ("(.......................................)", "center"),
    ], [
        ("ลงชื่อ.......................................", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
    ]])
    return _save(doc, f"งบกระทบยอดเงินฝากธนาคาร_{thai_date(rec.as_of) if rec.as_of else rec.id}")


# --------------------------------- หนังสือรับรองการหักภาษี ณ ที่จ่าย (50 ทวิ)
def render_wht_certificate(school, memo, *, payee_tax_id="", payee_address="",
                           pay_type="ค่าจ้างทำของ/ค่าบริการ", rate=1.0) -> str:
    """ออกจากบันทึกขออนุมัติเบิกจ่ายที่มีการหักภาษี ณ ที่จ่าย"""
    doc = _new()
    base = float(memo.amount or 0) - float(memo.vat or 0)
    wht = float(memo.wht or 0) or round(base * rate / 100, 2)
    _p(doc, "หนังสือรับรองการหักภาษี ณ ที่จ่าย", align="center", bold=True, size=18, after=0)
    _p(doc, "ตามมาตรา 50 ทวิ แห่งประมวลรัษฎากร", align="center", size=14, after=6)
    _p(doc, f"ผู้มีหน้าที่หักภาษี ณ ที่จ่าย : {(school.name or '').strip()}", size=15, after=1)
    _p(doc, f"ที่อยู่ : {(school.address or '').strip() or _BLANK}", size=15, after=1)
    _p(doc, f"เลขประจำตัวผู้เสียภาษีอากร : {(getattr(school, 'tax_id', '') or '').strip() or _BLANK}",
       size=15, after=4)
    _p(doc, f"ผู้ถูกหักภาษี ณ ที่จ่าย : {(memo.payee or '').strip() or _BLANK}", size=15, after=1)
    _p(doc, f"ที่อยู่ : {payee_address or _BLANK}", size=15, after=1)
    _p(doc, f"เลขประจำตัวผู้เสียภาษีอากร : {payee_tax_id or _BLANK}", size=15, after=4)

    widths = [Cm(7.5), Cm(3.0), Cm(3.0), Cm(3.0)]
    t = _grid(doc, ["ประเภทเงินได้พึงประเมินที่จ่าย", "วัน เดือน ปี ที่จ่าย",
                    "จำนวนเงินที่จ่าย", "ภาษีที่หักและนำส่งไว้"], widths, size=14)
    _row(t, [pay_type, thai_date(memo.date) if memo.date else "", _money(base), _money(wht)],
         widths, ["left", "center", "right", "right"], size=14)
    _row(t, ["รวมเงินที่จ่ายและภาษีที่หักนำส่ง", "", _money(base), _money(wht)],
         widths, ["right", "center", "right", "right"], size=14, bold=True)
    _p(doc, f"รวมเงินภาษีที่หักนำส่ง (ตัวอักษร) {bahttext(wht)}", bold=True, before=4, after=4)
    _p(doc, "ผู้จ่ายเงิน   ( ) หักภาษี ณ ที่จ่าย   ( ) ออกภาษีให้ตลอดไป   "
            "( ) ออกภาษีให้ครั้งเดียว", size=14, after=6)
    _p(doc, "ขอรับรองว่าข้อความและตัวเลขดังกล่าวข้างต้นถูกต้องตรงกับความจริงทุกประการ",
       align="justify", indent=1.25, size=15, after=12)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................ผู้จ่ายเงิน", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
        (f"วันที่ {thai_date(memo.date) if memo.date else _LINE}", "center"),
    ]])
    return _save(doc, f"หนังสือรับรองหักภาษีณที่จ่าย_{(memo.memo_no or memo.id)}")


# ------------------------------------ รายงานผลการใช้จ่ายงบประมาณรายไตรมาส
QUARTERS = {1: ("ไตรมาสที่ 1", "ตุลาคม - ธันวาคม"), 2: ("ไตรมาสที่ 2", "มกราคม - มีนาคม"),
            3: ("ไตรมาสที่ 3", "เมษายน - มิถุนายน"), 4: ("ไตรมาสที่ 4", "กรกฎาคม - กันยายน")}


def render_quarter_report(school, fiscal_year, quarter, rows, totals) -> str:
    """rows = [{account, opening, income, expense, balance}]"""
    doc = _new()
    qname, qmonths = QUARTERS.get(quarter, ("", ""))
    _p(doc, "รายงานผลการใช้จ่ายงบประมาณ", align="center", bold=True, size=18, after=0)
    _p(doc, f"{qname} ({qmonths}) ปีงบประมาณ {fiscal_year}", align="center", bold=True,
       size=15, after=0)
    _p(doc, (school.name or "").strip(), align="center", size=15, after=6)
    widths = [Cm(5.5), Cm(2.8), Cm(2.8), Cm(2.8), Cm(2.6)]
    t = _grid(doc, ["บัญชี/ประเภทเงิน", "ยอดยกมา", "รับในไตรมาส", "จ่ายในไตรมาส", "คงเหลือ"],
              widths, size=14)
    for r in rows:
        _row(t, [r["account"], _money(r["opening"]), _money(r["income"]),
                 _money(r["expense"]), _money(r["balance"])],
             widths, ["left", "right", "right", "right", "right"], size=14)
    _row(t, ["รวมทั้งสิ้น", _money(totals["opening"]), _money(totals["income"]),
             _money(totals["expense"]), _money(totals["balance"])],
         widths, ["right", "right", "right", "right", "right"], size=14, bold=True)
    _p(doc, f"เงินคงเหลือยกไป {_money(totals['balance'])} บาท ({bahttext(totals['balance'])})",
       bold=True, before=6, after=12)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................เจ้าหน้าที่การเงิน", "center"),
        ("(.......................................)", "center"),
    ], [
        ("ลงชื่อ.......................................", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
    ]])
    return _save(doc, f"รายงานการใช้จ่ายงบประมาณ_ไตรมาส{quarter}_ปีงบ{fiscal_year}")
