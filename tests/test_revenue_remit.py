from datetime import datetime
from tests.test_subsidy import env


def _setup():
    from app.accounts import acc_session, Account
    from app.tenancy import session_for
    from app.models import FinanceAccount, FinanceTxn
    with acc_session() as a:
        tid = a.query(Account).filter_by(username='demo').one().tenant_id
    db = session_for(tid)
    acc = FinanceAccount(name='เงินรายได้แผ่นดิน (ทดสอบ)', fund_type='เงินรายได้แผ่นดิน'); db.add(acc); db.flush()
    db.add_all([FinanceTxn(account_id=acc.id, fiscal_year=2569, date=datetime(2026, 6, 30), kind='in', amount=812.5, category='ดอกเบี้ยเงินฝากธนาคาร'),
                FinanceTxn(account_id=acc.id, fiscal_year=2570, date=datetime(2026, 10, 5), kind='in', amount=1500, note='ขายวัสดุเหลือใช้')])
    db.commit()
    return tid, acc.id, db


def test_summary_create_documents_and_delete(env):
    from app.models import FinanceTxn, RevenueRemit
    tid, aid, db = _setup()
    html = env.get('/finance/revenue').text
    assert 'ดอกเบี้ยเงินฝากสถาบันการเงิน' in html and 'ค่าขายของเบ็ดเตล็ด' in html and '812.50' in html
    # นำส่งเกินยอดค้าง = ไม่ยอม
    r = env.post('/finance/revenue', data={'account_id': aid, 'rtype': 'interest', 'amount': '900', 'date': '20/10/2569'}, follow_redirects=False)
    assert 'err=' in r.headers['location']
    r = env.post('/finance/revenue', data={'account_id': aid, 'rtype': 'interest', 'amount': '812.50', 'date': '20/10/2569',
                                           'memo_no': '15/2570', 'letter_no': 'ศธ 04001/99', 'send_to': 'สำนักงานเขตพื้นที่การศึกษาประถมศึกษาทดสอบ เขต 1',
                                           'company_code': '703935', 'ref1': '41010001', 'ref2': '821', 'method': 'เงินโอน',
                                           'payer': 'ครูการเงิน', 'phone': '0800000000'}, follow_redirects=False)
    assert 'msg=saved' in r.headers['location'] and 'year=2570' in r.headers['location']
    db.expire_all()
    rem = db.query(RevenueRemit).one()
    out = db.get(FinanceTxn, rem.txn_id)
    assert out.kind == 'out' and out.amount == 812.5 and out.fiscal_year == 2570 and out.account_id == aid
    for which in ('memo', 'letter', 'slip', 'all'):
        d = env.get(f'/finance/revenue/{rem.id}/{which}.docx')
        assert d.status_code == 200 and d.content[:2] == b'PK', which
    from docx import Document
    import io
    text = '\n'.join(p.text for p in Document(io.BytesIO(env.get(f'/finance/revenue/{rem.id}/all.docx').content)).paragraphs)
    assert 'ขออนุมัตินำส่งเงินรายได้แผ่นดิน' in text and 'การนำส่งเงินรายได้แผ่นดิน' in text
    rep = env.get('/finance/revenue/report.docx?month=2569-10')
    assert rep.status_code == 200 and rep.content[:2] == b'PK'
    # ค่าที่ใช้ครั้งก่อนจำไว้ให้
    html = env.get('/finance/revenue?year=2570').text
    assert 'value="703935"' in html and 'value="41010001"' in html
    rid, txn_id = rem.id, rem.txn_id
    env.post(f'/finance/revenue/{rid}/delete')
    db.expire_all()
    assert db.query(RevenueRemit).count() == 0 and db.get(FinanceTxn, txn_id) is None
    db.close()


def test_register_has_four_official_columns():
    from types import SimpleNamespace as N
    from app.services.fin_registers import _REV_COLS, _rev_bucket
    assert len(_REV_COLS) == 4
    assert _rev_bucket(N(category='ดอกเบี้ยเงินฝากธนาคาร', note='')) == 0
    assert _rev_bucket(N(category='', note='ขายของเหลือใช้')) == 2
    assert _rev_bucket(N(category='ค่าปรับผิดสัญญา', note='')) == 3
