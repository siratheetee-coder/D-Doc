# -*- coding: utf-8 -*-
"""โครงการนี้ใช้เงินจากหมวดไหน (ระยะ 1 ของการเชื่อมทะเบียนคุมเงินกับโครงการ)

เดิมฟอร์มขอเบิกจ่ายถามแยก 4 ช่องที่ไม่รู้จักกัน ผู้ใช้เลือกโครงการแล้วต้องไปเลือก
บัญชีกับหมวดเองอีก ตอนนี้ระบบหาให้จาก (1) จัดสรรไว้ในแผน (2) เคยใช้ครั้งก่อน
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_project_money.py
"""
import json
import pathlib
import shutil
import subprocess
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AccountItem, DisburseMemo, FinanceAccount, FinanceTxn, Procurement, Project

try:        # ระบบจัดสรรงบให้โครงการ ยังไม่มีในทุกเครื่อง ไม่มีก็ข้ามเทสต์ส่วน "จัดสรรไว้ในแผน"
    from app.models import PlanBudget, PlanFunding, ProjectFunding
except ImportError:
    PlanBudget = PlanFunding = ProjectFunding = None
needs_plan = pytest.mark.skipif(PlanFunding is None, reason="ยังไม่มีระบบจัดสรรงบให้โครงการ")
from app.services.project_money import ALLOCATED, USED_BEFORE, project_sources

ROOT = pathlib.Path(__file__).resolve().parents[1]
FY = 2570


@pytest.fixture
def db():
    eng = create_engine("sqlite://")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()
    eng.dispose()


def _money(db):
    """บัญชีเงินอุดหนุน มีหมวดค่ากิจกรรมฯ ทั้งปีงบ 2569 และ 2570 + บัญชีรายได้สถานศึกษา"""
    sub = FinanceAccount(name="เงินอุดหนุน")
    inc = FinanceAccount(name="เงินรายได้สถานศึกษา")
    db.add_all([sub, inc]); db.flush()
    act69 = AccountItem(account_id=sub.id, fiscal_year=2569, name="ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน")
    act70 = AccountItem(account_id=sub.id, fiscal_year=FY, name="ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน")
    teach70 = AccountItem(account_id=sub.id, fiscal_year=FY, name="ค่าจัดการเรียนการสอน")
    db.add_all([act69, act70, teach70]); db.flush()
    return sub, inc, act69, act70, teach70


def _project(db, name="กีฬาสี"):
    p = Project(name=name, budget=30000, plan_year=2569)
    db.add(p); db.flush()
    return p


def _allocate(db, project, item, amount=30000):
    plan = PlanBudget(year=2569, mode="academic", start_date=datetime(2026, 5, 1),
                      end_date=datetime(2027, 4, 30))
    db.add(plan); db.flush()
    f = PlanFunding(plan_id=plan.id, source_key=f"test:{item.id}", kind="opening",
                    name=item.name, amount=amount, account_item_id=item.id)
    db.add(f); db.flush()
    db.add(ProjectFunding(project_id=project.id, funding_id=f.id, amount=amount)); db.flush()


# ---------------- หาหมวดของโครงการ ----------------
def test_unknown_project_has_no_source(db):
    _money(db)
    p = _project(db)
    assert project_sources(db, p.id, FY) == []
    assert project_sources(db, None, FY) == []


@needs_plan
def test_allocated_in_the_plan_is_used_first(db):
    sub, inc, act69, act70, teach70 = _money(db)
    p = _project(db)
    _allocate(db, p, act70)
    out = project_sources(db, p.id, FY)
    assert len(out) == 1
    assert out[0]["item_id"] == act70.id and out[0]["account_id"] == sub.id
    assert out[0]["why"] == ALLOCATED
    assert out[0]["label"] == "เงินอุดหนุน / ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน"


def test_remembers_the_category_used_last_time(db):
    """ไม่ต้องตั้งค่าล่วงหน้า เลือกครั้งแรกครั้งเดียว ครั้งต่อไประบบจำให้"""
    sub, inc, act69, act70, teach70 = _money(db)
    p = _project(db)
    db.add(DisburseMemo(fiscal_year=FY, subject="ซื้อป้าย", amount=8000,
                        account_id=sub.id, item_id=act70.id, project_id=p.id))
    db.flush()
    out = project_sources(db, p.id, FY)
    assert [(s["item_id"], s["why"]) for s in out] == [(act70.id, USED_BEFORE)]


def test_remembers_through_a_procurement_linked_to_the_project(db):
    """บันทึกขอเบิกจ่ายที่ดึงมาจากเรื่องจัดซื้อ ผูกโครงการไว้ที่เรื่องจัดซื้อ ไม่ใช่ที่บันทึก"""
    sub, inc, act69, act70, teach70 = _money(db)
    p = _project(db)
    proc = Procurement(fiscal_year=FY, subject="ซื้อเสื้อ", project_id=p.id)
    db.add(proc); db.flush()
    db.add(DisburseMemo(fiscal_year=FY, subject="ซื้อเสื้อ", amount=5000, account_id=sub.id,
                        item_id=teach70.id, procurement_id=proc.id))
    db.flush()
    out = project_sources(db, p.id, FY)
    assert [s["item_id"] for s in out] == [teach70.id]


def test_category_from_last_fiscal_year_is_mapped_to_this_year(db):
    """หมวดแยกรายปีงบ จำของปีก่อนมาแล้วต้องหักเงินลงหมวดปีนี้ ไม่ใช่หมวดปีที่ปิดไปแล้ว

    แผนปีการศึกษา (พ.ค.-เม.ย.) คร่อมสองปีงบ จึงเจอกรณีนี้ทุกปี
    """
    sub, inc, act69, act70, teach70 = _money(db)
    p = _project(db)
    db.add(DisburseMemo(fiscal_year=2569, subject="ซื้อป้าย", amount=8000,
                        account_id=sub.id, item_id=act69.id, project_id=p.id))
    db.flush()
    out = project_sources(db, p.id, FY)
    assert [s["item_id"] for s in out] == [act70.id], "ต้องได้หมวดชื่อเดียวกันของปีงบ 2570"


def test_category_that_no_longer_exists_this_year_is_left_for_the_user(db):
    sub, inc, act69, act70, teach70 = _money(db)
    gone = AccountItem(account_id=sub.id, fiscal_year=2569, name="หมวดที่ปีนี้ไม่มีแล้ว")
    db.add(gone); db.flush()
    p = _project(db)
    db.add(DisburseMemo(fiscal_year=2569, subject="x", amount=1, account_id=sub.id,
                        item_id=gone.id, project_id=p.id))
    db.flush()
    assert project_sources(db, p.id, FY) == [], "ไม่มีหมวดปีนี้ ต้องไม่เดา ให้ผู้ใช้เลือกเอง"


@needs_plan
def test_same_category_is_listed_once_and_keeps_the_stronger_reason(db):
    sub, inc, act69, act70, teach70 = _money(db)
    p = _project(db)
    _allocate(db, p, act70)
    db.add(DisburseMemo(fiscal_year=FY, subject="ซื้อป้าย", amount=8000,
                        account_id=sub.id, item_id=act70.id, project_id=p.id))
    db.flush()
    out = project_sources(db, p.id, FY)
    assert len(out) == 1 and out[0]["why"] == ALLOCATED


@needs_plan
def test_several_categories_are_all_offered_allocated_first(db):
    sub, inc, act69, act70, teach70 = _money(db)
    p = _project(db)
    _allocate(db, p, act70)
    db.add(FinanceTxn(account_id=inc.id, fiscal_year=FY, kind="out", amount=500,
                      project_id=p.id, date=datetime(2026, 11, 1)))
    db.flush()
    out = project_sources(db, p.id, FY)
    assert [s["why"] for s in out] == [ALLOCATED, USED_BEFORE]
    assert out[1]["account_id"] == inc.id and out[1]["item_id"] is None
    assert out[1]["label"] == "เงินรายได้สถานศึกษา"


def test_other_projects_do_not_leak_in(db):
    sub, inc, act69, act70, teach70 = _money(db)
    a, b = _project(db, "กีฬาสี"), _project(db, "ค่ายคุณธรรม")
    db.add(DisburseMemo(fiscal_year=FY, subject="x", amount=1, account_id=sub.id,
                        item_id=act70.id, project_id=b.id))
    db.flush()
    assert project_sources(db, a.id, FY) == []


# ---------------- ฟอร์มและทะเบียนคุมเงิน ----------------
def test_both_disburse_forms_ask_for_the_project_first_and_load_the_helper():
    for rel in ("app/templates/disburse_form.html", "app/templates/disburse_detail.html"):
        html = (ROOT / rel).read_text(encoding="utf-8")
        assert 'id="projSel"' in html and 'id="srcPick"' in html and 'id="srcLine"' in html, rel
        assert "/static/project_source.js" in html, rel
        assert html.index('id="projSel"') < html.index('id="acctSel"'), \
            f"{rel}: โครงการต้องมาก่อนบัญชี/หมวด"
        assert html.count('name="project_id"') == 1, f"{rel}: มีช่องโครงการซ้ำ"
        assert "แหล่งเงิน/หมวดงบ" not in html, f"{rel}: ยังใช้คำเก่าที่ไม่ตรงกับคำว่า หมวด"


def test_ledger_rows_link_back_to_the_project():
    html = (ROOT / "app/templates/finance_ledger.html").read_text(encoding="utf-8")
    assert "txn_project.get(r.t.id)" in html and "/projects/{{ pj.id }}" in html


# ---------------- สคริปต์ฝั่งหน้าจอ (รันจริงบน DOM จำลอง) ----------------
NODE = shutil.which("node")
SCRIPT = ROOT / "app/static/project_source.js"


def _run_js(sources, project="7", edit=False, acct="", item="", src=""):
    runner = r"""
const [list, project, edit, acct0, item0, src0] = JSON.parse(process.argv[1]);
function el(id, extra){ return Object.assign({id, value:'', hidden:false, innerHTML:'', className:'',
  attrs:{}, getAttribute(k){ return this.attrs[k]; }, addEventListener(e, f){ this['on_'+e]=f; },
  querySelectorAll(){ return []; }, remove(){ this.removed=true; } }, extra||{}); }
const N = { projSel: el('projSel', {value: project, attrs:{'data-fy':'2570','data-edit': edit?'1':'0'}}),
            acctSel: el('acctSel', {value: acct0}), itemSel: el('itemSel', {value: item0}),
            srcLine: el('srcLine'), srcPick: el('srcPick'), srcChange: el('srcChange') };
const src = el('src', {value: src0});
let filled = null;
global.fillItems = function(id){ filled = id; N.itemSel.value = id == null ? '' : String(id); };
global.document = { getElementById: id => N[id] || null,
                    querySelector: q => q.indexOf('budget_source') >= 0 ? src : null };
global.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({ sources: list }) });
require(process.argv[2]);
setTimeout(() => console.log(JSON.stringify({
  acct: N.acctSel.value, item: N.itemSel.value, filled, src: src.value,
  lineHidden: N.srcLine.hidden, line: N.srcLine.innerHTML, cls: N.srcLine.className,
  pickHidden: N.srcPick.hidden })), 20);
"""
    payload = json.dumps([sources, project, edit, acct, item, src])
    r = subprocess.run([NODE, "-e", runner, payload, str(SCRIPT)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


_ONE = [{"account_id": 3, "account_name": "เงินอุดหนุน", "item_id": 11,
         "item_name": "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน",
         "label": "เงินอุดหนุน / ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", "why": ALLOCATED}]


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_one_category_fills_everything_and_hides_the_pickers():
    out = _run_js(_ONE)
    assert out["acct"] == "3" and out["item"] == "11" and out["filled"] == 11
    assert out["src"] == "เงินอุดหนุน", "ชื่อเงินที่พิมพ์ในเอกสารต้องเติมให้ด้วย"
    assert out["pickHidden"] is True and out["lineHidden"] is False
    assert "จะหักจาก" in out["line"] and "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน" in out["line"]


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_does_not_overwrite_what_the_user_typed():
    out = _run_js(_ONE, src="เงินบริจาค")
    assert out["src"] == "เงินบริจาค"


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_unknown_project_shows_the_pickers_and_says_it_will_remember():
    out = _run_js([])
    assert out["pickHidden"] is False
    assert "ครั้งหน้าระบบจำให้" in out["line"]


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_several_categories_ask_which_one():
    two = _ONE + [{"account_id": 4, "account_name": "เงินรายได้สถานศึกษา", "item_id": None,
                   "item_name": "", "label": "เงินรายได้สถานศึกษา", "why": USED_BEFORE}]
    out = _run_js(two)
    assert out["line"].count('type="radio"') == 2
    assert out["acct"] == "", "หลายหมวดต้องให้ผู้ใช้เลือก ไม่เดาให้"


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_no_project_keeps_the_old_form():
    out = _run_js(_ONE, project="")
    assert out["lineHidden"] is True and out["pickHidden"] is False and out["acct"] == ""


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_edit_form_never_silently_changes_a_saved_category():
    """หน้าแก้ไข: บันทึกหักหมวดอื่นไว้แล้ว ต้องไม่เปลี่ยนให้เงียบ ๆ แค่เตือน"""
    out = _run_js(_ONE, edit=True, acct="9", item="99")
    assert out["acct"] == "9" and out["item"] == "99"
    assert out["pickHidden"] is False and "ต่างจาก" in out["line"]


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_escapes_names():
    bad = [dict(_ONE[0], label='<img src=x onerror=alert(1)>')]
    out = _run_js(bad)
    assert "<img" not in out["line"] and "&lt;img" in out["line"]


# ---------------- เดินผ่าน HTTP จริง ----------------
def _login():
    from fastapi.testclient import TestClient
    import app.routers.auth as auth_mod
    import app.main as main_mod
    from app.main import app
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "tester", "role": "owner", "tenant_id": 1,
        "display_name": "ผู้ทดสอบ", "must_change": False, "is_owner": True}
    main_mod.can_use_module = lambda tid, mod: True
    main_mod.get_account_access = lambda uid: {
        "is_owner": True, "modules": "", "active": True, "welcomed": True}
    c = TestClient(app)
    r = c.post("/login", data={"username": "tester", "password": "x"}, follow_redirects=False)
    assert r.status_code in (302, 303), r.status_code
    return c


def test_http_memo_teaches_the_project_category_and_the_ledger_links_back():
    """เลือกหมวดครั้งแรกในบันทึกเบิกจ่าย → ครั้งต่อไประบบเสนอให้เอง → ลงจ่ายแล้วทะเบียนคุมเงินโชว์โครงการ"""
    from app.tenancy import session_for
    mark = "ทดสอบเชื่อมโครงการ_"
    s = session_for(1)
    acc = FinanceAccount(name=mark + "เงินอุดหนุน")
    s.add(acc); s.flush()
    it = AccountItem(account_id=acc.id, fiscal_year=FY, name=mark + "ค่ากิจกรรม")
    pj = Project(name=mark + "กีฬาสี", budget=30000, plan_year=2569)
    s.add_all([it, pj]); s.commit()
    acc_id, it_id, pj_id = acc.id, it.id, pj.id
    c = _login()
    try:
        r = c.get(f"/finance/project-sources/{pj_id}?fy={FY}")
        assert r.status_code == 200 and r.json() == {"sources": []}, "โครงการใหม่ยังไม่รู้หมวด"

        r = c.post("/finance/disburse", data={
            "fiscal_year": str(FY), "memo_no": "", "date": "01/11/2569", "subject": mark + "ซื้อป้าย",
            "payee": "ร้านทดสอบ", "amount": "8000", "budget_source": "เงินอุดหนุน",
            "account_id": str(acc_id), "item_id": str(it_id), "project_id": str(pj_id)},
            follow_redirects=False)
        assert r.status_code in (302, 303), r.status_code
        mid = int(r.headers["location"].rstrip("/").split("/")[-1])

        r = c.get(f"/finance/project-sources/{pj_id}?fy={FY}")
        src = r.json()["sources"]
        assert [(x["account_id"], x["item_id"], x["why"]) for x in src] == [(acc_id, it_id, USED_BEFORE)]

        r = c.post(f"/finance/disburse/{mid}/post", follow_redirects=False)
        assert r.status_code in (302, 303)
        r = c.get(f"/finance/accounts/{acc_id}?year={FY}")
        assert r.status_code == 200
        assert f'href="/projects/{pj_id}"' in r.text and mark + "กีฬาสี" in r.text, \
            "รายการจ่ายในทะเบียนคุมเงินต้องโยงกลับไปหน้าโครงการ"

        for url in ("/finance/disburse", f"/finance/disburse/{mid}"):
            r = c.get(url)
            assert r.status_code == 200 and 'id="projSel"' in r.text, url
    finally:
        s.expire_all()
        for t in s.query(FinanceTxn).filter_by(account_id=acc_id).all():
            s.delete(t)
        for m in s.query(DisburseMemo).filter(DisburseMemo.subject.like(mark + "%")).all():
            s.delete(m)
        # บันทึกขอเบิกจ่ายจองเลขในทะเบียนเลขหนังสือกลางด้วย ต้องคืนเลข ไม่งั้นโรงเรียนจริงเลขกระโดด
        from app.models import IssuedDocNo
        for d in s.query(IssuedDocNo).filter(IssuedDocNo.subject.like("%" + mark + "%")).all():
            s.delete(d)
        for x in (s.get(AccountItem, it_id), s.get(Project, pj_id), s.get(FinanceAccount, acc_id)):
            if x is not None:
                s.delete(x)
        s.commit(); s.close()


def _run_js_switch(by_project, steps, acct0="", item0=""):
    """จำลองผู้ใช้เปลี่ยนโครงการทีละขั้น · by_project: {รหัสโครงการ: รายการหมวด}
    steps: [("project", "7") | ("pick", "acct", "item")] คืนสถานะหลังขั้นสุดท้าย"""
    runner = r"""
const [by, steps, acct0, item0] = JSON.parse(process.argv[1]);
function el(id, extra){ return Object.assign({id, value:'', hidden:false, innerHTML:'', className:'',
  attrs:{}, getAttribute(k){ return this.attrs[k]; }, addEventListener(e, f){ this['on_'+e]=f; },
  querySelectorAll(){ return []; }, remove(){} }, extra||{}); }
const N = { projSel: el('projSel', {attrs:{'data-fy':'2570'}}), acctSel: el('acctSel', {value: acct0}),
            itemSel: el('itemSel', {value: item0}), srcLine: el('srcLine'), srcPick: el('srcPick'),
            srcChange: el('srcChange') };
const src = el('src');
global.fillItems = id => { N.itemSel.value = id == null ? '' : String(id); };
global.document = { getElementById: id => N[id] || null,
                    querySelector: q => q.indexOf('budget_source') >= 0 ? src : null };
global.fetch = url => { const pid = url.split('/').pop().split('?')[0];
  return Promise.resolve({ ok: true, json: () => Promise.resolve({ sources: by[pid] || [] }) }); };
require(process.argv[2]);
const tick = () => new Promise(r => setTimeout(r, 10));
(async () => {
  await tick();
  for (const s of steps) {
    if (s[0] === 'project') { N.projSel.value = s[1]; N.projSel.on_change(); }
    else { N.acctSel.value = s[1]; N.itemSel.value = s[2]; }
    await tick();
  }
  console.log(JSON.stringify({ acct: N.acctSel.value, item: N.itemSel.value, src: src.value,
                               pickHidden: N.srcPick.hidden, line: N.srcLine.innerHTML }));
})();
"""
    r = subprocess.run([NODE, "-e", runner, json.dumps([by_project, steps, acct0, item0]), str(SCRIPT)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_switching_to_an_unknown_project_drops_the_previous_projects_category():
    """เจอจากการเปิดหน้าจริง: เลือกกีฬาสี (ระบบเติมหมวดให้) แล้วเปลี่ยนเป็นโครงการที่ยังไม่รู้หมวด
    หมวดของกีฬาสียังค้างอยู่ในช่อง ผู้ใช้กดบันทึกได้ทันทีโดยไม่รู้ตัวว่าหักผิดหมวด"""
    out = _run_js_switch({"1": _ONE, "2": []}, [("project", "1"), ("project", "2")])
    assert out["acct"] == "" and out["item"] == "", "หมวดของโครงการเดิมต้องไม่ค้าง"
    assert out["src"] == "", "ชื่อเงินที่ระบบเติมให้โครงการเดิมต้องไม่ค้าง"
    assert out["pickHidden"] is False and "ครั้งหน้าระบบจำให้" in out["line"]


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_switching_project_keeps_what_the_user_chose_by_hand():
    out = _run_js_switch({"1": _ONE, "2": []},
                         [("project", "1"), ("pick", "5", "55"), ("project", "2")])
    assert out["acct"] == "5" and out["item"] == "55", "ค่าที่ผู้ใช้เลือกเองห้ามลบ"


@pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")
def test_js_switching_back_to_no_project_drops_the_auto_fill_too():
    out = _run_js_switch({"1": _ONE}, [("project", "1"), ("project", "")])
    assert out["acct"] == "" and out["pickHidden"] is False
