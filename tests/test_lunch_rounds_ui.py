from datetime import datetime
import pytest
from tests.test_subsidy import env
from app.models import LunchProgram,LunchClass,LunchHireRound,LunchInstallment,LunchLedger

@pytest.mark.parametrize('mode',['hire','person','ingredient'])
def test_rounds_cards_preserve_form_and_mode_workflow(env,mode):
    import app.tenancy as tn
    with tn.session_for(next(iter(tn._engines))) as s:
        p=LunchProgram(year=2569,operate_mode=mode,rate_per_head=36,days=10)
        p.classes.append(LunchClass(level='ป.1',num_students=20));s.add(p);s.flush()
        r=LunchHireRound(program=p,seq=1,start_date=datetime(2026,11,16),end_date=datetime(2026,11,20),amount=3600,status='ร่าง')
        if mode=='hire':r.installments.append(LunchInstallment(seq=1,status='จ่ายแล้ว',amount=3600))
        s.add(r);s.flush();s.add(LunchLedger(program=p,round_id=r.id,kind='out',amount=3600))
        s.commit();pid,rid=p.id,r.id
    page=env.get(f'/lunch/{pid}/rounds');assert page.status_code==200
    assert 'data-round-filter="active"' in page.text and 'id="lr-search"' in page.text
    assert 'data-detail-card' in page.text and 'class="lr-flow"' in page.text
    assert 'rstatus' not in page.text and 'saveRoundStatus' not in page.text
    assert f'/lunch/round/{rid}/duplicate' in page.text and f'/lunch/round/{rid}/delete' in page.text
    assert 'name="n_inst"' in page.text if mode=='hire' else 'name="n_inst"' not in page.text
    assert '<details class="lh-panel lr-form" id="new-round">' in page.text
    assert 'href="#ic-check"' in page.text
    if mode=='hire':assert 'จ่ายครบแล้ว' in page.text and '3,600.00' in page.text
    else:assert 'รับเงินยืม' in page.text and 'ส่งใช้' in page.text
    edit=env.get(f'/lunch/round/{rid}/edit');assert edit.status_code==200
    assert '<details class="lh-panel lr-form" id="new-round" open>' in edit.text
    error=env.get(f'/lunch/{pid}/rounds?err=test');assert 'id="new-round" open' in error.text
    with tn.session_for(next(iter(tn._engines))) as s:
        assert s.query(LunchLedger).count()==1 and s.get(LunchHireRound,rid).status=='ร่าง'
