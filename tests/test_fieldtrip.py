# -*- coding: utf-8 -*-
"""ทัศนศึกษา: กติกาตามระเบียบ ศธ. ว่าด้วยการพานักเรียนและนักศึกษาไปนอกสถานศึกษา พ.ศ. 2562"""
from datetime import datetime
from types import SimpleNamespace as NS

from app.services import fieldtrip as ft


def _trip(n_students=20, n_female=0, staff=(), controller="นายก ข", **kw):
    students = [NS(sex="F" if i < n_female else "M", consent="", level="ป.6") for i in range(n_students)]
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


def test_cost_caps_w2983():
    over = NS(kind="meal", rate=90, pay_method="procure", vendor_id=1, basis="person", times=1)
    ok = NS(kind="meal", rate=80, pay_method="procure", vendor_id=1, basis="person", times=1)
    assert any("เกินเพดาน 80" in w for w in ft.cost_warnings(over))
    assert ft.cost_warnings(ok) == []
    assert any("ผู้ขาย" in w for w in ft.cost_warnings(NS(kind="bus", rate=1, pay_method="procure",
                                                            vendor_id=None, basis="lump", times=1)))


def test_night_travel_w1057():
    t = _trip(staff=["นางก ข"], depart_at=datetime(2026, 10, 1, 4, 30), return_at=datetime(2026, 10, 1, 17, 0))
    assert "กลางคืน" in _texts(t)
    t.depart_at = datetime(2026, 10, 1, 6, 0)
    assert "กลางคืน" not in _texts(t)


def test_procure_groups_one_per_vendor():
    v1, v2 = NS(name="ร้านรถ"), NS(name="ร้านอาหาร")
    t = _trip(20, staff=["นางก ข"])
    t.costs = [NS(kind="bus", basis="lump", rate=8500, times=1, pay_method="procure", vendor_id=1, vendor=v1, procurement_id=None, procurement=None),
               NS(kind="meal", basis="person", rate=80, times=1, pay_method="procure", vendor_id=2, vendor=v2, procurement_id=None, procurement=None),
               NS(kind="snack", basis="person", rate=25, times=2, pay_method="procure", vendor_id=2, vendor=v2, procurement_id=None, procurement=None),
               NS(kind="entry", basis="student", rate=50, times=1, pay_method="receipt", vendor_id=None, vendor=None, procurement_id=None, procurement=None)]
    groups = {g["vendor"].name: g for g in ft.procure_groups(t)}
    assert set(groups) == {"ร้านรถ", "ร้านอาหาร"}
    assert groups["ร้านอาหาร"]["total"] == 80 * 22 + 25 * 22 * 2 and groups["ร้านอาหาร"]["proc_type"] == "จ้าง"
    assert [x.kind for x in ft.cash_costs(t)] == ["entry"]
