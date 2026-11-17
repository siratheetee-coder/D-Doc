"""เลขใบเบิกวัสดุรันให้อัตโนมัติ (ปีงบเดียวกัน ต่อจากเลขมากสุด)"""
from app.models import Requisition
from app.thai_utils import current_fiscal_year
from tests.test_budget_request import _db
from tests.test_subsidy import env  # noqa: F401


def test_requisition_number_runs(env):
    c = env
    tid, db = _db()
    try:
        fy = current_fiscal_year()
        db.add(Requisition(req_no=f"7/{fy}", requester="ก")); db.commit()
        assert f'value="8/{fy}"' in c.get("/requisitions/new").text
        c.post("/requisitions/new", data={"req_no": "", "requester": "ข", "item_name": ["กระดาษ"], "item_qty": ["1"],
                                          "item_unit": ["รีม"], "item_mid": [""]})
        db.expire_all()
        assert db.query(Requisition).order_by(Requisition.id.desc()).first().req_no == f"8/{fy}"
    finally:
        db.close()
