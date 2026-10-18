# -*- coding: utf-8 -*-
"""รายการเริ่มต้นงานวิชาการ บนหน้าหลักวิชาการ (กล่องเดียวกับงานการเงิน/พัสดุ)

ติ๊กจากข้อมูลจริง ขั้นถัดไปขั้นเดียว บอกชื่อห้อง/ชั้นที่ยังไม่ครบ ครบแล้วหาย · ครูไม่เห็น
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_academic_setup.py
"""
import re
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)
from app.models import (AcadClass, AcadPeriod, AcadStudent, AcadSubject, AcadTeaching,
                        AcadTimetable, AcadYearSetting, Person)

Y = 2591


def _next_step(html):
    m = re.search(r'class="fs-step is-next">.*?class="fs-name">(\d)\. ([^<]+)<', html, re.S)
    return (int(m.group(1)), m.group(2).strip()) if m else None


def test_checklist_walks_through_the_steps_in_order(env, monkeypatch):
    import app.tenancy as tn
    import app.accounts as accounts
    monkeypatch.setattr(accounts, 'list_teacher_accounts', lambda tid: [])
    sid = next(iter(tn._engines))
    page = lambda: env.get(f'/academic?year={Y}').text          # noqa: E731

    html = page()
    assert f'เริ่มต้นงานวิชาการ ปีการศึกษา {Y}' in html
    assert _next_step(html) == (1, 'ตั้งปฏิทินปีการศึกษา') and f'/academic/calendar?year={Y}' in html

    with tn.session_for(sid) as s:
        s.add(AcadYearSetting(year=Y, t1_start=datetime(2048, 5, 16), t1_end=datetime(2048, 10, 9),
                              t2_start=datetime(2048, 11, 1), t2_end=datetime(2049, 3, 31)))
        a = AcadClass(year=Y, level='ป.1', room='1'); b = AcadClass(year=Y, level='ป.1', room='2')
        s.add_all([a, b]); s.flush()
        s.add(AcadStudent(class_id=a.id, name='นักเรียนหนึ่ง', seq=1)); s.commit()
        cids = (a.id, b.id)
    html = page()
    assert _next_step(html) == (2, 'สร้างห้องเรียนและดึงนักเรียน') and 'ยังไม่มีนักเรียน: ป.1/2' in html

    with tn.session_for(sid) as s:
        s.add(AcadStudent(class_id=cids[1], name='นักเรียนสอง', seq=1))
        t = Person(name='ครูทดสอบวิชาการ'); s.add(t); s.flush()
        s.get(AcadClass, cids[0]).homeroom_id = t.id; s.commit()
        tid_ = t.id
    html = page()
    assert _next_step(html) == (3, 'เลือกครูประจำชั้น') and 'ยังไม่เลือก: ป.1/2' in html

    with tn.session_for(sid) as s:
        s.get(AcadClass, cids[1]).homeroom_id = tid_; s.commit()
    assert _next_step(page()) == (4, 'สร้างรายวิชา')

    with tn.session_for(sid) as s:
        subj = AcadSubject(year=Y, level='ป.1', name='ภาษาไทย', code='ท11101', hours=200); s.add(subj); s.flush()
        s.add(AcadTeaching(class_id=cids[0], subject_id=subj.id, teacher_id=tid_)); s.commit()
        subj_id = subj.id
    html = page()
    assert _next_step(html) == (5, 'กำหนดครูผู้สอน') and 'ยังไม่มีครูผู้สอน 1 จาก 2 วิชา-ห้อง' in html

    with tn.session_for(sid) as s:
        s.add(AcadTeaching(class_id=cids[1], subject_id=subj_id, teacher_id=tid_)); s.commit()
    html = page()
    assert _next_step(html) == (6, 'สร้างบัญชีครู'), "ไอดีหลักเห็นขั้นบัญชีครู"

    monkeypatch.setattr(accounts, 'list_teacher_accounts', lambda tid: [{'id': 1}])
    html = page()
    assert _next_step(html) == (7, 'ตั้งตารางเรียน (ข้ามได้ถ้ากรอกวันสอนเอง)') and 'ป.1/1, ป.1/2' in html

    with tn.session_for(sid) as s:
        p = AcadPeriod(year=Y, seq=1, name='คาบ 1', time_label='08:30-09:30', is_break=False); s.add(p); s.flush()
        for c in cids:
            s.add(AcadTimetable(class_id=c, subject_id=subj_id, period_id=p.id, day=1))
        s.commit()
    assert 'id="setup-acad"' not in page(), "ครบทุกขั้นแล้วกล่องต้องหายเอง"


def test_teachers_do_not_see_the_setup_list(env, monkeypatch):
    from app.routers import academic

    class Teacher:
        is_teacher = True
        class_ids, subject_ids, teach_pairs = set(), set(), set()
    monkeypatch.setattr(academic, '_scope', lambda *a: Teacher())
    monkeypatch.setattr(academic, '_teacher_todo', lambda *a: None)
    r = env.get(f'/academic?year={Y}')
    assert r.status_code == 200 and 'งานวิชาการ' in r.text
    assert 'id="setup-acad"' not in r.text
