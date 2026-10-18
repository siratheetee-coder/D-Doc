from datetime import datetime
from tests.test_subsidy import db
from app.models import School, FinanceAccount, AccountItem, AccountOpening, Project, Person, AcadYearSetting
from app.services import finance_setup, module_setup, academic_setup

def test_saved_zero_opening_stays_incomplete(db):
    a=FinanceAccount(name='Test');db.add(a);db.flush()
    db.add(AccountItem(account_id=a.id,fiscal_year=2570,name='Test',opening_balance=0))
    db.add(AccountOpening(account_id=a.id,fiscal_year=2570,amount=0));db.commit()
    assert finance_setup.setup_steps(db,2570)['steps'][2]['done']

def test_zero_cost_project_stays_incomplete(db):
    db.add(Project(name='No cost activity',plan_year=2570,budget=0,responsible='Academic'));db.commit()
    assert not finance_setup.project_steps(db,2570)['steps'][1]['done']

def test_director_spacing_changes_signature_result(db):
    s=School(name='School',director_name='First Last',director_email='test@example.com')
    db.add(Person(name='First  Last',active=True,signature='existing.png'));db.commit()
    assert module_setup.hr_steps(db,s)['steps'][3]['done']

def test_calendar_without_end_dates_passes(db):
    db.add(AcadYearSetting(year=2569,t1_start=datetime(2026,5,1),t2_start=datetime(2026,11,1)));db.commit()
    assert not academic_setup.setup_steps(db,2569)['steps'][0]['done']


def test_selected_plan_does_not_use_other_year(db):
    from app.models import PlanBudget
    db.add(PlanBudget(year=2569,mode='budget',start_date=datetime(2025,10,1),end_date=datetime(2026,9,30)))
    db.add(PlanBudget(year=2570,mode='budget',start_date=datetime(2026,10,1),end_date=datetime(2027,9,30)))
    db.commit()
    st=finance_setup.setup_steps(db,2569,selected_plan_year=2569)
    assert st['steps'][3]['href']=='/plan-budget/2569'
    assert st['steps'][4]['href']=='/projects?year=2569'
