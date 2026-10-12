# -*- coding: utf-8 -*-
"""ระยะ 3: ตั้งยอดตั้งต้นสำหรับโรงเรียนที่เริ่มใช้ระบบกลางปี

ปัญหาเดิม: ระบบรู้แต่เงินที่จ่ายผ่านระบบ โรงเรียนที่มาใช้กลางปีจึงเห็น "คงเหลือ" เต็มงบ
ทั้งที่ใช้ไปแล้ว · ทางแก้: ถามโครงการละข้อเดียวว่า "ตอนนี้เหลืองบกี่บาท"
แล้วระบบคำนวณเองว่าใช้ไปก่อนเริ่มใช้ระบบเท่าไร (ใช้ไปก่อนเริ่มใช้ระบบ = งบ - ใช้ในระบบแล้ว - เหลือตอนนี้)
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_projects_start.py
"""
import json
import pathlib
import re
import shutil
import subprocess
from datetime import datetime

import pytest

from app.models import DisburseMemo, Project
from app.services.budget import project_spent, project_spent_in_system

ROOT = pathlib.Path(__file__).resolve().parents[1]
YEAR = 2597
MARK = "ทดสอบยอดตั้งต้น_"


# ---------------- ตัวเลข ----------------
def test_spent_counts_the_starting_balance_once():
    p = Project(name="x", budget=30000, plan_year=YEAR, spent_before=8000)
    assert project_spent_in_system(p) == 0          # ยังไม่ได้ผูกกับฐานข้อมูล
    assert project_spent(p) == 8000


# ---------------- หน้าเว็บ ----------------
@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app.routers.auth as auth_mod
    import app.main as main_mod
    from app.main import app
    auth_mod.authenticate = lambda u, p: {"uid": 1, "username": "t", "role": "owner", "tenant_id": 1,
                                          "display_name": "t", "must_change": False, "is_owner": True}
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {"is_owner": True, "modules": "", "active": True,
                                               "welcomed": True}
    c = TestClient(app)
    assert c.post("/login", data={"username": "t", "password": "x"},
                  follow_redirects=False).status_code in (302, 303)
    return c


@pytest.fixture
def world():
    """กีฬาสี งบ 30,000 (ยังไม่มีรายจ่าย) · ค่ายคุณธรรม งบ 25,000 มีบันทึกเบิกในระบบแล้ว 5,000"""
    from app.tenancy import session_for
    s = session_for(1)
    sport = Project(name=MARK + "กีฬาสี", budget=30000, plan_year=YEAR)
    camp = Project(name=MARK + "ค่ายคุณธรรม", budget=25000, plan_year=YEAR)
    s.add_all([sport, camp]); s.flush()
    s.add(DisburseMemo(fiscal_year=2570, subject=MARK + "ค่าอาหาร", amount=5000, project_id=camp.id,
                       status="จ่ายแล้ว"))
    s.commit()
    w = dict(s=s, sport=sport.id, camp=camp.id)
    yield w
    s.rollback()
    s.query(DisburseMemo).filter(DisburseMemo.subject.like(MARK + "%")).delete(synchronize_session=False)
    s.query(Project).filter(Project.name.like(MARK + "%")).delete(synchronize_session=False)
    s.commit(); s.close()


def _fresh(w, pid):
    w["s"].expire_all()
    return w["s"].get(Project, pid)


def test_page_opens_and_is_not_mistaken_for_a_project_number(client, world):
    """/projects/start ต้องลงทะเบียนก่อน /projects/{pid} ไม่งั้น FastAPI อ่าน start เป็นเลขโครงการแล้วตอบ 422"""
    r = client.get(f"/projects/start?year={YEAR}")
    assert r.status_code == 200, r.status_code
    assert MARK + "กีฬาสี" in r.text and "ตอนนี้เหลือ" in r.text
    assert "ตัวอย่าง" in r.text, "ต้องมีตัวอย่างตัวเลขอธิบาย เจ้าของบอกว่าคำอธิบายแบบศัพท์บัญชีงง"


def test_answering_how_much_is_left_works_out_what_was_spent_before(client, world):
    r = client.post("/projects/start", data={"year": str(YEAR), f"remain_{world['sport']}": "22,000",
                                             f"remain_{world['camp']}": "15000"},
                    follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"], r.headers["location"]
    sport, camp = _fresh(world, world["sport"]), _fresh(world, world["camp"])
    assert sport.spent_before == 8000 and sport.spent_before_at is not None
    # ค่ายคุณธรรม: งบ 25,000 ใช้ในระบบแล้ว 5,000 ตอนนี้เหลือ 15,000 -> ใช้ก่อนใช้ระบบ 5,000
    assert camp.spent_before == 5000
    assert project_spent(sport) == 8000 and project_spent(camp) == 10000


def test_blank_rows_are_left_alone(client, world):
    s = world["s"]
    _fresh(world, world["sport"]).spent_before = 3000; s.commit()
    client.post("/projects/start", data={"year": str(YEAR), f"remain_{world['sport']}": "",
                                         f"remain_{world['camp']}": "20000"}, follow_redirects=False)
    assert _fresh(world, world["sport"]).spent_before == 3000


def test_bad_input_saves_nothing_and_says_why(client, world):
    """แถวหนึ่งผิด ต้องไม่บันทึกแถวอื่นไปครึ่ง ๆ กลาง ๆ"""
    r = client.post("/projects/start", data={"year": str(YEAR), f"remain_{world['sport']}": "22000",
                                             f"remain_{world['camp']}": "21000"},   # เหลือได้ไม่เกิน 20,000
                    follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert _fresh(world, world["sport"]).spent_before in (0, None), "แถวที่ถูกต้องห้ามบันทึกไปก่อน"
    page = client.get(r.headers["location"]).text
    assert "เหลือได้ไม่เกิน 20,000.00" in page
    for bad in ("-1", "abc"):
        r = client.post("/projects/start", data={"year": str(YEAR), f"remain_{world['sport']}": bad},
                        follow_redirects=False)
        assert "err=" in r.headers["location"], bad


def test_entering_the_full_unspent_amount_clears_the_starting_balance(client, world):
    s = world["s"]
    p = _fresh(world, world["sport"]); p.spent_before = 8000; p.spent_before_at = datetime.now(); s.commit()
    client.post("/projects/start", data={"year": str(YEAR), f"remain_{world['sport']}": "30000"},
                follow_redirects=False)
    p = _fresh(world, world["sport"])
    assert p.spent_before == 0 and p.spent_before_at is None


def test_projects_list_suggests_the_page_only_for_a_fresh_start(client, world):
    s = world["s"]
    s.query(DisburseMemo).filter(DisburseMemo.subject.like(MARK + "%")).delete(synchronize_session=False)
    s.commit()
    assert "เพิ่งเริ่มใช้ระบบกลางปีใช่ไหม" in client.get(f"/projects?year={YEAR}").text
    _fresh(world, world["sport"]).spent_before = 8000; s.commit()
    assert "เพิ่งเริ่มใช้ระบบกลางปีใช่ไหม" not in client.get(f"/projects?year={YEAR}").text
    assert f"/projects/start?year={YEAR}" in client.get(f"/projects?year={YEAR}").text, "ปุ่มต้องอยู่เสมอ"


def test_project_page_shows_it_and_does_not_call_it_waiting_to_be_paid(client, world):
    """ยอดตั้งต้นจ่ายไปแล้วนอกระบบ ห้ามนับเป็น "ทำเรื่องแล้วรอจ่าย"

    ต้องมีการจ่ายจริงในระบบด้วย บรรทัด "จ่ายจริงตามทะเบียนคุมเงิน" ถึงจะขึ้น
    (รอบแรกเทสต์นี้ไม่มีการจ่าย บรรทัดนั้นไม่ขึ้นเลย จึงผ่านทั้งที่โค้ดผิด)
    """
    from app.models import FinanceAccount, FinanceTxn
    s = world["s"]
    acc = FinanceAccount(name=MARK + "บัญชี"); s.add(acc); s.flush()
    s.add(FinanceTxn(account_id=acc.id, fiscal_year=2570, kind="out", amount=1000,
                     project_id=world["sport"], date=datetime(2026, 11, 1)))
    _fresh(world, world["sport"]).spent_before = 8000; s.commit()
    try:
        html = client.get(f"/projects/{world['sport']}").text
        assert "รวมใช้ไปก่อนเริ่มใช้ระบบ 8,000.00" in html
        assert "จ่ายจริงตามทะเบียนคุมเงิน 1,000.00" in html, "บรรทัดนี้ต้องขึ้น ไม่งั้นเทสต์ไม่ได้ทดสอบอะไร"
        assert "ทำเรื่องแล้วรอจ่าย" not in html
    finally:
        s.query(FinanceTxn).filter_by(account_id=acc.id).delete()
        s.query(FinanceAccount).filter_by(id=acc.id).delete()
        s.commit()


def test_summary_report_lines_add_up_to_the_spent_total(world):
    from app.services.project_summary import build_rows
    s = world["s"]
    camp = _fresh(world, world["camp"]); camp.spent_before = 5000; camp.spent_before_at = datetime.now()
    s.commit()
    row = build_rows(s, [_fresh(world, world["camp"])])[0]
    assert row["works"][0]["method"] == "ยอดตั้งต้น" and row["works"][0]["amount"] == 5000
    assert round(sum(w["amount"] for w in row["works"]), 2) == row["spent"] == 10000


def test_column_is_migrated_for_existing_schools():
    db = (ROOT / "app/database.py").read_text(encoding="utf-8")
    assert '("project", "spent_before"' in db and '("project", "spent_before_at"' in db


# ---------------- สคริปต์ฝั่งหน้าจอ ----------------
NODE = shutil.which("node")


@pytest.mark.skipif(not NODE, reason="ต้องมี node")
def test_live_calculation_and_inline_errors():
    html = (ROOT / "app/templates/projects_start.html").read_text(encoding="utf-8")
    script = re.search(r"<script>\s*(\(function \(\) \{.*?\}\)\(\);)\s*</script>", html, re.S).group(1)
    runner = r"""
const cases = JSON.parse(process.argv[1]);
function mk(room, val){
  const out = {textContent:'-'}, err = {hidden:true, textContent:''};
  const tr = {getAttribute: () => String(room), querySelector: q => q === '.st-out' ? out : err};
  const cls = new Set();
  const inp = {value: val, closest: () => tr, addEventListener(e, f){ this['on_'+e] = f; },
               classList: {add: c => cls.add(c), remove: c => cls.delete(c)}, focus(){} };
  return {inp, out, err, cls};
}
const rows = cases.map(c => mk(c[0], c[1]));
let submitted = null, prevented = false;
const form = {querySelectorAll: () => rows.map(r => r.inp), querySelector: () => null,
              addEventListener(e, f){ submitted = f; }};
global.document = {getElementById: () => form};
SCRIPT
rows.forEach(r => r.inp.on_input());
submitted({preventDefault(){ prevented = true; }});
console.log(JSON.stringify({out: rows.map(r => r.out.textContent), bad: rows.map(r => r.cls.has('bad')),
                            err: rows.map(r => r.err.hidden ? '' : r.err.textContent), prevented}));
""".replace("SCRIPT", script)
    cases = [[30000, "22,000"], [20000, "21000"], [30000, ""], [30000, "-5"]]
    r = subprocess.run([NODE, "-e", runner, json.dumps(cases)], capture_output=True, text=True,
                       encoding="utf-8")
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["out"][0] == "8,000.00", "คำนวณใช้ไปก่อนเริ่มใช้ระบบให้เห็นทันที"
    assert out["bad"] == [False, True, False, True]
    assert "ไม่เกิน 20,000.00" in out["err"][1]
    assert out["prevented"] is True, "มีช่องผิดต้องไม่ส่งฟอร์ม"
