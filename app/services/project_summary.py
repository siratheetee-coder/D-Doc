# -*- coding: utf-8 -*-
"""
project_summary.py - รายงานสรุปการใช้งบประมาณรายโครงการ (Word / Excel)

ตอบคำถามที่ ผอ. ถามบ่อย: "ปีนี้แต่ละโครงการใช้งบไปเท่าไหร่ ทำอะไรไปบ้าง"
รูปแบบคล้าย สขร.1 (สรุปผลการจัดซื้อจัดจ้างรายเดือน) แต่จัดกลุ่มตาม "โครงการ"
แทนที่จะเรียงตามเดือน

ยอดใช้จริงใช้ตัวเดียวกับหน้าโครงการในระบบ (project_spent) จึงตรงกันเสมอ
"""
from datetime import datetime

from docx import Document
from docx.shared import Cm

from app.services.doc_page import set_a4
from app.database import get_data_dir
from app.thai_utils import thai_date, bahttext
from app.services.book_receipt_doc import _safe
from app.services.build_templates import (
    _font, _p, _set_cell, _repeat_header_row, _no_split_row, _fixed_cols, _sign_table,
)
from app.services.budget import project_budget, project_spent, project_procurements

_BLANK = "................................"


def _money(v) -> str:
    return f"{float(v or 0):,.2f}"


def build_rows(db, projects) -> list:
    """สรุปรายโครงการ + รายการจัดซื้อ/จัดจ้างที่เกิดขึ้นจริงในโครงการนั้น"""
    from app.models import DisburseMemo
    rows = []
    for p in projects:
        budget = project_budget(p)
        spent = project_spent(p)
        works = []
        for pr in sorted(project_procurements(p), key=lambda x: (x.request_date or datetime.min)):
            works.append({
                "date": pr.request_date, "no": pr.memo_no or "",
                "subject": f"{pr.proc_type or ''}{pr.subject or ''}".strip(),
                "method": pr.method or "", "amount": float(pr.total_amount or 0),
                "vendor": (pr.vendor.name if pr.vendor else ""),
                "status": pr.status or "",
            })
        # ขอเบิกจ่ายเดี่ยว (ไม่ได้ผ่านเรื่องจัดซื้อ) เช่น ค่าเดินทาง/ค่าตอบแทน
        for d in (db.query(DisburseMemo)
                  .filter(DisburseMemo.project_id == p.id,
                          DisburseMemo.procurement_id.is_(None))
                  .order_by(DisburseMemo.date).all()):
            works.append({
                "date": d.date, "no": d.memo_no or "", "subject": d.subject or "",
                "method": "เบิกจ่าย", "amount": float(d.amount or 0),
                "vendor": d.payee or "", "status": d.status or "",
            })
        works.sort(key=lambda w: (w["date"] or datetime.min))
        rows.append({
            "p": p, "name": p.name or "", "responsible": p.responsible or "",
            "budget": budget, "spent": spent, "left": round(budget - spent, 2),
            "pct": round(spent / budget * 100, 1) if budget else 0.0,
            "works": works,
        })
    return rows


# ------------------------------------------------------------------ Word
def render_project_summary(school, year, year_label, rows, *, detail=True, as_of=None) -> str:
    """detail=True แนบรายการงานของแต่ละโครงการด้วย · False = เฉพาะตารางสรุป
    as_of = วันที่ที่ตัดยอด (ไม่ระบุ = วันที่ออกรายงาน)"""
    doc = Document(); set_a4(doc, landscape=True); _font(doc)
    sname = (school.name or "โรงเรียน").strip()
    t_budget = sum(r["budget"] for r in rows)
    t_spent = sum(r["spent"] for r in rows)

    _p(doc, "รายงานสรุปการใช้งบประมาณรายโครงการ", align="center", bold=True, size=18, after=0)
    _p(doc, sname, align="center", bold=True, size=16, after=0)
    _p(doc, f"{year_label} {year}", align="center", size=15, after=0)
    _p(doc, f"ข้อมูล ณ วันที่ {thai_date(as_of or datetime.now())}",
       align="center", size=15, after=6)

    headers = ["ที่", "ชื่อโครงการ", "ผู้รับผิดชอบ", "งบที่ได้รับ", "ใช้ไป",
               "คงเหลือ", "ร้อยละที่ใช้", "จำนวนงาน"]
    widths = [Cm(1.1), Cm(7.6), Cm(4.2), Cm(3.0), Cm(3.0), Cm(3.0), Cm(2.4), Cm(2.4)]
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    _fixed_cols(t, widths)
    _repeat_header_row(t.rows[0]); _no_split_row(t.rows[0])
    for c, h, w in zip(t.rows[0].cells, headers, widths):
        _set_cell(c, h, bold=True, align="center", size=14)
        c.width = w
    aligns = ["center", "left", "left", "right", "right", "right", "right", "center"]
    for i, r in enumerate(rows, start=1):
        vals = [str(i), r["name"], r["responsible"], _money(r["budget"]), _money(r["spent"]),
                _money(r["left"]), f"{r['pct']:.1f}", str(len(r["works"]))]
        row = t.add_row(); _no_split_row(row)
        for c, v, w, al in zip(row.cells, vals, widths, aligns):
            _set_cell(c, v, align=al, size=14)
            c.width = w
    row = t.add_row(); _no_split_row(row)
    tot = ["", "รวมทั้งสิ้น", "", _money(t_budget), _money(t_spent),
           _money(t_budget - t_spent),
           f"{(t_spent / t_budget * 100) if t_budget else 0:.1f}",
           str(sum(len(r["works"]) for r in rows))]
    for c, v, w, al in zip(row.cells, tot, widths,
                           ["center", "right", "left", "right", "right", "right",
                            "right", "center"]):
        _set_cell(c, v, bold=True, align=al, size=14)
        c.width = w

    _p(doc, f"งบประมาณที่ได้รับรวม {_money(t_budget)} บาท ({bahttext(t_budget)}) · "
            f"ใช้ไป {_money(t_spent)} บาท ({bahttext(t_spent)}) · "
            f"คงเหลือ {_money(t_budget - t_spent)} บาท",
       before=8, after=8, size=15)

    if detail:
        for r in rows:
            if not r["works"]:
                continue
            doc.add_page_break()
            _p(doc, "รายการที่ดำเนินการ", align="center", bold=True, size=17, after=0)
            _p(doc, r["name"], align="center", bold=True, size=16, after=0)
            _p(doc, f"{sname} · {year_label} {year}", align="center", size=14, after=0)
            _p(doc, f"งบที่ได้รับ {_money(r['budget'])} บาท · ใช้ไป {_money(r['spent'])} บาท · "
                    f"คงเหลือ {_money(r['left'])} บาท", align="center", size=14, after=6)
            h2 = ["ที่", "วัน เดือน ปี", "เลขที่", "รายการ", "วิธี", "ผู้ขาย/ผู้รับจ้าง",
                  "จำนวนเงิน", "สถานะ"]
            w2 = [Cm(1.1), Cm(2.6), Cm(2.4), Cm(7.4), Cm(3.0), Cm(5.0), Cm(2.8), Cm(2.4)]
            t2 = doc.add_table(rows=1, cols=len(h2))
            t2.style = "Table Grid"
            _fixed_cols(t2, w2)
            _repeat_header_row(t2.rows[0]); _no_split_row(t2.rows[0])
            for c, h, w in zip(t2.rows[0].cells, h2, w2):
                _set_cell(c, h, bold=True, align="center", size=13)
                c.width = w
            sub = 0.0
            for i, wk in enumerate(r["works"], start=1):
                sub += wk["amount"]
                vals = [str(i), thai_date(wk["date"]) if wk["date"] else "", wk["no"],
                        wk["subject"], wk["method"], wk["vendor"], _money(wk["amount"]),
                        wk["status"]]
                row = t2.add_row(); _no_split_row(row)
                for c, v, w, al in zip(row.cells, vals, w2,
                                       ["center", "center", "center", "left", "left",
                                        "left", "right", "center"]):
                    _set_cell(c, v, align=al, size=13)
                    c.width = w
            row = t2.add_row(); _no_split_row(row)
            _set_cell(row.cells[3], "รวม", bold=True, align="right", size=13)
            _set_cell(row.cells[6], _money(sub), bold=True, align="right", size=13)
            for c, w in zip(row.cells, w2):
                c.width = w

    _p(doc, "", after=10)
    _sign_table(doc, [[
        ("ลงชื่อ.......................................ผู้จัดทำรายงาน", "center"),
        ("(.......................................)", "center"),
        ("เจ้าหน้าที่พัสดุ", "center"),
    ], [
        ("ลงชื่อ.......................................", "center"),
        (f"( {(school.director_name or '').strip() or _BLANK} )", "center"),
        ("ผู้อำนวยการ" + (sname if sname.startswith("โรงเรียน") else "โรงเรียน"), "center"),
    ]])

    out = get_data_dir() / "documents"
    out.mkdir(exist_ok=True)
    path = out / (_safe(f"สรุปการใช้งบประมาณรายโครงการ_{year}") + ".docx")
    doc.save(str(path))
    return str(path)


# ------------------------------------------------------------------ Excel
def export_project_summary(school, year, year_label, rows) -> str:
    """ไฟล์ Excel: ชีตสรุป + ชีตรายการทั้งหมด (กรองต่อเองได้)"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2563EB")
    money = "#,##0.00"

    def head(ws, titles, widths):
        ws.append(titles)
        for i, (t, w) in enumerate(zip(titles, widths), start=1):
            cell = ws.cell(row=1, column=i)
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "A2"

    ws = wb.active
    ws.title = "สรุปรายโครงการ"
    head(ws, ["ที่", "ชื่อโครงการ", "ผู้รับผิดชอบ", "งบที่ได้รับ", "ใช้ไป", "คงเหลือ",
              "ร้อยละที่ใช้", "จำนวนงาน"], [6, 46, 22, 15, 15, 15, 12, 11])
    for i, r in enumerate(rows, start=1):
        ws.append([i, r["name"], r["responsible"], r["budget"], r["spent"], r["left"],
                   r["pct"], len(r["works"])])
    last = ws.max_row
    ws.append(["", "รวมทั้งสิ้น", "",
               sum(r["budget"] for r in rows), sum(r["spent"] for r in rows),
               sum(r["left"] for r in rows), "", sum(len(r["works"]) for r in rows)])
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=4, max_col=6):
        for c in row:
            c.number_format = money

    ws2 = wb.create_sheet("รายการทั้งหมด")
    head(ws2, ["โครงการ", "วันที่", "เลขที่", "รายการ", "วิธี", "ผู้ขาย/ผู้รับจ้าง",
               "จำนวนเงิน", "สถานะ"], [34, 13, 13, 44, 16, 28, 15, 13])
    for r in rows:
        for wk in r["works"]:
            ws2.append([r["name"], thai_date(wk["date"]) if wk["date"] else "", wk["no"],
                        wk["subject"], wk["method"], wk["vendor"], wk["amount"],
                        wk["status"]])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row, min_col=7, max_col=7):
        for c in row:
            c.number_format = money

    for sheet in (ws, ws2):
        sheet.insert_rows(1, 2)
        sheet["A1"] = f"รายงานสรุปการใช้งบประมาณรายโครงการ  {(school.name or '').strip()}"
        sheet["A2"] = f"{year_label} {year}  ·  ข้อมูล ณ วันที่ {thai_date(datetime.now())}"
        sheet["A1"].font = Font(bold=True, size=14)
        sheet.freeze_panes = "A4"

    out = get_data_dir() / "documents"
    out.mkdir(exist_ok=True)
    path = out / (_safe(f"สรุปการใช้งบประมาณรายโครงการ_{year}") + ".xlsx")
    wb.save(str(path))
    return str(path)
