# -*- coding: utf-8 -*-
"""เวลาเรียนรายคาบ: ปฏิทินเลือกวันสอนใช้ปฏิทินปีการศึกษา + ลบคาบที่บันทึกผิดได้

เจ้าของแจ้ง: บันทึกวันแล้วลบวันที่เลือกไม่ได้ และอยากเห็นวันหยุดจากหน้าตั้งค่าปฏิทินปีการศึกษา
บั๊กที่เจอระหว่างตรวจ: เลือกวันของภาคเรียนที่ 2 ในหน้าภาคเรียนที่ 1 ได้ แล้วนับเป็นภาคเรียนที่ 1
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_lessons_calendar.py
"""
import json
import pathlib
import shutil
import subprocess
from datetime import date, datetime

import pytest

from app.models import AcadCalendar, AcadHoliday, AcadLesson, AcadLessonMark, AcadYearSetting
from app.services import academic_lessons as svc
from tests.test_academic_lessons import db, seed  # noqa: F401  (fixture)
from tests.test_subsidy import env  # noqa: F401  (fixture)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _terms(db, year=2569):
    db.add(AcadYearSetting(year=year, t1_start=datetime(2026, 5, 18), t1_end=datetime(2026, 10, 9),
                           t2_start=datetime(2026, 11, 2), t2_end=datetime(2027, 3, 31)))
    db.commit()


def test_day_info_marks_open_holiday_closed_and_terms(db):
    _terms(db)
    db.add(AcadHoliday(year=2569, month=7, day=28, name='วันเฉลิมพระชนมพรรษา'))
    db.add(AcadCalendar(year=2569, month=6, days_csv='1,2,3,4'))         # มิ.ย. เปิดแค่ 4 วัน
    db.commit()
    info = svc.day_info(db, 2569)
    assert info['2026-07-28'] == {'s': 'hol', 't': 1, 'n': 'วันเฉลิมพระชนมพรรษา'}
    assert info['2026-07-27']['s'] == 'open'                                 # จันทร์ เดือนที่ยังไม่ตั้ง ใช้ จ.-ศ.
    assert info['2026-07-25']['s'] == 'closed'                               # เสาร์
    assert info['2026-06-05']['s'] == 'closed', 'เดือนที่ตั้งปฏิทินไว้ ใช้วันที่ตั้งไว้'
    assert info['2026-05-11'] == {'s': 'off', 't': 0}                        # ก่อนเปิดภาคเรียน
    assert info['2026-11-02']['t'] == 2 and info['2027-01-05']['t'] == 2      # คร่อมปีปฏิทิน
    assert '2027-04-30' in info and '2027-05-01' not in info


def test_without_term_dates_nothing_is_blocked(db):
    info = svc.day_info(db, 2569)
    assert all(d['t'] is None for d in info.values()) and not any(d['s'] == 'off' for d in info.values())


def test_adding_a_day_from_the_other_term_is_refused(env):
    import app.tenancy as tn
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        c, subject, _ = seed(s); _terms(s)
        cid, sid = c.id, subject.id
    base = dict(cid=cid, sid=sid, term=1, slots=json.dumps([dict(name='คาบ 1', minutes=50)]))
    r = env.post('/academic/lessons/batch-add', data={**base, 'dates': json.dumps(['2026-11-03'])})
    assert 'อยู่ในภาคเรียนที่ 2 ไม่ใช่ภาคเรียนที่ 1' in r.text
    r = env.post('/academic/lessons/batch-add', data={**base, 'dates': json.dumps(['2026-05-12'])})
    assert 'อยู่นอกภาคเรียน' in r.text
    # วันหยุด/เสาร์ เพิ่มเป็นวันสอนชดเชยได้ (หน้าเว็บถามยืนยันก่อน)
    r = env.post('/academic/lessons/batch-add', data={**base, 'dates': json.dumps(['2026-07-25'])})
    assert 'เพิ่มแล้ว 1 คาบ' in r.text
    with tn.session_for(tid) as s:
        assert [x.term for x in svc.lessons_for(s, cid, sid)] == [1]


def test_marked_period_can_be_removed_after_confirming(env):
    import app.tenancy as tn
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        c, subject, student = seed(s)
        svc.add_lesson(s, c, subject, 1, date(2026, 5, 18), 'คาบ 1', 50)
        lid = svc.lessons_for(s, c.id, subject.id)[0].id
        s.add(AcadLessonMark(lesson_id=lid, acad_student_id=student.id, mark='/')); s.commit()
        cid, sid = c.id, subject.id
    args = dict(cid=cid, sid=sid, term=1, lesson_id=lid, month='2026-05')
    r = env.post('/academic/lessons/remove', data=args)
    assert 'มีผลเช็คชื่อแล้ว' in r.text
    with tn.session_for(tid) as s:
        assert s.get(AcadLesson, lid) is not None, 'ยังไม่ยืนยัน ห้ามลบ'
    r = env.post('/academic/lessons/remove', data={**args, 'force': '1'}, follow_redirects=False)
    assert r.status_code == 303 and 'month=2026-05' in r.headers['location']
    with tn.session_for(tid) as s:
        assert s.get(AcadLesson, lid) is None
        assert s.query(AcadLessonMark).filter_by(lesson_id=lid).count() == 0


def test_page_sends_calendar_and_flags_periods_on_holidays(env):
    import app.tenancy as tn
    tid = next(iter(tn._engines))
    with tn.session_for(tid) as s:
        c, subject, _ = seed(s)
        s.add(AcadHoliday(year=2569, month=7, day=28, name='วันเฉลิมพระชนมพรรษา')); s.commit()
        svc.add_lesson(s, c, subject, 1, date(2026, 7, 28), 'คาบ 1', 50); s.commit()
        cid, sid = c.id, subject.id
    html = env.get(f'/academic/lessons?cid={cid}&sid={sid}&term=1&month=2026-07').text
    cfg = json.loads(html.split('id="lessonConfig" type="application/json">')[1].split('</script>')[0])
    assert cfg['days']['2026-07-28']['s'] == 'hol' and cfg['term'] == 1 and cfg['students'] == 1
    assert cfg['events'][0]['checked'] == 0 and 'id' in cfg['events'][0]
    assert 'class="lg-flag"' in html and 'วันเฉลิมพระชนมพรรษา' in html
    assert 'อ. 28 ก.ค.' in html, 'หัวตารางบอกวันในสัปดาห์และเดือนแบบสั้น'
    assert 'id="removeLesson"' in html and 'id="savedList"' in html


NODE = shutil.which('node')


@pytest.mark.skipif(not NODE, reason='ต้องมี node')
def test_script_parses():
    r = subprocess.run([NODE, '--check', str(ROOT / 'app/static/academic_lessons_grid.js')],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
