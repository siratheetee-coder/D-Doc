# -*- coding: utf-8 -*-
"""หน้าโครงการ: ใส่งบตรง ๆ + ปรับงบให้เชื่อมกับการจัดสรรเงิน

1. งบเป็น 0 ใส่ได้เลย / มีงบแล้วกด "แก้งบ" ได้ ตราบใดที่ยังไม่เคยปรับงบ (เจ้าของเลือกแบบมีปุ่มแก้งบ)
   เดิมทางเดียวคือ "ปรับงบ ครั้งที่ 1" ทั้งที่แค่ใส่งบครั้งแรก
2. ปรับงบเพิ่ม: พาไปช่องจัดสรร เติมยอดใหม่ไว้ให้ (ปรับงบเปลี่ยนแค่ตัวเลขแผน เงินผูกผ่านการจัดสรร)
3. ปรับงบลดต่ำกว่าที่จัดสรร: กลับหน้าเดิมพร้อมบอกวิธีแก้ (เดิมเด้งไปหน้าข้อผิดพลาด 409)
รัน: .venv\Scripts\python.exe -m pytest tests/test_project_budget_edit.py
"""
import pathlib
import re
from urllib.parse import unquote

import pytest

from tests.test_subsidy import env  # noqa: F401  (fixture)
from tests.test_plan_funding import import_all
from app.models import FinanceAccount, AccountItem, Project, ProjectBudgetRevision
from app.services import plan_funding as pf

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def world(env):
    """แผนปีงบ 2570 มีเงินหมวดกิจกรรม 50,000 นำเข้าแผนแล้ว · กีฬาสี งบ 30,000 จัดสรรครบ · ค่าย งบ 0"""
    import app.tenancy as tn
    sid = next(iter(tn._engines))
    env.post('/plan-budget/2570/period', data=dict(mode='budget', start='01/10/2569', end='30/09/2570'))
    with tn.session_for(sid) as s:
        a = FinanceAccount(name='เงินอุดหนุน'); s.add(a); s.flush()
        s.add(AccountItem(account_id=a.id, fiscal_year=2570, name='กิจกรรม', opening_balance=50000)); s.commit()
        p = pf.plan(s, 2570); import_all(s, p, 'opening')
        sport = Project(name='กีฬาสี', plan_year=2570, budget=30000)
        camp = Project(name='ค่าย', plan_year=2570, budget=0)
        s.add_all([sport, camp]); s.commit()
        fid = pf.sources(s, p)[0].id
        pf.allocate(s, p, sport, {str(fid): '30000'}, pf.allocation_token(s, p, sport)); s.commit()
        return dict(sid=sid, sport=sport.id, camp=camp.id, fid=fid)


def _proj(w, pid):
    import app.tenancy as tn
    with tn.session_for(w['sid']) as s:
        p = s.get(Project, pid)
        return float(p.budget or 0), [(r.seq, r.amount) for r in p.revisions]


def test_zero_budget_can_be_entered_directly(env, world):
    html = env.get(f"/projects/{world['camp']}").text
    assert 'โครงการนี้ยังไม่ได้ใส่งบ' in html and f'action="/projects/{world["camp"]}/set-budget"' in html
    env.post(f"/projects/{world['camp']}/set-budget", data={'amount': '25,000'})
    assert _proj(world, world['camp']) == (25000, []), "ใส่งบครั้งแรกต้องไม่นับเป็นการปรับงบ"
    html = env.get(f"/projects/{world['camp']}").text
    assert 'โครงการนี้ยังไม่ได้ใส่งบ' not in html and '>แก้งบ</button>' in html


def test_edit_button_goes_away_once_revised(env, world):
    env.post(f"/projects/{world['camp']}/set-budget", data={'amount': '25000'})
    env.post(f"/projects/{world['camp']}/revise", data={'amount': '27000', 'reason': 'แผนเปลี่ยน'})
    html = env.get(f"/projects/{world['camp']}").text
    assert '>แก้งบ</button>' not in html and 'id="setBudget"' not in html
    r = env.post(f"/projects/{world['camp']}/set-budget", data={'amount': '1'}, follow_redirects=False)
    assert 'err=' in r.headers['location'] and _proj(world, world['camp'])[0] == 25000


def test_raising_the_budget_leads_to_allocation_with_the_new_amount_filled_in(env, world):
    r = env.post(f"/projects/{world['sport']}/revise", data={'amount': '32000', 'reason': 'เพิ่มกิจกรรม'},
                 follow_redirects=False)
    assert r.headers['location'].endswith('?saved=1&grew=1#project-funding')
    html = env.get(r.headers['location'].split('#')[0]).text
    assert 'ยังไม่ได้จัดสรรอีก <b>2,000.00</b>' in html
    assert '<div class="pf-grew">' in html, "ห้ามใช้ class alert ระบบจะแปลงเป็น toast แล้วหายไป"
    assert re.search(rf'name="fund_{world["fid"]}"[^>]*value="32000.0"', html), "เติมยอดใหม่ไว้ให้ในหมวดเดิม"


def test_short_of_money_in_the_plan_says_so(env, world):
    r = env.post(f"/projects/{world['sport']}/revise", data={'amount': '90000'}, follow_redirects=False)
    html = env.get(r.headers['location'].split('#')[0]).text
    assert 'ยังจัดสรรไม่ได้อีก 40,000.00 บาท' in html and re.search(
        rf'name="fund_{world["fid"]}"[^>]*value="50000.0"', html)


def test_lowering_below_allocation_stays_on_the_page_and_explains(env, world):
    r = env.post(f"/projects/{world['sport']}/revise", data={'amount': '25000'}, follow_redirects=False)
    assert r.status_code == 303 and 'err=' in r.headers['location'], "ต้องไม่เด้งไปหน้าข้อผิดพลาด 409"
    msg = unquote(r.headers['location'])
    assert '30,000.00' in msg and 'ลดการจัดสรร' in msg
    assert _proj(world, world['sport'])[1] == [], "ไม่ผ่านต้องไม่บันทึกการปรับงบ"
    r = env.post(f"/projects/{world['sport']}/set-budget", data={'amount': '20000'}, follow_redirects=False)
    assert 'err=' in r.headers['location'] and _proj(world, world['sport'])[0] == 30000


def test_floor_counts_spending_before_the_system(env, world):
    import app.tenancy as tn
    with tn.session_for(world['sid']) as s:
        p = pf.plan(s, 2570); camp = s.get(Project, world['camp'])
        camp.budget, camp.spent_before = 30000, 8000; s.commit()
        pf.allocate(s, p, camp, {str(world['fid']): '20000'}, pf.allocation_token(s, p, camp)); s.commit()
    r = env.post(f"/projects/{world['camp']}/revise", data={'amount': '27000'}, follow_redirects=False)
    assert 'err=' in r.headers['location'] and '28,000.00' in unquote(r.headers['location'])
    r = env.post(f"/projects/{world['camp']}/revise", data={'amount': '28000'}, follow_redirects=False)
    assert 'err=' not in r.headers['location']


def test_page_warns_before_submitting(env, world):
    html = env.get(f"/projects/{world['sport']}").text
    assert 'var assigned = 30000' in html and html.count('class="pj-budget-in"') >= 1


NODE = __import__('shutil').which('node')


@pytest.mark.skipif(not NODE, reason='ต้องมี node')
def test_live_warning_script(env, world):
    import json, subprocess
    html = env.get(f"/projects/{world['sport']}").text
    script = re.search(r'<script>\s*(\(function \(\) \{\s*var assigned.*?\}\)\(\);)\s*</script>', html, re.S).group(1)
    runner = r"""
const vals = JSON.parse(process.argv[1]), out = [];
function mk(v){ const msg={hidden:true,className:'',innerHTML:'',textContent:''}, btn={disabled:false};
  const inp={value:v, addEventListener(e,f){this.f=f;}, form:{querySelector:q=>q==='.pj-bmsg'?msg:btn}}; return {inp,msg,btn}; }
const items = vals.map(mk);
global.document = {querySelectorAll: () => items.map(x => x.inp)};
SCRIPT
items.forEach(x => out.push({bad: x.msg.className.includes('is-bad'), up: x.msg.className.includes('is-up'),
                              disabled: x.btn.disabled, text: x.msg.innerHTML || x.msg.textContent}));
console.log(JSON.stringify(out));
""".replace('SCRIPT', script)
    r = subprocess.run([NODE, '-e', runner, json.dumps(['25000', '30000', '32000'])], capture_output=True,
                       text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    low, same, up = json.loads(r.stdout)
    assert low['bad'] and low['disabled'] and '30,000.00' in low['text']
    assert not same['bad'] and not same['up'] and not same['disabled']
    assert up['up'] and 'งบเพิ่ม 2,000.00' in up['text'] and not up['disabled']


def test_script_comes_after_both_budget_forms(env, world):
    """สคริปต์หาฟอร์มตอนรัน วางก่อนฟอร์มปรับงบแล้วคำเตือนไม่ขึ้นบนหน้าจริง (เทสต์ node จับไม่ได้)"""
    html = env.get(f"/projects/{world['camp']}").text
    pos = html.index('var assigned')
    assert html.index('action="/projects/%d/revise"' % world['camp']) < pos
    assert html.index('id="setBudget"') < pos
