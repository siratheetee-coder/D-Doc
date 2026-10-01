# -*- coding: utf-8 -*-
"""ช่วยกรอก e-Budget (ระบบบัญชีการศึกษาขั้นพื้นฐาน สนผ. สพฐ.)

กติกาของ e-Budget ที่ต้องถูก
  - รายงานปีละ 2 ครั้ง · ครั้งที่ 1 = 1 ต.ค.-31 มี.ค. · ครั้งที่ 2 = 1 เม.ย.-30 ก.ย.
  - เว็บตรวจว่า (ยกมา + รายรับ) − รายจ่าย = คงเหลือ ถ้าไม่ตรงกรอกไม่ผ่าน
  - ประเภทเงินต้องลงให้ตรงช่อง (รายหัว/ค่าหนังสือเรียน/ทุนเสมอภาค ฯลฯ)
  - รายการที่จับคู่ไม่ได้ ต้องบอกครูตรง ๆ ไม่ใช่เงียบแล้วยัดลงอื่น ๆ
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_ebudget.py
"""
import importlib.util
import pathlib
import sys
import tempfile
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FY = 2569


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
    monkeypatch.setattr(main_mod, "tenant_state", ac.tenant_state)
    monkeypatch.setattr(main_mod, "can_use_module", ac.can_use_module)
    monkeypatch.setattr(main_mod, "get_account_access", ac.get_account_access)

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from app.accounts import Tenant, acc_session
    from app.models import AccountItem, FinanceAccount, FinanceTxn
    from app.tenancy import session_for
    with acc_session() as s:
        tid = s.query(Tenant).filter_by(slug="demo").one().id
    db = session_for(tid)
    a = FinanceAccount(name="เงินอุดหนุน", fund_type="เงินนอกงบประมาณ",
                       deposit_type="bank", opening_balance=0)
    inc = FinanceAccount(name="เงินรายได้สถานศึกษา", fund_type="เงินนอกงบประมาณ",
                         deposit_type="cash", opening_balance=5000)
    db.add_all([a, inc])
    db.flush()
    ids = {}
    for nm in ("ค่าจัดการเรียนการสอน", "ค่าหนังสือเรียน", "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน",
               "ค่าตกแต่งสวนหย่อม"):
        it = AccountItem(account_id=a.id, fiscal_year=FY, name=nm, deposit_type="bank")
        db.add(it)
        db.flush()
        ids[nm] = it.id
    # ครั้งที่ 1 (ธ.ค. 2568) · ครั้งที่ 2 (พ.ค./ส.ค. 2569)
    for d, kind, amt, item, acct in [
            (datetime(2025, 12, 5), "in", 100000, "ค่าจัดการเรียนการสอน", a),
            (datetime(2025, 12, 20), "out", 30000, "ค่าจัดการเรียนการสอน", a),
            (datetime(2026, 5, 10), "in", 50000, "ค่าหนังสือเรียน", a),
            (datetime(2026, 5, 20), "out", 20000, "ค่าหนังสือเรียน", a),
            (datetime(2026, 8, 3), "out", 4000, "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", a),
            (datetime(2026, 8, 9), "out", 1500, "ค่าตกแต่งสวนหย่อม", a),
            (datetime(2026, 6, 1), "in", 2000, None, inc)]:
        db.add(FinanceTxn(account_id=acct.id, fiscal_year=FY, date=d, kind=kind,
                          amount=amt, note=item or "รับเงินรายได้",
                          item_id=ids.get(item) if item else None))
    db.commit()
    db.close()

    from fastapi.testclient import TestClient

    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"username": "demo", "password": "Demo!2569"},
               follow_redirects=False)
    assert r.status_code in (302, 303)
    return c, tid


def _build(tid, rnd):
    from app.services.ebudget import build
    from app.tenancy import session_for
    db = session_for(tid)
    try:
        return build(db, FY, rnd)
    finally:
        db.close()


def test_period_matches_the_official_windows():
    from app.services.ebudget import period
    s1, e1, l1 = period(FY, 1)
    s2, e2, l2 = period(FY, 2)
    assert (s1.day, s1.month, s1.year) == (1, 10, 2025)      # 1 ต.ค. 2568
    assert (e1.day, e1.month, e1.year) == (31, 3, 2026)      # 31 มี.ค. 2569
    assert (s2.day, s2.month) == (1, 4) and (e2.day, e2.month) == (30, 9)
    assert "1 ต.ค." in l1 and "30 ก.ย." in l2


@pytest.mark.parametrize("name,code", [
    ("ค่าจัดการเรียนการสอน", "3.1.1"),
    ("ค่าหนังสือเรียน", "3.1.2"),
    ("ค่าอุปกรณ์การเรียน", "3.1.3"),
    ("ค่าเครื่องแบบนักเรียน", "3.1.4"),
    ("ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", "3.1.5"),
    ("ปัจจัยพื้นฐานนักเรียนยากจน", "3.1.6"),
    ("เงินอุดหนุนนักเรียนยากจนพิเศษ (ทุนเสมอภาค) กสศ.", "3.12"),
    ("เงินรายได้สถานศึกษา", "3.5"),
    ("เงินประกันสัญญา", "3.7"),
    ("เงินภาษีหัก ณ ที่จ่าย", "3.8"),
    ("ค่าอาหารกลางวัน", "3.2.2"),
    ("ค่าตกแต่งสวนหย่อม", "3.13"),
])
def test_money_type_maps_to_the_right_box(name, code):
    """ทุนเสมอภาคต้องไม่ตกไปช่อง 'ปัจจัยพื้นฐานนักเรียนยากจน' (ชื่อมีคำว่ายากจนเหมือนกัน)"""
    from app.services.ebudget import classify
    assert classify(name)[0] == code, name


def test_round_one_counts_only_its_own_window(env):
    _c, tid = env
    d = _build(tid, 1)
    assert d["income"]["3.1.1"] == 100000
    assert d["income"]["3.1.2"] == 0          # ของรอบ 2 ต้องไม่หลุดมา
    assert d["totals"]["expense"] == 30000


def test_round_two_counts_only_its_own_window(env):
    _c, tid = env
    d = _build(tid, 2)
    assert d["income"]["3.1.2"] == 50000
    assert d["income"]["3.1.1"] == 0
    assert d["totals"]["expense"] == 25500    # 20,000 + 4,000 + 1,500


def test_opening_carries_the_earlier_window(env):
    """ยกมาต้นงวดรอบ 2 = ผลของรอบ 1 (รับ 100,000 − จ่าย 30,000) + ยอดตั้งต้นบัญชี"""
    _c, tid = env
    d = _build(tid, 2)
    assert d["opening"]["3.1.1"] == 70000
    assert d["opening"]["3.5"] == 5000        # เงินรายได้สถานศึกษา ยอดตั้งต้น


def test_totals_balance_like_the_website_checks(env):
    """(ยกมา + รายรับ) − รายจ่าย = คงเหลือ · ถ้าไม่ตรง e-Budget จะไม่ให้กรอก"""
    for rnd in (1, 2):
        _c, tid = env
        d = _build(tid, rnd)
        t = d["totals"]
        assert round(t["opening"] + t["income"] - t["expense"] - t["closing"], 2) == 0
        assert d["check"] == 0


def test_expense_is_split_by_funding_source(env):
    _c, tid = env
    d = _build(tid, 2)
    assert d["expense"]["free"] == 24000      # หนังสือเรียน + กิจกรรมพัฒนา
    assert d["expense"]["etc"] == 1500        # รายการที่จับคู่ไม่ได้
    assert sum(d["expense"].values()) == d["totals"]["expense"]


def test_unmapped_items_are_reported_not_hidden(env):
    _c, tid = env
    d = _build(tid, 2)
    assert "ค่าตกแต่งสวนหย่อม" in d["unmapped"]


def test_page_lists_every_box_with_copy_buttons(env):
    c, _tid = env
    html = c.get(f"/finance/ebudget?year={FY}&round=2").text
    assert "ช่วยกรอก e-Budget" in html
    for label in ("รายหัว", "ค่าหนังสือเรียน", "เงินรายได้สถานศึกษา", "ทุนเสมอภาค"):
        assert label in html, label
    assert "cpText(this,'50000.00')" in html         # รายรับค่าหนังสือเรียน
    assert "ส่วนที่ 2" in html and "ส่วนที่ 5" in html
    assert "ไม่ได้ส่งข้อมูลไปที่ e-Budget" in html    # บอกชัดว่าต้องคัดลอกไปวางเอง
    assert "ค่าตกแต่งสวนหย่อม" in html                # เตือนรายการที่จับคู่ไม่ได้


def test_page_switches_rounds(env):
    c, _tid = env
    assert "cpText(this,'100000.00')" in c.get(f"/finance/ebudget?year={FY}&round=1").text
    assert "cpText(this,'100000.00')" not in c.get(f"/finance/ebudget?year={FY}&round=2").text


def test_nav_links_the_page(env):
    c, _tid = env
    assert "/finance/ebudget" in c.get("/finance").text


def test_parent_rows_are_the_sum_of_their_children(env):
    """3.1 ในแบบ e-Budget เป็นยอดรวมของ 3.1.1-3.1.7 ไม่ใช่ช่องแยก
    ถ้าไม่รวมให้ ครูจะคัดลอก 0.00 ไปกรอกช่องหัวข้อรวม"""
    _c, tid = env
    d = _build(tid, 2)
    kids = sum(d["income"][k] for k in
               ("3.1.1", "3.1.2", "3.1.3", "3.1.4", "3.1.5", "3.1.6", "3.1.7"))
    assert d["income"]["3.1"] == kids > 0
    assert d["opening"]["3.1"] == sum(d["opening"][k] for k in
                                      ("3.1.1", "3.1.2", "3.1.3", "3.1.4",
                                       "3.1.5", "3.1.6", "3.1.7"))


def test_totals_still_balance_after_rollup(env):
    """ยอดรวมต้องไม่ถูกนับซ้ำจากหัวข้อรวม"""
    _c, tid = env
    d = _build(tid, 2)
    assert d["check"] == 0


# ---- เทียบกับหน้าจริงของ e-Budget (อ่านจากเว็บ สพฐ. เมื่อ 1 ต.ค. 2569) ----
REAL_BOXES = [
    "เงินกันไว้เบิกจ่ายเหลื่อมปี", "ค่าครุภัณฑ์", "ค่าที่ดินและสิ่งก่อสร้าง",
    "เงินรายได้แผ่นดินคงเหลือ", "ค่าขายของเบ็ตเตล็ด", "ค่าธรรมเนียมเบ็ตเตล็ด",
    "เงินอุดหนุนทั่วไปที่เหลือจ่ายเกิน 2 ปีงบประมาณ", "ดอกเบี้ยเงินฝากฯ",
    "เงินนอกงบประมาณคงเหลือ", "เงินอุดหนุนทั่วไป โครงการเรียนฟรี", "รายหัว",
    "ค่าหนังสือเรียน", "ค่าอุปกรณ์การเรียน", "ค่าเครื่องแบบนักเรียน",
    "ค่ากิจกรรมพัฒนาคุณภาพผู้เรียน", "ปัจจัยพื้นฐานสำหรับนักเรียนยากจน",
    "ค่าอาหารนักเรียนประจำพักนอน", "เงินอุดหนุนทั่วไป (นอกเหนือจากข้อ 3.1)",
    "ค่าจ้างครูและบุคลากร (ได้รับจากท้องถิ่น)", "ค่าอาหารกลางวัน (ได้รับจากท้องถิ่น)",
    "ค่าอาหารนักเรียนพักนอนสำหรับโรงเรียนในพื้นที่ยากลำบาก",
    "เงินบำรุงการศึกษา", "เงินบริจาค", "เงินรายได้สถานศึกษา",
    "เงินค่าใช้จ่ายในการดำเนินงาน กยศ.", "เงินประกันสัญญา", "เงินลูกเสือ",
    "เงินเนตรนารี/ผู้บำเพ็ญประโยชน์", "เงินยุวกาชาด", "เงินอื่น ๆ คงเหลือ",
]


@pytest.mark.parametrize("box", REAL_BOXES)
def test_every_box_on_the_real_page_exists_here(box):
    """รายการช่องต้องครบตามหน้า e-Budget จริง ไม่งั้นครูจะหาช่องไม่เจอตอนไล่กรอก"""
    from app.services.ebudget import ORDER
    text = "\n".join(label for _c, label, _b in ORDER)
    assert box in text, box


def test_box_order_follows_the_real_page():
    from app.services.ebudget import ORDER
    codes = [c for c, _l, _b in ORDER]
    assert codes[:4] == ["1", "1.1", "1.2", "1.3"]
    assert codes[codes.index("2"):codes.index("2") + 6] == \
        ["2", "2.1", "2.2", "2.3", "2.4", "2.5"]
    assert codes[-1] == "4"                       # เงินอื่น ๆ คงเหลือ ปิดท้าย


def test_state_revenue_account_goes_to_section_two(env):
    """บัญชีหมวด 'เงินรายได้แผ่นดิน' ต้องลงหมวด 2 ไม่ปนกับเงินนอกงบประมาณ"""
    from app.models import FinanceAccount, FinanceTxn
    from app.services.ebudget import classify
    from app.tenancy import session_for
    _c, tid = env
    assert classify("เงินรายได้แผ่นดิน", "เงินรายได้แผ่นดิน")[0] == "2.5"
    assert classify("ดอกเบี้ยเงินฝาก", "เงินรายได้แผ่นดิน")[0] == "2.4"
    db = session_for(tid)
    land = FinanceAccount(name="เงินรายได้แผ่นดิน", fund_type="เงินรายได้แผ่นดิน",
                          deposit_type="cash", opening_balance=0)
    db.add(land)
    db.flush()
    db.add(FinanceTxn(account_id=land.id, fiscal_year=FY, date=datetime(2026, 7, 1),
                      kind="in", amount=662.63, note="ดอกเบี้ยเงินฝาก"))
    db.commit()
    db.close()
    d = _build(tid, 2)
    assert d["income"]["2.5"] == 662.63
    assert d["income"]["2"] == 662.63            # หัวข้อรวมหมวด 2


def test_group_three_is_the_sum_of_its_children(env):
    _c, tid = env
    d = _build(tid, 2)
    kids = ["3.1", "3.2", "3.3", "3.4", "3.5", "3.6", "3.7", "3.8",
            "3.9", "3.10", "3.11", "3.12", "3.13"]
    assert d["closing"]["3"] == round(sum(d["closing"][k] for k in kids), 2)


# ---- หมวดรายจ่าย e-Budget: เลือกตอนลงรายการ + ไล่เติมย้อนหลัง ----
@pytest.mark.parametrize("note,code", [
    ("ค่าไฟฟ้า เดือนกรกฎาคม", "4.1.1"),
    ("ค่าน้ำประปา", "4.1.2"),
    ("ค่าอินเทอร์เน็ตรายเดือน", "4.1.5"),
    ("ค่ากระดาษ หมึกพิมพ์", "4.4"),
    ("ค่าจ้างรถทัศนศึกษา ป.4-6", "1.6"),
    ("ค่าหนังสือเรียน ป.1", "1.3"),
    ("ค่าจ้างธุรการโรงเรียน", "2.1.5"),
    ("ค่าจ้างนักการภารโรง", "2.1.2"),
    ("จัดซื้อครุภัณฑ์คอมพิวเตอร์", "3.1"),
    ("ค่าอาหารกลางวันเดือน ก.ค.", "5.3"),
    ("นำส่งภาษีหัก ณ ที่จ่าย", "4.7"),
    ("ค่าเบี้ยเลี้ยงไปราชการ", "4.3"),
])
def test_guess_expense_from_what_the_teacher_typed(note, code):
    """เดาหมวดจากข้อความที่ครูพิมพ์ ครูจะได้ไม่ต้องเลือกเองทุกบรรทัด"""
    from app.services.ebudget_cat import guess_expense
    assert guess_expense(note) == code, note


def test_guess_falls_back_to_project_plan():
    """ผูกโครงการไว้แต่เดาจากข้อความไม่ได้ = โครงการตามแผนปฏิบัติการ"""
    from app.services.ebudget_cat import guess_expense
    assert guess_expense("จ่ายตามบันทึก", "", "ส่งเสริมคุณธรรม") == "1.1"
    assert guess_expense("จ่ายตามบันทึก") == ""      # ไม่มีอะไรให้เดา = ให้ครูเลือกเอง


@pytest.mark.parametrize("text,code", [
    ("รับจัดสรรเงินอุดหนุนรายหัว", "i2"),
    ("รับเงินอาหารกลางวันจาก อบต.", "i4"),
    ("รับเงินทุนเสมอภาค กสศ.", "i3"),
    ("ดอกเบี้ยเงินฝากธนาคาร", "i6"),
    ("รับเงินบริจาคจากผู้ปกครอง", "i5"),
])
def test_guess_income_source(text, code):
    from app.services.ebudget_cat import guess_income
    assert guess_income("", "", text) == code, text


def test_ledger_form_offers_the_category(env):
    from app.models import FinanceAccount
    from app.tenancy import session_for
    c, tid = env
    db = session_for(tid)
    aid = db.query(FinanceAccount).first().id
    db.close()
    html = c.get(f"/finance/accounts/{aid}?year={FY}").text
    assert 'name="eb_code"' in html
    assert "ค่าไฟฟ้า" in html and "กิจกรรมพัฒนาผู้เรียน" in html
    assert 'data-kind="out"' in html and 'data-kind="in"' in html   # สลับตามรับ/จ่าย


def test_fill_page_pre_guesses_and_saves(env):
    """หน้าไล่เติมหมวด: เดาให้ก่อน ครูกดบันทึกครั้งเดียว"""
    from app.models import FinanceTxn
    from app.tenancy import session_for
    c, tid = env
    html = c.get(f"/finance/ebudget/fill?year={FY}&round=2").text
    assert "เติมหมวด e-Budget" in html and "ระบบเดาหมวดให้ไว้แล้ว" in html
    db = session_for(tid)
    t = (db.query(FinanceTxn).filter_by(kind="out")
         .filter(FinanceTxn.note.like("%ค่าตกแต่ง%")).first())
    tid_ = t.id
    db.close()
    assert f'name="eb_{tid_}"' in html
    r = c.post("/finance/ebudget/fill",
               data={"year": FY, "round": 2, f"eb_{tid_}": "4.9"}, follow_redirects=False)
    assert r.status_code == 303
    db = session_for(tid)
    assert db.get(FinanceTxn, tid_).eb_code == "4.9"
    db.close()


def test_matrix_appears_once_codes_are_filled(env):
    """พอระบุหมวดแล้ว ส่วนที่ 4 ต้องออกมาเป็นตารางไขว้จริง"""
    from app.models import FinanceTxn
    from app.tenancy import session_for
    c, tid = env
    db = session_for(tid)
    for t in db.query(FinanceTxn).filter_by(kind="out").all():
        t.eb_code = "4.4"
    db.commit()
    db.close()
    d = _build(tid, 2)
    assert d["matrix"]["4.4"]["free"] == 24000
    assert d["matrix"]["4.4"]["etc"] == 1500
    assert not d["missing"]
    html = c.get(f"/finance/ebudget?year={FY}&round=2").text
    assert "ค่าวัสดุ" in html and "รวมทุกด้าน" in html


def test_missing_codes_are_flagged_on_the_report(env):
    c, tid = env
    d = _build(tid, 2)
    assert d["missing"], "ยังไม่ระบุหมวด ต้องขึ้นเตือน"
    html = c.get(f"/finance/ebudget?year={FY}&round=2").text
    assert "ยังไม่ได้ระบุหมวด" in html and "/finance/ebudget/fill" in html
