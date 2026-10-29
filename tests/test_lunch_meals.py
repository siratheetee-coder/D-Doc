"""จ้างเหมาปรุงสำเร็จ: บันทึกมื้อจริงรายวัน รายชั้น -> ยอดงวด = มื้อจริง x ราคาต่อหัว + ค่าปรับ + เอกสาร
(คู่มือ สพฐ. 2569: ชำระเงินตามที่ได้ประกอบอาหารจริงในแต่ละงวด, ค่าปรับร้อยละ 0.2 ต่อวัน)"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_meals_set_installment_amount_and_docs(env):
    from docx import Document
    from app.models import LunchProgram, LunchClass, LunchHireRound, LunchInstallment, Vendor
    with _db() as s:
        v = Vendor(name="นางทดสอบ ปรุงอร่อย"); s.add(v); s.flush()
        p = LunchProgram(year=2569, rate_per_head=22, operate_mode="hire"); s.add(p); s.flush()
        a = LunchClass(program_id=p.id, seq=1, level="ป.1", num_students=10)
        b = LunchClass(program_id=p.id, seq=2, level="ป.2", num_students=12)
        s.add_all([a, b]); s.flush()
        r = LunchHireRound(program_id=p.id, seq=1, vendor_id=v.id, start_date=datetime(2026, 6, 8),
                           end_date=datetime(2026, 6, 12), days=5, amount=2420)
        s.add(r); s.flush()
        i = LunchInstallment(round_id=r.id, seq=1, start_date=datetime(2026, 6, 8), end_date=datetime(2026, 6, 12),
                             days=5, amount=5 * 22 * 22)        # ตั้งต้นตามสิทธิ์เต็ม 2,420
        s.add(i); s.commit()
        iid, ca, cb, rid = i.id, a.id, b.id, r.id

    page = env.get(f"/lunch/installment/{iid}/meals").text
    assert 'name="m_2026-06-08_%d"' % ca in page and "ยังไม่บันทึก" in page

    # บันทึก 4 วัน -> ยังไม่ครบ ยอดงวดไม่เปลี่ยน
    days = ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]
    data = {f"m_{d}_{ca}": "10" for d in days[:4]} | {f"m_{d}_{cb}": "12" for d in days[:4]}
    env.post(f"/lunch/installment/{iid}/meals", data=data)
    with _db() as s:
        assert s.get(LunchInstallment, iid).amount == 2420

    # ครบ 5 วัน โดยวันศุกร์ ป.2 มา 9 คน -> มื้อจริง 107 x 22 = 2,354
    data = {f"m_{days[4]}_{ca}": "10", f"m_{days[4]}_{cb}": "9", "penalty_days": "1"}
    r = env.post(f"/lunch/installment/{iid}/meals", data=data, follow_redirects=False)
    assert "amt=1" in r.headers["location"]
    from app.services.lunch_meals import summary
    with _db() as s:
        inst = s.get(LunchInstallment, iid)
        assert inst.amount == 2354 and inst.penalty_days == 1
        sm = summary(s, inst)
        assert sm["meals"] == 107 and sm["complete"]
        assert sm["penalty"] == round(1 * 0.002 * 2354 / 5, 2)
        assert sm["net"] == round(2354 - 23.54 - sm["penalty"], 2)

    # จ่ายแล้ว: แก้มื้อไม่เปลี่ยนยอด
    env.post(f"/lunch/installment/{iid}/update", data={"status": "จ่ายแล้ว"})
    env.post(f"/lunch/installment/{iid}/meals", data={f"m_{days[0]}_{ca}": "1"})
    with _db() as s:
        assert s.get(LunchInstallment, iid).amount == 2354

    # เอกสารงวดมีบัญชีจำนวนนักเรียนรายวัน
    import io
    doc = Document(io.BytesIO(env.get(f"/lunch/installment/{iid}/doc").content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "บัญชีจำนวนนักเรียนที่รับประทานอาหารกลางวัน" in text
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert "ป.2" in cells
    # บันทึกขอเบิกจ่ายมีค่าปรับ
    doc = Document(io.BytesIO(env.get(f"/lunch/installment/{iid}/disburse-doc").content))
    cells = [c.text for t in doc.tables for row in t.rows for c in row.cells]
    assert any("0.94 บาท" in c for c in cells)
    # หน้ารอบแสดงสถานะมื้อจริงในแถวงวด
    assert "ยอดนักเรียนรายวัน" in env.get(f"/lunch/round/{rid}/plan").text


def test_pay_once_for_whole_round(env):
    """รอบ 50 วันแบ่ง 5 งวด ส่งมอบ/ตรวจรับรายงวด แต่จ่ายเงินครั้งเดียวทั้งรอบ"""
    import io
    from docx import Document
    from app.models import (LunchProgram, LunchClass, LunchHireRound, LunchInstallment, LunchLedger, Vendor)
    with _db() as s:
        v = Vendor(name="ร้านอิ่มทั้งรอบ"); s.add(v); s.flush()
        p = LunchProgram(year=2569, rate_per_head=20, operate_mode="hire"); s.add(p); s.flush()
        c = LunchClass(program_id=p.id, seq=1, level="ป.1", num_students=10); s.add(c); s.flush()
        r = LunchHireRound(program_id=p.id, seq=1, vendor_id=v.id, start_date=datetime(2026, 6, 8),
                           end_date=datetime(2026, 6, 19), days=10, amount=2000, status="จ้างแล้ว")
        s.add(r); s.flush()
        i1 = LunchInstallment(round_id=r.id, seq=1, start_date=datetime(2026, 6, 8), end_date=datetime(2026, 6, 12),
                              days=5, amount=1000, status="จ่ายแล้ว")
        i2 = LunchInstallment(round_id=r.id, seq=2, start_date=datetime(2026, 6, 15), end_date=datetime(2026, 6, 19),
                              days=5, amount=1000)
        s.add_all([i1, i2]); s.commit()
        rid, a, b, cid = r.id, i1.id, i2.id, c.id

    # มีงวดที่จ่ายแล้ว เปลี่ยนเป็นจ่ายทั้งรอบไม่ได้
    r_ = env.post(f"/lunch/round/{rid}/pay-mode", data={"pay_mode": "round"}, follow_redirects=False)
    assert "err=" in r_.headers["location"]
    env.post(f"/lunch/installment/{a}/update", data={"status": "ตรวจรับแล้ว"})
    env.post(f"/lunch/round/{rid}/pay-mode", data={"pay_mode": "round"})
    with _db() as s:
        assert s.get(LunchHireRound, rid).pay_mode == "round"
        assert s.query(LunchLedger).filter_by(installment_id=a).count() == 0

    # งวดเลือก "จ่ายแล้ว" ไม่ได้ จบที่ตรวจรับ
    env.post(f"/lunch/installment/{b}/update", data={"status": "จ่ายแล้ว"})
    with _db() as s:
        assert s.get(LunchInstallment, b).status == "ตรวจรับแล้ว"

    # ยอดนักเรียน: งวด 2 ขาด 5 คนรวม -> 45 x 20 = 900
    days2 = ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"]
    env.post(f"/lunch/installment/{b}/meals", data={f"m_{d}_{cid}": ("5" if d == days2[0] else "10") for d in days2})
    page = env.get(f"/lunch/round/{rid}/plan").text
    assert "จ่ายเงินทั้งรอบ" in page and "1,900.00" in page and "ตรวจรับครบแล้ว" in page

    # เอกสารขอเบิกทั้งรอบ
    doc = Document(io.BytesIO(env.get(f"/lunch/round/{rid}/disburse-doc").content))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "รอบที่ 1 (งวดที่ 1-2)" in text and "1,900" in text

    # จ่ายทั้งรอบ -> ลงบัญชีรายการเดียว 1,900
    r_ = env.post(f"/lunch/round/{rid}/status", data={"status": "จ่ายแล้ว", "back": f"/lunch/round/{rid}/plan#installments"},
                  follow_redirects=False)
    assert r_.headers["location"].startswith(f"/lunch/round/{rid}/plan")
    with _db() as s:
        leds = s.query(LunchLedger).filter((LunchLedger.round_id == rid) | (LunchLedger.installment_id.in_([a, b]))).all()
        assert len(leds) == 1 and leds[0].round_id == rid and leds[0].amount == 1900


def test_round_chart_and_doc_checks(env):
    """กราฟยอดนักเรียนรายวันทั้งรอบ + ตรวจความถูกต้องก่อนออกเอกสาร"""
    import json, re
    from app.models import LunchProgram, LunchClass, LunchHireRound, LunchInstallment, Vendor
    with _db() as s:
        v = Vendor(name="ร้านตรวจก่อนออก"); s.add(v); s.flush()
        p = LunchProgram(year=2569, rate_per_head=20, operate_mode="hire"); s.add(p); s.flush()
        c = LunchClass(program_id=p.id, seq=1, level="ป.1", num_students=10); s.add(c); s.flush()
        r = LunchHireRound(program_id=p.id, seq=1, vendor_id=v.id, start_date=datetime(2026, 6, 8),
                           end_date=datetime(2026, 6, 19), days=10, amount=2000)
        s.add(r); s.flush()
        i1 = LunchInstallment(round_id=r.id, seq=1, start_date=datetime(2026, 6, 8), end_date=datetime(2026, 6, 12),
                              days=5, amount=1000, deliver_date=datetime(2026, 6, 12), inspect_date=datetime(2026, 6, 11))
        i2 = LunchInstallment(round_id=r.id, seq=2, start_date=datetime(2026, 6, 12), end_date=datetime(2026, 6, 19),
                              days=5, amount=0)
        s.add_all([i1, i2]); s.commit()
        rid, a, b, cid = r.id, i1.id, i2.id, c.id

    # ป.1 มีสิทธิ์ 10 คน แต่บันทึกวันแรก 12 คน
    env.post(f"/lunch/installment/{a}/meals", data={f"m_2026-06-08_{cid}": "12", f"m_2026-06-09_{cid}": "9"})
    page = env.get(f"/lunch/round/{rid}/plan").text
    assert "ยอดนักเรียนรายวันทั้งรอบ" in page and 'id="rc-chart"' in page
    assert "ตรวจก่อนออกเอกสาร" in page and 'data-chk="i%d"' % a in page

    chk = json.loads(re.search(r"var CHK = (\{.*?\});\n", page).group(1))
    msgs = lambda k: " | ".join(x["msg"] for x in chk[k])
    assert "วันตรวจรับอยู่ก่อนวันส่งมอบ" in msgs(f"i{a}")
    assert "เกินจำนวนนักเรียนที่มีสิทธิ์" in msgs(f"i{a}")
    assert "บันทึกยอดนักเรียนรายวันแล้ว 2 จาก 5 วัน" in msgs(f"i{a}")
    assert "ซ้อนกับงวดที่ 1" in msgs(f"i{b}") and "ค่าจ้างงวดเป็น 0 บาท" in msgs(f"i{b}")
    assert "ยังไม่ได้ตรวจรับ" in msgs(f"d{a}") and "เลขประจำตัวผู้เสียภาษี" in msgs(f"d{a}")
    assert "งวดที่ 2: ค่าจ้างงวดเป็น 0 บาท" in msgs("r")

    from app.services.lunch_checks import round_chart
    with _db() as s:
        d = round_chart(s, s.get(LunchHireRound, rid))
        assert d["eligible"] == 10 and d["recorded"] == 2 and d["max"] == 12
        assert d["groups"][0]["days"][0]["n"] == 12 and d["groups"][0]["days"][2]["n"] is None
