# -*- coding: utf-8 -*-
"""หมุนล้อเมาส์บนช่องตัวเลขที่กำลังพิมพ์ ห้ามเปลี่ยนค่า (เจ้าของขอให้ตัดทั้งระบบ กันคำนวณผิด)
รัน: .venv\Scripts\python.exe -m pytest tests/test_no_wheel_number.py
"""
import json
import pathlib
from tests.test_subsidy import env  # noqa: F401  (fixture)
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TAG = '<script src="/static/no-wheel-number.js'


def test_loaded_on_every_page_layout():
    """ทุกหน้าที่มีช่องตัวเลขใช้ base.html ยกเว้นหน้าผู้ดูแลระบบที่เป็นหน้าแยก"""
    for name in ('base.html', 'superadmin.html'):
        assert TAG in (ROOT / 'app/templates' / name).read_text(encoding='utf-8'), name
    standalone = []
    for f in (ROOT / 'app/templates').glob('*.html'):
        s = f.read_text(encoding='utf-8')
        if '<!doctype' in s.lower()[:200] and 'type="number"' in s and TAG not in s:
            standalone.append(f.name)
    assert standalone == [], f'หน้าแยกที่มีช่องตัวเลขแต่ไม่ได้โหลดสคริปต์: {standalone}'


def test_page_includes_script(env):
    assert TAG in env.get('/projects').text


NODE = shutil.which('node')


@pytest.mark.skipif(not NODE, reason='ต้องมี node')
def test_wheel_blurs_only_the_focused_number_input():
    js = (ROOT / 'app/static/no-wheel-number.js').read_text(encoding='utf-8')
    runner = r"""
let handler=null; const log=[];
function inp(type){ return {tagName:'INPUT', type, blurred:false, blur(){ this.blurred=true; }, contains(x){ return x===this; }}; }
const num=inp('number'), text=inp('text'), other=inp('number'), num2=inp('number');
global.document={activeElement:null, addEventListener(ev,fn,opt){ if(ev==='wheel'){handler=fn; log.push(opt);} }};
SCRIPT
function wheel(active,target){ document.activeElement=active; handler({target}); }
wheel(num,num); wheel(text,text); wheel(num2,other);
console.log(JSON.stringify({num:num.blurred, text:text.blurred, num2:num2.blurred, passive:log[0].passive}));
""".replace('SCRIPT', js)
    r = subprocess.run([NODE, '-e', runner], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out == {'num': True, 'text': False, 'num2': False, 'passive': True}, 'หมุนบนช่องอื่นต้องไม่ไปยุ่งช่องที่โฟกัส'


# ---------------- ตารางล้นจอ: บอกให้รู้ว่าเลื่อนขวาได้ ----------------
def test_table_scroll_hint_is_loaded_and_installment_table_is_slim(env):
    import re
    from datetime import datetime
    import app.tenancy as tn
    from app.models import LunchHireRound, LunchInstallment, LunchProgram
    assert '<script src="/static/table-scroll-hint.js' in (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
    with tn.session_for(next(iter(tn._engines))) as s:
        p = LunchProgram(year=2569, operate_mode='hire'); s.add(p); s.flush()
        r = LunchHireRound(program_id=p.id, seq=1); s.add(r); s.flush()
        s.add(LunchInstallment(round_id=r.id, seq=1, days=10, amount=25680, status='จ่ายแล้ว',
                               start_date=datetime(2026, 11, 2), end_date=datetime(2026, 11, 13))); s.commit()
        rid = r.id
    html = env.get(f'/lunch/round/{rid}/plan').text
    head = re.search(r'<table class="iq-table">\s*<thead><tr>(.*?)</tr>', html, re.S).group(1)
    assert head.count('<th') == 6, 'ตารางงวดเหลือ 6 คอลัมน์ (เดิม 10 ล้นจอ)'
    assert '10 วัน <b>25,680.00</b> บาท' in html and '✓ ลงบัญชีแล้ว' in html


@pytest.mark.skipif(not NODE, reason='ต้องมี node')
def test_hint_shows_only_when_there_is_more_to_the_right():
    js = (ROOT / 'app/static/table-scroll-hint.js').read_text(encoding='utf-8')
    runner = r"""
function el(cls){ const e={className:cls||'', children:[], dataset:{}, listeners:{}, style:{},
  classList:{ set:new Set(), toggle(c,on){ on?this.set.add(c):this.set.delete(c); } },
  appendChild(c){ this.children.push(c); c.parentNode=this; }, insertBefore(n,ref){ this.children.push(n); n.parentNode=this; },
  addEventListener(t,f){ this.listeners[t]=f; }, setAttribute(){}, };
  return e; }
const wrap=el('table-wrap'); wrap.scrollWidth=1100; wrap.clientWidth=800; wrap.scrollLeft=0; const card=el('card'); card.appendChild(wrap);
global.window={addEventListener(){}}; global.document={readyState:'complete', createElement:()=>el(''), querySelectorAll:()=>[wrap]};
SCRIPT
const outer=wrap.parentNode, st=()=>[...outer.classList.set].sort().join(' ');
const a=st(); wrap.scrollLeft=300; wrap.listeners.scroll(); const b=st(); wrap.scrollWidth=800; wrap.scrollLeft=0; wrap.listeners.scroll(); const c=st();
console.log(JSON.stringify([a,b,c]));
""".replace('SCRIPT', js)
    r = subprocess.run([NODE, '-e', runner], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == ['tsh-more-r', 'tsh-more-l', ''], 'เริ่ม: ขวายังมี · เลื่อนสุด: เหลือแต่ซ้าย · ไม่ล้น: ไม่มีอะไร'
