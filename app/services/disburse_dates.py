"""Document dates follow their source: request date vs recorded payment date."""
from app.models import DisburseMemo, FinanceTxn
from sqlalchemy.orm import object_session

def certificate_date(memo):
    if isinstance(memo, DisburseMemo):
        db = object_session(memo)
        if db is not None:
            rows = db.query(FinanceTxn).filter_by(disburse_id=memo.id, kind='out').all()
            if rows:
                dates = {t.date.date() if t.date else None for t in rows}
                # Never invent one payment date when historical payments occurred on different days.
                return rows[0].date if len(dates) == 1 and None not in dates else None
        return None
    return memo.date
