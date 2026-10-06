"""Fiscal-year/term estimates for ordinary OBEC schools, with immutable confirmations.

Legacy annual rates/censuses remain untouched. Missing data is not zero; receipts are
explicitly allocated, never matched by account names. FY2569 census advancement rule.
"""
import hashlib
import json
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from sqlalchemy import update
from app.models import (School, Student, SubsidyCensus, SubsidyRate, SubsidyTermSetting,
    SubsidyCensusRevision, SubsidySnapshot, SubsidyReceiptLink, SubsidyBudgetContribution,
    SubsidyBudgetHistory, SubsidyItemMapping, AccountItem, FinanceAccount, FinanceTxn)

LEVELS = [f'อ.{i}' for i in range(1, 4)] + [f'ป.{i}' for i in range(1, 7)] + [f'ม.{i}' for i in range(1, 7)]
ITEMS = [('teach', 'ค่าจัดการเรียนการสอน', True), ('book', 'ค่าหนังสือเรียน', False),
    ('equip', 'ค่าอุปกรณ์การเรียน', True), ('uniform', 'ค่าเครื่องแบบนักเรียน', False),
    ('activity', 'ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน', True)]
EXTRAS = [('small', 'เงินเพิ่มเติมโรงเรียนขนาดเล็ก'), ('poor', 'ปัจจัยพื้นฐานนักเรียนยากจน'),
    ('boarding', 'ค่าอาหารนักเรียนประจำพักนอน'), ('uniform_extra', 'ค่าเครื่องแบบเพิ่มเติม')]
NAMES = {k: n for k, n, _ in ITEMS} | dict(EXTRAS)
BUDGET_BASES = {'estimate': 'ยอดคำนวณจากนักเรียนและอัตรา', 'allocated': 'ยอดจัดสรรจริงที่กรอกครบสองงวด'}
ROUND_LABEL = {'jun': '10 มิถุนายน', 'nov': '10 พฤศจิกายน'}


def dumps(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(x):
    return hashlib.sha256(dumps(x).encode()).hexdigest()


def money(x):
    return float(Decimal(str(x)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def number(raw, label, integer=False):
    if raw is None or str(raw).strip() == '':
        return None
    try:
        n = Decimal(str(raw))
        if not n.is_finite() or n < 0 or n > 1_000_000_000:
            raise ValueError()
        if integer and (n != n.to_integral_value() or n > 1_000_000):
            raise ValueError()
        return int(n) if integer else money(n)
    except (ValueError, InvalidOperation):
        raise ValueError(f'{label}: กรุณากรอกตัวเลขไม่ติดลบ' + (' และเป็นจำนวนเต็ม' if integer else ''))


def fiscal_year(ay, term):
    if not 2500 <= ay <= 2700 or term not in (1, 2):
        raise ValueError('ปีการศึกษาหรือภาคเรียนไม่ถูกต้อง')
    return ay if term == 1 else ay + 1


def keys_for(term):
    return [k for k, _, both in ITEMS if both or term == 1]


def rounds(ay, term):
    return [(ay - 1, 'nov'), (ay, 'jun')] if term == 1 else [(ay, 'jun'), (ay, 'nov')]


def advance_source(level, term):
    if term == 2 or level in ('อ.1', 'อ.2', 'ป.1', 'ม.1', 'ม.4'):
        return level
    return level.split('.')[0] + '.' + str(int(level.split('.')[1]) - 1)


def lock(db):
    db.execute(update(School).values(id=School.id))  # Serialize SQLite read/check/write.


def census(db, year, rnd):
    row = db.query(SubsidyCensusRevision).filter_by(academic_year=year, round=rnd).order_by(SubsidyCensusRevision.id.desc()).first()
    data = json.loads(row.payload) if row else {
        'counts': {r.level: r.count for r in db.query(SubsidyCensus).filter_by(academic_year=year, round=rnd)},
        'source': '', 'confirmed': False}
    return dict(data, id=row.id if row else None, year=year, round=rnd,
        label=f'{ROUND_LABEL[rnd]} {year}', key=f'{rnd}{year}')


def state(db, ay, term):
    fy = fiscal_year(ay, term)
    scans = [census(db, y, r) for y, r in rounds(ay, term)]
    row = db.query(SubsidyTermSetting).filter_by(fiscal_year=fy, term=term).first()
    now = {lv: 0 for lv in LEVELS}
    for lv, in db.query(Student.level):
        if lv in now:
            now[lv] += 1
    if row:
        cfg = json.loads(row.payload)
    else:
        old = db.query(SubsidyRate).filter_by(academic_year=ay).all()
        rates = {}
        for r in old:
            if r.item_key in keys_for(term):
                rates.setdefault(r.level, {})[r.item_key] = money(Decimal(str(r.amount)) / (1 if r.item_key in ('book', 'uniform') else 2))
        levels = [lv for lv in LEVELS if now[lv] or any(r['counts'].get(lv) for r in scans)]
        cfg = {'levels': levels or LEVELS[:9], 'rates': rates,
            'first': {}, 'first_ref': '', 'second': {}, 'second_ref': '', 'extras': {}, 'legacy': bool(old), 'note': ''}
    data = {'academic_year': ay, 'term': term, 'fiscal_year': fy, 'config': cfg, 'census': scans}
    data['token'] = fingerprint(data)
    data['now_counts'] = now
    data['result'] = calculate(cfg, scans, term)
    data['history'] = db.query(SubsidySnapshot).filter_by(academic_year=ay, term=term).order_by(SubsidySnapshot.id.desc()).all()
    data['latest'] = data['history'][0] if data['history'] else None
    data['changed'] = bool(data['latest'] and json.loads(data['latest'].payload)['token'] != data['token'])
    return data


def _group_missing(flat):
    """ยุบข้อความเตือนที่ซ้ำรูปแบบเดียวกันให้เหลือบรรทัดเดียว

    ของเดิมเตือนทีละชั้นทีละรายการ โรงเรียนประถมเปิดหน้าครั้งแรกจะเจอ 47 บรรทัด
    ซึ่งอ่านไม่ออกว่าต้องทำอะไรก่อน · จัดกลุ่มแล้วเหลือ 3-4 บรรทัด
    flat = [(ชนิด, หัวข้อ, รายละเอียด, ชื่อช่องที่ต้องกรอก), ...]
    """
    order, buckets, fields = [], {}, []
    for kind, head, detail, field in flat:
        key = (kind, head)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        if detail:
            buckets[key].append(detail)
        if field:
            fields.append(field)
    out = []
    for kind, head in order:
        items = buckets[(kind, head)]
        if not items:
            out.append(head)
        elif len(items) > 6:
            out.append(f"{head} ({len(items)} ชั้น)")
        else:
            out.append(f"{head} ({', '.join(items)})")
    return out, list(dict.fromkeys(fields))


def calculate(cfg, scans, term):
    rows, missing, basis = [], [], []
    budget_basis = cfg.get('budget_basis', 'estimate')
    allocation_missing, extra_missing = [], []
    for scan in scans:
        if not (scan.get('id') or scan.get('saved') or scan.get('confirmed')):
            missing.append(('census', f"ยังไม่ได้บันทึกยอด DMC {scan['label']}", '', ''))
        if scan.get('year') and datetime(scan['year'] - 543, 6 if scan['round'] == 'jun' else 11, 10).date() > datetime.now(timezone(timedelta(hours=7))).date():
            missing.append(('future', f"DMC {scan['label']} ยังไม่ถึงวันสำรวจ ใช้เป็นประมาณการก่อน", '', ''))
    for lv in cfg['levels']:
        src = advance_source(lv, term)
        basis.append({'level': lv, 'source_level': src, 'advance': scans[0]['counts'].get(src), 'final': scans[1]['counts'].get(lv)})
        if basis[-1]['advance'] is None:
            missing.append(('adv', f"ยังไม่ได้กรอกยอด DMC {scans[0]['label']}", src,
                            f"n_{scans[0]['key']}_{src}"))
        if basis[-1]['final'] is None:
            missing.append(('fin', f"ยังไม่ได้กรอกยอด DMC {scans[1]['label']}", lv,
                            f"n_{scans[1]['key']}_{lv}"))
    for key in keys_for(term):
        initial_est = Decimal(0)
        full = Decimal(0)
        valid_initial = valid_full = True
        for b in basis:
            rate = cfg.get('rates', {}).get(b['level'], {}).get(key)
            if rate is None:
                missing.append(('rate', f'ยังไม่ได้กรอกอัตรา {NAMES[key]}', b['level'],
                                f"r_{b['level']}_{key}"))
                valid_initial = valid_full = False
                continue
            if b['advance'] is None:
                valid_initial = False
            else:
                initial_est += Decimal(str(rate)) * b['advance'] * Decimal('.7')
            if b['final'] is None:
                valid_full = False
            else:
                full += Decimal(str(rate)) * b['final']
        initial = cfg.get('first', {}).get(key)
        used = initial if initial is not None else (money(initial_est) if valid_initial else None)
        full = money(full) if valid_full else None
        second = cfg.get('second', {}).get(key)
        balance = money(Decimal(str(full)) - Decimal(str(used))) if full is not None and used is not None else None
        allocated = money((initial or 0) + (second or 0)) if initial is not None or second is not None else None
        # แยกเป็นคนละข้อความเพื่อไฮไลต์ช่องที่ขาดได้ตรงตัว แต่ยังบอกว่าต้องครบสองงวด
        if initial is None:
            allocation_missing.append(('alloc', 'ยังไม่ได้กรอกยอดจัดสรรงวดแรก '
                                       '(ต้องกรอกให้ครบสองงวด กรอก 0 หากไม่มี)',
                                       NAMES[key], f'first_{key}'))
        if second is None:
            allocation_missing.append(('alloc2', 'ยังไม่ได้กรอกยอดจัดสรรงวดปรับยอด '
                                       '(ต้องกรอกให้ครบสองงวด กรอก 0 หากไม่มี)',
                                       NAMES[key], f'second_{key}'))
        budget_amount = full if budget_basis == 'estimate' else (allocated if initial is not None and second is not None else None)
        rows.append({'key': key, 'name': NAMES[key], 'first_estimate': money(initial_est) if valid_initial else None,
            'first': initial, 'second': second, 'basis': used, 'full': full, 'remaining': balance,
            'allocated': allocated, 'budget_amount': budget_amount, 'extra': False})
    for key, label in EXTRAS:
        extra = cfg.get('extras', {}).get(key)
        if extra is not None:
            if not extra.get('ref'):
                extra_missing.append(('ref', 'ยังไม่ได้ระบุเลขที่หนังสือจัดสรรของเงินเพิ่มเติม',
                                      label, f'extra_ref_{key}'))
            rows.append({'key': key, 'name': label, 'full': extra['amount'], 'allocated': extra['amount'],
                'first_estimate': None, 'first': None, 'second': None, 'remaining': None, 'basis': None,
                'budget_amount': extra['amount'], 'extra': True})
    complete = all(r['full'] is not None for r in rows)
    selected_missing = (missing if budget_basis == 'estimate' else allocation_missing) + extra_missing
    budget_complete = all(r['budget_amount'] is not None for r in rows)
    grouped, fields = _group_missing(selected_missing)
    return {'rows': rows, 'basis': basis, 'missing': grouped, 'missing_fields': fields,
        'estimate_missing': _group_missing(missing)[0], 'budget_basis': budget_basis,
        'budget_label': BUDGET_BASES[budget_basis],
        'budget_total': money(sum(r['budget_amount'] for r in rows)) if budget_complete else None,
        'ready': budget_complete and not selected_missing, 'total': money(sum(r['full'] for r in rows)) if complete else None,
        'known_total': money(sum(r['full'] or 0 for r in rows))}


def save(db, ay, term, form):
    lock(db)
    before = state(db, ay, term)
    if form.get('token') != before['token']:
        raise ValueError('ข้อมูลถูกแก้จากหน้าอื่นแล้ว กรุณารีเฟรชก่อนบันทึก')
    levels = [lv for lv in LEVELS if lv in form.getlist('levels')]
    if not levels:
        raise ValueError('เลือกชั้นเรียนอย่างน้อย 1 ชั้น')
    cfg = {'levels': levels, 'rates': {}, 'first': {}, 'second': {},
        'budget_basis': form.get('budget_basis', 'estimate'),
        'first_ref': (form.get('first_ref') or '').strip(), 'second_ref': (form.get('second_ref') or '').strip(),
        'extras': {}, 'legacy': False, 'note': (form.get('note') or '').strip()}
    if cfg['budget_basis'] not in BUDGET_BASES:
        raise ValueError('เลือกวิธีตั้งงบให้ถูกต้อง')
    for lv in LEVELS:
        cfg['rates'][lv] = {k: number(form.get(f'r_{lv}_{k}'), f'อัตรา {lv}') for k in keys_for(term)}
    for which in ('first', 'second'):
        cfg[which] = {k: number(form.get(f'{which}_{k}'), NAMES[k]) for k in keys_for(term)}
        if any(v is not None for v in cfg[which].values()) and not cfg[which + '_ref']:
            raise ValueError('กรอกเลขที่/วันที่หนังสือแจ้งจัดสรรของแต่ละงวดที่ลงยอดจริง')
    for key, label in EXTRAS:
        values, refs = form.getlist('extra_' + key), form.getlist('extra_ref_' + key)
        if len(values) != len(refs) or len(values) > 100:
            raise ValueError(f'รายการเพิ่มเติม {label} ไม่ครบคู่ หรือเกิน 100 ครั้ง')
        entries = []
        for raw, raw_ref in zip(values, refs):
            value, ref = number(raw, label), (raw_ref or '').strip()
            if value is None and not ref:
                continue
            if value is None:
                raise ValueError(f'กรอกจำนวนเงิน {label}')
            if not ref:
                raise ValueError(f'กรอกหนังสือแจ้งจัดสรร {label}')
            entries.append({'amount': value, 'ref': ref})
        if entries:
            cfg['extras'][key] = {'amount': money(sum(e['amount'] for e in entries)),
                'ref': ' / '.join(e['ref'] for e in entries), 'entries': entries}
    for scan in before['census']:
        prefix = scan['key']
        data = {'counts': {lv: number(form.get(f'n_{prefix}_{lv}'), f'DMC {lv}', True) for lv in LEVELS},
            'saved': True, 'source': '', 'confirmed': False}
        if data != {k: scan.get(k) for k in data}:
            db.add(SubsidyCensusRevision(academic_year=scan['year'], round=scan['round'], payload=dumps(data)))
    row = db.query(SubsidyTermSetting).filter_by(fiscal_year=before['fiscal_year'], term=term).first()
    if row is None:
        row = SubsidyTermSetting(fiscal_year=before['fiscal_year'], term=term)
        db.add(row)
    row.payload = dumps(cfg)
    db.flush()
    return state(db, ay, term)


def confirm(db, ay, term, token):
    lock(db)
    current = state(db, ay, term)
    if token != current['token']:
        raise ValueError('ข้อมูลเปลี่ยนแล้ว กรุณารีเฟรชและตรวจใหม่')
    if not current['result']['ready']:
        raise ValueError('ยังยืนยันไม่ได้: ' + ' · '.join(current['result']['missing']))
    if current['latest'] and not current['changed']:
        return current['latest']
    data = {k: current[k] for k in ('academic_year', 'term', 'fiscal_year', 'config', 'census', 'token', 'result')}
    row = SubsidySnapshot(academic_year=ay, term=term, fiscal_year=current['fiscal_year'], payload=dumps(data))
    db.add(row)
    db.flush()
    return row


def receipt_summary(db, ay, term):
    all_links = db.query(SubsidyReceiptLink).all()
    totals, by_item, details = {}, {}, []
    destinations = mappings(db,fiscal_year(ay,term))
    for link in all_links:
        totals[link.txn_id] = money(totals.get(link.txn_id, 0) + link.amount)
    for link in all_links:
        if (link.academic_year, link.term) != (ay, term):
            continue
        txn = db.get(FinanceTxn, link.txn_id)
        item = destinations.get(link.item_key)
        valid = bool(txn and item and txn.kind == 'in' and txn.item_id == item.id
            and txn.account_id == item.account_id and txn.fiscal_year == item.fiscal_year
            and totals[link.txn_id] <= money(txn.amount))
        if valid:
            by_item[link.item_key] = money(by_item.get(link.item_key, 0) + link.amount)
        details.append({'link': link, 'txn': txn, 'valid': valid, 'name': NAMES[link.item_key]})
    return by_item, details, totals


def link_receipt(db, ay, term, txn_id, key, rnd, raw):
    lock(db)
    fiscal_year(ay, term)
    if key not in keys_for(term) + [k for k, _ in EXTRAS] or rnd not in ('first', 'balance', 'extra'):
        raise ValueError('ประเภทเงินหรืองวดไม่ถูกต้อง')
    txn = db.get(FinanceTxn, txn_id)
    value = number(raw, 'ยอดที่เชื่อม')
    if not txn or txn.kind != 'in' or value is None or value <= 0:
        raise ValueError('เลือกรายการรับเงินและจำนวนมากกว่า 0')
    item = mappings(db,fiscal_year(ay,term)).get(key)
    if not item or txn.account_id != item.account_id or txn.item_id != item.id or txn.fiscal_year != item.fiscal_year:
        raise ValueError('รายการรับไม่ตรงกับหมวดที่จับคู่ไว้ กรุณาตรวจการจับคู่และหมวดของรายการรับ')
    if db.query(SubsidyReceiptLink).filter_by(txn_id=txn_id, academic_year=ay, term=term, item_key=key, round=rnd).first():
        raise ValueError('เชื่อมรายการรับเงินกับงวดนี้แล้ว หากต้องการแก้ยอดให้ยกเลิกการเชื่อมเดิมก่อน')
    used = money(sum(x.amount for x in db.query(SubsidyReceiptLink).filter_by(txn_id=txn_id)))
    if money(used + value) > money(txn.amount):
        raise ValueError('ยอดที่เชื่อมรวมทุกเทอม/รายการเกินเงินรับจริง หรือรายการนี้เชื่อมครบแล้ว')
    db.add(SubsidyReceiptLink(txn_id=txn_id, academic_year=ay, term=term, item_key=key, round=rnd, amount=value))


def mappings(db, fy):
    rows = db.query(SubsidyItemMapping).filter_by(fiscal_year=fy).all()
    return {r.item_key: db.get(AccountItem, r.account_item_id) for r in rows}


def mapping_token(db, fy):
    return fingerprint({k: [v.id, v.account_id, v.fiscal_year] if v else None for k,v in mappings(db,fy).items()})


def save_mapping(db, fy, account_id, choices, token):
    lock(db)
    if not 2500 <= fy <= 2700 or token != mapping_token(db,fy):
        raise ValueError('การจับคู่เปลี่ยนแล้ว กรุณาเปิดหน้าใหม่')
    account = db.get(FinanceAccount,account_id) if account_id else None
    if not account:
        raise ValueError('เลือกบัญชีที่มีอยู่ หากยังไม่มีให้ไปสร้างที่ทะเบียนคุมเงิน')
    desired = {}
    for key in NAMES:
        choice = choices.get(key,'')
        if not choice:
            if key in keys_for(1):
                raise ValueError('เลือกหมวดสำหรับ '+NAMES[key])
            continue
        if choice == 'new':
            matches = db.query(AccountItem).filter_by(account_id=account.id,fiscal_year=fy,name=NAMES[key]).all()
            if matches:
                raise ValueError('มีหมวด '+NAMES[key]+' แล้ว กรุณาเลือกหมวดเดิม')
            item = AccountItem(account_id=account.id,fiscal_year=fy,name=NAMES[key],budget=0)
            db.add(item);db.flush()
        else:
            item = db.get(AccountItem,int(choice))
        if not item or item.account_id != account.id or item.fiscal_year != fy:
            raise ValueError('หมวดไม่ตรงกับบัญชีหรือปีงบที่เลือก')
        if item.id in [i.id for i in desired.values()]:
            raise ValueError('แต่ละรายการต้องใช้คนละหมวด')
        desired[key] = item
    old = mappings(db,fy)
    for key in set(old) | set(desired):
        item = desired.get(key)
        prior = db.query(SubsidyBudgetContribution).join(AccountItem,AccountItem.id==SubsidyBudgetContribution.account_item_id).filter(
            AccountItem.fiscal_year==fy,SubsidyBudgetContribution.item_key==key).all()
        if any(not item or p.account_item_id != item.id for p in prior):
            raise ValueError('รายการนี้เคยตั้งงบแล้ว ต้องตรวจยอดเดิมก่อนเปลี่ยนหมวด: '+NAMES[key])
        links = db.query(SubsidyReceiptLink).filter_by(item_key=key).all()
        for link in links:
            if fiscal_year(link.academic_year,link.term) != fy:
                continue
            txn = db.get(FinanceTxn,link.txn_id)
            if txn and (not item or txn.account_id != item.account_id or txn.item_id != item.id):
                raise ValueError('มีเงินรับที่เชื่อมแล้ว กรุณายกเลิกการเชื่อมก่อนเปลี่ยนหมวด: '+NAMES[key])
    for row in db.query(SubsidyItemMapping).filter_by(fiscal_year=fy).all():db.delete(row)
    db.flush()
    for key,item in desired.items():
        db.add(SubsidyItemMapping(fiscal_year=fy,item_key=key,account_item_id=item.id))
    db.flush()
    return account


def budget_preview(db, snapshot, account_id):
    if not db.get(FinanceAccount, account_id):
        raise ValueError('ไม่พบบัญชีปลายทาง')
    data = json.loads(snapshot.payload)
    # Include removed supplementary categories to subtract only their previous contribution.
    desired = {r['key']: r for r in data['result']['rows']}
    prior_rows = db.query(SubsidyBudgetContribution).filter_by(academic_year=snapshot.academic_year, term=snapshot.term).all()
    for p in prior_rows:
        desired.setdefault(p.item_key, {'key': p.item_key, 'name': NAMES[p.item_key], 'full': 0, 'budget_amount': 0})
    rows = []
    destinations = mappings(db,snapshot.fiscal_year)
    for r in desired.values():
        prior = next((p for p in prior_rows if p.item_key == r['key']), None)
        item = destinations.get(r['key'])
        if not item or item.account_id != account_id or item.fiscal_year != snapshot.fiscal_year:
            raise ValueError('กรุณาจับคู่หมวดทะเบียนคุมก่อนตั้งงบ: '+r['name'])
        if prior and prior.account_item_id != item.id:
            raise ValueError('เคยตั้งงบไว้ในหมวดอื่น กรุณาตรวจยอดเดิมก่อนเปลี่ยนหมวด')
        old = money(item.budget or 0) if item else 0
        previous = money(prior.amount) if prior else 0
        contribution = r.get('budget_amount', r['full'])  # Old snapshots retain their original estimate basis.
        if contribution is None:
            raise ValueError('ยอดที่จะตั้งงบยังไม่ครบ กรุณาบันทึกและยืนยันข้อมูลก่อน')
        delta = money(contribution - previous)
        new = money(old + delta)
        if new < 0:
            raise ValueError('งบปลายทางถูกแก้จนต่ำกว่าส่วนที่จะปรับลด กรุณาตรวจทะเบียนคุม')
        rows.append({'key': r['key'], 'name': r['name'], 'item_id': item.id if item else None,
            'destination': item.name, 'old': old, 'previous': previous, 'contribution': contribution, 'delta': delta, 'new': new})
    return {'rows': rows, 'account_id': account_id, 'snapshot_id': snapshot.id, 'fiscal_year': snapshot.fiscal_year,
        'budget_label': data['result'].get('budget_label', BUDGET_BASES['estimate'])}


def apply_budget(db, snapshot, account_id, token):
    lock(db)
    current = state(db, snapshot.academic_year, snapshot.term)
    if current['changed'] or not current['latest'] or current['latest'].id != snapshot.id:
        raise ValueError('มีข้อมูลฉบับใหม่แล้ว กรุณายืนยันและดูยอดเปรียบเทียบใหม่ก่อนตั้งงบ')
    preview = budget_preview(db, snapshot, account_id)
    if token != fingerprint(preview):
        raise ValueError('ยอดงบปลายทางเปลี่ยนแล้ว กรุณาเปิดหน้าเปรียบเทียบใหม่')
    for r in preview['rows']:
        item = db.get(AccountItem, r['item_id']) if r['item_id'] else None
        if not item:
            item = AccountItem(account_id=account_id, fiscal_year=snapshot.fiscal_year, name=r['name'], budget=0)
            db.add(item)
            db.flush()
        item.budget = r['new']
        prior = db.query(SubsidyBudgetContribution).filter_by(academic_year=snapshot.academic_year, term=snapshot.term, item_key=r['key']).first()
        if not prior:
            prior = SubsidyBudgetContribution(academic_year=snapshot.academic_year, term=snapshot.term,
                item_key=r['key'], account_item_id=item.id)
            db.add(prior)
        prior.amount = r['contribution']
        prior.snapshot_id = snapshot.id
    db.add(SubsidyBudgetHistory(snapshot_id=snapshot.id, payload=dumps(preview)))
    return preview
