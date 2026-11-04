# -*- coding: utf-8 -*-
"""ทะเบียนคุมโครงการรายเดือน: ทุกโครงการในตารางเดียว จ่ายจริงแยกเดือน (แบบที่ FinVouch มี เจ้าของขอ)

เดือนเดินตามช่วงเวลาของแผน แผนปีงบ ต.ค. ถึง ก.ย. แผนปีการศึกษา พ.ค. ถึง เม.ย. (หรือตามที่โรงเรียนตั้ง)
ตัวเลขมาจาก project_money_summary ชุดเดียวกับหน้าโครงการ จึงบวกกันลงตัวเสมอ
  ก่อนเริ่มระบบ + จ่ายรายเดือน + จ่ายนอกช่วงแผน + รอจ่าย = ใช้/กันงบ
"""
from datetime import date

_TH = ["", "ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.", "พ.ค.", "มิ.ย.", "ก.ค.", "ส.ค.", "ก.ย.", "ต.ค.", "พ.ย.", "ธ.ค."]


def months_of(start, end) -> list:
    """[(ปี ค.ศ., เดือน, ป้าย)] ตั้งแต่เดือนของวันเริ่มถึงเดือนของวันสิ้นสุด"""
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month) and len(out) < 24:
        out.append((y, m, f"{_TH[m]} {str(y + 543)[2:]}"))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def build(db, year, projects) -> dict:
    from app.services.budget import project_budget, project_money_summary
    from app.services.project_realign import plan_range
    start, end = plan_range(db, year)
    months = months_of(start, end)
    keys = [(y, m) for y, m, _ in months]
    half = (len(keys) + 1) // 2
    rows = []
    for p in projects:
        money = project_money_summary(p)
        vals = [round(money["by_month"].get(k, 0.0), 2) for k in keys]
        other = round(sum(v for k, v in money["by_month"].items() if k not in keys), 2)
        budget = round(project_budget(p), 2)
        rows.append(dict(p=p, dept=(p.responsible or "").strip() or "ไม่ระบุฝ่าย", budget=budget,
                         before=money["before"], months=vals, other=other, waiting=money["waiting"],
                         h1=round(sum(vals[:half]), 2), h2=round(sum(vals[half:]), 2),
                         used=money["used"], left=round(budget - money["used"], 2)))
    groups = {}
    for r in rows:
        groups.setdefault(r["dept"], []).append(r)

    def total(rs):
        n = len(keys)
        return dict(budget=round(sum(r["budget"] for r in rs), 2), before=round(sum(r["before"] for r in rs), 2),
                    months=[round(sum(r["months"][i] for r in rs), 2) for i in range(n)],
                    other=round(sum(r["other"] for r in rs), 2), waiting=round(sum(r["waiting"] for r in rs), 2),
                    h1=round(sum(r["h1"] for r in rs), 2), h2=round(sum(r["h2"] for r in rs), 2),
                    used=round(sum(r["used"] for r in rs), 2), left=round(sum(r["left"] for r in rs), 2))
    return dict(months=months, half=half, start=start, end=end,
                groups=[dict(name=k, rows=v, total=total(v)) for k, v in sorted(groups.items())],
                total=total(rows), has_other=any(r["other"] for r in rows))


def xlsx(school_name, year_label, year, data):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook(); ws = wb.active; ws.title = "ทะเบียนคุมโครงการ"
    mlabels = [lb for _, _, lb in data["months"]]
    head = (["ที่", "ฝ่าย / โครงการ", "งบตามแผน", "ก่อนเริ่มระบบ"] + mlabels
            + (["นอกช่วงแผน"] if data["has_other"] else []) + ["6 เดือนแรก", "6 เดือนหลัง", "รอจ่าย", "ใช้/กันงบ", "คงเหลือ"])
    ws.append([f"ทะเบียนคุมโครงการรายเดือน {year_label} {year} {school_name}"])
    ws.append(head)
    bold, fill = Font(bold=True), PatternFill("solid", fgColor="EDE9FE")

    def line(no, name, d, strong=False):
        vals = ([no, name, d["budget"], d["before"]] + list(d["months"]) + ([d["other"]] if data["has_other"] else [])
                + [d["h1"], d["h2"], d["waiting"], d["used"], d["left"]])
        ws.append(vals)
        if strong:
            for cell in ws[ws.max_row]:
                cell.font = bold; cell.fill = fill
    n = 0
    for g in data["groups"]:
        ws.append(["", g["name"]]); ws[ws.max_row][1].font = bold
        for r in g["rows"]:
            n += 1
            line(n, r["p"].name, r)
        line("", f"รวม {g['name']}", g["total"], True)
    line("", "รวมทั้งสิ้น", data["total"], True)
    for cell in ws[2]:
        cell.font = bold; cell.fill = fill; cell.alignment = Alignment(horizontal="center", wrap_text=True)
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 5; ws.column_dimensions["B"].width = 42
    for i in range(3, len(head) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 12
        for row in ws.iter_rows(min_row=3, min_col=i, max_col=i):
            row[0].number_format = '#,##0.00'
    ws.freeze_panes = "C3"
    return wb
