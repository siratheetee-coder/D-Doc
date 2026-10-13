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
