"""Purchase candidates are separate from stock received."""
import json
import math
import re
from uuid import uuid4


def load_selection(raw):
    if raw is None:
        return None
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError("รายการคัดเลือกไม่ถูกต้อง")
    return rows


def parse_selection(form, previous=()):
    rows = []
    valid_keys = {row.get('key') for row in previous}
    used_keys = set()
    indices = sorted({int(m.group(1)) for key in form
                      if (m := re.fullmatch(r"book(\d+)_title", key))})
    for i in indices:
        def text(field):
            return str(form.get(f"book{i}_{field}") or "").strip()
        if not text("title"):
            if any(text(f) for f in ("level", "subject", "publisher")):
                raise ValueError("กรุณากรอกชื่อหนังสือในรายการคัดเลือก")
            continue
        if not text("level"):
            raise ValueError("กรุณาระบุระดับชั้นของหนังสือ")
        try:
            price, qty = float(text("price") or 0), int(text("qty") or 0)
        except ValueError:
            raise ValueError("ราคาและจำนวนหนังสือต้องเป็นตัวเลข")
        if not math.isfinite(price) or price < 0 or qty < 0:
            raise ValueError("ราคาและจำนวนหนังสือต้องไม่ติดลบ")
        key = text('key')
        if key not in valid_keys or key in used_keys:
            key = uuid4().hex
        used_keys.add(key)
        rows.append({"key": key, **{field: text(field) for field in (
            "title", "level", "subject", "publisher", "source_id", "publication")},
            "price": price, "qty": qty, "selected": text("selected") == "1"})
    # เรียงตามระดับชั้น (อนุบาล -> ประถม -> มัธยม) คงลำดับที่กรอกไว้ภายในชั้นเดียวกัน
    from app.thai_utils import level_key
    rows.sort(key=lambda r: level_key(r["level"])[0])
    return rows


def selection_groups(rows, levels, selected_only=True):
    groups = {}
    for row in rows:
        if selected_only and not row.get("selected"):
            continue
        groups.setdefault(row["level"], []).append(row)
    return sorted(groups.items(), key=lambda pair: (
        levels.index(pair[0]) if pair[0] in levels else 99, pair[0]))
