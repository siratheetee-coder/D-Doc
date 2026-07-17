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
from app.modules import MODULE_KEYS, MODULE_LABELS, MODULE_PRICE_KEY, module_for_path
from app.seller_config import pricing_context


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

def my_modules(tenant_id=None) -> set:
    """งานที่โรงเรียนนี้ "ซื้อแล้ว" (ไม่ใช่งานที่เข้าได้ — งานที่ยังไม่ซื้ออาจเข้าได้ด้วยโควตาทดลอง)"""
    try:
        from app.accounts import tenant_modules
        if tenant_id is None:
            from app.tenancy import current_school_id
            tenant_id = current_school_id.get()
        return tenant_modules(tenant_id)
    except Exception:
        return set()


def can_use(tenant_id, module) -> bool:
    """เข้าใช้งานนี้ได้ไหม = ซื้อแล้ว หรือ โควตาทดลองยังเหลือ (ตรรกะเดียวกับ middleware)"""
    try:
        from app.accounts import can_use_module
        return can_use_module(tenant_id, module)
    except Exception:
        return True


TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# โมดูลที่ "สร้างเสร็จแล้ว" ในระบบ (คนละเรื่องกับ "โรงเรียนนี้ซื้อหรือยัง" -> my_modules)
MODULES_LIVE = {"procurement": True, "admin": True, "finance": True, "lunch": True, "hr": True,
                "academic": True}

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
    my_modules=my_modules, can_use=can_use,
    module_labels=MODULE_LABELS, module_keys=MODULE_KEYS,
    module_price_key=MODULE_PRICE_KEY, module_for_path=module_for_path,
    # ตั้งชื่อ price_list ไม่ใช่ prices เพราะหลายหน้า (landing/checkout/guide) ส่ง key ชื่อ
    # "prices" (dict) เข้ามาเองผ่าน pricing_context() ซึ่งจะทับ global ตัวนี้จนเรียกใช้ไม่ได้
    price_list=lambda: pricing_context()["prices"],
)
