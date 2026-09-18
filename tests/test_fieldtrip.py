# -*- coding: utf-8 -*-
"""ทัศนศึกษา: กติกาตามระเบียบ ศธ. ว่าด้วยการพานักเรียนและนักศึกษาไปนอกสถานศึกษา พ.ศ. 2562"""
from datetime import datetime
from types import SimpleNamespace as NS

from app.services import fieldtrip as ft


def _trip(n_students=20, n_female=0, staff=(), controller="นายก ข", **kw):
    students = [NS(sex="F" if i < n_female else "M", consent="") for i in range(n_students)]
    base = dict(students=students, staff=[NS(name=s) for s in staff],
                controller_id=1 if controller else None,
                controller=NS(name=controller) if controller else None,
                costs=[], checklist="[]", trip_type="day", depart_at=None, return_at=None,
                request_date=None, status="draft", lodging="")
    base.update(kw)
    return NS(**base)


def _texts(t, today=None):
    return " ".join(x for _, x in ft.warnings(t, today))


def test_assistant_ratio_1_to_30():
    assert "ผู้ช่วยผู้ควบคุมไม่พอ" in _texts(_trip(30))
    assert "ผู้ช่วยผู้ควบคุมไม่พอ" not in _texts(_trip(30, staff=["นายค ง"]))
    assert "ผู้ช่วยผู้ควบคุมไม่พอ" in _texts(_trip(31, staff=["นายค ง"]))       # 31 คน ต้อง 2 คน
    assert "ผู้ช่วยผู้ควบคุมไม่พอ" not in _texts(_trip(0))


def test_female_teacher_reminder():
    assert "ครูสตรี" in _texts(_trip(10, n_female=3, staff=["นายค ง"]))
    assert "ครูสตรี" not in _texts(_trip(10, n_female=3, staff=["นางสาวจ ฉ"]))
    assert "ครูสตรี" not in _texts(_trip(10, n_female=3, staff=["นายค ง"], controller="นางช ซ"))


def test_fifteen_days_before_departure():
    t = _trip(staff=["นายค ง"], depart_at=datetime(2026, 10, 1), request_date=datetime(2026, 9, 20))
    assert "ไม่ถึง 15 วัน" in _texts(t)
    t.request_date = datetime(2026, 9, 16)
    assert "ไม่ถึง 15 วัน" not in _texts(t)


def test_cost_bases():
    t = _trip(20, staff=["นายค ง"])                     # คน = 20 + ผู้ควบคุม 1 + ผู้ช่วย 1 = 22
    t.costs = [NS(basis="lump", rate=8500, times=1), NS(basis="person", rate=80, times=2),
               NS(basis="student", rate=50, times=1)]
    assert ft.total_cost(t) == 8500 + 80 * 22 * 2 + 50 * 20


def test_approver_by_trip_type():
    school = NS(name="โรงเรียนบ้านตัวอย่าง", area_office="สำนักงานเขตพื้นที่การศึกษาประถมศึกษาสมมติ เขต 1",
                director_position="")
    t = _trip(request_to="")
    assert ft.approver_title(t, school) == "ผู้อำนวยการโรงเรียนบ้านตัวอย่าง"
    t.trip_type = "overnight"
    assert ft.approver_title(t, school) == "ผู้อำนวยการสำนักงานเขตพื้นที่การศึกษาประถมศึกษาสมมติ เขต 1"
    t.request_to = "ผู้ได้รับมอบหมาย"
    assert ft.approver_title(t, school) == "ผู้ได้รับมอบหมาย"
