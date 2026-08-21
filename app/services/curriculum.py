# -*- coding: utf-8 -*-
"""
curriculum.py - ตัวชี้วัดตามหลักสูตรแกนกลางการศึกษาขั้นพื้นฐาน พ.ศ. 2551
ชุดข้อมูลกลาง (bundled) เก็บเป็นไฟล์ JSON ที่ app/data/curriculum/<กลุ่มสาระ>.json
ผูกเข้ารายวิชาด้วย "กลุ่มสาระ + ชั้น" (ไม่ใช่รหัสวิชา)

รูปแบบไฟล์: {"area": "ภาษาไทย", "levels": {"ป.6": [{"code","std","seq","text"}, ...]}}
"""
import json
import functools
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent / "data" / "curriculum"

# คำสำคัญจับคู่ learn_group ของรายวิชา -> ชื่อกลุ่มสาระในไฟล์ข้อมูล
_AREA_KEYWORDS = [
    ("ภาษาไทย", ["ไทย"]),
    ("คณิตศาสตร์", ["คณิต"]),
    ("วิทยาศาสตร์และเทคโนโลยี", ["วิทย"]),
    ("สังคมศึกษา ศาสนา และวัฒนธรรม", ["สังคม", "ประวัติ"]),
    ("สุขศึกษาและพลศึกษา", ["สุขศึก", "พลศึก"]),
    ("ศิลปะ", ["ศิลป", "ดนตรี", "นาฏศิลป", "ทัศนศิลป"]),
    ("การงานอาชีพ", ["การงาน", "อาชีพ"]),
    ("ภาษาต่างประเทศ", ["อังกฤษ", "ต่างประเทศ"]),
]


@functools.lru_cache(maxsize=1)
def _load():
    """โหลดทุกไฟล์กลุ่มสาระ -> {(area, level): [items...]}"""
    data = {}
    if _DIR.exists():
        for f in sorted(_DIR.glob("*.json")):
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            area = (j.get("area") or "").strip()
            for lv, items in (j.get("levels") or {}).items():
                data[(area, lv.strip())] = items
    return data


def _area_of(learn_group: str) -> str:
    """แปลง learn_group ของรายวิชา -> ชื่อกลุ่มสาระในไฟล์ข้อมูล"""
    g = (learn_group or "").strip()
    for area, kws in _AREA_KEYWORDS:
        if any(k in g for k in kws):
            return area
    return g


def indicators_for(learn_group: str, level: str):
    """คืนรายการตัวชี้วัดของกลุ่มสาระ+ชั้นนั้น (เรียงตามมาตรฐาน/ลำดับ) · [] ถ้ายังไม่มีข้อมูล"""
    return _load().get((_area_of(learn_group), (level or "").strip()), [])


def has_indicators(learn_group: str, level: str) -> bool:
    return bool(indicators_for(learn_group, level))


def selected_indicators(subject):
    """ตัวชี้วัดที่ใช้จริงของรายวิชา = ที่ครูติ๊กเลือก (subject.indicator_codes คั่นด้วย |)
    ถ้ายังไม่เลือก (ว่าง) = ใช้ทุกตัวของกลุ่มสาระ+ชั้น"""
    allx = indicators_for(subject.learn_group, subject.level)
    csv = (getattr(subject, "indicator_codes", "") or "").strip()
    if not csv:
        return allx
    picked = {c.strip() for c in csv.split("|") if c.strip()}
    sel = [it for it in allx if it["code"] in picked]
    return sel or allx        # ถ้า code ที่เลือกไม่ตรงเลย (เช่นเปลี่ยนชั้น) -> คืนทุกตัวกันหน้าว่าง


def available_areas() -> set:
    """ชื่อกลุ่มสาระที่มีข้อมูลตัวชี้วัดแล้ว (ใช้โชว์สถานะ/หน้าเกี่ยวกับ)"""
    return {area for area, _ in _load().keys()}
