import io
import re
from datetime import datetime
from openpyxl import Workbook
from tests.test_subsidy import env


def _file():
    wb = Workbook(); ws = wb.active; ws.title = 'บัญชีเงิน'
    ws.append(['คำแนะนำ']); ws.append(['หัว'])
    ws.append(['เงินทดสอบนำเข้า', 1000, '', '', 2570])
    t = wb.create_sheet('รายการรับ-จ่าย'); t.append(['คำแนะนำ']); t.append(['หัว'])
    t.append(['เงินทดสอบนำเข้า', '05/11/2569', 'จ่าย', 300, 'ค่าวัสดุ', 'บข.1', ''])
    t.append(['เงินทดสอบนำเข้า', '05/11/2569', 'จ่าย', 300, 'ค่าวัสดุ', 'บข.1', ''])   # ซ้ำในไฟล์
    t.append(['เงินทดสอบนำเข้า', '', 'รับ', 50, '', '', ''])                           # ไม่มีวันที่
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_preview_then_confirm_maps_item_and_never_duplicates(env):
    from app.accounts import acc_session, Account
    from app.tenancy import session_for
    from app.models import FinanceAccount, AccountItem, FinanceTxn, AccountOpening
    with acc_session() as a:
        tid = a.query(Account).filter_by(username='demo').one().tenant_id
    db = session_for(tid)
    acc = FinanceAccount(name='เงินทดสอบนำเข้า'); db.add(acc); db.flush()
    db.add(AccountItem(account_id=acc.id, fiscal_year=2570, name='ค่าวัสดุ')); db.commit()
    aid = acc.id; db.close()

    r = env.post('/finance/import', files={'file': ('fin.xlsx', _file())})
    assert r.status_code == 200 and 'ตรวจก่อนนำเข้า' in r.text
    assert 'ซ้ำกับแถวก่อนหน้าในไฟล์' in r.text and 'อ่านวันที่ไม่ได้' in r.text
    token = re.search(r'name="token" value="([0-9a-f]{32})"', r.text).group(1)
    r = env.post('/finance/import/confirm', data={'token': token}, follow_redirects=False)
    assert r.status_code == 303 and 'imported=' in r.headers['location']

    db = session_for(tid)
    txns = db.query(FinanceTxn).filter_by(account_id=aid).all()
    assert len(txns) == 1 and txns[0].fiscal_year == 2570 and txns[0].item_id is not None
    assert db.query(AccountOpening).filter_by(account_id=aid, fiscal_year=2570).one().amount == 1000
    db.close()
    # อัปโหลดไฟล์เดิมอีกรอบ: รายการเดิมต้องไม่ถูกนำเข้าซ้ำ
    r = env.post('/finance/import', files={'file': ('fin.xlsx', _file())})
    assert 'มีรายการนี้ในระบบแล้ว' in r.text
    token = re.search(r'name="token" value="([0-9a-f]{32})"', r.text).group(1)
    env.post('/finance/import/confirm', data={'token': token})
    db = session_for(tid)
    assert db.query(FinanceTxn).filter_by(account_id=aid).count() == 1
    db.close()
    # token ใช้ได้ครั้งเดียว
    r = env.post('/finance/import/confirm', data={'token': token}, follow_redirects=False)
    assert 'import_err=expired' in r.headers['location']
