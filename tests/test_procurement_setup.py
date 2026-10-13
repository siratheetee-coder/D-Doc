# -*- coding: utf-8 -*-
"""รายการเริ่มต้นงานพัสดุ บนหน้าหลักพัสดุ (แบบเดียวกับงานการเงิน ใช้กล่องเดียวกัน)

ติ๊กจากข้อมูลจริง ขั้นถัดไปขั้นเดียวพร้อมปุ่ม ครบแล้วหาย
ขั้นที่ 1 แทนกล่องเตือน "ยังตั้งค่าโรงเรียนไม่ครบ" เดิม ไม่ให้เตือนซ้ำสองที่
รัน: .venv\Scripts\python.exe -m pytest tests/test_procurement_setup.py
"""
import re

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import Person, Procurement, ProcurementPlan, School, Vendor

FY = 2570


def _next_step(html):
    m = re.search(r'class="fs-step is-next">.*?class="fs-name">(\d)\. ([^<]+)<', html, re.S)
    return (int(m.group(1)), m.group(2).strip()) if m else None


def test_checklist_walks_through_the_steps_in_order(env):
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    page = lambda: env.get(f'/procurement?year={FY}').text          # noqa: E731
    with tn.session_for(sid) as s:                                # เริ่มจากโรงเรียนที่ยังไม่กรอกอะไร
        sc = s.query(School).first()
        for k in ('director_name', 'officer_name', 'head_officer_name'):
            setattr(sc, k, '')
        s.query(Person).delete(); s.query(Vendor).delete()
        s.query(ProcurementPlan).delete(); s.query(Procurement).delete(); s.commit()

    html = page()
    assert 'เริ่มต้นงานพัสดุ' in html and _next_step(html) == (1, 'กรอกข้อมูลโรงเรียนและผู้ลงนาม')
    assert 'ยังไม่ได้กรอก: ชื่อผู้อำนวยการ, เจ้าหน้าที่พัสดุ, หัวหน้าเจ้าหน้าที่พัสดุ' in html
    assert 'ยังตั้งค่าโรงเรียนไม่ครบ</b>' not in html, "กล่องเตือนเดิมต้องไม่ขึ้นซ้ำ"

    with tn.session_for(sid) as s:
        sc = s.query(School).first()
        sc.director_name, sc.officer_name, sc.head_officer_name = 'นายผอ', 'นายพัสดุ', 'นางหัวหน้า'
        s.commit()
    html = page()
    assert _next_step(html) == (2, 'เพิ่มรายชื่อบุคลากร') and 'ยังไม่มีรายชื่อ' in html

    with tn.session_for(sid) as s:                      # เจ้าของเลือก: อย่างน้อย 1 คนก็พอ
        s.add(Person(name='ครูหนึ่ง')); s.commit()
    assert _next_step(page()) == (3, 'เพิ่มผู้ขายหรือผู้รับจ้าง')

    with tn.session_for(sid) as s:
        s.add(Vendor(name='ร้านเครื่องเขียน')); s.commit()
    html = page()
    assert _next_step(html) == (4, f'ทำแผนจัดซื้อจัดจ้างปีงบ {FY}') and f'/procurement/plan?year={FY}' in html

    with tn.session_for(sid) as s:
        s.add(ProcurementPlan(fiscal_year=FY, seq=1, name='วัสดุสำนักงาน', budget=30000)); s.commit()
    html = page()
    assert _next_step(html) == (5, 'ทำเรื่องจัดซื้อจัดจ้างเรื่องแรก') and '/procurement/wizard' in html

    with tn.session_for(sid) as s:
        s.add(Procurement(fiscal_year=FY, subject='ซื้อกระดาษ')); s.commit()
    assert 'id="setup-proc"' not in page(), "ครบทุกขั้นแล้วกล่องต้องหายเอง"


def test_finance_and_procurement_remember_hiding_separately(env):
    import app.tenancy as tn
    with tn.session_for(next(iter(tn._engines))) as s:
        s.query(Vendor).delete(); s.commit()
    html = env.get(f'/procurement?year={FY}').text
    assert "var KEY = 'setupHidden_proc'" in html
    assert "var KEY = 'setupHidden_fin'" in env.get(f'/finance?year={FY}').text
