# -*- coding: utf-8 -*-
""""จ่ายแล้วก่อนเริ่มใช้ระบบ": เรื่องพัสดุที่จ่ายไปก่อนเริ่มลงเงินในระบบ ไม่ขึ้นว่ารอจ่าย และไม่สร้างรายการเงิน
กรณีจริง (บ้านหินลาด 2569-10): อาหารกลางวันรอบที่จ่ายไปก่อน 1 ต.ค. ขึ้นว่ารอจ่ายตลอด เสี่ยงทำเบิกซ้ำ
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_paid_before.py
"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401  (fixture)


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _seed():
    """เริ่มใช้ระบบปีงบปัจจุบันด้วยยอดยกมา มีเรื่องพัสดุก่อนวันเริ่ม 2 เรื่อง และหลังวันเริ่ม 1 เรื่อง"""
    from app.models import FinanceAccount, AccountOpening, Project, Procurement
    from app.thai_utils import current_fiscal_year
    fy = current_fiscal_year()
    ce = fy - 544
    db = _db()
    try:
        a = FinanceAccount(name="อาหารกลางวัน"); db.add(a); db.flush()
        db.add(AccountOpening(account_id=a.id, fiscal_year=fy, amount=50000))
        pj = Project(name="โครงการอาหารกลางวัน", budget=264000, plan_year=fy); db.add(pj); db.flush()
        old1 = Procurement(fiscal_year=fy - 1, memo_no="10/x", subject="จ้างเหมาอาหาร รอบ 1", proc_type="จ้าง",
                           total_amount=132000, order_date=datetime(ce, 5, 18), project_id=pj.id)
        old2 = Procurement(fiscal_year=fy - 1, memo_no="11/x", subject="วัสดุ", total_amount=3000,
                           order_date=datetime(ce, 9, 1))
        new = Procurement(fiscal_year=fy, memo_no="1/y", subject="วัสดุใหม่", total_amount=800,
                          order_date=datetime(ce, 10, 5))
        db.add_all([old1, old2, new]); db.commit()
        return fy, pj.id, old1.id, old2.id, new.id, a.id
    finally:
        db.close()


def _money(pid):
    from app.models import Project
    from app.services.budget import project_money_summary, project_spent
    db = _db()
    try:
        p = db.get(Project, pid)
        return project_money_summary(p), project_spent(p)
    finally:
        db.close()


def test_mark_moves_waiting_to_before_and_budget_unchanged(env):
    fy, pid, old1, old2, new, aid = _seed()
    m0, s0 = _money(pid)
    assert m0["waiting"] == 132000 and m0["before"] == 0

    html = env.get("/finance/paid-before").text.split("<tbody>")[1].split("</tbody>")[0]
    assert "10/x" in html and "11/x" in html and "1/y" not in html, "เฉพาะเรื่องก่อนวันเริ่มใช้ระบบ (1 ต.ค.)"
    r = env.post("/finance/paid-before", data={"on": "1", "pid": [str(old1), str(old2)], "back": "/finance/paid-before"},
                 follow_redirects=False)
    assert "msg=" in r.headers["location"]

    m1, s1 = _money(pid)
    assert m1["waiting"] == 0 and m1["paid_pre"] == 132000 and m1["before"] == 132000 and m1["paid"] == 0
    assert (m1["used"], m1["remaining"], s1) == (m0["used"], m0["remaining"], s0), "งบที่ใช้ไปและงบเหลือเท่าเดิม"
    from app.models import FinanceTxn
    db = _db()
    try:
        assert db.query(FinanceTxn).count() == 0, "ไม่สร้างรายการเงิน"
    finally:
        db.close()

    page = env.get("/finance/paid-before").text
    assert "ทำเครื่องหมายแล้ว 2 เรื่อง" in page and "10/x" not in page.split("<tbody>")[1].split("</tbody>")[0]
    assert "จ่ายแล้ว (ก่อนเริ่มใช้ระบบ)" in env.get(f"/projects/{pid}").text
    assert "จ่ายแล้ว (ก่อนเริ่มใช้ระบบ)" in env.get(f"/procurement?year={fy - 1}").text

    # ยกเลิกได้
    env.post("/finance/paid-before", data={"on": "0", "pid": str(old1)})
    assert _money(pid)[0]["waiting"] == 132000


def test_single_button_on_procurement_page_and_disburse_guard(env):
    from app.models import DisburseMemo, FinanceTxn
    fy, pid, old1, old2, new, aid = _seed()
    html = env.get(f"/procurement/{old1}?keep=1").text
    assert 'action="/finance/paid-before"' in html and "จ่ายแล้วก่อนเริ่มใช้ระบบ" in html
    r = env.post("/finance/paid-before", data={"on": "1", "pid": str(old1), "back": f"/procurement/{old1}?keep=1"},
                 follow_redirects=False)
    assert r.headers["location"].startswith(f"/procurement/{old1}?keep=1&msg=")
    html = env.get(r.headers["location"]).text
    assert "pb-pill" in html and "ยกเลิกเครื่องหมาย" in html

    # บันทึกขอเบิกจ่าย: ไม่มีให้ดึงเรื่องที่ทำเครื่องหมายแล้ว และถ้าผูกอยู่แล้ว เตือนก่อนลงจ่าย (ไม่บังคับ)
    assert f'value="{old1}"' not in env.get(f"/finance/disburse?year={fy - 1}").text.split('id="procSel"')[1].split("</select>")[0]
    db = _db()
    try:
        m = DisburseMemo(fiscal_year=fy - 1, memo_no="7/x", subject="อาหาร", amount=132000, procurement_id=old1,
                         account_id=aid, status="อนุมัติ", date=datetime(fy - 544, 9, 30))
        db.add(m); db.commit(); mid = m.id
    finally:
        db.close()
    html = env.get(f"/finance/disburse/{mid}").text
    assert "ทำเครื่องหมายว่าจ่ายแล้วก่อนเริ่มใช้ระบบ" in html and "ตัดซ้ำ" in html
    assert f'action="/finance/disburse/{mid}/post"' in html

    # มีรายการจ่ายในระบบแล้ว = ทำเครื่องหมายไม่ได้ และหน้าเรื่องพัสดุไม่มีปุ่ม
    env.post(f"/finance/disburse/{mid}/post")
    db = _db()
    try:
        assert db.query(FinanceTxn).filter_by(disburse_id=mid).count() == 1
    finally:
        db.close()
    r = env.post("/finance/paid-before", data={"on": "1", "pid": str(old2)}, follow_redirects=False)
    assert "msg=" in r.headers["location"]
    env.post("/finance/paid-before", data={"on": "0", "pid": str(old1)})
    r = env.post("/finance/paid-before", data={"on": "1", "pid": str(old1)}, follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert 'action="/finance/paid-before"' not in env.get(f"/procurement/{old1}?keep=1").text


def test_health_notice_until_marked(env):
    from app.services.finance_health import run
    fy, pid, old1, old2, new, aid = _seed()
    db = _db()
    try:
        keys = {i["key"] for i in run(db, fy)["notice"]}
    finally:
        db.close()
    assert "paid_before_pending" in keys
    from app.services import paid_before as pb
    db = _db()
    try:
        ids = [str(p.id) for p in pb.candidates(db, pb.default_cutoff(db))]   # รวมเรื่องตัวอย่างของชุดทดสอบ
    finally:
        db.close()
    env.post("/finance/paid-before", data={"on": "1", "pid": ids})
    db = _db()
    try:
        assert "paid_before_pending" not in {i["key"] for i in run(db, fy)["notice"]}
    finally:
        db.close()


def test_select_many_on_procurement_page_and_project_shown(env):
    fy, pid, old1, old2, new, aid = _seed()
    html = env.get(f"/procurement?year={fy}").text
    assert "เรื่องพัสดุที่ทำก่อนเริ่มใช้ระบบและจ่ายไปแล้ว" in html
    box = html.split('class="pbx"')[1].split("</details>")[0]
    assert f'name="pid" value="{old1}"' in box and f'name="pid" value="{new}"' not in box
    assert f'name="back" value="/procurement?year={fy}"' in box and "เลือกทั้งหมด" in box
    r = env.post("/finance/paid-before", data={"on": "1", "pid": [str(old1), str(old2)], "back": f"/procurement?year={fy}"},
                 follow_redirects=False)
    assert r.headers["location"].startswith(f"/procurement?year={fy}&msg=")

    # หน้าเรื่องพัสดุ: ช่องโครงการแสดงโครงการที่ผูกด้วย project_id (เดิมขึ้นเป็นขีด)
    detail = env.get(f"/procurement/{old1}?keep=1").text
    assert f'<a href="/projects/{pid}">โครงการอาหารกลางวัน</a>' in detail

    from app.services.finance_health import run
    db = _db()
    try:
        titles = [i["title"] for i in run(db, fy)["notice"]]
    finally:
        db.close()
    assert all("รอจ่าย" not in t for t in titles)
