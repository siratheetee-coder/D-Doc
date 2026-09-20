import unittest
from datetime import date, datetime, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import MoneyLoan, LoanReturn, DisburseMemo, LeaveRequest, TravelRequest, Person
from app.services.dashboard_tasks import finance_tasks, hr_tasks

class DashboardTests(unittest.TestCase):
    def test_finance_date_boundaries_partial_settlement_and_year(self):
        engine=create_engine('sqlite://')
        Base.metadata.create_all(engine)
        today=date(2026,9,20)
        with Session(engine) as db:
            for i, days in enumerate([-1,0,7,8,None,-3]):
                loan=MoneyLoan(fiscal_year=2568 if i==0 else 2569, amount=100, borrower=str(i), due_date=datetime.combine(today+timedelta(days=days),datetime.min.time()) if days is not None else None)
                if i==0: loan.returns=[LoanReturn(amount=40)]
                if i==5: loan.returns=[LoanReturn(amount=100)]
                db.add(loan)
            db.add_all([DisburseMemo(fiscal_year=2569,status='ร่าง'),DisburseMemo(fiscal_year=2569,status='จ่ายแล้ว'),DisburseMemo(fiscal_year=2568,status='อนุมัติ')]);db.commit()
            cards=finance_tasks(db,2569,today)
            self.assertEqual([x['count'] for x in cards],[1,2,1,1])
            self.assertIn('60.00', cards[0]['items'][0]['detail'])
            self.assertIn('year=2568',cards[0]['items'][0]['href'])
        engine.dispose()

    def test_hr_pending_stages_and_empty(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        with Session(engine) as db:
            self.assertEqual([x['count'] for x in hr_tasks(db)],[0,0,0,0])
            for model in [LeaveRequest,TravelRequest]:
                for status in ['pending','personnel','approved','rejected']:
                    db.add(model(person_id=1,status=status))
            db.commit()
            self.assertEqual([x['count'] for x in hr_tasks(db)],[1,1,1,1])
        engine.dispose()
