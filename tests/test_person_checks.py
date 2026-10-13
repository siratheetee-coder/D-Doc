# -*- coding: utf-8 -*-
"""ทะเบียนบุคลากร: ข้อมูลรายคนครบหรือยัง (เจ้าของขอเช็กลิสต์รายคน)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_person_checks.py
"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import Person
from app.services.module_setup import person_checks

FULL = dict(position='ครู', rank='ครู คศ.1', id_card='1-2345-67890-12-3', birthdate=datetime(1990, 1, 1),
            start_date=datetime(2015, 5, 1), salary=30000, email='t@example.com', signature='s.png')


def _missing(p):
    return [c['label'] for c in person_checks(p) if not c['ok']]


def test_complete_teacher_has_nothing_missing():
    assert _missing(Person(name='ครู ก', person_type='ครู', **FULL)) == []


def test_reports_exactly_what_is_missing():
    p = Person(name='ครู ข', person_type='ครู', **{**FULL, 'id_card': '12345', 'email': '', 'signature': ''})
    assert _missing(p) == ['เลขบัตรประชาชน 13 หลัก', 'อีเมล', 'ลายเซ็น']


def test_rank_only_asked_for_teachers_and_executives():
    janitor = Person(name='นาย ค', person_type='นักการภารโรง', **{**FULL, 'rank': ''})
    assert 'วิทยฐานะ/ระดับ' not in [c['label'] for c in person_checks(janitor)]
    boss = Person(name='นาย ง', person_type='ผู้บริหาร', **{**FULL, 'rank': ''})
    assert _missing(boss) == ['วิทยฐานะ/ระดับ']


def test_staff_page_summary_chip_filter_and_edit_box(env):
    import app.tenancy as tn
    with tn.session_for(next(iter(tn._engines))) as s:
        s.query(Person).update({Person.active: False}); s.commit()
        a = Person(name='ครูครบ ทดสอบ', person_type='ครู', active=True, **FULL)
        b = Person(name='ครูไม่ครบ ทดสอบ', person_type='ครู', active=True, position='ครู')
        s.add_all([a, b]); s.commit(); aid, bid = a.id, b.id
    html = env.get('/hr/staff').text
    assert 'ข้อมูลบุคลากรครบ 1 จาก 2 คน' in html
    assert '<span class="ps-chip ok">ครบ</span>' in html and f'href="/hr/staff?edit={bid}#edit"' in html
    html = env.get('/hr/staff?incomplete=1').text
    assert 'ครูไม่ครบ ทดสอบ' in html and 'ครูครบ ทดสอบ' not in html
    html = env.get(f'/hr/staff?edit={bid}').text
    assert 'ข้อมูลของ ครูไม่ครบ ทดสอบ: ครบ 1 จาก 8 รายการ' in html and 'อัปโหลดลายเซ็น' in html
