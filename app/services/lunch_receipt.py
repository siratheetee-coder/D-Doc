# -*- coding: utf-8 -*-
"""
lunch_receipt.py - เอกสารจากบัญชีรับ-จ่ายอาหารกลางวัน (หน้าโครงการอาหารกลางวัน)

เดิมมีแค่ "ใบสำคัญรับเงิน" ของรายการรับ เป็นย่อหน้าเล่าเรื่อง ไม่มีตารางรายการ/จำนวนเงิน
เจ้าของบอกว่าดูไม่เหมือนใบสำคัญรับเงิน จึงทำใหม่:
  - ใบสำคัญรับเงิน (ทั้งรายการรับและจ่าย) ใช้ฟอร์มกลาง receipt_voucher (ตาราง รายการ/บาท/ส.ต.
    จำนวนเงินตัวอักษร ช่องลงชื่อผู้รับเงิน/ผู้จ่ายเงิน) แบบเดียวกับงานพัสดุ
      รายการจ่าย  ผู้รับเงิน = ผู้รับจ้าง/ร้านของรอบนั้น  ผู้จ่ายเงิน = เจ้าหน้าที่โครงการอาหารกลางวัน
      รายการรับ   ผู้รับเงิน = เจ้าหน้าที่การเงิน ในนามโรงเรียน  ได้รับเงินจาก = อปท.ผู้จัดสรร
  - ใบเสร็จรับเงิน (รายการรับ) โรงเรียนออกให้ อปท. เมื่อรับเงินอุดหนุน ต้นฉบับ + สำเนา
"""
from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.shared import Cm

from app.database import get_data_dir
from app.services.build_templates import _font, _p, _set_cell, _sign_table
from app.services.doc_page import set_a4
from app.services.receipt_voucher import _fixed_grid, _split_satang, render_receipt_voucher
from app.thai_utils import bahttext, thai_date

_DOT = "..........................................."


def _safe(text: str) -> str:
    from app.services.filenames import fit_name
    return fit_name(_safe_chars(text))


def _safe_chars(text: str) -> str:
    for ch in '<>:"/\\|?*\n\r\t':
        text = text.replace(ch, "_")
    return " ".join(text.split()).strip()


def _org(program):
    return (getattr(program, "funding_org", "") or "").strip() or "องค์กรปกครองส่วนท้องถิ่น"


def _finance_officer(school):
    return ((getattr(school, "finance_officer_name", "") or "").strip()
            or (getattr(school, "officer_name", "") or "").strip())


def _lunch_officer(school, program):
    return ((getattr(program, "lunch_officer", "") or "").strip() or _finance_officer(school))


def _detail(ledger):
    return (ledger.detail or "").strip() or ("เงินอุดหนุนโครงการอาหารกลางวัน" if ledger.kind == "in"
                                             else "ค่าใช้จ่ายโครงการอาหารกลางวัน")


def render_ledger_voucher(school, program, ledger, vendor=None) -> str:
    """ใบสำคัญรับเงินของรายการรับหรือจ่าย 1 รายการ (ฟอร์มกลางแบบเดียวกับงานพัสดุ)
    vendor = ผู้รับจ้าง/ร้านของรอบที่สร้างรายการจ่ายนี้ (route หาให้จาก round_id/installment_id)"""
    sname = (school.name or "").strip()
    item = [(_detail(ledger) + (f" (อ้างอิง {ledger.ref})" if (ledger.ref or "").strip() else ""),
             ledger.amount or 0)]
    if ledger.kind == "in":
        officer = _finance_officer(school)
        return render_receipt_voucher(
            school, payee=f"{officer or _DOT} เจ้าหน้าที่การเงิน ในนาม{sname}", payee_sign=officer or None,
            items=item, date=ledger.date, received_from=_org(program), payer="",
            subject=f"รับเงินอาหารกลางวัน_{ledger.id}")
    v = vendor
    return render_receipt_voucher(
        school, payee=(v.name if v else ""), payee_address=(v.address if v else "") or "",
        items=item, date=ledger.date, received_from=sname, payer=_lunch_officer(school, program),
        subject=f"จ่ายเงินอาหารกลางวัน_{ledger.id}")


def _official_receipt_page(doc, school, program, ledger, copy_label):
    sname = (school.name or "").strip()
    addr = " ".join(x for x in [(school.address or "").strip(),
                                (f"อำเภอ{school.district}" if (school.district or "").strip() else ""),
                                (f"จังหวัด{school.province}" if (school.province or "").strip() else "")] if x)
    _p(doc, copy_label, align="right", size=14, after=0)
    _p(doc, "ใบเสร็จรับเงิน", align="center", bold=True, size=22, after=2)
    _p(doc, sname or _DOT, align="center", bold=True, size=16, after=0)
    if addr:
        _p(doc, addr, align="center", size=14, after=6)
    ref = (ledger.ref or "").strip()
    t = doc.add_table(rows=1, cols=2)
    _set_cell(t.rows[0].cells[0], "เล่มที่ ....................", size=16)
    _set_cell(t.rows[0].cells[1], f"เลขที่ {ref or '....................'}", align="right", size=16)
    _p(doc, f"วันที่ {thai_date(ledger.date) if ledger.date else _DOT}", align="right", before=4, after=8)
    _p(doc, f"ได้รับเงินจาก  {_org(program)}", after=2, indent=0.5)
    _p(doc, "ดังรายการต่อไปนี้", after=6, indent=0.5)

    tbl = doc.add_table(rows=2, cols=4)
    tbl.style = "Table Grid"; tbl.autofit = False
    wcm = [1.4, 9.6, 3.0, 1.5]
    _fixed_grid(tbl, wcm)
    h0, h1 = tbl.rows[0].cells, tbl.rows[1].cells
    for i, txt in ((0, "ลำดับ"), (1, "รายการ")):
        c = h0[i].merge(h1[i]); _set_cell(c, txt, bold=True, align="center", size=15)
        c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    c = h0[2].merge(h0[3]); _set_cell(c, "จำนวนเงิน", bold=True, align="center", size=15)
    _set_cell(h1[2], "บาท", bold=True, align="center", size=14)
    _set_cell(h1[3], "ส.ต.", bold=True, align="center", size=14)
    amount = round(float(ledger.amount or 0), 2)
    rows = [("1", _detail(ledger), amount)] + [("", "", None)] * 4
    for no, name, amt in rows:
        cells = tbl.add_row().cells
        b, s = _split_satang(amt) if amt is not None else ("", "")
        _set_cell(cells[0], no, align="center", size=14)
        _set_cell(cells[1], name, size=14)
        _set_cell(cells[2], b, align="right", size=14)
        _set_cell(cells[3], s, align="right", size=14)
    b, s = _split_satang(amount)
    cells = tbl.add_row().cells
    m = cells[0].merge(cells[1]); _set_cell(m, "รวมเงิน", bold=True, align="right", size=14)
    _set_cell(cells[2], b, bold=True, align="right", size=14)
    _set_cell(cells[3], s, bold=True, align="right", size=14)
    for row in tbl.rows:
        for cell, w in zip(row.cells, wcm):
            cell.width = Cm(w)
    _p(doc, f"จำนวนเงิน (ตัวอักษร)  {bahttext(amount)}", bold=True, before=6, after=20, indent=0.5)
    officer = _finance_officer(school)
    _sign_table(doc, [
        [("", "center")],
        [(f"ลงชื่อ {_DOT} ผู้รับเงิน", "center"),
         (f"( {officer or _DOT} )", "center"),
         ("ตำแหน่ง เจ้าหน้าที่การเงิน", "center")],
    ])


def render_official_receipt(school, program, ledger) -> str:
    """ใบเสร็จรับเงินที่โรงเรียนออกให้ อปท. เมื่อรับเงินอุดหนุนอาหารกลางวัน · ต้นฉบับ + สำเนา (คนละหน้า)"""
    doc = Document(); set_a4(doc); _font(doc)
    _official_receipt_page(doc, school, program, ledger, "ต้นฉบับ")
    doc.add_page_break()
    _official_receipt_page(doc, school, program, ledger, "สำเนา")
    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    out = out_dir / (_safe(f"ใบเสร็จรับเงินอาหารกลางวัน_{ledger.id}") + ".docx")
    doc.save(str(out))
    return str(out)


def render_lunch_receipt(school, program, ledger, vendor=None) -> str:
    """ชื่อเดิม (เรียกจาก route เดิม) = ใบสำคัญรับเงินแบบใหม่"""
    return render_ledger_voucher(school, program, ledger, vendor)
