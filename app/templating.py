# -*- coding: utf-8 -*-
"""
templating.py
-------------
ตัว Jinja2Templates กลางตัวเดียวที่ทุก router ใช้ร่วมกัน (พัสดุ/ธุรการ/การเงิน)
พร้อมลงทะเบียน global helper ให้เรียกในเทมเพลตได้ทุกหน้า

แยกออกมาเพื่อเลี่ยง circular import (router หลายตัว import templates ตัวเดียวกันได้)
"""
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.thai_utils import thai_date, bahttext, be_date_input
from app.services.asset_utils import (
    accumulated_depreciation, net_book_value, annual_depreciation, material_balance,
    account_balance, account_balance_year, opening_for,
)
from app.services.nav import nav_alerts, nav_holidays
from app.services.budget import project_budget, project_spent, project_remaining


def account_status(tenant_id=None):
    """สถานะแพ็กเกจของโรงเรียน (ส่ง tenant_id จาก request.session — เชื่อถือได้ตอนเรนเดอร์)
    ถ้าไม่ส่ง จะลองอ่านจาก contextvar (อาจว่างตอน render lazy) หรือคืน None"""
    try:
        from app.accounts import tenant_status
        if tenant_id is None:
            from app.tenancy import current_school_id
            tenant_id = current_school_id.get()
        return tenant_status(tenant_id)
    except Exception:
        return None

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# โมดูลที่เปิดใช้งานแล้ว (เปิดทีละเฟส: พัสดุ -> ธุรการ -> การเงิน)
MODULES_LIVE = {"procurement": True, "admin": True, "finance": True, "lunch": True}

# global helper ใช้ได้ทุกเทมเพลต
templates.env.globals.update(
    thai_date=thai_date, bahttext=bahttext, be_date=be_date_input,
    nav_alerts=nav_alerts, nav_holidays=nav_holidays,
    accum_dep=accumulated_depreciation, nbv=net_book_value,
    annual_dep=annual_depreciation, mat_balance=material_balance,
    acct_balance=account_balance, acct_balance_year=account_balance_year,
    acct_opening=opening_for,
    proj_budget=project_budget, proj_spent=project_spent, proj_remaining=project_remaining,
    modules_live=MODULES_LIVE, account_status=account_status,
)
