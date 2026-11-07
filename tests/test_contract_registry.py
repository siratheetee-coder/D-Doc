"""Contract register integrity and reviewed imports, isolated tenant fixtures."""
from datetime import datetime,date,timedelta
import json,os
from pathlib import Path
import pytest
from tests.test_subsidy import db,env
from app.models import Contract,Procurement,LunchProgram,LunchHireRound,Vendor
from app.services import contract_registry as cr

def procurement(db,**kwargs):
    data=dict(fiscal_year=2570,subject='ซื้อวัสดุสำนักงาน',order_no='12/2570',order_date=datetime(2026,11,1),
              delivery_due_date=datetime(2026,11,20),total_amount=4500,status='อนุมัติ')
    data.update(kwargs);p=Procurement(**data);db.add(p);db.commit();return p

def lunch(db,p=None,**kwargs):
    program=LunchProgram(year=2569);db.add(program);db.flush()
    data=dict(program_id=program.id,order_no=p.order_no if p else 'L1/2569',order_date=datetime(2026,11,1),
        start_date=datetime(2026,11,2),end_date=datetime(2026,11,20),amount=4500,
        procurement_id=p.id if p else None)
    data.update(kwargs);r=LunchHireRound(**data);db.add(r);db.commit();return r

def apply_all(db,kind,fy=2570):
    v=cr.preview(db,fy,kind);keys=[r['key'] for r in v['rows'] if r['action'] in ('add','update')]
    result=cr.apply(db,fy,kind,keys,v['token']);db.commit();return result

@pytest.mark.parametrize('status,expected',[('ระหว่างดำเนินการ','overdue'),('ส่งมอบแล้ว',None),('ตรวจรับแล้ว',None),('จ่ายแล้ว',None),('สิ้นสุด',None)])
def test_delivery_alerts_stop_after_delivery(db,status,expected):
    c=Contract(status=status,end_date=datetime(2026,11,1),contract_no='12')
    assert cr.alert(c,date(2026,11,7))[1]==expected
    db.add(c);c.fiscal_year=2570;db.commit()
    from app.services.nav import _procurement_alerts
    assert any('12' in a['title'] for a in _procurement_alerts(db,date(2026,11,7)))==bool(expected)

@pytest.mark.parametrize('data',[{'amount':'-1'},{'amount':'nan'},{'amount':'Infinity'},{'amount':'1.001'},
    {'end_date':'31/02/2569'},{'sign_date':'20/11/2569','end_date':'19/11/2569'},
    {'start_date':'20/11/2569','end_date':'19/11/2569'},{'status':'unknown'},{'ctype':'bad'}])
def test_bad_inputs_rejected_before_mutation(data):
    old=Contract(subject='เดิม',amount=10,ctype='ใบสั่งซื้อ',status='ระหว่างดำเนินการ',sign_date=datetime(2026,11,1))
    with pytest.raises(cr.InvalidContract):cr.validate(data,old)
    assert old.amount==10 and old.sign_date==datetime(2026,11,1)

def test_partial_edit_preserves_omitted_dates_and_can_clear_explicitly():
    c=Contract(subject='เดิม',ctype='ใบสั่งซื้อ',status='ระหว่างดำเนินการ',amount=50,sign_date=datetime(2026,11,1))
    assert cr.validate({'subject':'ใหม่'},c)['sign_date']==datetime(2026,11,1)
    assert cr.validate({'sign_date':''},c)['sign_date'] is None

def test_lunch_year_and_shared_procurement_identity(db):
    p=procurement(db);r=lunch(db,p);old=lunch(db,order_no='old',order_date=datetime(2025,8,1),start_date=datetime(2025,8,2),end_date=datetime(2025,8,31))
    v=cr.preview(db,2570,'lunch')
    assert len(v['rows'])==1 and v['excluded']==1
    assert apply_all(db,'lunch')==(1,0)
    v=cr.preview(db,2570,'procurement');assert v['rows'][0]['action']=='same'
    assert db.query(Contract).count()==1
    assert not cr.preview(db,2569,'lunch')['rows']
    # An old import in the wrong year must be reviewed, not copied into another year.
    c=db.query(Contract).one();c.fiscal_year=2569;db.commit()
    assert cr.preview(db,2570,'lunch')['rows'][0]['action']=='blocked'

def test_existing_legacy_aliases_and_duplicates_are_not_silently_deleted(db):
    p=procurement(db);r=lunch(db,p)
    db.add(Contract(fiscal_year=2570,source='lunch',ref_id=r.id,contract_no=p.order_no,subject='เดิม',ctype='ใบสั่งจ้าง',amount=1,status='ระหว่างดำเนินการ'));db.commit()
    assert apply_all(db,'procurement')==(0,1)
    assert db.query(Contract).count()==1
    db.add(Contract(fiscal_year=2570,source='procurement',ref_id=p.id,contract_no=p.order_no));db.commit()
    assert cr.preview(db,2570,'lunch')['rows'][0]['action']=='blocked'
    assert db.query(Contract).count()==2

def test_update_preview_requires_explicit_confirmation_and_stale_forms_rejected(db):
    p=procurement(db);assert apply_all(db,'procurement')==(1,0)
    c=db.query(Contract).one();c.note='เก็บหมายเหตุ';c.warranty_end=datetime(2027,11,1)
    p.subject='ชื่อใหม่';p.status='ตรวจรับแล้ว';db.commit()
    v=cr.preview(db,2570,'procurement');assert v['rows'][0]['action']=='update'
    assert c.subject=='ซื้อวัสดุสำนักงาน'
    assert {'subject','status'}<={d['field'] for d in v['rows'][0]['diffs']}
    p.total_amount=6000;db.commit()
    with pytest.raises(ValueError,match='เปลี่ยน'):cr.apply(db,2570,'procurement',[v['rows'][0]['key']],v['token'])
    db.rollback();assert apply_all(db,'procurement')==(0,1)
    assert c.subject=='ชื่อใหม่' and c.amount==6000 and c.note=='เก็บหมายเหตุ' and c.warranty_end.year==2027
    assert cr.alert(c,date(2026,11,30))==(None,None)

def test_import_without_dates_is_visible_but_blocked_and_bad_selection_cannot_write(db):
    r=lunch(db,order_date=None)
    v=cr.preview(db,2570,'lunch');assert v['rows'][0]['action']=='blocked'
    with pytest.raises(ValueError):cr.apply(db,2570,'lunch',[v['rows'][0]['key']],v['token'])
    assert db.query(Contract).count()==0

def test_manual_same_number_and_party_prevents_import_duplicate(db):
    vendor=Vendor(name='ร้านทดสอบ');db.add(vendor);db.commit();p=procurement(db,vendor_id=vendor.id)
    db.add(Contract(fiscal_year=2570,contract_no=p.order_no,party='ร้านทดสอบ',source='manual'));db.commit()
    assert cr.preview(db,2570,'procurement')['rows'][0]['action']=='blocked'

def test_multiple_linked_lunch_rounds_have_one_stable_import_identity(db):
    p=procurement(db,total_amount=9000)
    lunch(db,p);lunch(db,p,seq=2,start_date=datetime(2026,11,21),end_date=datetime(2026,11,30))
    assert len(cr.preview(db,2570,'lunch')['rows'])==1
    assert apply_all(db,'procurement')==(1,0)
    assert cr.preview(db,2570,'lunch')['rows'][0]['action']=='same'
    assert db.query(Contract).count()==1

def test_replayed_import_and_foreign_selection_do_not_create_duplicates(db):
    p=procurement(db);v=cr.preview(db,2570,'procurement')
    with pytest.raises(ValueError):cr.apply(db,2570,'procurement',['procurement:99999'],v['token'])
    assert db.query(Contract).count()==0
    cr.apply(db,2570,'procurement',[v['rows'][0]['key']],v['token']);db.commit()
    with pytest.raises(ValueError,match='เปลี่ยน'):cr.apply(db,2570,'procurement',[v['rows'][0]['key']],v['token'])
    assert db.query(Contract).count()==1

def test_http_validation_missing_row_dates_and_reviewed_import(env):
    import app.tenancy as tn
    with tn.session_for(next(iter(tn._engines))) as s:
        p=procurement(s);pid=p.id
        c=Contract(fiscal_year=2570,contract_no='M1',subject='เดิม',ctype='ใบสั่งจ้าง',amount=10,
            status='ระหว่างดำเนินการ',sign_date=datetime(2026,11,1));s.add(c);s.commit();cid=c.id
    headers={'X-Requested-With':'fetch'}
    r=env.post(f'/procurement/contracts/{cid}/update',data={'subject':'แก้ชื่อ'},headers=headers)
    assert r.status_code==200 and r.json()['contract']['sign_date']=='01/11/2569'
    assert env.post('/procurement/contracts/99999/update',data={'subject':'x'},headers=headers).status_code==404
    assert env.post(f'/procurement/contracts/{cid}/update',data={'amount':'-2'},headers=headers).status_code==422
    assert env.post('/procurement/contracts/add',data={'fiscal_year':'2570','subject':'x','end_date':'31/02/2569'}).status_code==422
    # Legacy import buttons lead to review; they never bypass consent.
    r=env.post('/procurement/contracts/pull-procurement',data={'fiscal_year':'2570'},follow_redirects=False)
    assert r.status_code==303 and 'import=procurement' in r.headers['location']
    with tn.session_for(next(iter(tn._engines))) as s:
        assert s.query(Contract).count()==1;v=cr.preview(s,2570,'procurement')
    r=env.post('/procurement/contracts/pull-procurement',data={'fiscal_year':'2570','token':v['token'],'selected':[v['rows'][0]['key']]},follow_redirects=False)
    assert r.status_code==303 and 'added=1' in r.headers['location']
    assert env.get('/procurement/contracts/export.xlsx?year=2570').content[:2]==b'PK'
    assert env.get('/procurement/contracts?year=2570').status_code==200

def test_capture_new_ui_and_update_preview(env):
    import app.tenancy as tn
    today=datetime.now().replace(hour=0,minute=0,second=0,microsecond=0)
    with tn.session_for(next(iter(tn._engines))) as s:
        vendor=Vendor(name='ร้านสมใจเครื่องเขียน');s.add(vendor);s.commit()
        p=procurement(s,vendor_id=vendor.id);pid=p.id
        apply_all(s,'procurement');p.total_amount=5000;p.subject='จัดซื้อวัสดุสำนักงาน ประจำภาคเรียน';s.commit()
        for i,(name,status,day) in enumerate([('ซ่อมระบบไฟฟ้าอาคารเรียน','ระหว่างดำเนินการ',-3),('จ้างเหมาประกอบอาหารกลางวัน','ระหว่างดำเนินการ',7),('จัดซื้อวัสดุห้องเรียน','ตรวจรับแล้ว',-10),('จัดซื้ออุปกรณ์กีฬา','ระหว่างดำเนินการ',None)],1):
            s.add(Contract(fiscal_year=2570,contract_no=f'{i}/2570',ctype='ใบสั่งจ้าง',party='บริษัท ตัวอย่าง จำกัด',subject=name,amount=i*3500,status=status,sign_date=today-timedelta(days=20),end_date=today+timedelta(days=day) if day is not None else None))
        s.commit()
    for n,url in [('contracts','/procurement/contracts?year=2570'),('preview','/procurement/contracts?year=2570&import=procurement')]:
        r=env.get(url);assert r.status_code==200,r.text[:200]
        if n=='preview':assert 'ct-diffs' in r.text and 'ข้อมูลต้นทางเปลี่ยน' in r.text and '5,000.00 บาท' in r.text
        if os.environ.get('CONTRACT_CAPTURE'):
            out=Path(os.environ['CONTRACT_CAPTURE']);(out/('screen-'+n+'.html')).write_text(r.text,encoding='utf-8')
            (out/'fixture.json').write_text(json.dumps(dict(pid=pid)),encoding='utf-8')
