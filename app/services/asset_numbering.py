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
