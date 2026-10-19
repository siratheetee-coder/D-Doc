# -*- coding: utf-8 -*-
"""e-Budget ส่วนที่ 1 จำนวนบุคลากร 16 ประเภท (นับจากทะเบียนบุคลากร แก้เองได้) + หน้าพิมพ์รายงาน 5 ส่วน
รัน: .venv\Scripts\python.exe -m pytest tests/test_ebudget_staff.py
"""
import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)

FY = 2570


@pytest.mark.parametrize("position,ptype,code", [
    ("ผู้อำนวยการโรงเรียน", "ผู้บริหาร", "1"),
    ("รองผู้อำนวยการโรงเรียน", "ผู้บริหาร", "2"),
    ("ครู", "ครู", "3"),
    ("ครูผู้ช่วย", "ครู", "3"),
    ("ครู (มาช่วยราชการ)", "ครู", "4"),
    ("ครูอัตราจ้าง (งบประมาณ สพฐ.)", "ครู", "5"),
    ("ครูอัตราจ้าง", "ครู", "6"),
    ("พนักงานราชการ (ครู)", "ครู", "7"),
    ("พนักงานราชการ", "อื่นๆ", "8"),
    ("เจ้าหน้าที่ธุรการ", "ธุรการ", "9"),
    ("บรรณารักษ์", "อื่นๆ", "10"),
    ("นักการภารโรง", "นักการ", "11"),
    ("", "นักการ", "11"),
    ("พนักงานขับรถ", "อื่นๆ", "12"),
    ("ช่างไฟฟ้า", "อื่นๆ", "13"),
    ("เจ้าหน้าที่ห้องปฏิบัติการวิทยาศาสตร์", "อื่นๆ", "14"),
    ("พี่เลี้ยงเด็กพิการ", "อื่นๆ", "15"),
    ("แม่ครัว", "อื่นๆ", "16"),
])
def test_classify(position, ptype, code):
    from app.services.ebudget_staff import classify
    assert classify(position, ptype) == code


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_auto_count_edit_reset_and_print(env):
    from app.models import Person
    db = _db()
    try:
        db.query(Person).delete()
        db.add_all([Person(name="ผอ.", position="ผู้อำนวยการโรงเรียน", person_type="ผู้บริหาร"),
                    Person(name="ครู ก", position="ครู"), Person(name="ครู ข", position="ครูชำนาญการ"),
                    Person(name="ภารโรง", position="นักการภารโรง", person_type="นักการ"),
                    Person(name="ลาออก", position="ครู", active=False)])
        db.commit()
    finally:
        db.close()
    html = env.get(f"/finance/ebudget?year={FY}&round=1").text
    assert 'id="eb-staff"' in html and "รวม 4 คน" in html, "ไม่นับคนที่ไม่ active"
    assert 'name="n_3" value="2"' in html and 'name="n_1" value="1"' in html and 'name="n_11" value="1"' in html
    data = {"year": FY, "round": "1"}
    data.update({f"n_{c}": "0" for c in range(1, 17)})
    data.update({"n_1": "1", "n_3": "5", "n_11": "1", "n_6": "-3"})
    r = env.post("/finance/ebudget/staff", data=data, follow_redirects=False)
    assert r.headers["location"].endswith("staff_saved=1#eb-staff")
    html = env.get(f"/finance/ebudget?year={FY}&round=1").text
    assert 'name="n_3" value="5"' in html and 'name="n_6" value="0"' in html and "รวม 7 คน" in html
    assert "staff-cell edited" in html and "กลับไปนับจากทะเบียนบุคลากร" in html
    assert 'name="n_3" value="2"' in env.get(f"/finance/ebudget?year={FY}&round=2").text, "แยกตามครั้งที่รายงาน"
    p = env.get(f"/finance/ebudget/print?year={FY}&round=1").text
    for part in ("ส่วนที่ 1 ข้อมูลบุคลากร (รวม 7 คน)", "ส่วนที่ 2 เงินคงเหลือยกมา", "ส่วนที่ 3 รายรับ",
                 "ส่วนที่ 4 รายจ่าย", "ส่วนที่ 5 เงินคงเหลือ", "1. งบประมาณคงเหลือจากที่ผ่านมา", "window.print()"):
        assert part in p, part
    env.post("/finance/ebudget/staff", data={"year": FY, "round": "1", "reset": "1"})
    assert 'name="n_3" value="2"' in env.get(f"/finance/ebudget?year={FY}&round=1").text


def test_section3_tree_sums_leaves_and_opening():
    from app.services.ebudget import section3_rows
    op = {k: 0.0 for k in ("1", "2", "3", "3.1", "3.2", "4")}
    op.update({"3": 900.0, "3.1": 500.0, "3.2": 100.0, "4": 50.0})
    d = {"opening": op, "income_src": {"i2.1.1": {"3.1.1": 100.0}, "i2.1.2": {"3.1.2": 40.0},
                                       "i2.2.1": {"3.2.3": 60.0}, "i5": {"3.5": 7.0}}}
    rows = {r["code"]: r for r in section3_rows(d)}
    assert rows["c1"]["amount"] == 950 and rows["c1.3.3"]["amount"] == 300, "(3) อุดหนุนอื่น = 1.3 - (1) - (2)"
    assert rows["i2"]["amount"] == 200 and rows["i2.1"]["amount"] == 140 and rows["i2.1.1"]["amount"] == 100
    assert rows["i5"]["amount"] == 7 and rows["i5"]["unsorted"] == 7 and rows["i5.1"]["amount"] == 0
