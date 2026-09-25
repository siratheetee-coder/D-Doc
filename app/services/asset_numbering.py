"""School-local numbering. All writes serialize on the SQLite counter row."""
import re
from sqlalchemy.dialects.sqlite import insert
from app.models import Asset, AssetNumberSeries, AssetNumberCounter, AssetNumberUsed


def lock_numbers(db):
    stmt = insert(AssetNumberCounter).values(key='__lock__', last=0)
    db.execute(stmt.on_conflict_do_update(index_elements=['key'], set_={'last': AssetNumberCounter.last}))
    # Preserve legacy numbers too, including records subsequently edited/deleted.
    for code, in db.query(Asset.asset_code).filter(Asset.asset_code != '').all():
        db.execute(insert(AssetNumberUsed).values(code=code).on_conflict_do_nothing())


def options(form):
    prefix = (form.get('number_prefix') or '').strip().rstrip('-')
    if not re.fullmatch(r'[\w-]{1,50}', prefix) or prefix == '__lock__':
        raise ValueError('กรอกรหัสนำหน้า ใช้ตัวอักษร ตัวเลข หรือขีดกลาง ไม่เกิน 50 ตัว')
    try:
        digits = int(form.get('number_digits', 4))
        year = int(form.get('number_year', 0))
        start = int(form.get('number_start', 1))
    except (ValueError, TypeError):
        raise ValueError('จำนวนหลัก ปี และลำดับเริ่มต้นต้องเป็นตัวเลข')
    if not (1 <= digits <= 8 and 2400 <= year <= 3000 and 1 <= start <= 99999999):
        raise ValueError('ตรวจจำนวนหลัก (1–8) ปี พ.ศ. และลำดับเริ่มต้น (1–99999999)')
    reset = form.get('number_reset') == 'yearly'
    append = form.get('number_append') == 'yes'
    if reset and not append:
        raise ValueError('เมื่อเริ่มลำดับใหม่แต่ละปี ต้องต่อท้ายปีเพื่อไม่ให้เลขซ้ำ')
    return prefix, digits, year, start, reset, append


def next_number(db, form, reserve=False):
    prefix, digits, year, start, reset, append = options(form)
    series = db.get(AssetNumberSeries, prefix)
    if series and (series.digits, series.reset_yearly, series.append_year) != (digits, reset, append):
        raise ValueError('รหัสนำหน้านี้มีรูปแบบที่บันทึกไว้แล้ว กรุณาใช้รูปแบบเดิมหรือรหัสนำหน้าใหม่')
    key = f'{prefix}:{year if reset else "all"}'
    counter = db.get(AssetNumberCounter, key)
    last = counter.last if counter else 0
    pattern = re.compile(re.escape(prefix) + r'-(\d+)' + (r'/(\d{4})' if append else '') + '$')
    codes = {c for c, in db.query(Asset.asset_code).all()} | {c for c, in db.query(AssetNumberUsed.code).all()}
    for code in codes:
        match = pattern.fullmatch(code or '')
        if match and (not reset or int(match[2]) == year):
            last = max(last, int(match[1]))
    number = max(last + 1, start)
    if number > 99999999:
        raise ValueError('ลำดับเกินขอบเขต กรุณาใช้รหัสนำหน้าใหม่')
    code = f'{prefix}-{number:0{digits}d}' + (f'/{year}' if append else '')
    if reserve:
        if not series:
            db.add(AssetNumberSeries(prefix=prefix, digits=digits, reset_yearly=reset, append_year=append))
        if not counter:
            counter = AssetNumberCounter(key=key, last=number)
            db.add(counter)
        counter.last = number
        db.add(AssetNumberUsed(code=code))
    return code


def manual_number(db, code, old_code=None):
    if code and code != old_code:
        if db.get(AssetNumberUsed, code) or db.query(Asset).filter_by(asset_code=code).first():
            raise ValueError('เลขครุภัณฑ์นี้ถูกใช้แล้ว กรุณาใช้เลขอื่น (รวมเลขที่เคยลบหรือจำหน่าย)')
        db.add(AssetNumberUsed(code=code))
    return code


def _parse_code(code):
    """แยกเลขครุภัณฑ์เป็น (นำหน้า, ลำดับ, จำนวนหลัก, ปี) · คืน None ถ้ารูปแบบไม่เข้าเกณฑ์

    รองรับ 3 รูปแบบที่โรงเรียนใช้จริง
      7440-001-0001/2569  รหัส FSN + ปี พ.ศ. เต็ม
      7440-0001           ไม่ต่อท้ายปี
      นอ/01/06/01/59      รหัสทรัพย์สินตามคู่มือฯ (ย่อโรงเรียน/ประเภท/ชนิด/ตัวที่/ปีงบ)
                          ช่องรองสุดท้ายคือ "ตัวที่, เครื่องที่" ซึ่งเป็นตัวที่ต้องรัน
    ปีเก็บตามที่เขียนไว้ (2 หรือ 4 หลัก) เพื่อเขียนกลับให้เหมือนเดิม
    """
    s = (code or '').strip()
    # รูปแบบคั่นด้วย / : ช่องท้าย = ปี, ช่องรองท้าย = ตัวที่
    m = re.fullmatch(r'(.+/)(\d+)/(\d{2}|\d{4})', s)
    if m:
        return m[1], int(m[2]), len(m[2]), m[3]
    m = re.fullmatch(r'(.+)-(\d+)(?:/(\d{4}))?', s)
    if not m:
        return None
    return m[1], int(m[2]), len(m[2]), (m[3] if m[3] else None)


def _join_code(prefix, n, digits, year):
    """ประกอบเลขกลับ โดยคงรูปแบบตัวคั่นเดิม (ลงท้ายด้วย / = รูปแบบรหัสทรัพย์สิน)"""
    body = f'{n:0{digits}d}'
    if prefix.endswith('/'):
        return f'{prefix}{body}/{year}'
    return f'{prefix}-{body}' + (f'/{year}' if year else '')


def _parse_lot(code):
    """แยกเลขแบบช่วง (ลอต) เป็น (นำหน้า, เริ่ม, สิ้นสุด, จำนวนหลัก, ปี)

    คู่มือฯ ให้เขียนครุภัณฑ์ชุดเดียวกันที่เหมือนกันทุกชิ้นเป็นช่วงเลขในทะเบียนใบเดียว
    เช่น นอ/04/01/01-10/59 = ชุดโต๊ะ-เก้าอี้ 10 ชุด ตัวที่ 1 ถึง 10
    """
    s = (code or '').strip()
    m = re.fullmatch(r'(.+/)(\d+)-(\d+)/(\d{2}|\d{4})', s)
    if m:
        a, b = int(m[2]), int(m[3])
        return (m[1], a, b, len(m[2]), m[4]) if b > a else None
    m = re.fullmatch(r'(.+)-(\d+)-(\d+)(?:/(\d{4}))?', s)
    if m:
        a, b = int(m[2]), int(m[3])
        if b > a and len(m[2]) == len(m[3]):
            return m[1], a, b, len(m[2]), (m[4] if m[4] else None)
    return None


def lot_code(code, qty):
    """เลขแบบช่วงสำหรับครุภัณฑ์ชุดเดียวกัน qty ชิ้นที่เก็บเป็นทะเบียนใบเดียว

    นอ/04/01/01/59 + 10 ชิ้น -> นอ/04/01/01-10/59
    คืนค่าเดิมถ้า qty <= 1 หรืออ่านเลขไม่ออก · ถ้าเป็นช่วงอยู่แล้วคืนค่าเดิม
    """
    qty = int(qty or 1)
    if qty <= 1 or _parse_lot(code):
        return (code or '').strip()
    parsed = _parse_code(code)
    if not parsed:
        return (code or '').strip()
    prefix, seq, digits, year = parsed
    last = seq + qty - 1
    body = f'{seq:0{digits}d}-{last:0{digits}d}'
    if prefix.endswith('/'):
        return f'{prefix}{body}/{year}'
    return f'{prefix}-{body}' + (f'/{year}' if year else '')


def expand_lot(code):
    """แตกเลขแบบช่วงเป็นเลขรายชิ้น · ไม่ใช่ช่วงคืน [] (ให้ผู้เรียกไปรันเลขต่อเอง)"""
    parsed = _parse_lot(code)
    if not parsed:
        return []
    prefix, a, b, digits, year = parsed
    if b - a + 1 > 200:
        return []
    return [_join_code(prefix, n, digits, year) for n in range(a, b + 1)]


def _taken(db):
    """เลขครุภัณฑ์ที่ใช้ไปแล้วทั้งหมด (รวมที่เคยลบ/จำหน่าย)"""
    return ({c for c, in db.query(Asset.asset_code).all() if c}
            | {c for c, in db.query(AssetNumberUsed.code).all() if c})


def next_codes_like(db, code, count):
    """เลขถัดไป count เลข ในชุดเดียวกับ code (รันเลขต่อจากเลขที่ใช้ไปแล้ว)
    คืนลิสต์ความยาว count · ถ้าเลขต้นแบบอ่านไม่ออก คืนค่าว่างทั้งหมดให้กรอกเอง"""
    parsed = _parse_code(code)
    if not parsed or count <= 0:
        return [''] * max(count, 0)
    prefix, seq, digits, year = parsed
    taken = _taken(db)
    out, n = [], seq
    while len(out) < count:
        n += 1
        if n > 99999999:
            out.extend([''] * (count - len(out)))
            break
        cand = _join_code(prefix, n, digits, year)
        if cand not in taken:
            out.append(cand)
            taken.add(cand)
    return out


# ฟิลด์ที่คัดลอกไปยังชิ้นที่แยกออกมา (ทุกอย่างยกเว้นเลขครุภัณฑ์/จำนวน/รหัส)
_COPY_FIELDS = ("name", "category", "acquired_date", "useful_life", "salvage_value",
                "location", "funding_source", "vendor_name", "procurement_id", "note",
                "status", "disposed_date", "dispose_method", "dispose_reason",
                "dispose_value", "dispose_doc_ref", "brand_model", "vendor_address",
                "fund_type", "acquire_method", "doc_ref", "unit")


def split_asset(db, asset, cost_mode='each'):
    """แยกครุภัณฑ์แถวเดียวที่มีจำนวน > 1 ออกเป็นรายชิ้น ชิ้นละ 1 ระเบียน

    แถวเดิมเก็บเลขครุภัณฑ์เดิมไว้ (เหลือจำนวน 1) · ชิ้นที่เพิ่มรันเลขต่อในชุดเดียวกัน

    cost_mode ตีความช่อง "ราคาทุน" ของแถวเดิม
      'each'  = เป็นราคาต่อชิ้นอยู่แล้ว  -> ทุกชิ้นใช้ราคาเดิม
      'total' = เป็นราคารวมทั้ง N ชิ้น   -> หารเฉลี่ยให้ชิ้นละเท่า ๆ กัน
                (เศษสตางค์ยกให้ชิ้นแรก ผลรวมจึงเท่าเดิมเป๊ะ ไม่ทำให้ทะเบียนเพี้ยน)
    ช่องราคาทุนในทะเบียนคือราคาของระเบียนนั้น (1 ระเบียน = 1 ชิ้น) และเป็นฐานคิดค่าเสื่อม
    คืนจำนวนชิ้นที่เพิ่ม
    """
    qty = int(asset.quantity or 1)
    if qty <= 1:
        raise ValueError('รายการนี้มีจำนวน 1 อยู่แล้ว ไม่ต้องแยก')
    if qty > 200:
        raise ValueError('แยกได้ครั้งละไม่เกิน 200 ชิ้น')
    each_cost = float(asset.cost or 0)
    first_cost = each_cost
    if cost_mode == 'total':
        each_cost = round(each_cost / qty, 2)
        first_cost = round(float(asset.cost or 0) - each_cost * (qty - 1), 2)   # เก็บเศษไว้ชิ้นแรก
    # ถ้าเลขเดิมเขียนเป็นช่วง (ลอต) ให้แตกช่วงนั้นออกตรง ๆ แถวเดิมรับตัวแรกของช่วง
    lot = expand_lot(asset.asset_code)
    if len(lot) == qty:
        asset.asset_code = lot[0]
        codes = lot[1:]
    else:
        codes = next_codes_like(db, asset.asset_code, qty - 1)
    for code in codes:
        new = Asset(asset_code=code, quantity=1)
        for f in _COPY_FIELDS:
            setattr(new, f, getattr(asset, f))
        new.cost = each_cost
        db.add(new)
        if code:
            db.execute(insert(AssetNumberUsed).values(code=code).on_conflict_do_nothing())
    asset.quantity = 1
    asset.cost = first_cost
    return qty - 1


def cost_groups(db, min_rows=2):
    """กลุ่มครุภัณฑ์ที่เป็นของชุดเดียวกัน (ชื่อ+ประเภท+วันที่ได้มา+เรื่องจัดซื้อเดียวกัน)

    ใช้หาแถวที่แยกรายชิ้นมาแล้วแต่ราคาทุนยังเป็น "ราคารวม" ติดมาทุกแถว
    คืน [{key, name, category, acquired_date, rows, ids, n, each, total, same_cost}]
    เรียงกลุ่มที่น่าสงสัยที่สุดขึ้นก่อน (ราคาทุกแถวเท่ากัน = น่าจะก๊อปมาทั้งก้อน)
    """
    groups = {}
    for a in db.query(Asset).order_by(Asset.asset_code, Asset.id).all():
        key = ((a.name or "").strip(), (a.category or "").strip(),
               a.acquired_date, a.procurement_id)
        groups.setdefault(key, []).append(a)
    out = []
    for key, rows in groups.items():
        if len(rows) < min_rows:
            continue
        costs = [float(r.cost or 0) for r in rows]
        out.append({
            "key": key, "name": key[0], "category": key[1], "acquired_date": key[2],
            "rows": rows, "ids": ",".join(str(r.id) for r in rows), "n": len(rows),
            "each": costs[0] if costs else 0.0, "total": round(sum(costs), 2),
            "same_cost": len(set(costs)) == 1,
        })
    out.sort(key=lambda g: (not g["same_cost"], -g["total"]))
    return out


def set_group_cost(db, ids, mode, value):
    """ตั้งราคาทุนให้ครุภัณฑ์ทั้งกลุ่ม

    mode 'each'  = value คือราคาต่อชิ้น  -> ทุกแถวเท่ากับ value
    mode 'total' = value คือราคารวมทั้งกลุ่ม -> หารเฉลี่ย เศษสตางค์ยกให้แถวแรก
    คืนจำนวนแถวที่แก้
    """
    rows = [a for a in (db.get(Asset, int(i)) for i in ids if str(i).strip().isdigit()) if a]
    if not rows:
        raise ValueError('ไม่พบครุภัณฑ์ที่เลือก')
    value = float(value or 0)
    if value < 0:
        raise ValueError('ราคาทุนต้องไม่ติดลบ')
    n = len(rows)
    if mode == 'total':
        each = round(value / n, 2)
        rest = round(value - each * (n - 1), 2)     # เศษสตางค์ยกให้แถวแรก ผลรวมเท่าที่กรอกเป๊ะ
        for i, a in enumerate(rows):
            a.cost = rest if i == 0 else each
    else:
        for a in rows:
            a.cost = round(value, 2)
    return n
