# -*- coding: utf-8 -*-
"""สคริปต์หน้าส่งแผน: เลือกไฟล์แล้วต้องขึ้นช่องชื่อหน่วยให้ครบทุกไฟล์

ถ้าสคริปต์พัง ครูจะไม่เห็นช่องกรอกชื่อหน่วยเลยและไม่มีอะไรฟ้อง เทสต์ฝั่งเซิร์ฟเวอร์
จับไม่ได้เพราะฟอร์มยังส่งไฟล์ได้ตามปกติ จึงต้องรันสคริปต์จริงบน DOM จำลอง
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_lesson_unit_rows_js.py
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(not NODE, reason="ต้องมี node เพื่อรันสคริปต์ฝั่งหน้าจอ")

PAGE = pathlib.Path(__file__).resolve().parents[1] / "app/templates/academic_lesson_plans.html"


def _unit_rows_script() -> str:
    """ดึงเฉพาะก้อน IIFE ที่สร้างช่องชื่อหน่วย ออกมาจากเทมเพลต"""
    html = PAGE.read_text(encoding="utf-8")
    start = html.index("  (function(){\n    var input = document.getElementById('planFiles');")
    end = html.index("</script>", start)
    return html[start:end]


def _run(file_names):
    """จำลอง DOM เท่าที่สคริปต์ใช้ แล้วคืนผลลัพธ์ที่เรนเดอร์ออกมา"""
    script = _unit_rows_script()
    runner = r"""
const files = JSON.parse(process.argv[1]);
function el(id){
  return {id, innerHTML:'', hidden:false, children:[],
          appendChild(c){ this.children.push(c); this.innerHTML += c.innerHTML; },
          addEventListener(ev, fn){ this['on_'+ev] = fn; },
          files: null, className:'', style:{cssText:''}};
}
const nodes = {planFiles: el('planFiles'), unitRows: el('unitRows'), unitList: el('unitList')};
global.document = {
  getElementById: (id) => nodes[id] || null,
  createElement: () => el('div'),
};
SCRIPT_HERE
nodes.planFiles.files = files.map(n => ({name:n}));
nodes.planFiles.on_change();
console.log(JSON.stringify({html: nodes.unitList.innerHTML, hidden: nodes.unitRows.hidden,
                            rows: nodes.unitList.children.length}));
"""
    runner = runner.replace("SCRIPT_HERE", script)
    r = subprocess.run([NODE, "-e", runner, json.dumps(file_names)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_one_row_per_file_with_the_file_name_as_the_default_unit_name():
    out = _run(["หน่วยที่ 1 จำนวนนับ.docx", "unit2.docx", "การวัด.docx"])
    assert out["rows"] == 3, out
    assert out["hidden"] is False
    assert out["html"].count('name="unit_name"') == 3
    assert out["html"].count('name="unit_hours"') == 3
    # ชื่อไฟล์ (ตัดนามสกุล) เป็นค่าตั้งต้นที่โชว์ให้เห็น
    assert 'placeholder="หน่วยที่ 1 จำนวนนับ"' in out["html"]
    assert 'placeholder="unit2"' in out["html"]
    for i in (1, 2, 3):
        assert f"หน่วยที่ {i}" in out["html"]


def test_choosing_no_file_hides_the_block():
    out = _run([])
    assert out["rows"] == 0 and out["hidden"] is True


def test_file_name_is_escaped_so_it_cannot_inject_markup():
    out = _run(['<img src=x onerror=alert(1)>.docx'])
    assert "<img" not in out["html"], out["html"]
    assert "&lt;img" in out["html"]


def test_rows_are_rebuilt_not_appended_when_the_choice_changes():
    """เลือกไฟล์ใหม่ทับของเดิม ต้องไม่เหลือแถวเก่าค้าง"""
    script = _unit_rows_script()
    assert re.search(r"list\.innerHTML\s*=\s*''", script), "ต้องล้างรายการเดิมก่อนสร้างใหม่"
