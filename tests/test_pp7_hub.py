# -*- coding: utf-8 -*-
"""หน้ารวม ปพ.7 (ใบรับรองผลการศึกษา) + เมนูข้าง + การ์ดหน้าหลักวิชาการ

เดิมต้องเข้าไปหาในหน้าห้องเรียนแต่ละห้องเท่านั้น (เจ้าของขอให้มีหน้าของตัวเอง)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_pp7_hub.py
"""
import json

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import AcadCertificate, AcadClass, AcadStudent

Y = 2592


def _seed(sid):
    import app.tenancy as tn
    with tn.session_for(sid) as s:
        a = AcadClass(year=Y, level='ป.6', room='1'); b = AcadClass(year=Y, level='ป.6', room='2')
        s.add_all([a, b]); s.flush()
        x = AcadStudent(class_id=a.id, name='กัญญารัตน์ ทดสอบ', seq=1, student_no='1001')
        y = AcadStudent(class_id=b.id, name='ธีรภัทร ทดสอบ', seq=1)
        s.add_all([x, y]); s.flush()
        s.add(AcadCertificate(acad_student_id=x.id, number='ปพ7-ทดสอบ-1', payload=json.dumps({'name': x.name})))
        s.commit()
        return a.id, b.id, x.id, y.id


def test_hub_lists_class_search_and_recent(env):
    import app.tenancy as tn
    a, b, x, y = _seed(next(iter(tn._engines)))
    html = env.get(f'/academic/pp7?year={Y}&cid={a}').text
    assert 'กัญญารัตน์ ทดสอบ' in html and 'ธีรภัทร ทดสอบ' not in html
    assert f'href="/academic/student/{x}/pp7"' in html and '1 ฉบับ' in html
    assert 'ดาวน์โหลดฉบับล่าสุด' in html and 'ออกล่าสุด' in html and 'ปพ7-ทดสอบ-1' in html
    html = env.get(f'/academic/pp7?year={Y}&q=ธีรภัทร').text
    assert 'ธีรภัทร ทดสอบ' in html and 'ป.6/2' in html, 'ค้นชื่อข้ามห้อง และบอกว่าอยู่ห้องไหน'
    assert 'ไม่พบนักเรียนชื่อ' in env.get(f'/academic/pp7?year={Y}&q=ไม่มีคนนี้').text


def test_teacher_sees_only_homeroom_classes(env, monkeypatch):
    import app.tenancy as tn
    from app.routers import academic
    a, b, x, y = _seed(next(iter(tn._engines)))

    class Homeroom:
        is_teacher = True
        def can_homeroom(self, cid):
            return cid == a
    monkeypatch.setattr(academic, '_scope', lambda *args: Homeroom())
    html = env.get(f'/academic/pp7?year={Y}&q=ทดสอบ').text
    assert 'กัญญารัตน์ ทดสอบ' in html and 'ธีรภัทร ทดสอบ' not in html
    html = env.get(f'/academic/pp7?year={Y}&cid={b}').text
    assert 'ธีรภัทร ทดสอบ' not in html, 'ห้องที่ไม่ได้เป็นครูประจำชั้น ห้ามเห็น'


def test_menu_and_home_card_link_to_it(env):
    html = env.get('/academic').text
    assert 'class="nav-card" href="/academic/pp7"' in html
    assert '<a href="/academic/pp7"' in html, 'มีในเมนูข้าง'


def test_mode_toggle_puts_class_mode_first(env):
    html = env.get('/academic/attendance?mode=subject').text
    assert html.index('เช็คเวลาเรียนรายห้อง</a>') < html.index('เช็คชื่อรายวิชา</a>')
