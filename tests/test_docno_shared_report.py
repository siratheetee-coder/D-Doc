from datetime import datetime
from pathlib import Path
import os
import pytest
from fastapi import HTTPException
from app import models as m
from app.services import doc_number as dn,doc_register as reg
from app.routers.pages import _sync_proc_docnos
from tests.test_subsidy import db,env


def linked(db,field='inspect_memo_no'):
    a=m.FinanceAccount(name='เงินอุดหนุน',deposit_type='bank');db.add(a);db.flush()
    p=m.Procurement(fiscal_year=2570,proc_type='จ้าง',subject='อาหารกลางวัน โครงการพัฒนาครู',total_amount=1800,
        request_date=datetime(2026,11,12),inspect_date=datetime(2026,11,12),**{field:'219/2570'})
    db.add(p);db.flush();_sync_proc_docnos(db,p)
    memo=m.DisburseMemo(procurement_id=p.id,fiscal_year=2570,memo_no='219/2570',subject=p.subject,
        date=datetime(2026,11,12),account_id=a.id,amount=1800,status='ร่าง')
    db.add(memo);db.commit();return p,memo,a


@pytest.mark.parametrize('field',['inspect_memo_no','memo_no'])
def test_linked_shared_report_can_save_both_sources_without_overwriting_owner(db,field):
    p,memo,a=linked(db,field)
    original=db.query(m.IssuedDocNo).one();before=(original.source,original.ref_id,original.subject,original.date)
    dn.commit_doc_no(db,'memo',2570,memo.memo_no,source='finance',ref_id=memo.id,subject=memo.subject,date=memo.date)
    db.commit()
    assert (original.source,original.ref_id,original.subject,original.date)==before
    assert db.query(m.IssuedDocNo).count()==1
    rows=[r for r in reg.records(db) if r.doc_type=='memo' and r.seq==219]
    assert len(rows)==1 and not rows[0].conflict
    warning=dn.check_doc_no(db,'memo',2570,memo.memo_no,exclude_source='finance',exclude_ref=memo.id)
    assert warning is None or warning['level']!='duplicate'
    _sync_proc_docnos(db,p);db.commit()
    assert db.query(m.IssuedDocNo).one().source=='procurement'


def test_unrelated_memo_with_identical_number_and_title_is_still_rejected(db):
    p,memo,a=linked(db)
    other=m.DisburseMemo(fiscal_year=2570,memo_no='219/2570',subject=p.subject,account_id=a.id,amount=1800)
    db.add(other);db.flush()
    with pytest.raises(HTTPException) as err:
        dn.commit_doc_no(db,'memo',2570,other.memo_no,source='finance',ref_id=other.id)
    assert err.value.status_code==409
    db.rollback()
    assert db.query(m.IssuedDocNo).one().source=='procurement'


def test_second_finance_claim_for_same_procurement_is_not_a_shared_report(db):
    p,memo,a=linked(db)
    other=m.DisburseMemo(procurement_id=p.id,fiscal_year=2570,memo_no='219/2570',subject=p.subject,amount=1800)
    db.add(other);db.flush()
    with pytest.raises(HTTPException):dn.commit_doc_no(db,'memo',2570,other.memo_no,source='finance',ref_id=other.id)
    db.rollback()


def test_stale_registry_pointer_does_not_block_a_real_source_and_numbers_stay_reserved(db):
    p=m.SchoolOrder(fiscal_year=2569,order_no='81/2569',subject='เรื่องจริง')
    db.add(p);db.flush()
    db.add(m.IssuedDocNo(doc_type='command',fiscal_year=2569,seq=81,full_no='81/2569',source='admin',ref_id=99999))
    db.commit()
    dn.commit_doc_no(db,'command',2569,'81/2569',source='admin',ref_id=p.id,subject=p.subject)
    db.commit()
    assert db.query(m.IssuedDocNo).one().ref_id==p.id
    assert dn.suggest_next(db,'command',2569)==82


def test_http_save_original_219_shared_report_succeeds_and_new_duplicate_rolls_back(env):
    import app.tenancy as tn
    db=tn.session_for(next(iter(tn._engines)))
    try:
        p,memo,a=linked(db)
        data={'memo_no':'219/2570','date':'12/11/2569','subject':p.subject,'amount':'1800',
              'account_id':str(a.id),'status':'ร่าง','proc_kind':'จัดจ้าง'}
        result=env.post(f'/finance/disburse/{memo.id}/update',data=data,follow_redirects=False)
        assert result.status_code==303,result.text[:300]
        r=env.get(result.headers['location']);assert r.status_code==200
        out=Path(os.environ['SHARED_REPORT_CAPTURE'])
        (out/'shared-finance.html').write_text(r.text,encoding='utf-8')
        r=env.get('/docnos?year=2570');assert r.status_code==200
        assert 'เลขซ้ำกับเอกสารอื่น' not in r.text
        (out/'shared-register.html').write_text(r.text,encoding='utf-8')
        result=env.post('/finance/disburse',data=dict(data,fiscal_year='2570'),follow_redirects=False)
        assert result.status_code==409,result.text[:300]
        db.expire_all()
        assert db.query(m.DisburseMemo).filter_by(memo_no='219/2570').count()==1
        assert db.query(m.IssuedDocNo).filter_by(doc_type='memo',seq=219).one().source=='procurement'
    finally:db.close()
