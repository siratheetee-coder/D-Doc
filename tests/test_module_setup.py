# -*- coding: utf-8 -*-
"""รายการเริ่มต้นงานอาหารกลางวัน งานธุรการ งานบุคคล (กล่องเดียวกับการเงิน/พัสดุ/วิชาการ)

ติ๊กจากข้อมูลจริง ขั้นถัดไปขั้นเดียว บอกตรง ๆ ว่ายังขาดอะไร ครบแล้วหาย
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_module_setup.py
"""
import re
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)
from tests.test_academic_lessons import db  # noqa: F401  (fixture)
from app.models import (IncomingLetter, LunchClass, LunchHireRound, LunchMenu, LunchProgram,
                        OfficeMemo, Person, School)
from app.services import module_setup as ms


def _next(st):
    return st['next']['title'] if st['next'] else None


def test_lunch_steps_in_order(db):
    st = ms.lunch_steps(db, 2569)
    assert _next(st) == 'ตั้งโครงการปีการศึกษา 2569' and st['total'] == 5
    p = LunchProgram(year=2569, days=200, rate_per_head=0, operate_mode='hire'); db.add(p); db.flush()
    db.add(LunchClass(program_id=p.id, level='ป.1', num_students=120)); db.commit()
    assert _next(ms.lunch_steps(db, 2569)) == 'ใส่จำนวนนักเรียนและอัตราต่อหัว'
    p.rate_per_head = 36; db.commit()
    st = ms.lunch_steps(db, 2569)
    assert _next(st) == 'เลือกรูปแบบและผู้รับผิดชอบ' and 'งบทั้งปี 864,000.00 บาท' in st['steps'][1]['detail']
    assert 'อปท.ผู้จัดสรร' in st['next']['detail']
    p.funding_org, p.lunch_officer = 'อบต.ทดสอบ', 'ครูอาหาร'; db.commit()
    assert _next(ms.lunch_steps(db, 2569)) == 'เพิ่มรอบจัดจ้างแรก'
    db.add(LunchHireRound(program_id=p.id, seq=1)); db.commit()
    assert _next(ms.lunch_steps(db, 2569)) == 'ใส่เมนูอาหาร'
    db.add(LunchMenu(program_id=p.id, date=datetime(2026, 5, 18), main='ข้าวผัด')); db.commit()
    assert ms.lunch_steps(db, 2569)['complete']


def test_lunch_self_mode_skips_rounds_and_ingredient_says_purchase(db):
    p = LunchProgram(year=2569, operate_mode='self'); db.add(p); db.commit()
    assert all('รอบ' not in s['title'] for s in ms.lunch_steps(db, 2569)['steps'])
    p.operate_mode = 'ingredient'; db.commit()
    assert any(s['title'] == 'เพิ่มรอบจัดซื้อแรก' for s in ms.lunch_steps(db, 2569)['steps'])


def test_admin_steps(db):
    school = School(name='โรงเรียนทดสอบ', director_name='นายผอ', doc_prefix='ศธ'); db.add(school); db.commit()
    st = ms.admin_steps(db, school)
    assert _next(st) == 'กรอกข้อมูลโรงเรียนและผู้ลงนาม' and 'เจ้าหน้าที่ธุรการ' in st['next']['detail']
    school.admin_officer_name = 'นางธุรการ'; db.commit()
    st = ms.admin_steps(db, school)
    assert _next(st) == 'ตั้งอักษรนำเลขที่หนังสือ' and 'ศธ 04123' in st['next']['detail']
    school.doc_prefix = 'ศธ 04123'; db.commit()
    assert _next(ms.admin_steps(db, school)) == 'ลงรับหนังสือฉบับแรก'
    db.add(IncomingLetter(fiscal_year=2570, recv_no=1, subject='ทดสอบ')); db.commit()
    assert _next(ms.admin_steps(db, school)) == 'ออกหนังสือส่งหรือบันทึกข้อความ'
    db.add(OfficeMemo(fiscal_year=2570, subject='ทดสอบ')); db.commit()
    assert ms.admin_steps(db, school)['complete']


def test_hr_steps_find_the_director_signature_by_name(db):
    school = School(name='โรงเรียนทดสอบ', director_name='นายผอ ทดสอบ'); db.add(school); db.commit()
    assert _next(ms.hr_steps(db, school)) == 'เพิ่มทะเบียนบุคลากร'
    d = Person(name='นายผอ ทดสอบ', position='ผู้อำนวยการ'); db.add(d); db.commit()
    assert _next(ms.hr_steps(db, school)) == 'ตั้งอีเมลผู้อนุมัติ'
    school.director_email = 'director@example.com'; db.commit()
    st = ms.hr_steps(db, school)
    assert _next(st) == 'อัปโหลดลายเซ็นผู้อำนวยการ' and 'ยังไม่มีลายเซ็นของ นายผอ ทดสอบ' in st['next']['detail']
    d.signature = 'sig.png'; db.commit()
    assert ms.hr_steps(db, school)['complete']


def test_home_pages_show_the_lists(env):
    """โรงเรียนใหม่ยังตั้งค่าไม่ครบ ทั้งสามหน้าต้องมีกล่อง และซ่อนแยกกันรายงาน"""
    for url, key in [('/lunch', 'lunch'), ('/admin', 'admin'), ('/hr', 'hr')]:
        r = env.get(url)
        assert r.status_code == 200, url
        assert f'id="setup-{key}"' in r.text and f"var KEY = 'setupHidden_{key}'" in r.text, url
