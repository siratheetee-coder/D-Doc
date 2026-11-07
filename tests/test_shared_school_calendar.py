"""Shared academic/lunch calendar, frozen history and explicit draft realignment."""
from datetime import datetime,date
from pathlib import Path
from types import SimpleNamespace
import json,os
import pytest
from tests.test_subsidy import db,env
from app.models import (AcadCalendar,AcadHoliday,LunchProgram,LunchClass,LunchHireRound,LunchInstallment,
                        LunchMealCount,LunchLedger,FinanceTxn)
from app.services import school_calendar as sc,lunch_calendar as lc
from app.services.lunch_meals import workdays

def setup(db):
    p=LunchProgram(year=2569,rate_per_head=24,operate_mode='hire');db.add(p);db.flush()
    cls=LunchClass(program_id=p.id,seq=1,level='ป.1',num_students=106);db.add(cls)
    r=LunchHireRound(program_id=p.id,seq=1,start_date=datetime(2026,12,11),end_date=datetime(2026,12,31),days=6,amount=15264,status='จ้างแล้ว')
    db.add(r);db.flush()
    a=LunchInstallment(round_id=r.id,seq=1,start_date=datetime(2026,12,11),end_date=datetime(2026,12,15),days=3,amount=7632,status='ร่าง',deliver_date=datetime(2026,12,15),inspect_date=datetime(2026,12,15))
    b=LunchInstallment(round_id=r.id,seq=2,start_date=datetime(2026,12,16),end_date=datetime(2026,12,18),days=3,amount=7632,status='ร่าง',deliver_date=datetime(2026,12,18),inspect_date=datetime(2026,12,18))
    db.add_all([a,b]);db.commit();return p,cls,r,a,b

def close15(db):
    db.add(AcadHoliday(year=2569,month=12,day=15,name='วันหยุดพิเศษ',kind='other'));db.commit()
    db.info.clear()

def test_shared_holiday_and_explicit_saturday_makeup(db):
    close15(db)
    state=sc.state(db,2569);assert not state['2026-12-15'] and state['2026-12-16']
    db.add(AcadCalendar(year=2569,month=12,days_csv='11,12,14,16,17,18'));db.commit();db.info.clear()
    assert sc.state(db,2569)['2026-12-12'] is True
    assert sc.ranges(db,2569,date(2026,12,11),[3])[0]==[date(2026,12,11),date(2026,12,12),date(2026,12,14)]

def test_preview_then_apply_keeps_money_and_counts_and_moves_following_installments(db):
    p,cls,r,a,b=setup(db);old=workdays(a);close15(db)
    assert workdays(a)==old and date(2026,12,15) in old
    db.add(LunchMealCount(program_id=p.id,date=datetime(2026,12,11),class_id=cls.id,count=106));db.commit()
    plan=lc.preview(db,r);assert not plan['errors'] and plan['changed']==2
    assert plan['rows'][0]['end']==date(2026,12,16) and plan['rows'][1]['start']==date(2026,12,17)
    facts=(a.amount,b.amount,db.query(LunchMealCount).count(),db.query(FinanceTxn).count())
    assert lc.apply(db,r,plan['token'])==2;db.commit()
    assert a.end_date==datetime(2026,12,16) and b.start_date==datetime(2026,12,17)
    assert a.deliver_date==a.end_date and a.inspect_date==a.end_date
    assert date(2026,12,15) not in workdays(a) and date(2026,12,16) in workdays(a)
    assert facts==(a.amount,b.amount,db.query(LunchMealCount).count(),db.query(FinanceTxn).count())
    # Future calendar edits do not change the newly confirmed served-day list.
    db.add(AcadHoliday(year=2569,month=12,day=16,name='หยุดเพิ่ม',kind='other'));db.commit();db.info.clear()
    assert date(2026,12,16) in workdays(a)

@pytest.mark.parametrize('status',['ส่งมอบแล้ว','ตรวจรับแล้ว','จ่ายแล้ว'])
def test_completed_installments_are_preserved(db,status):
    p,cls,r,a,b=setup(db);a.status=status;db.commit();close15(db)
    plan=lc.preview(db,r);assert plan['rows'][0]['protected'] and not plan['rows'][0]['changed']
    original=(a.start_date,a.end_date,a.amount,a.calendar_dates)
    if plan['changed'] and not plan['errors']:lc.apply(db,r,plan['token']);db.commit()
    assert (a.start_date,a.end_date,a.amount,a.calendar_dates)==original

def test_recorded_day_removal_contract_limit_and_stale_preview_block_changes(db):
    p,cls,r,a,b=setup(db);close15(db)
    plan=lc.preview(db,r)
    db.add(LunchMealCount(program_id=p.id,date=datetime(2026,12,15),class_id=cls.id,count=106));db.commit()
    with pytest.raises(ValueError,match='เปลี่ยน'):lc.apply(db,r,plan['token'])
    db.rollback();plan=lc.preview(db,r);assert any('ยอดนักเรียน' in e for e in plan['errors'])
    with pytest.raises(ValueError):lc.apply(db,r,plan['token'])
    assert a.end_date==datetime(2026,12,15)
    db.query(LunchMealCount).delete();r.end_date=datetime(2026,12,18);db.commit()
    assert any('สิ้นสุดรอบ' in e for e in lc.preview(db,r)['errors'])

def test_bounded_empty_calendar_and_safe_returns(db):
    db.add(AcadCalendar(year=2569,month=12,days_csv=''));db.commit()
    assert not sc.days(db,2569,date(2026,12,1),date(2026,12,31))
    with pytest.raises(ValueError):sc.ranges(db,2569,date(2027,4,30),[100])
    for path in ['https://evil.test','//evil.test','http://[','/admin-console','/lunch/1/rounds?next=//evil','/lunch/1/rounds\\x']:
        assert sc.safe_return(path)==''
    assert sc.safe_return('/lunch/round/1/plan#installments')=='/lunch/round/1/plan#installments'

def test_calendar_aliases_saved_holidays_back_link_and_shared_day_data(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p,cls,r,a,b=setup(s);pid,rid=p.id,r.id
        s.add(AcadCalendar(year=2569,month=12,days_csv='11,12,14,15,16,17,18,21'));s.commit()
    back=f'/lunch/{pid}/rounds'
    url='/settings/calendar?year=2569&return_to='+back
    assert env.get(url).status_code==200
    response=env.post('/settings/calendar/holidays',data={'year':'2569','return_to':back,'new_month':'12','new_day':'15','new_name':'วันหยุดพิเศษ'},follow_redirects=False)
    assert response.status_code==303 and 'return_to=' in response.headers['location']
    shared=env.get(response.headers['location']);legacy=env.get('/academic/calendar?year=2569')
    assert shared.status_code==legacy.status_code==200
    assert back in shared.text and 'วันหยุดพิเศษ' in legacy.text
    with tn.session_for(sid) as s:
        row=s.query(AcadCalendar).filter_by(year=2569,month=12).one();assert row.days_csv=='11,12,14,16,17,18,21'
        r=s.get(LunchHireRound,rid);plan=lc.preview(s,r);token=plan['token']
    response=env.post(f'/lunch/round/{rid}/calendar-review',data={'token':token},follow_redirects=False)
    assert response.status_code==303 and 'calendar_updated=1' in response.headers['location']
    assert env.get(f'/lunch/round/{rid}/plan').status_code==200
    assert env.get('/settings/calendar?year=99999').status_code==400
    assert 'evil.test' not in env.get('/settings/calendar?return_to=https://evil.test').text

def test_lunch_only_staff_can_use_shared_calendar_without_academic_access(env,monkeypatch):
    import app.main as main
    base=main.get_account_access(1)
    def role(**kw):monkeypatch.setattr(main,'get_account_access',lambda uid:{**base,**kw})
    role(is_owner=False,modules='lunch',person_id=123)
    assert env.get('/settings/calendar?year=2569').status_code==200
    assert env.post('/settings/calendar/save',data={'year':'2569','m_12':'11,12,14,16'}).status_code==200
    assert env.get('/academic/calendar?year=2569').status_code==403
    role(is_owner=False,modules='academic',person_id=123)
    assert env.get('/settings/calendar?year=2569').status_code==200
    assert env.post('/settings/calendar/save',data={'year':'2569','m_12':'15'}).status_code==403
    role(is_owner=False,modules='finance',person_id=None)
    assert env.get('/settings/calendar?year=2569').status_code==403

def test_new_rounds_and_auto_installments_use_school_calendar(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p=LunchProgram(year=2569,rate_per_head=24,operate_mode='hire');s.add(p);s.commit();pid=p.id
        s.add(AcadCalendar(year=2569,month=12,days_csv='11,12,14,16,17,18,21'));s.commit()
    response=env.post(f'/lunch/{pid}/rounds/add',data={'start_date':'11/12/2569','end_date':'18/12/2569','days':'6','n_inst':'2','amount':'6000','status':'ร่าง'},follow_redirects=False)
    assert response.status_code==303 and '/plan' in response.headers['location']
    with tn.session_for(sid) as s:
        r=s.query(LunchHireRound).filter_by(program_id=pid).one()
        assert [i.days for i in r.installments]==[3,3] and sum(i.amount for i in r.installments)==6000
        assert r.installments[0].end_date==datetime(2026,12,14)
        assert workdays(r.installments[0])==[date(2026,12,11),date(2026,12,12),date(2026,12,14)]

def test_capture_settings_rounds_and_review(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p,cls,r,a,b=setup(s);close15(s);pid,rid=p.id,r.id
    paths={'calendar':sc.settings_link(2569,f'/lunch/{pid}/rounds'), 'rounds':f'/lunch/{pid}/rounds',
           'plan':f'/lunch/round/{rid}/plan','review':f'/lunch/round/{rid}/calendar-review'}
    for name,url in paths.items():
        response=env.get(url);assert response.status_code==200,(url,response.text[:250])
        if os.environ.get('SHARED_CALENDAR_CAPTURE'):
            out=Path(os.environ['SHARED_CALENDAR_CAPTURE']);(out/('screen-'+name+'.html')).write_text(response.text,encoding='utf-8')
            (out/'fixture.json').write_text(json.dumps(dict(pid=pid,rid=rid)),encoding='utf-8')


def test_duplicate_round_freezes_calendar_and_program_copy_still_works(env):
    import app.tenancy as tn
    sid=next(iter(tn._engines))
    with tn.session_for(sid) as s:
        p,cls,r,a,b=setup(s);pid,rid=p.id,r.id
        s.add(AcadCalendar(year=2569,month=1,days_csv='4,5,6,7,8,11,12'));s.commit()
    copied=env.post(f'/lunch/{pid}/duplicate',follow_redirects=False)
    assert copied.status_code==303
    response=env.post(f'/lunch/round/{rid}/duplicate',follow_redirects=False)
    assert response.status_code==303 and '/plan' in response.headers['location']
    with tn.session_for(sid) as s:
        r=s.query(LunchHireRound).filter_by(program_id=pid,seq=2).one()
        assert r.calendar_dates is not None and len(lc.stored_days(r,r.program))==6
        assert lc.stored_days(r,r.program)[0]==date(2027,1,4)


def test_same_bounds_calendar_change_invalidates_approval(db):
    from app.services.lunch_approval import fp_inst,fp_pay,fp_round
    p,cls,r,a,b=setup(db)
    old_inst,old_pay,old_round=fp_inst(a),fp_pay(r),fp_round(r)
    assert '|calendar:' not in old_inst and '|calendar:' not in old_round
    a.calendar_dates=json.dumps(['2026-12-11','2026-12-14','2026-12-15'])
    assert fp_inst(a)!=old_inst and fp_pay(r)!=old_pay and fp_round(r)==old_round
    first=fp_inst(a)
    a.calendar_dates=json.dumps(['2026-12-11','2026-12-12','2026-12-15'])
    assert fp_inst(a)!=first
