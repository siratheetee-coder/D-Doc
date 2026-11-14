from datetime import date,datetime
from pathlib import Path
import json,os
import pytest
from tests.test_subsidy import db,env
from tests.test_shared_school_calendar import setup,close15
from app.models import AcadCalendar,LunchHireRound,LunchInstallment,LunchMealCount,FinanceTxn,LunchLedger,LunchMenu
from app.services import lunch_calendar as lc
from app.services.lunch_meals import workdays

CHOSEN=['2026-12-11','2026-12-14','2026-12-16']

def test_manual_dates_move_only_colliding_following_drafts_and_keep_money(db):
    p,cls,r,a,b=setup(db);close15(db)
    db.add(LunchMealCount(program_id=p.id,date=datetime(2026,12,11),class_id=cls.id,count=106));db.commit()
    plan=lc.preview(db,r,a.id,CHOSEN)
    assert not plan['errors'] and plan['changed']==2
    assert plan['rows'][1]['after']==[date(2026,12,17),date(2026,12,18),date(2026,12,21)]
    before=(a.days,a.amount,b.days,b.amount,db.query(LunchMealCount).count(),db.query(FinanceTxn).count())
    assert lc.apply(db,r,plan['token'],a.id,CHOSEN)==2;db.commit()
    assert workdays(a)==[date.fromisoformat(x) for x in CHOSEN]
    assert before==(a.days,a.amount,b.days,b.amount,db.query(LunchMealCount).count(),db.query(FinanceTxn).count())
    assert a.deliver_date==a.inspect_date==a.end_date==datetime(2026,12,16)
    assert db.query(LunchLedger).count()==0

def test_gaps_makeup_and_untouched_prior_and_following_dates(db):
    p,cls,r,a,b=setup(db)
    db.add(AcadCalendar(year=2569,month=12,days_csv='11,12,14,16,17,18,21,22,23'));db.commit();db.info.clear()
    dates=['2026-12-11','2026-12-12','2026-12-14']
    plan=lc.preview(db,r,a.id,dates);assert not plan['errors'] and plan['changed']==1
    assert plan['rows'][1]['after']==lc.stored_days(b,p)
    lc.apply(db,r,plan['token'],a.id,dates);db.commit()
    assert date(2026,12,12) in workdays(a) and date(2026,12,15) not in workdays(a)
    dates=['2026-12-18','2026-12-22','2026-12-23']
    plan=lc.preview(db,r,b.id,dates);assert not plan['errors'] and plan['changed']==1
    assert plan['rows'][0]['after']==workdays(a)

@pytest.mark.parametrize('chosen',[
    CHOSEN[:2],['2026-12-11']*3,['2026-12-11','2026-12-14','2026-12-15'],
    ['2026-12-09','2026-12-11','2026-12-14'],['bad']*3,None,{},[42]*3])
def test_invalid_dates_block_before_any_mutation(db,chosen):
    p,cls,r,a,b=setup(db);close15(db)
    with pytest.raises(ValueError):lc.preview(db,r,a.id,chosen)
    assert a.end_date==datetime(2026,12,15) and a.calendar_dates is None

@pytest.mark.parametrize('status',['ส่งมอบแล้ว','ตรวจรับแล้ว','จ่ายแล้ว'])
def test_selected_completed_installment_or_following_collision_blocks(db,status):
    p,cls,r,a,b=setup(db);a.status=status;db.commit()
    plan=lc.preview(db,r,a.id,CHOSEN);assert plan['errors']
    with pytest.raises(ValueError):lc.apply(db,r,plan['token'],a.id,CHOSEN)
    db.rollback();a.status='ร่าง';b.status=status;db.commit()
    plan=lc.preview(db,r,a.id,CHOSEN);assert any('ชน' in e for e in plan['errors'])

def test_ledger_link_lock_recorded_days_boundary_and_stale_token(db):
    p,cls,r,a,b=setup(db)
    plan=lc.preview(db,r,a.id,CHOSEN)
    with pytest.raises(ValueError,match='เปลี่ยน'):lc.apply(db,r,plan['token'],b.id,['2026-12-17','2026-12-18','2026-12-21'])
    db.rollback()
    db.add(LunchMealCount(program_id=p.id,date=datetime(2026,12,15),class_id=cls.id,count=0));db.commit()
    with pytest.raises(ValueError,match='เปลี่ยน'):lc.apply(db,r,plan['token'],a.id,CHOSEN)
    db.rollback();plan=lc.preview(db,r,a.id,CHOSEN);assert any('ยอดนักเรียน' in e for e in plan['errors'])
    db.query(LunchMealCount).delete();r.end_date=datetime(2026,12,18);db.commit()
    plan=lc.preview(db,r,a.id,CHOSEN);assert plan['required_end']==date(2026,12,21)
    with pytest.raises(ValueError):lc.apply(db,r,plan['token'],a.id,CHOSEN)
    db.rollback();plan=lc.preview(db,r,b.id,['2026-12-14','2026-12-17','2026-12-18']);assert any('ชน' in e for e in plan['errors'])
    db.add(LunchLedger(program_id=p.id,installment_id=a.id,date=datetime(2026,12,15),kind='จ่าย',amount=7632));db.commit()
    plan=lc.preview(db,r,a.id,CHOSEN);assert plan['rows'][0]['protected'] and plan['errors']

def test_manual_dates_http_preview_confirmation_and_capture(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p,cls,r,a,b=setup(s);close15(s);rid,iid=r.id,a.id
    response=env.get(f'/lunch/installment/{iid}/dates');assert response.status_code==200
    data=response.json();assert not data['readonly'] and data['calendar']['2026-12-15'] is False
    assert env.get('/lunch/installment/999999/dates').status_code==404
    form={'selected_dates':json.dumps(CHOSEN)}
    preview=env.post(f'/lunch/installment/{iid}/dates-preview',data=form)
    assert preview.status_code==200 and 'ตรวจวันที่ที่เลือก' in preview.text and 'หลังแก้ไข' in preview.text
    assert f'/lunch/installment/{iid}/dates-confirm' in preview.text
    import re
    token=re.search(r'name="token" value="([^"]+)"',preview.text).group(1)
    # Preview alone never changes dates.
    with tn.session_for(sid) as s:assert s.get(LunchInstallment,iid).calendar_dates is None
    out=Path(os.environ['LUNCH_PICKER_CAPTURE'])
    (out/'screen-plan.html').write_text(env.get(f'/lunch/round/{rid}/plan').text,encoding='utf-8')
    (out/'screen-review.html').write_text(preview.text,encoding='utf-8')
    (out/'dates.json').write_text(json.dumps(data),encoding='utf-8')
    assert env.post(f'/lunch/installment/{iid}/dates-confirm',data={**form,'token':token},follow_redirects=False).status_code==303
    with tn.session_for(sid) as s:
        assert [d.isoformat() for d in workdays(s.get(LunchInstallment,iid))]==CHOSEN
        s.get(LunchInstallment,iid).status='ตรวจรับแล้ว';s.commit()
    readonly=env.get(f'/lunch/installment/{iid}/dates').json();assert readonly['readonly']
    (out/'dates-readonly.json').write_text(json.dumps(readonly),encoding='utf-8')
    blocked=env.post(f'/lunch/installment/{iid}/dates-preview',data=form)
    assert 'เปิดดูได้อย่างเดียว' in blocked.text and 'class="cr-confirm"' not in blocked.text

def test_director_readonly_and_other_module_denied(env,monkeypatch):
    import app.tenancy as tn,app.main as main
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p,cls,r,a,b=setup(s);iid=a.id
    base=main.get_account_access(1)
    monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'is_director':True})
    response=env.get(f'/lunch/installment/{iid}/dates')
    assert response.status_code==200 and response.json()['readonly']
    assert env.post(f'/lunch/installment/{iid}/dates-preview',data={'selected_dates':json.dumps(CHOSEN)}).status_code==403
    monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,'is_owner':False,'is_director':False,'modules':'finance'})
    assert env.get(f'/lunch/installment/{iid}/dates').status_code==403

@pytest.mark.parametrize('mode',['hire','person'])
def test_generated_documents_only_include_selected_serving_dates(env,mode):
    import app.tenancy as tn
    from docx import Document
    import io
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p,cls,r,a,b=setup(s);p.operate_mode=mode;iid=a.id
        a.calendar_dates=json.dumps(['2026-12-11','2026-12-14','2026-12-16']);a.end_date=datetime(2026,12,16)
        for day,name in [(11,'selected-menu-eleven'),(14,'selected-menu-fourteen'),(15,'excluded-menu-fifteen'),(16,'selected-menu-sixteen')]:
            s.add(LunchMenu(program_id=p.id,date=datetime(2026,12,day),main=name))
        s.commit()
    response=env.get(f'/lunch/installment/{iid}/doc');assert response.status_code==200
    doc=Document(io.BytesIO(response.content))
    text='\n'.join(c.text for t in doc.tables for row in t.rows for c in row.cells)
    assert 'excluded-menu-fifteen' not in text
    for name in ['selected-menu-eleven','selected-menu-fourteen','selected-menu-sixteen']:assert name in text

