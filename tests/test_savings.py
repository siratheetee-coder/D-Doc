"""ธนาคารโรงเรียน: ฝาก/ถอนทั้งห้อง ถอนเกินยอด ยกเลิก ปิดยอดเดือน สิทธิ์ครูประจำชั้น หน้าพิมพ์ นักเรียนดูยอด"""
from tests.test_subsidy import env  # noqa: F401
from tests.test_access_shared_pages import _account
from tests.test_behavior import _class_with_students


def _s():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _bal(sid):
    from app.services import savings
    with _s() as s:
        return savings.balances(s, [sid])[sid]


D = "21/11/2569"


def test_deposit_withdraw_and_overdraw_blocked(env):
    cid, (a, b), _y = _class_with_students()
    assert "ธนาคารโรงเรียน" in env.get(f"/general/savings?cid={cid}").text
    r = env.post("/general/savings/save", data={"date": D, f"dep_{a}": "100", f"dep_{b}": "1,250.50"},
                 follow_redirects=False)
    assert r.status_code == 303 and _bal(a) == 100 and _bal(b) == 1250.5
    env.post("/general/savings/save", data={"date": D, f"wd_{a}": "30"})
    assert _bal(a) == 70
    r = env.post("/general/savings/save", data={"date": D, f"wd_{a}": "80", f"dep_{b}": "5"}, follow_redirects=False)
    assert "ถอนเกินยอด" in __import__("urllib.parse").parse.unquote(r.headers["location"])
    assert _bal(a) == 70 and _bal(b) == 1250.5          # ผิดคนเดียว ไม่บันทึกทั้งชุด
    r = env.post("/general/savings/save", data={"date": D, f"dep_{a}": "abc"}, follow_redirects=False)
    assert _bal(a) == 70
    # ฝากและถอนวันเดียวกันในชุดเดียว ลงฝากก่อน
    env.post("/general/savings/save", data={"date": D, f"dep_{a}": "50", f"wd_{a}": "120"})
    assert _bal(a) == 0


def test_void_needs_reason_and_keeps_history(env):
    _cid, (a, _b), _y = _class_with_students()
    env.post("/general/savings/save", data={"date": D, f"dep_{a}": "40"})
    env.post("/general/savings/save", data={"date": D, f"wd_{a}": "10"})
    from app.models import SavingsTxn
    with _s() as s:
        dep = s.query(SavingsTxn).filter_by(student_id=a, kind="dep").one().id
        wd = s.query(SavingsTxn).filter_by(student_id=a, kind="wd").one().id
    env.post(f"/general/savings/t/{wd}/void", data={"reason": ""})
    assert _bal(a) == 30
    # ยกเลิกเงินฝากที่ถูกถอนไปบางส่วนแล้ว ยอดไม่ติดลบ จึงยกเลิกได้เมื่อถอนรายการถอนก่อน
    env.post(f"/general/savings/t/{wd}/void", data={"reason": "กรอกผิด"})
    assert _bal(a) == 40
    env.post(f"/general/savings/t/{dep}/void", data={"reason": "กรอกผิดคน"})
    assert _bal(a) == 0
    page = env.get(f"/general/savings/s/{a}").text
    assert "ยกเลิกแล้ว" in page and "กรอกผิดคน" in page


def test_void_deposit_blocked_when_balance_would_go_negative(env):
    _cid, (a, _b), _y = _class_with_students()
    env.post("/general/savings/save", data={"date": D, f"dep_{a}": "40"})
    env.post("/general/savings/save", data={"date": D, f"wd_{a}": "30"})
    from app.models import SavingsTxn
    with _s() as s:
        dep = s.query(SavingsTxn).filter_by(student_id=a, kind="dep").one().id
    env.post(f"/general/savings/t/{dep}/void", data={"reason": "ผิด"})
    assert _bal(a) == 10


def test_month_lock_blocks_add_and_void(env):
    _cid, (a, _b), _y = _class_with_students()
    env.post("/general/savings/save", data={"date": D, f"dep_{a}": "20"})
    env.post("/general/savings/months/2026-11/lock")
    env.post("/general/savings/save", data={"date": D, f"dep_{a}": "20"})
    assert _bal(a) == 20
    from app.models import SavingsTxn
    with _s() as s:
        t = s.query(SavingsTxn).filter_by(student_id=a).first().id
    env.post(f"/general/savings/t/{t}/void", data={"reason": "ผิด"})
    assert _bal(a) == 20
    assert "ปิดยอดแล้ว" in env.get("/general/savings/months").text


def test_teacher_only_own_homeroom(env):
    cid, (a, _b), _y = _class_with_students()
    t = _account("ครูออมทรัพย์", "academic")
    r = t.post("/general/savings/save", data={"date": D, f"dep_{a}": "10"}, follow_redirects=False)
    assert r.status_code == 303 and _bal(a) == 0
    assert t.get(f"/general/savings/s/{a}", follow_redirects=False).status_code == 303
    assert t.get("/general/savings/months", follow_redirects=False).status_code == 303


def test_print_pages(env):
    _cid, (a, _b), _y = _class_with_students()
    env.post("/general/savings/save", data={"date": D, f"dep_{a}": "75"})
    book = env.get(f"/general/savings/s/{a}/print").text
    assert "สมุดคู่ฝาก" in book and "75.00" in book
    daily = env.get("/general/savings/daily?date=" + D).text
    assert "สรุปการรับฝาก" in daily and "75.00" in daily


def test_parse_amount():
    from app.services.savings import parse_amount
    assert parse_amount("1,000.50") == 1000.5 and parse_amount("") == 0
    assert parse_amount("-5") is None and parse_amount("x") is None and parse_amount("nan") is None
