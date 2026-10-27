# -*- coding: utf-8 -*-
"""ย้ายเรื่องที่ลงวันที่นอกช่วงปีของแผน ไปโครงการชื่อเดียวกันของปีที่ถูกต้อง
กรณีจริง (บ้านหินลาด 2569-10): ทำเรื่องพัสดุตามปีงบ 2569 แต่ผูกกับโครงการปีการศึกษา 2569 ทั้งหมด
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_project_realign.py
"""
import re
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)

AY = 2569


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _seed():
    from app.models import School, Project, Procurement, DisburseMemo, FinanceTxn, FinanceAccount
    db = _db()
    try:
        db.query(School).first().project_year_mode = "academic"      # ปีการศึกษา: 1 พ.ค. 2569 ถึง 30 เม.ย. 2570
        lunch = Project(name="โครงการอาหารกลางวัน", budget=264000, plan_year=AY, responsible="ฝ่ายบริหารงานทั่วไป")
        read = Project(name="โครงการอ่านออกเขียนได้", budget=4000, plan_year=AY)
        db.add_all([lunch, read]); db.flush()
        acc = FinanceAccount(name="เงินอุดหนุน"); db.add(acc); db.flush()
        db.add_all([
            Procurement(fiscal_year=2569, memo_no="4/2569", subject="อาหารกลางวันภาคเรียนที่ 2 รอบที่ 1", proc_type="จ้าง",
                        total_amount=132000, request_date=datetime(2025, 10, 31), project_id=lunch.id),
            Procurement(fiscal_year=2569, memo_no="6/2569", subject="อาหารกลางวันภาคเรียนที่ 2 รอบที่ 2", proc_type="จ้าง",
                        total_amount=132000, request_date=datetime(2026, 1, 20), project_id=lunch.id),
            Procurement(fiscal_year=2569, memo_no="10/2569", subject="อาหารกลางวันภาคเรียนที่ 1 รอบที่ 1", proc_type="จ้าง",
                        total_amount=132000, request_date=datetime(2026, 5, 18), project_id=lunch.id),
            # เรื่องเก่าผูกด้วยชื่อ + ปี (ไม่มี project_id) แบบที่ระบบเคยทำ
            Procurement(fiscal_year=2569, memo_no="4/2569", subject="วัสดุอ่านออกเขียนได้", proc_type="ซื้อ",
                        total_amount=15000, request_date=datetime(2025, 11, 24), project_name="โครงการอ่านออกเขียนได้"),
            Procurement(fiscal_year=2569, memo_no="15/2569", subject="ถ่ายเอกสารอ่านออกเขียนได้", proc_type="จ้าง",
                        total_amount=536, request_date=datetime(2026, 7, 20), project_id=read.id),
            # วันสุดท้ายของปีการศึกษา (30 เม.ย. 2570) ตอนบ่าย ยังอยู่ในช่วงปี
            Procurement(fiscal_year=2570, memo_no="40/2570", subject="วัสดุปลายปี", proc_type="ซื้อ",
                        total_amount=300, request_date=datetime(2027, 4, 30, 15, 0), project_id=read.id),
        ])
        db.add(DisburseMemo(fiscal_year=2569, memo_no="9/2569", subject="ค่าป้าย", amount=630,
                            date=datetime(2026, 3, 1), project_id=read.id))
        db.add(FinanceTxn(account_id=acc.id, kind="out", amount=200, date=datetime(2027, 6, 1), fiscal_year=2570,
                          note="จ่ายหลังสิ้นปีการศึกษา", project_id=read.id))
        db.commit()
        return lunch.id, read.id
    finally:
        db.close()


def _spent(pid):
    from app.models import Project
    from app.services.budget import project_spent
    db = _db()
    try:
        return round(project_spent(db.get(Project, pid)), 2)
    finally:
        db.close()


def test_preview_move_and_idempotent(env):
    lunch_id, read_id = _seed()
    assert _spent(lunch_id) == 396000 and _spent(read_id) == 15000 + 536 + 300 + 630 + 200
    page = env.get(f"/projects?year={AY}").text
    assert "มี 5 เรื่องที่ลงวันที่นอกช่วงปีการศึกษา 2569" in page and f'href="/projects/realign?year={AY}"' in page
    html = env.get(f"/projects/realign?year={AY}").text
    body = html.split('<form method="post" action="/projects/realign"')[0].split("<tbody>")[-1].split("</tbody>")[0]
    assert body.count("<tr>") == 5, "5 เรื่อง (เรื่องในช่วงปีไม่อยู่ในรายการ)"
    assert "โครงการอาหารกลางวัน 2568" in html and "โครงการอ่านออกเขียนได้ 2570" in html
    assert "สร้างใหม่" in html and "ครั้งนี้จะสร้าง 3 โครงการ" in html
    assert "18 พฤษภาคม 2569" not in html and "20 กรกฎาคม 2569" not in html
    tok = re.search(r'name="token" value="([0-9a-f]+)"', html).group(1)

    r = env.post("/projects/realign", data={"year": AY, "token": "ผิด"}, follow_redirects=False)
    assert "err=" in r.headers["location"] and _spent(lunch_id) == 396000, "รายการเปลี่ยน/โทเคนไม่ตรง = ไม่ทำอะไร"

    r = env.post("/projects/realign", data={"year": AY, "token": tok}, follow_redirects=False)
    assert r.headers["location"].endswith("done=5&created=3")
    assert _spent(lunch_id) == 132000, "เหลือเฉพาะรอบ พ.ค. 2569"
    assert _spent(read_id) == 536 + 300, "เหลือเฉพาะเรื่องในช่วงปีการศึกษา 2569 (รวมวันสุดท้ายของปี)"

    from app.models import Project, Procurement
    db = _db()
    try:
        old = {(p.name, p.plan_year): p for p in db.query(Project)}
        l68, r68, r70 = old[("โครงการอาหารกลางวัน", 2568)], old[("โครงการอ่านออกเขียนได้", 2568)], old[("โครงการอ่านออกเขียนได้", 2570)]
        assert l68.budget == 0 and l68.responsible == "ฝ่ายบริหารงานทั่วไป"
        named = db.query(Procurement).filter_by(subject="วัสดุอ่านออกเขียนได้").one()
        assert named.project_id == r68.id and named.memo_no == "4/2569" and named.fiscal_year == 2569, \
            "เรื่องพัสดุไม่เปลี่ยน แค่เปลี่ยนโครงการ"
        ids = (l68.id, r68.id, r70.id)
    finally:
        db.close()
    assert [_spent(i) for i in ids] == [264000, 15000 + 630, 200]
    assert "ไม่มีเรื่องที่ลงวันที่นอกช่วง" in env.get(f"/projects/realign?year={AY}").text
    assert "มี 5 เรื่อง" not in env.get(f"/projects?year={AY}").text


def test_reuses_existing_target_project(env):
    from app.models import Project
    lunch_id, _ = _seed()
    db = _db()
    try:
        db.add(Project(name="โครงการอาหารกลางวัน", budget=250000, plan_year=2568)); db.commit()
    finally:
        db.close()
    html = env.get(f"/projects/realign?year={AY}").text
    tok = re.search(r'name="token" value="([0-9a-f]+)"', html).group(1)
    env.post("/projects/realign", data={"year": AY, "token": tok})
    db = _db()
    try:
        same = db.query(Project).filter_by(name="โครงการอาหารกลางวัน", plan_year=2568).all()
        assert len(same) == 1 and same[0].budget == 250000, "ใช้โครงการปี 2568 ที่มีอยู่ ไม่สร้างซ้ำ ไม่แตะงบ"
    finally:
        db.close()


def test_uses_order_date_not_request_date_entered_later(env):
    """ลงเรื่องย้อนหลัง: request_date = วันที่พิมพ์เข้าระบบ (ต.ค. 69) แต่ใบสั่งซื้อลงวันที่ปีการศึกษาก่อน
    ต้องยึดวันที่ใบสั่งซื้อ (ตัวที่แสดงในรายการเรื่องพัสดุ)"""
    from app.models import School, Project, Procurement
    db = _db()
    try:
        db.query(School).first().project_year_mode = "academic"
        pj = Project(name="โครงการส่งเสริมความเป็นเลิศ", budget=30000, plan_year=AY)
        db.add(pj); db.flush()
        db.add_all([
            Procurement(fiscal_year=2569, memo_no="3/2569", subject="วัสดุศิลปหัตถกรรม", total_amount=4990,
                        request_date=datetime(2026, 10, 15), order_date=datetime(2025, 11, 12), project_id=pj.id),
            Procurement(fiscal_year=2569, memo_no="23/2569", subject="วัสดุแข่งขันภาษาไทย", total_amount=4000,
                        request_date=datetime(2026, 10, 15), order_date=datetime(2026, 6, 18), project_id=pj.id),
            Procurement(fiscal_year=2569, memo_no="99/2569", subject="ยังไม่ออกใบสั่ง", total_amount=100,
                        request_date=datetime(2026, 3, 1), project_id=pj.id),
        ])
        db.commit()
    finally:
        db.close()
    from app.services.project_realign import find
    db = _db()
    try:
        got = sorted(r["no"] for r in find(db, AY))
    finally:
        db.close()
    assert got == ["3/2569", "99/2569"], "ยึดวันที่ใบสั่งซื้อ · ไม่มีใบสั่งค่อยใช้วันที่รายงานขอซื้อ"
