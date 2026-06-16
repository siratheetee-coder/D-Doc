# -*- coding: utf-8 -*-
"""
asset_export.py — ส่งออกทะเบียนครุภัณฑ์ (+ค่าเสื่อมราคา) เป็น Excel (.xlsx)
"""
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

from app.database import get_data_dir
from app.thai_utils import thai_date
from app.services.asset_utils import (
    annual_depreciation, accumulated_depreciation, net_book_value,
)

THAI_FONT = "TH Sarabun New"
_thin = Side(style="thin")
_BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
_HEAD = PatternFill("solid", fgColor="E8F0FF")


def export_asset_register(assets) -> str:
    wb = Workbook()
    ws = wb.active
    ws.title = "ทะเบียนครุภัณฑ์"
    today = date.today()

    ws.append([f"ทะเบียนคุมครุภัณฑ์ (คำนวณค่าเสื่อม ณ {thai_date(today)})"])
    ws.append([])
    headers = ["เลขครุภัณฑ์", "ชื่อครุภัณฑ์", "ประเภท", "วันที่ได้มา", "ราคาทุน",
               "อายุ (ปี)", "มูลค่าซาก", "ค่าเสื่อม/ปี", "ค่าเสื่อมสะสม", "มูลค่าสุทธิ",
               "สถานที่/ผู้รับผิดชอบ", "แหล่งเงิน", "ผู้ขาย", "สถานะ"]
    ws.append(headers)
    n = len(headers)
    HEAD_ROW = 3

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n)
    t = ws.cell(row=1, column=1)
    t.font = Font(name=THAI_FONT, bold=True, size=18)
    t.alignment = Alignment(horizontal="center", vertical="center")
    for col in range(1, n + 1):
        c = ws.cell(row=HEAD_ROW, column=col)
        c.font = Font(name=THAI_FONT, bold=True, size=14)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = _BORDER; c.fill = _HEAD

    tot_cost = tot_acc = tot_nbv = 0.0
    for a in assets:
        ann = annual_depreciation(a.cost, a.salvage_value, a.useful_life)
        acc = accumulated_depreciation(a.cost, a.salvage_value, a.useful_life, a.acquired_date, today)
        nbv = net_book_value(a.cost, a.salvage_value, a.useful_life, a.acquired_date, today)
        tot_cost += (a.cost or 0); tot_acc += acc; tot_nbv += nbv
        ws.append([
            a.asset_code or "", a.name, a.category or "", thai_date(a.acquired_date) if a.acquired_date else "",
            a.cost or 0, a.useful_life or 0, a.salvage_value or 0, ann, acc, nbv,
            a.location or "", a.funding_source or "", a.vendor_name or "", a.status or "",
        ])
    ws.append(["", "", "", "รวม", tot_cost, "", "", "", round(tot_acc, 2), round(tot_nbv, 2), "", "", "", ""])

    widths = [16, 26, 18, 14, 13, 9, 11, 11, 13, 13, 22, 16, 20, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    money_cols = [5, 7, 8, 9, 10]
    for row in ws.iter_rows(min_row=HEAD_ROW + 1):
        for cell in row:
            cell.font = Font(name=THAI_FONT, size=14)
            cell.border = _BORDER
            cell.alignment = Alignment(vertical="center")
        for mc in money_cols:
            row[mc - 1].number_format = "#,##0.00"
    # แถวรวม ตัวหนา
    last = ws.max_row
    for col in range(1, n + 1):
        ws.cell(row=last, column=col).font = Font(name=THAI_FONT, bold=True, size=14)

    out_dir = get_data_dir() / "documents"; out_dir.mkdir(exist_ok=True)
    path = out_dir / "ทะเบียนครุภัณฑ์.xlsx"
    wb.save(str(path))
    return str(path)
