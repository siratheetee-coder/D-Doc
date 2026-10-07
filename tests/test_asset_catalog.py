"""Reference selection must never infer a code or rewrite existing asset numbers."""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import Asset, AssetNumberSeries, AssetNumberLabel, AssetNumberCounter, AssetNumberUsed
from app.services.asset_catalog import catalog, search, prepare, series_options
from app.services.asset_numbering import next_number, lock_numbers, next_codes_like
from tests.test_subsidy import env


@pytest.fixture
def db():
    engine=create_engine('sqlite://')
    for model in (Asset,AssetNumberSeries,AssetNumberLabel,AssetNumberCounter,AssetNumberUsed):
        model.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def form(**kw):
    data=dict(number_mode='auto',number_choice='catalog',number_catalog_id='53-12',
              number_digits='4',number_year='2570',number_start='1',
              number_reset='yearly',number_append='yes')
    data.update(kw)
    return data


def test_source_integrity_and_ambiguous_codes():
    data=catalog()
    assert len(data['items'])==907
    assert len({r['id'] for r in data['items']})==907
    assert len([r for r in data['items'] if r['ambiguous']])==8
    drawer=next(r for r in data['items'] if r['code']=='7110-0204')
    assert drawer['name']=='ตู้เหล็กเก็บเอกสาร ชนิด 4 ลิ้นชัก'
    assert drawer['page']==53
    assert all(len(r['code'])==9 and r['code'][4]=='-' for r in data['items'])


def test_search_by_words_code_and_school_names(db):
    results=search(db,'ตู้ 4 ลิ้นชัก')
    assert any(r['code']=='7110-0204' for r in results['items'])
    assert search(db,'7110-0204')['items'][0]['name']=='ตู้เหล็กเก็บเอกสาร ชนิด 4 ลิ้นชัก'
    assert search(db,'ไม่พบ123')['total']==0
    db.add(AssetNumberSeries(prefix='SCHOOL-1',digits=3,reset_yearly=False,append_year=False))
    db.add(AssetNumberLabel(prefix='SCHOOL-1',label='ตู้เหล็กแบบเดิม'));db.commit()
    assert search(db,'ตู้เหล็ก')['items'][0]['kind']=='existing'
    assert series_options(db)[0]['name']=='ตู้เหล็กแบบเดิม'


def test_reference_prefix_fixed_and_sequence_separate(db):
    chosen=next(r for r in catalog()['items'] if r['code']=='7110-0204')
    f=form(number_catalog_id=chosen['id'],number_prefix='tampered')
    options=prepare(db,f)
    assert next_number(db,options)=='7110-0204-0001/2570'
    assert db.query(AssetNumberLabel).count()==0 # previews cannot write metadata
    lock_numbers(db)
    number=next_number(db,prepare(db,f,reserve=True),reserve=True)
    db.add(Asset(name='ตู้ 1',asset_code=number));db.commit()
    assert next_number(db,prepare(db,f))=='7110-0204-0002/2570'
    assert next_codes_like(db,number,1)==['7110-0204-0002/2570']
    assert db.get(AssetNumberLabel,'7110-0204').catalog_id==chosen['id']
    assert db.get(AssetNumberSeries,'7110-0204') is not None


def test_ambiguous_and_invalid_selection_rejected(db):
    for row in catalog()['items']:
        if row['ambiguous']:
            with pytest.raises(ValueError,match='ซ้ำ'):prepare(db,form(number_catalog_id=row['id']))
    with pytest.raises(ValueError,match='เลือก'):prepare(db,form(number_catalog_id='nope'))
    with pytest.raises(ValueError):prepare(db,form(number_choice='existing',number_prefix='missing'))
    with pytest.raises(ValueError):prepare(db,form(number_choice='custom',number_prefix='LOCAL'))


def test_existing_format_cannot_be_changed_by_new_picker(db):
    db.add(AssetNumberSeries(prefix='7110-0204',digits=2,reset_yearly=False,append_year=False));db.commit()
    chosen=next(r for r in catalog()['items'] if r['code']=='7110-0204')
    f=prepare(db,form(number_catalog_id=chosen['id']))
    assert next_number(db,f)=='7110-0204-01'
    old=dict(form(),number_prefix='OLD',number_choice='')
    assert prepare(db,old) is old # old clients still work


def test_custom_label_rollback_and_start(db):
    f=form(number_choice='custom',number_prefix='โรงเรียน-01',number_label='โต๊ะของโรงเรียน',number_start='28')
    assert prepare(db, {**f, 'number_prefix': 'โรงเรียน-01-'})['number_prefix']=='โรงเรียน-01'
    lock_numbers(db)
    assert next_number(db,prepare(db,f,reserve=True),reserve=True)=='โรงเรียน-01-0028/2570'
    db.flush();db.rollback()
    assert db.query(AssetNumberLabel).count()==0
    assert db.query(AssetNumberSeries).count()==0


def test_http_preview_add_manual_and_duplicate(env):
    import app.tenancy as tn
    cid=next(r['id'] for r in catalog()['items'] if r['code']=='7110-0204')
    f=form(number_catalog_id=cid)
    page=env.get('/assets')
    assert page.status_code==200 and 'asset-number-picker.js' in page.text
    r=env.get('/assets/catalog-search',params={'q':'ตู้ 4 ลิ้นชัก'})
    assert r.status_code==200 and any(x['code']=='7110-0204' for x in r.json()['items'])
    before=env.get('/assets/number-preview',params=f)
    assert before.json()['code']=='7110-0204-0001/2570'
    f.update(name='ตู้ทดสอบ',quantity='1',unit='ตู้',cost='1000')
    for expected in ('0001','0002'):
        result=env.post('/assets',data=f)
        assert result.status_code==200, result.text[:200]
        assert '7110-0204-'+expected+'/2570' in result.text
    bad=env.post('/assets',data={**f,'number_catalog_id':'43-5'})
    assert bad.status_code==400
    bad_qty=env.post('/assets',data={**f,'quantity':'2'})
    assert bad_qty.status_code==400
    assert env.get('/assets/number-preview',params=f).json()['code']=='7110-0204-0003/2570'
    manual={**f,'number_mode':'manual','asset_code':'เดิม/1/69'}
    assert env.post('/assets',data=manual).status_code==200
    assert env.post('/assets',data=manual).status_code==400
    with tn.session_for(next(iter(tn._engines))) as db:
        assert db.query(AssetNumberLabel).filter_by(prefix='7110-0204').count()==1
