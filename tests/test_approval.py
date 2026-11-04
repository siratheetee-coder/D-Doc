# -*- coding: utf-8 -*-
"""ส่งเรื่องพัสดุ/การเงินให้ ผอ. อนุมัติ (services/approval.py)

กติกาที่ต้องถูก
  - ลายเซ็น ผอ. ขึ้นเฉพาะเอกสารของขั้นที่อนุมัติแบบ "แปะลายเซ็น" แล้ว ขั้นอื่นไม่ขึ้น
  - อนุมัติแบบไม่แปะลายเซ็น = ติ๊ก ☑ อนุมัติ แต่ไม่มีรูป
  - แก้ยอดเงินหลังอนุมัติ ลายเซ็นหลุด ต้องส่งใหม่
  - ส่งกลับแก้ต้องมีเหตุผล
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_approval.py
"""
import importlib.util
import io
import pathlib
import sys
import tempfile
import zipfile
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DIRECTOR = "นายทดสอบ ผู้อำนวยการ"


@pytest.fixture()
def env(monkeypatch):
    tmp = pathlib.Path(tempfile.mkdtemp())
    import app.accounts as ac
    import app.database as dbm
    import app.services.signature as sigm
    import app.tenancy as tn
    for m in (dbm, tn, ac, sigm):
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

    from PIL import Image
    from app.accounts import Account, Tenant, acc_session
    from app.models import DisburseMemo, Person, Procurement, ProcurementItem, School
    from app.tenancy import session_for
    with acc_session() as s:
        tid = s.query(Tenant).filter_by(slug="demo").one().id
    db = session_for(tid)
    sig = "sigtest.png"
    Image.new("RGBA", (200, 60), (0, 0, 120, 255)).save(sigm.signatures_dir() / sig)
    p = Person(name=DIRECTOR, position="ผู้อำนวยการโรงเรียน", signature=sig)
    db.add(p)
    sc = db.query(School).first()
    sc.director_name, sc.approval_on = DIRECTOR, True
    pr = Procurement(fiscal_year=2569, subject="วัสดุสำนักงาน", proc_type="ซื้อ", total_amount=3000,
                     request_date=datetime(2026, 1, 5))
    pr.items.append(ProcurementItem(name="กระดาษ A4", quantity=10, unit="รีม", unit_price=300))
    db.add(pr)
    m = DisburseMemo(fiscal_year=2569, subject="ขอเบิกค่าวัสดุ", payee="ร้านทดสอบ", amount=3000,
                     date=datetime(2026, 1, 20))
    db.add(m)
    db.commit()
    ids = dict(proc=pr.id, memo=m.id, person=p.id)
    global SIG_BYTES
    SIG_BYTES = (sigm.signatures_dir() / sig).read_bytes()
    db.close()
    with acc_session() as s:
        u = s.query(Account).filter_by(tenant_id=tid, username="demo").one()
        u.is_director, u.person_id = True, ids["person"]
        s.commit()

    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app, raise_server_exceptions=False)
    r = c.post("/login", data={"username": "demo", "password": "Demo!2569"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    return c, tid, ids


SIG_BYTES = b""


def _docx(resp):
    """(document.xml, มีรูปลายเซ็น ผอ. ไหม) ตรวจจากไบต์ของรูปจริง เพราะบันทึกข้อความมีรูปครุฑอยู่แล้ว"""
    assert resp.status_code == 200, resp.status_code
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    xml = z.read("word/document.xml").decode("utf-8")
    return xml, any(z.read(n) == SIG_BYTES for n in z.namelist() if n.startswith("word/media/"))


def _latest(tid, kind, ref):
    from app.services import approval
    from app.tenancy import session_for
    db = session_for(tid)
    try:
        a = approval.latest(db, kind, ref)
        return (a.id, a.status, a.with_sign, a.sig_file) if a else None
    finally:
        db.close()


def test_sign_only_approved_stage_and_drop_after_edit(env):
    c, tid, ids = env
    pid = ids["proc"]
    r = c.post(f"/procurement/{pid}/approval", data={"kind": "proc_request", "action": "send"},
               follow_redirects=False)
    assert r.status_code == 303
    aid, status, _s, _f = _latest(tid, "proc_request", pid)
    assert status == "pending"
    assert "วัสดุสำนักงาน" in c.get("/approvals").text

    # ส่งกลับแก้ต้องมีเหตุผล
    c.post(f"/approvals/doc/{aid}/decide", data={"action": "return", "comment": ""})
    assert _latest(tid, "proc_request", pid)[1] == "pending"

    c.post(f"/approvals/doc/{aid}/decide", data={"action": "sign"})
    _id, status, with_sign, sig_file = _latest(tid, "proc_request", pid)
    assert status == "approved" and with_sign and sig_file.startswith("ap_")

    _xml, has_img = _docx(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "รายงานขอซื้อ"}))
    assert has_img                                   # ขั้นที่ 1 อนุมัติแล้ว ขึ้นลายเซ็น
    _xml, has_img = _docx(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "รายงานผลการพิจารณา"}))
    assert not has_img                               # ขั้นที่ 2 ยังไม่ส่ง ไม่ขึ้น

    # แก้ยอดเงินหลังอนุมัติ ลายเซ็นหลุด
    from app.models import Procurement
    from app.tenancy import session_for
    db = session_for(tid)
    db.get(Procurement, pid).total_amount = 3500
    db.commit(); db.close()
    _xml, has_img = _docx(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "รายงานขอซื้อ"}))
    assert not has_img
    assert "แก้หลังอนุมัติ" in c.get(f"/procurement/{pid}").text


def test_approve_without_signature_ticks_only(env):
    c, tid, ids = env
    mid = ids["memo"]
    c.post("/finance/approval", data={"kind": "disburse", "ref_id": mid, "action": "send"})
    aid = _latest(tid, "disburse", mid)[0]
    xml, has_img = _docx(c.get(f"/finance/disburse/{mid}/generate"))
    assert "☑" not in xml and not has_img            # ยังไม่อนุมัติ

    c.post(f"/approvals/doc/{aid}/decide", data={"action": "approve"})
    assert _latest(tid, "disburse", mid)[1:3] == ("approved", False)
    xml, has_img = _docx(c.get(f"/finance/disburse/{mid}/generate"))
    assert "☑" in xml and not has_img


def test_off_by_default_shows_nothing(env):
    c, tid, ids = env
    from app.models import School
    from app.tenancy import session_for
    db = session_for(tid)
    db.query(School).first().approval_on = False
    db.commit(); db.close()
    assert "ส่ง ผอ. อนุมัติ" not in c.get(f"/procurement/{ids['proc']}").text
    r = c.post(f"/procurement/{ids['proc']}/approval", data={"kind": "proc_request", "action": "send"},
               follow_redirects=False)
    assert "err=" in r.headers["location"]
    assert _latest(tid, "proc_request", ids["proc"]) is None
