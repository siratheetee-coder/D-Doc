"""Recognize a procurement report explicitly reused by its single linked finance memo."""
from app.models import Procurement, DisburseMemo


def same_document(db, doc_type, year, seq, source, ref_id, other_source, other_ref):
    if doc_type != 'memo' or {source,other_source} != {'procurement','finance'}:
        return False
    proc_id=ref_id if source=='procurement' else other_ref
    memo_id=ref_id if source=='finance' else other_ref
    proc=db.get(Procurement,proc_id) if proc_id else None
    memo=db.get(DisburseMemo,memo_id) if memo_id else None
    if not proc or not memo or memo.procurement_id != proc.id:
        return False
    from app.services.doc_number import doc_year,parse_seq
    def matches(no,fy,date):
        return parse_seq(no)==seq and doc_year('memo',fy,no,date)==year
    if not matches(memo.memo_no,memo.fiscal_year,memo.date):return False
    # These are the two fields older finance forms explicitly prefilled from procurement.
    if not any(matches(no,proc.fiscal_year,date)
               for no,date in ((proc.inspect_memo_no,proc.inspect_date),(proc.memo_no,proc.request_date))):
        return False
    # A second finance memo is a distinct claim, even if it points at the same procurement.
    linked=[m for m in db.query(DisburseMemo).filter_by(procurement_id=proc.id)
            if matches(m.memo_no,m.fiscal_year,m.date)]
    return len(linked)==1 and linked[0].id==memo.id
