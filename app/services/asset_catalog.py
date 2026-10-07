"""Searchable reference, with source codes kept verbatim and tenant-local series labels."""
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from app.models import AssetNumberSeries, AssetNumberLabel


@lru_cache(maxsize=1)
def catalog():
    data = json.loads((Path(__file__).resolve().parents[1] / 'data' / 'asset_catalog.json').read_text(encoding='utf-8'))
    counts = Counter(row['code'] for row in data['items'])
    for row in data['items']:
        row['ambiguous'] = counts[row['code']] > 1
    return data


def compact(value):
    return re.sub(r'\s+', '', value.replace('ํา', 'ำ')).casefold()


def series_options(db):
    labels = {r.prefix: r.label for r in db.query(AssetNumberLabel)}
    return [dict(prefix=r.prefix, name=labels.get(r.prefix, 'ชุดรหัสเดิมของโรงเรียน'),
                 digits=r.digits, reset=r.reset_yearly, append=r.append_year)
            for r in db.query(AssetNumberSeries).order_by(AssetNumberSeries.prefix)]


def search(db, query, limit=30):
    query = str(query or '').strip()[:120]
    tokens = [compact(token) for token in query.split()]
    def matches(row):
        text = compact(row['name'] + row['code'])
        return all(token in text for token in tokens)
    saved = [dict(id=r['prefix'], name=r['name'], code=r['prefix'], kind='existing',
                  ambiguous=False, **{k:r[k] for k in ('digits','reset','append')}) for r in series_options(db)]
    found = [r for r in saved if matches(r)]
    references = [dict(r, kind='catalog') for r in catalog()['items'] if matches(r)]
    # Common school equipment first; no codes are inferred from a user's free text.
    references.sort(key=lambda r: (r['ambiguous'], r['code'][:2] not in ('71','74','41','58','67','78'),
                                   len(r['name']), r['code']))
    found.extend(references)
    return dict(items=found[:limit], total=len(found), source_url=catalog()['source_url'])


def prepare(db, form, *, reserve=False):
    """Validate selections on the server, then reuse the transactional sequence allocator.

    With no number_choice, old clients retain their previous numbering semantics.
    The reference code is the entire immutable prefix; the per-item sequence follows it.
    """
    choice = form.get('number_choice', '')
    if not choice:
        return form
    out = dict(form)
    label, catalog_id = '', ''
    if choice == 'catalog':
        row = next((r for r in catalog()['items'] if r['id'] == form.get('number_catalog_id')), None)
        if not row:
            raise ValueError('เลือกรายการครุภัณฑ์จากผลการค้นหาก่อน')
        if row['ambiguous']:
            raise ValueError('รหัสรายการนี้ซ้ำกับอีกชนิดในต้นฉบับ กรุณาตรวจคู่มือหรือใช้รหัสตามทะเบียนของโรงเรียน')
        out['number_prefix'], label, catalog_id = row['code'], row['name'], row['id']
    elif choice == 'existing':
        if not db.get(AssetNumberSeries, form.get('number_prefix', '')):
            raise ValueError('ไม่พบชุดรหัสของโรงเรียน กรุณาเลือกใหม่')
    elif choice == 'custom':
        label = str(form.get('number_label') or '').strip()
        if not label or len(label) > 200:
            raise ValueError('ตั้งชื่อชุดรหัสของโรงเรียน ไม่เกิน 200 ตัวอักษร')
    else:
        raise ValueError('เลือกรายการครุภัณฑ์หรือใช้เลขตามทะเบียนเดิม')
    from app.services.asset_numbering import options
    prefix = str(out.get('number_prefix') or '').strip().rstrip('-')
    saved = db.get(AssetNumberSeries, prefix)
    if saved:
        out.update(number_digits=saved.digits, number_reset='yearly' if saved.reset_yearly else 'continuous',
                   number_append='yes' if saved.append_year else 'no')
    prefix, *_ = options(out)
    out['number_prefix'] = prefix
    if reserve and label and not db.get(AssetNumberLabel, prefix):
        db.add(AssetNumberLabel(prefix=prefix, label=label, catalog_id=catalog_id))
    return out
