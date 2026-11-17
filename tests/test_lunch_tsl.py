import json
from app.services import lunch_tsl as t
from tests.test_subsidy import env  # noqa: F401
from tests.test_budget_request import _db

ROWS = [
    ["วันที่", "อาหาร", "ส่วนประกอบ", "ปริมาณที่ซื้อ", "ราคาต่อหน่วย", "จำนวนเงิน"],
    ["03/11/69", "ฝรั่ง 1/4 ผลส่วนที่กินได้ 62 กรัม", "ฝรั่ง", "6.20", "kg", "20.00", "124.00"],
    ["นมสด ยูเอชที รสจืด 200 ml", "นมวัว ยูเอชที รสจืด (นมโรงเรียน)", "100.00", "กล่อง", "0.00", "0.00"],
    ["ไข่ดาว 1 ฟอง 50 กรัม", "ไข่ไก่ ขนาดกลาง(เบอร์2)", "100.00", "ฟอง 50 กรัม (เบอร์ 2)", "4.20", "420.00"],
    ["น้ำมันปาล์มโอเลอิน", "0.48", "ขวดใหญ่ 1000 ml", "46.00", "22.08"],
    ["ข้าวสวยขาว 150 กรัม 2.5 ทัพพี", "ข้าวสารเจ้า หุงข้าวสวย", "6.45", "kg", "25.00", "161.25"],
    ["ผัดกะเพราหมู ใส่ตับ", "หมูสับ", "3.50", "kg", "135.00", "472.50"],
    ["กระเทียม หัว", "2.42", "ขีด", "6.20", "15.00"],
    ["น้ำประปา น้ำเปล่า", "2.00", "ลิตร", "0.00", "0.00"],
    ["จำนวนเงิน", "1,485.73"],
    ["04/11/69", "กล้วยน้ำว้า 1 ผลส่วนที่กินได้ 52 กรัม", "กล้วยน้ำว้า สุก", "100.00", "ผลกลาง (52 กรัม)", "3.10", "310.00"],
    ["ข้าวมันไก่ ตับ เลือด", "กระเทียม หัว", "1.00", "ขีด", "6.20", "6.20"],
    ["กระเทียม หัว", "1.00", "ขีด", "6.20", "6.20"],
]


def test_parse_and_menu():
    days = t.parse_rows(ROWS)
    assert [d["date"].day for d in days] == [3, 4]
    assert t.menu_text(days[0]) == ("ไข่ดาว, ผัดกะเพราหมู ใส่ตับ", "ฝรั่ง")
    names = [g["name"] for g in days[0]["ings"]]
    assert "นมวัว ยูเอชที รสจืด (นมโรงเรียน)" not in names and "น้ำประปา น้ำเปล่า" not in names
    assert days[0]["date"].year == 2026
    m = t.merge_ings(days[1]["ings"])
    assert [g for g in m if g["name"] == "กระเทียม หัว"][0]["qty"] == 2.0
    assert t.report_students("ช่วงชั้น ประถม จำนวน (คน) 100 ช่วงวันที่") == 100


def test_scale():
    assert t.scale_qty(100, "ฟอง 50 กรัม", 0.83) == 83.0
    assert t.scale_qty(100, "ฟอง", 0.835) == 84.0
    assert t.scale_qty(3.5, "kg", 0.5) == 1.75


def test_flow(env):
    client = env
    from app.models import LunchProgram, LunchClass, LunchIngredient, LunchMenu
    from datetime import datetime
    _, db = _db()
    p = LunchProgram(year=2569, operate_mode="ingredient"); db.add(p); db.flush()
    db.add(LunchClass(program_id=p.id, level="ป.1", num_students=50, seq=1))
    db.add(LunchIngredient(program_id=p.id, date=datetime(2026, 10, 1), name="หมูสับ", unit="kg", quantity=1, unit_price=120))
    db.commit(); pid = p.id
    r = client.post(f"/lunch/{pid}/tsl-import/preview", data={"rows": json.dumps(ROWS), "text": "จำนวน (คน) 100"})
    assert r.status_code == 200 and "ราคาที่เคยใช้" in r.text and "ไข่ดาว" in r.text
    r = client.post(f"/lunch/{pid}/tsl-import/save", data={
        "d_on": ["0"], "d_date": ["2026-11-03", "2026-11-04"], "d_main": ["กะเพรา", "ข้าวมันไก่"], "d_dessert": ["ฝรั่ง", "กล้วย"],
        "i_day": ["0", "0", "1"], "i_name": ["หมูสับ", "ไข่ไก่", "กระเทียม"], "i_qty": ["1.75", "50", "1"],
        "i_unit": ["kg", "ฟอง", "ขีด"], "i_price": ["120", "4.2", "6.2"]}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert [m.main for m in db.query(LunchMenu).filter(LunchMenu.program_id == pid).all()] == ["กะเพรา"]
    assert db.query(LunchIngredient).filter(LunchIngredient.date == datetime(2026, 11, 3)).count() == 2
    db.close()
