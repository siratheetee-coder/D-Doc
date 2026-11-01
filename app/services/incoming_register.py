"""Calendar-year incoming register; keep legacy fiscal-year data unchanged."""
from datetime import datetime
from sqlalchemy import func
from app.models import IncomingLetter, DocNumberCounter

def current_year():
    return datetime.now().year + 543

def next_number(db, year):
    counter = db.query(DocNumberCounter).filter_by(doc_type='incoming', fiscal_year=year).first()
    used = db.query(func.max(IncomingLetter.recv_no)).filter(IncomingLetter.calendar_year == year).scalar() or 0
    # Unclassified legacy numbers are reserved until their year is confirmed.
    legacy = db.query(func.max(IncomingLetter.recv_no)).filter(IncomingLetter.calendar_year.is_(None)).scalar() or 0
    return max(used, legacy, (counter.last_number or 0) if counter else 0) + 1

def reserve(db, year, number):
    counter = db.query(DocNumberCounter).filter_by(doc_type='incoming', fiscal_year=year).first()
    if counter is None:
        counter = DocNumberCounter(doc_type='incoming', fiscal_year=year, last_number=0)
        db.add(counter)
    counter.last_number = max(counter.last_number or 0, number)

def year_options(db, chosen):
    return sorted({current_year(), chosen if chosen > 0 else current_year(),
                   *range(current_year()-3, current_year()+2),
                   *(y for y, in db.query(IncomingLetter.calendar_year).distinct() if y)}, reverse=True)

def duplicate(db, year, number, exclude=None):
    query = db.query(IncomingLetter).filter_by(calendar_year=year, recv_no=number)
    if exclude is not None: query = query.filter(IncomingLetter.id != exclude)
    return query.first() is not None
