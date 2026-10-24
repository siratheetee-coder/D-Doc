import io
from openpyxl import Workbook
from tests.test_subsidy import env


def _xlsx(rows, header=None):
    wb = Workbook(); ws = wb.active
    ws.append(['ทะเบียนครุภัณฑ์ โรงเรียนเดิม'])
    ws.append(header or ['ลำดับ', 'รหัสครุภัณฑ์', 'รายการ', 'ยี่ห้อ', 'วัน เดือน ปี', 'ราคาต่อหน่วย', 'จำนวน', 'หน่วยนับ', 'สถานที่'])
    for r in rows: ws.append(r)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_template_downloads(env):
    r = env.get('/assets/import/template.xlsx')
    assert r.status_code == 200 and r.content[:2] == b'PK'


def test_preview_flags_problems_then_imports_only_good_rows(env):
    from app.models import Asset
    from app.tenancy import session_for
    from app.accounts import acc_session, Account
    with acc_session() as a:
        tid = a.query(Account).filter_by(username='demo').one().tenant_id
    db = session_for(tid)
    db.add(Asset(name='ของเดิม', asset_code='OLD-1')); db.commit(); db.close()
    data = _xlsx([
        [1, 'NEW-1', 'โต๊ะทำงานครู', 'ไม้', '15/05/2565', '3,500', 2, 'ตัว', 'ห้องพักครู'],
        [2, 'NEW-1', 'เก้าอี้', '', '15/05/2565', 900, 1, 'ตัว', ''],     # เลขซ้ำในไฟล์
        [3, 'OLD-1', 'ตู้เหล็ก', '', '01/06/2560', 5000, 1, 'ตู้', ''],  # เลขมีในระบบแล้ว
        [4, '', 'พัดลม', '', 'ไม่ทราบ', 1200, 1, 'ตัว', ''],             # วันที่อ่านไม่ได้
        [5, '', 'โปรเจกเตอร์', '', '', 15000, 1, 'เครื่อง', ''],         # ไม่มีเลข/วันที่ = เตือนแต่ผ่าน
    ])
    r = env.post('/assets/import', files={'file': ('ทะเบียน.xlsx', data)})
    assert r.status_code == 200
    html = r.text
    assert 'นำเข้าได้<b>2 รายการ' in html and 'ไม่นำเข้า<b>3 รายการ' in html
    assert 'เลขครุภัณฑ์ซ้ำกับแถวก่อนหน้าในไฟล์' in html and 'เลขครุภัณฑ์นี้มีในระบบแล้ว' in html
    import re, html as h
    payload = h.unescape(re.search(r'name="payload" value="([^"]*)"', html).group(1))
    r = env.post('/assets/import/confirm', data={'payload': payload}, follow_redirects=False)
    assert r.status_code == 303 and 'imported=2' in r.headers['location']
    db = session_for(tid)
    desk = db.query(Asset).filter_by(asset_code='NEW-1').one()
    assert desk.name == 'โต๊ะทำงานครู' and desk.cost == 3500 and desk.quantity == 2 and desk.acquired_date.year == 2022
    assert desk.location == 'ห้องพักครู'
    # ยืนยันซ้ำ (กดย้อนกลับแล้วส่งอีกครั้ง) ต้องไม่สร้างเลขซ้ำ
    r = env.post('/assets/import/confirm', data={'payload': payload}, follow_redirects=False)
    assert 'err=' in r.headers['location']
    assert db.query(Asset).filter_by(asset_code='NEW-1').count() == 1
    db.close()


def test_rejects_file_without_name_column(env):
    r = env.post('/assets/import', files={'file': ('x.xlsx', _xlsx([[1, 2]], header=['a', 'b']))}, follow_redirects=False)
    assert r.status_code == 303 and 'err=' in r.headers['location']
