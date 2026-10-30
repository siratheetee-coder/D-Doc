"""ตรวจสอบพัสดุ: หน้าภาพรวมทั้งปี (ตรวจสอบ > ชำรุด > จำหน่าย > ลงจ่าย/แจ้ง สตง.) + เมนูข้างของตัวเอง"""
from datetime import datetime, timedelta

from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def test_inspection_year_flow(env):
    from app.models import Asset, AssetDisposal, IssuedDocNo
    from app.services.asset_inspection import overview
    from app.thai_utils import current_fiscal_year
    fy = current_fiscal_year()
    with _db() as s:
        a = Asset(asset_code="7440-001-0001/1", name="เครื่องคอมพิวเตอร์ทดสอบ", cost=18000, status="ชำรุด")
        s.add(a); s.commit()
        aid = a.id
        o = overview(s, fy)
        st = {x["key"]: x for x in o["stages"]}
        assert not st["audit"]["done"] and not st["damaged"]["done"]
        assert aid in [x.id for x in o["waiting"]]

    html = env.get("/assets/inspection").text
    assert "ขั้นตอนทั้งปี" in html and "รอเปิดสำนวน" in html
    assert 'href="/assets/inspection/damaged"' in html and 'class="nav-sec">ตรวจสอบพัสดุ<' in html
    assert "เครื่องคอมพิวเตอร์ทดสอบ" in env.get("/assets/inspection/damaged").text

    # เปิดสำนวนจากหน้าพัสดุชำรุด -> ขั้นชำรุดครบ ขั้นจำหน่ายกำลังดำเนินการ
    r = env.post("/assets/disposal", data={"asset_ids": str(aid), "year": str(fy)}, follow_redirects=False)
    did = int(r.headers["location"].split("/")[-1].split("?")[0])
    with _db() as s:
        o = overview(s, fy)
        assert aid not in [x.id for x in o["waiting"]] and (aid, did) in [(x.id, d) for x, d in o["in_case"]]
        assert did in [d.id for d in o["open_cases"]] and not {x["key"]: x for x in o["stages"]}["dispose"]["done"]

    # ลงจ่ายเมื่อ 40 วันก่อน ยังไม่แจ้ง -> เลยกำหนด 30 วัน
    env.post(f"/assets/disposal/{did}/write-off")
    with _db() as s:
        dp = s.get(AssetDisposal, did)
        dp.written_off_date = datetime.now() - timedelta(days=40)
        s.commit()
        o = overview(s, fy)
        assert o["overdue"] and {x["key"]: x for x in o["stages"]}["report"]["status"].startswith("เลยกำหนด")
    page = env.get("/assets/inspection/report").text
    assert "เลยกำหนด" in page and "แจ้ง สตง." in page and f"/assets/disposal/{did}#tab-close" in page

    # แจ้ง สพท. + สตง. แล้ว -> รายงานครบ, ออกเอกสารตรวจสอบประจำปีแล้ว -> ขั้นตรวจสอบครบ
    with _db() as s:
        dp = s.get(AssetDisposal, did)
        dp.area_no, dp.sao_no = "ศธ 1/2569", "ศธ 2/2569"
        s.add(IssuedDocNo(doc_type="command", fiscal_year=fy, seq=9, full_no="9/2569", source="asset_audit",
                          ref_id=fy, subject="คำสั่งแต่งตั้งคณะกรรมการตรวจสอบพัสดุ"))
        s.commit()
        o = overview(s, fy)
        assert did not in [d.id for d, _s in o["report_todo"]]
        assert {x["key"]: x for x in o["stages"]}["audit"]["done"]
