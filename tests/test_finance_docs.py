# -*- coding: utf-8 -*-
"""ทุกหัวข้อในงานการเงินต้องออกเอกสารได้ และหน้าหลักต้องมีการ์ดครบทุกหัวข้อ

เคยมี 2 หัวข้อที่เปิดหน้าได้แต่พิมพ์อะไรไม่ได้เลย (ทะเบียนใบเสร็จ · คำนวณเงินอุดหนุน)
และการ์ดในหน้าหลักการเงินมีไม่ครบตามเมนูข้าง ๆ
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_finance_docs.py
"""
import importlib.util
import pathlib
import re
import sys
import tempfile
import zipfile
from datetime import date

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FY = 2570


@pytest.fixture()
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    import app.database as dbm
    import app.tenancy as tn
    for m in (dbm, tn, ac):
        monkeypatch.setattr(m, "get_data_dir", lambda t=tmp: t)
    monkeypatch.setattr(tn, "_engines", type(tn._engines)())
    monkeypatch.setattr(ac, "_engine", None)
    monkeypatch.setattr(ac, "_Session", None)
    import app.main as main_mod
    import app.routers.auth as auth_mod
    monkeypatch.setattr(auth_mod, "authenticate", ac.authenticate)
    for key in ("tenant_state", "can_use_module", "get_account_access"):
        monkeypatch.setattr(main_mod, key, getattr(ac, key))

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from app.models import BankRecon, FinanceAccount, Project, Receipt
    from app.tenancy import session_for
    db = session_for(1)
    acct = db.query(FinanceAccount).first()
    if acct is None:
        acct = FinanceAccount(name="เงินอุดหนุนทั่วไป", fund_type="เงินงบประมาณ")
        db.add(acct)
        db.flush()
    db.add(Receipt(fiscal_year=FY, receipt_no="001/2570", date=date(2026, 10, 2),
                   kind="รับ", party="สพป. เขต 1", amount=50000, account_id=acct.id))
    db.add(Receipt(fiscal_year=FY, receipt_no="002/2570", date=date(2026, 10, 3),
                   kind="จ่าย", party="ร้านตัวอย่าง", amount=1200, account_id=acct.id))
    # ปุ่มพิมพ์ของบางหน้าโผล่เมื่อมีข้อมูลเท่านั้น (ไม่มีข้อมูล = ไม่มีอะไรให้พิมพ์)
    db.add(Project(plan_year=FY, name="โครงการพัฒนาคุณภาพผู้เรียน", budget=50000))
    db.add(BankRecon(fiscal_year=FY, as_of=date(2026, 10, 31), stmt_balance=100000,
                     account_id=acct.id))
    db.commit()
    db.close()

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "demo", "password": "Demo!2569"}, follow_redirects=False)
    return c


def _docx_text(content: bytes) -> str:
    import io
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))


# ---------------------------------------------------------------- เอกสารที่เคยขาด
def test_receipt_register_prints(env):
    c = env
    r = c.get(f"/finance/receipts/register.docx?year={FY}")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    text = _docx_text(r.content)
    assert "ทะเบียนคุมใบเสร็จรับเงินและใบสำคัญรับเงิน" in text
    assert "001/2570" in text and "สพป. เขต 1" in text
    assert "รวมด้านรับ" in text and "รวมด้านจ่าย" in text
    assert "50,000.00" in text and "1,200.00" in text


def test_subsidy_sheet_prints(env):
    c = env
    html = c.get('/finance/subsidy?year=2569&term=1').text
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)
    data = {"academic_year": 2569, "term": 1, "token": token, "levels": "ป.1"}
    for key in ("nov2568", "jun2569", "nov2569"):
        data[f"n_{key}_ป.1"] = 10
    for item, amount in (("teach", 2000), ("book", 600), ("equip", 400),
                         ("uniform", 360), ("activity", 500)):
        data[f"r_ป.1_{item}"] = amount
    assert c.post("/finance/subsidy", data=data, follow_redirects=False).status_code == 303

    r = c.get("/finance/subsidy.docx?year=2569")
    assert r.status_code == 200 and r.content[:2] == b"PK"
    text = _docx_text(r.content)
    assert "กระดาษคำนวณเงินอุดหนุนเรียนฟรี 15 ปี" in text
    assert "ภาคเรียนที่ 1" in text and "อัตราปีงบประมาณ 2569" in text
    assert "ร่าง" in text and "20,000.00" in text and "6,000.00" in text
    assert "DMC 10 พฤศจิกายน 2568" in text
    assert "เงินรับจริงต้องตรวจจากรายการโอนที่เชื่อมแยกต่างหาก" in text


# ---------------------------------------------------------------- ปุ่มบนหน้าจอ
SECTION_PAGES = [
    "/finance/accounts", "/finance/projects", "/finance/disburse", "/finance/receipts",
    "/finance/cashbook", "/finance/cash-report", "/finance/loans", "/finance/checks",
    "/finance/bank-recon", "/finance/report", "/finance/quarter", "/finance/audit",
    "/finance/subsidy", "/finance/import",
]


@pytest.mark.parametrize("page", SECTION_PAGES)
def test_every_section_offers_a_download(env, page):
    """เปิดหน้าได้อย่างเดียวไม่พอ ต้องมีปุ่มให้พิมพ์ออกมาด้วย (ยกเว้น e-Budget ที่เป็นตัวช่วยคัดลอก)"""
    c = env
    r = c.get(page)
    assert r.status_code == 200, page
    links = set(re.findall(r'href="(/finance[^"]*\.(?:docx|xlsx)[^"]*)"', r.text))
    assert links, f"{page} ไม่มีปุ่มดาวน์โหลดเลย"


def test_dashboard_has_a_card_for_every_menu_item(env):
    """การ์ดในหน้าหลักการเงิน ต้องครบเท่าเมนูข้าง ๆ ไม่งั้นผู้ใช้หาไม่เจอ

    ต้องเทียบกับ "หน้าที่เรนเดอร์แล้ว" ไม่ใช่โค้ดเทมเพลต ไม่งั้นเทสผ่านทั้งที่ยังขาด
    """
    c = env
    html = c.get("/finance").text
    cards = set(re.findall(r'class="nav-card" href="(/finance/[a-z-]+)"', html))
    side = html.split('class="side', 1)[1] if 'class="side' in html else html
    menu = {m for m in re.findall(r'href="(/finance/[a-z-]+)"', side)} - {"/finance"}
    assert len(cards) >= 14, f"การ์ดน้อยผิดปกติ: {sorted(cards)}"
    assert menu, "หาเมนูข้างไม่เจอ เทสนี้จะผ่านลอย ๆ"
    missing = menu - cards
    assert not missing, f"เมนูที่ยังไม่มีการ์ด: {sorted(missing)}"


def test_accounts_header_links_to_the_subsidy_calculator(env):
    c = env
    html = c.get("/finance/accounts").text
    head = html.split('class="hero"', 1)[1].split("</div>\n\n", 1)[0]
    assert "/finance/subsidy" in head and "คำนวณเงินอุดหนุน" in head


def test_cashbook_delete_updates_ledger_and_linked_records(env):
    from app.tenancy import session_for
    from app.models import FinanceAccount, FinanceTxn, Receipt, SubsidyReceiptLink
    from app.routers.finance import _cashbook_fund_data
    db=session_for(1)
    a=FinanceAccount(name='บัญชีทดสอบลบ',opening_balance=0)
    db.add(a);db.flush()
    t=FinanceTxn(account_id=a.id,fiscal_year=FY,kind='in',amount=500,ref='รับผิด')
    other=FinanceTxn(account_id=a.id,fiscal_year=FY,kind='out',amount=100,ref='เก็บไว้')
    db.add_all([t,other]);db.flush()
    db.add(Receipt(fiscal_year=FY,txn_id=t.id,account_id=a.id,amount=500))
    db.add(SubsidyReceiptLink(txn_id=t.id,academic_year=FY,term=1,item_key='teach',round='first',amount=500))
    db.commit();tid,oid,aid=t.id,other.id,a.id;db.close()
    r=env.get(f'/finance/cashbook?year={FY}&account={aid}')
    assert r.status_code==200 and f'/finance/txn/{tid}/delete?return_to=cashbook' in r.text
    assert f'/finance/txn/{oid}/delete?return_to=cashbook' in r.text
    url=f'/finance/txn/{tid}/delete?return_to=cashbook&year={FY}&account={aid}'
    r=env.post(url,follow_redirects=False)
    assert r.status_code==303 and r.headers['location']==f'/finance/cashbook?year={FY}&account={aid}'
    db=session_for(1)
    assert db.get(FinanceTxn,tid) is None and db.get(FinanceTxn,oid) is not None
    assert db.query(Receipt).filter_by(txn_id=tid).count()==0
    assert db.query(SubsidyReceiptLink).filter_by(txn_id=tid).count()==0
    _,_,receipts,payments=_cashbook_fund_data(db,FY,aid)
    assert receipts==[] and sum(r['amount'] for r in payments)==100
    db.close()
    assert env.post(url,follow_redirects=False).status_code==303
