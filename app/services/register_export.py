"""
register_export.py
------------------
ส่งออก 'ทะเบียนคุมการจัดซื้อจัดจ้าง' เป็นไฟล์ Excel (.xlsx)
"""
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

from app.database import get_data_dir
from app.thai_utils import thai_date

THAI_FONT = "TH Sarabun New"


# ชื่อเล่มทะเบียนตามชนิด (kind)
_REGISTER_LABEL = {
    "buy": "ทะเบียนคุมการจัดซื้อ",
    "hire": "ทะเบียนคุมการจัดจ้าง",
    "all": "ทะเบียนคุมการจัดซื้อจัดจ้าง",
}


def export_register(procurements, fiscal_year: int, kind: str = "all") -> str:
    """สร้างไฟล์ Excel ทะเบียนคุม คืนค่าที่อยู่ไฟล์
    kind: all = รวม, buy = เฉพาะจัดซื้อ, hire = เฉพาะจัดจ้าง (แยกเล่ม)"""
    label = _REGISTER_LABEL.get(kind, _REGISTER_LABEL["all"])
    wb = Workbook()
    ws = wb.active
    ws.title = f"{label} {fiscal_year}"[:31]   # ชื่อชีต Excel จำกัด 31 ตัว

    # หัวกระดาษ (ชื่อเล่ม + ปีงบ) เหนือหัวตาราง
    ws.append([f"{label}  ประจำปีงบประมาณ {fiscal_year}"])
    ws.append([])

    headers = ["เลขที่", "วันที่", "เรื่อง", "ประเภท", "วิธี",
               "วงเงิน (บาท)", "ผู้ขาย/ผู้รับจ้าง", "สถานะ"]
    ws.append(headers)

    thin = Side(style="thin")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    header_fill = PatternFill("solid", fgColor="D9E1F2")
    n_col = len(headers)
    HEADER_ROW = 3   # แถวที่ 1 = ชื่อเล่ม, 2 = ว่าง, 3 = หัวตาราง, 4+ = ข้อมูล

    # ชื่อเล่ม (แถว 1) ผสานเซลล์ + จัดกึ่งกลาง
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_col)
    title_cell = ws.cell(row=1, column=1)
    title_cell.font = Font(name=THAI_FONT, bold=True, size=18)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")

    # หัวตาราง (แถว 3)
    for col in range(1, n_col + 1):
        cell = ws.cell(row=HEADER_ROW, column=col)
        cell.font = Font(name=THAI_FONT, bold=True, size=14)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
        cell.fill = header_fill

    # เติมข้อมูล (เลขที่ = เลขใบสั่งซื้อ/จ้าง ถ้ายังไม่มีใช้เลขบันทึก)
    for p in procurements:
        ws.append([
            (p.order_no or "").strip() or p.doc_no or "-",
            thai_date(p.order_date or p.request_date),
            p.subject,
            p.proc_type,
            p.method,
            p.total_amount or 0,
            p.vendor.name if p.vendor else "-",
            p.status,
        ])

    # จัดรูปทุกเซลล์ข้อมูล + กำหนดความกว้างคอลัมน์
    widths = [10, 16, 36, 10, 14, 16, 26, 14]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[chr(64 + i)].width = w
    for row in ws.iter_rows(min_row=HEADER_ROW + 1):
        for cell in row:
            cell.font = Font(name=THAI_FONT, size=14)
            cell.border = border
            # wrap_text: ข้อความยาว (เรื่อง/ผู้ขาย) ขึ้นบรรทัดใหม่ในช่อง ไม่ถูกตัด
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        row[5].number_format = "#,##0.00"  # คอลัมน์วงเงิน

    out_dir = get_data_dir() / "documents"
    out_dir.mkdir(exist_ok=True)
    suffix = {"buy": "จัดซื้อ", "hire": "จัดจ้าง"}.get(kind, "จัดซื้อจัดจ้าง")
    path = out_dir / f"ทะเบียนคุม{suffix}_ปีงบ{fiscal_year}.xlsx"
    wb.save(str(path))
    return str(path)
