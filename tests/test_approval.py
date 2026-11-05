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


def _approve(c, tid, path, kind, ref, action="sign", **extra):
    data = {"kind": kind, "action": "send", **extra}
    r = c.post(path, data=data, follow_redirects=False)
    assert r.status_code == 303 and "err=" not in r.headers["location"], r.headers.get("location")
    aid = _latest(tid, kind, ref)[0]
    c.post(f"/approvals/doc/{aid}/decide", data={"action": action})
    assert _latest(tid, kind, ref)[1] == "approved"
    return aid


def test_special_case_w804_signed_with_ellipsis_dots(env):
    """ว.804 ใช้ … แทนจุด และอนุมัติครั้งเดียวทั้งชุด ติ๊ก เห็นชอบ/อนุมัติ"""
    c, tid, ids = env
    from app.models import Procurement
    from app.tenancy import session_for
    db = session_for(tid)
    db.get(Procurement, ids["proc"]).proc_case = "w804"
    db.commit(); db.close()
    pid = ids["proc"]
    _xml, has_img = _docx(c.get(f"/procurement/{pid}/altdoc/w804"))
    assert not has_img
    _approve(c, tid, f"/procurement/{pid}/approval", "proc_alt", pid)
    xml, has_img = _docx(c.get(f"/procurement/{pid}/altdoc/w804"))
    assert has_img and "☑" in xml
    # ข้อ 79 วรรคสอง หัวหน้าเจ้าหน้าที่อนุมัติ ไม่มีกล่องส่ง ผอ.
    db = session_for(tid)
    db.get(Procurement, pid).proc_case = "clause79"
    db.commit(); db.close()
    assert "ส่ง ผอ. อนุมัติ" not in c.get(f"/procurement/{pid}").text


def test_admin_docs_sign_only_after_approval(env):
    c, tid, ids = env
    from app.models import OfficeMemo, OfficialLetter, SchoolOrder
    from app.tenancy import session_for
    db = session_for(tid)
    o = SchoolOrder(fiscal_year=2569, subject="แต่งตั้งครูเวร", body="ให้ครูอยู่เวร", date=datetime(2026, 1, 5))
    lt = OfficialLetter(fiscal_year=2569, subject="ขอเชิญประชุม", to="ผอ.สพป.", body="เนื้อความ",
                        signer_name=DIRECTOR, date=datetime(2026, 1, 5))
    m = OfficeMemo(fiscal_year=2569, subject="ขออนุญาตจัดกิจกรรม", body="รายละเอียด",
                   signer_name="นางครู ทดสอบ", date=datetime(2026, 1, 5))
    db.add_all([o, lt, m]); db.commit()
    oid, lid, mid = o.id, lt.id, m.id
    db.close()
    # ก่อนอนุมัติ: คำสั่ง/หนังสือ ที่ ผอ. ลงนาม ไม่ขึ้นลายเซ็น (เดิมแปะให้เลย)
    assert not _docx(c.get(f"/admin/orders/{oid}/generate"))[1]
    assert not _docx(c.get(f"/admin/letters/{lid}/generate"))[1]
    _approve(c, tid, "/admin/approval", "order", oid, ref_id=oid)
    _approve(c, tid, "/admin/approval", "letter", lid, ref_id=lid)
    assert _docx(c.get(f"/admin/orders/{oid}/generate"))[1]
    assert _docx(c.get(f"/admin/letters/{lid}/generate"))[1]
    # บันทึกที่ครูลงนาม: อนุมัติแล้วต่อท้ายความเห็น ผอ. + ลายเซ็น
    xml, has_img = _docx(c.get(f"/admin/memos/{mid}/generate"))
    assert "ความเห็นของ" not in xml and not has_img
    _approve(c, tid, "/admin/approval", "memo", mid, ref_id=mid)
    xml, has_img = _docx(c.get(f"/admin/memos/{mid}/generate"))
    assert "ความเห็นของ" in xml and "☑" in xml and has_img


def test_project_and_report(env):
    c, tid, ids = env
    from app.models import Project, ProjectReport
    from app.tenancy import session_for
    db = session_for(tid)
    p = Project(name="ส่งเสริมการอ่าน", budget=10000, plan_year=2569)
    db.add(p); db.flush()
    r = ProjectReport(project_id=p.id, title="ส่งเสริมการอ่าน", responsible="นางครู ทดสอบ")
    db.add(r); db.commit()
    pid, rid = p.id, r.id
    db.close()
    _approve(c, tid, "/projects/approval", "project", pid, action="approve", ref_id=pid)
    assert "ผอ. อนุมัติแล้ว" in c.get(f"/projects/{pid}").text
    assert not _docx(c.get(f"/project-reports/{rid}/doc.docx"))[1]
    _approve(c, tid, "/projects/approval", "project_report", rid, ref_id=rid)
    assert _docx(c.get(f"/project-reports/{rid}/doc.docx"))[1]


def test_signed_files_have_no_internal_marker(env):
    """เครื่องหมายภายในของตัววางลายเซ็นต้องไม่หลุดไปในไฟล์ (Word อาจเปิดไม่ได้)"""
    c, tid, ids = env
    from app.models import OfficeMemo
    from app.tenancy import session_for
    db = session_for(tid)
    m = OfficeMemo(fiscal_year=2569, subject="ทดสอบ", body="x", signer_name="นางครู ทดสอบ",
                   date=datetime(2026, 1, 5))
    db.add(m); db.commit(); mid = m.id; db.close()
    _approve(c, tid, "/admin/approval", "memo", mid, ref_id=mid)
    _approve(c, tid, f"/procurement/{ids['proc']}/approval", "proc_request", ids["proc"])
    for resp in (c.get(f"/admin/memos/{mid}/generate"),
                 c.post(f"/procurement/{ids['proc']}/generate", data={"doc_kind": "รายงานขอซื้อ"})):
        xml, has_img = _docx(resp)
        assert has_img and "easy-ekkasan" not in xml


def test_preview_lists_docs_and_serves_pages(env, monkeypatch):
    """ดูตัวอย่างเอกสาร: รายชื่อเอกสาร -> ภาพทีละหน้า (แทนตัวแปลงจริงด้วย PDF 2 หน้า ไม่ต้องมี LibreOffice)"""
    pymupdf = pytest.importorskip("pymupdf")
    from app.services import doc_preview as dp
    calls = []

    def fake_pdf(docx, out_dir):
        calls.append(docx)
        doc = pymupdf.open()
        for _ in range(2):
            doc.new_page(width=595, height=842)
        out = out_dir / (docx.stem + ".pdf")
        doc.save(str(out))
        return out
    monkeypatch.setattr(dp, "_to_pdf", fake_pdf)
    monkeypatch.setattr(dp, "_AVAIL", True)
    c, tid, ids = env
    pid = ids["proc"]

    # ผู้ส่งดูก่อนกดส่ง (path ของงานพัสดุ)
    docs = c.get(f"/procurement/{pid}/approval/preview?kind=proc_request").json()["docs"]
    assert "รายงานขอซื้อ" in [d["key"] for d in docs]
    r = c.get(f"/procurement/{pid}/approval/preview?kind=proc_request&doc=รายงานขอซื้อ").json()
    assert r["ok"] and r["total"] == 2 and len(r["pages"]) == 2
    img = c.get(r["pages"][1])
    assert img.status_code == 200 and img.content[:4] == b"\x89PNG"
    # เอกสารไม่ถูกแก้ = ใช้ภาพเดิม ไม่แปลงซ้ำ
    c.get(f"/procurement/{pid}/approval/preview?kind=proc_request&doc=รายงานขอซื้อ")
    assert len(calls) == 1
    # เอกสารที่ไม่อยู่ในขั้นนี้ / คีย์มั่ว
    assert not c.get(f"/procurement/{pid}/approval/preview?kind=proc_request&doc=ใบสั่งซื้อ/สั่งจ้าง").json()["ok"]
    assert c.get("/approvals/preview/" + "0" * 40 + "/1.png").status_code == 404
    assert c.get("/approvals/preview/../1.png").status_code == 404

    # ฝั่ง ผอ.
    c.post(f"/procurement/{pid}/approval", data={"kind": "proc_request", "action": "send"})
    aid = _latest(tid, "proc_request", pid)[0]
    page = c.get(f"/approvals/doc/{aid}").text
    assert f'data-dp-inline="/approvals/doc/{aid}/preview"' in page
    j = c.get(f"/approvals/doc/{aid}/preview").json()
    assert all(d["file"].startswith(f"/approvals/doc/{aid}/file?doc=") for d in j["docs"])
    assert c.get(f"/approvals/doc/{aid}/preview?doc=รายงานขอซื้อ").json()["ok"]


# ---------------------------------------------------------------- ระยะ 3
def _lunch_round(tid):
    from app.models import LunchClass, LunchCommittee, LunchHireRound, LunchInstallment, LunchProgram, Vendor
    from app.tenancy import session_for
    db = session_for(tid)
    v = db.query(Vendor).first()
    if v is None:
        v = Vendor(name="ร้านอาหารทดสอบ")
        db.add(v)
        db.flush()
    prog = LunchProgram(year=2569, days=200, rate_per_head=36, operate_mode="hire")
    prog.classes.append(LunchClass(seq=0, level="ป.1", num_students=20))
    db.add(prog)
    db.flush()
    rnd = LunchHireRound(program_id=prog.id, seq=1, start_date=datetime(2026, 5, 18), end_date=datetime(2026, 6, 30),
                         days=20, vendor_id=v.id, amount=14400, status="จ้างแล้ว")
    db.add(rnd)
    db.flush()
    for i, role in enumerate(("ประธานกรรมการ", "กรรมการ", "กรรมการและเลขานุการ"), 1):
        db.add(LunchCommittee(round_id=rnd.id, kind="inspect", seq=i, name=f"ครูทดสอบ {i}", role=role))
    ids = []
    for n in (1, 2):
        it = LunchInstallment(round_id=rnd.id, seq=n, start_date=datetime(2026, 6, 1 + (n - 1) * 14),
                              end_date=datetime(2026, 6, 12 + (n - 1) * 14), days=10, amount=7200)
        db.add(it)
        db.flush()
        ids.append(it.id)
    db.commit()
    rid = rnd.id
    db.close()
    return rid, ids


def test_lunch_round_sign_and_bulk_installments(env):
    c, tid, _ids = env
    rid, insts = _lunch_round(tid)
    page = c.get(f"/lunch/round/{rid}/plan").text
    assert 'action="/lunch/approval"' in page and "งวดที่ 2" in page

    docs = c.get(f"/lunch/approval/preview?kind=lunch_round&ref_id={rid}").json()["docs"]
    assert [d["key"] for d in docs][:2] == ["hire-report", "committee"]

    c.post("/lunch/approval", data={"kind": "lunch_round", "ref_id": rid, "action": "send"})
    aid = _latest(tid, "lunch_round", rid)[0]
    c.post(f"/approvals/doc/{aid}/decide", data={"action": "sign"})
    _xml, has_img = _docx(c.get(f"/lunch/round/{rid}/hire-report-doc"))
    assert has_img                                   # รอบอนุมัติแล้ว รายงานขอจ้างมีลายเซ็น
    _xml, has_img = _docx(c.get(f"/lunch/installment/{insts[0]}/doc"))
    assert not has_img                               # งวดยังไม่ส่ง

    # อนุมัติหลายงวดพร้อมกัน
    for i in insts:
        c.post("/lunch/approval", data={"kind": "lunch_inst", "ref_id": i, "action": "send"})
    aids = [_latest(tid, "lunch_inst", i)[0] for i in insts]
    r = c.post("/approvals/docs/decide-many", data={"action": "approve", "aid": aids}, follow_redirects=False)
    assert r.status_code == 303 and "msg=" in r.headers["location"]
    assert all(_latest(tid, "lunch_inst", i)[1] == "approved" for i in insts)
    xml, has_img = _docx(c.get(f"/lunch/installment/{insts[1]}/disburse-doc"))
    assert not has_img                               # อนุมัติแบบไม่แปะลายเซ็น
    assert c.get(f"/lunch/installment/{insts[0]}/approval-go", follow_redirects=False).headers["location"] \
        == f"/lunch/round/{rid}/plan#approval"


def test_revenue_remit_signed(env):
    c, tid, _ids = env
    from app.models import FinanceAccount, RevenueRemit
    from app.tenancy import session_for
    db = session_for(tid)
    acc = FinanceAccount(name="เงินรายได้แผ่นดิน", opening_balance=0, deposit_type="bank")
    db.add(acc)
    db.flush()
    r = RevenueRemit(fiscal_year=2569, date=datetime(2026, 1, 15), account_id=acc.id, rtype="interest",
                     amount=125.5, send_to="สพป.ทดสอบ เขต 1", memo_no="ศธ 1/2569", letter_no="ศธ 2/2569")
    db.add(r)
    db.commit()
    rid = r.id
    db.close()
    assert 'action="/finance/approval"' in c.get("/finance/revenue?year=2569").text
    c.post("/finance/approval", data={"kind": "revenue", "ref_id": rid, "action": "send"})
    aid = _latest(tid, "revenue", rid)[0]
    c.post(f"/approvals/doc/{aid}/decide", data={"action": "sign"})
    xml, has_img = _docx(c.get(f"/finance/revenue/{rid}/memo.docx"))
    assert has_img and "( ✓ )" in xml
    _xml, has_img = _docx(c.get(f"/finance/revenue/{rid}/letter.docx"))
    assert has_img                                   # หนังสือนำส่ง: ลายเซ็นในบรรทัดว่างเหนือชื่อ
    assert c.get(f"/approvals/doc/{aid}/preview").json()["docs"][1]["key"] == "letter"


def test_acting_director_name_on_document(env):
    """ผู้อนุมัติไม่ใช่ ผอ. ตามตั้งค่า = รักษาราชการแทน ชื่อในเอกสารเป็นผู้อนุมัติ"""
    c, tid, ids = env
    from app.models import School
    from app.tenancy import session_for
    db = session_for(tid)
    db.query(School).first().director_name = "นายผู้อำนวยการ ตัวจริง"
    db.commit(); db.close()
    pid = ids["proc"]
    c.post(f"/procurement/{pid}/approval", data={"kind": "proc_request", "action": "send"})
    aid = _latest(tid, "proc_request", pid)[0]
    assert "รักษาราชการแทน" in c.get(f"/approvals/doc/{aid}").text
    c.post(f"/approvals/doc/{aid}/decide", data={"action": "sign"})
    xml, has_img = _docx(c.post(f"/procurement/{pid}/generate", data={"doc_kind": "รายงานขอซื้อ"}))
    assert has_img
    assert f"( {DIRECTOR} )" in xml and "นายผู้อำนวยการ ตัวจริง" not in xml
    assert "รักษาราชการแทน" in xml


def test_acting_director_on_admin_letter_and_memo(env):
    c, tid, _ids = env
    from app.models import OfficeMemo, OfficialLetter, School
    from app.tenancy import session_for
    real = "นายผู้อำนวยการ ตัวจริง"
    db = session_for(tid)
    db.query(School).first().director_name = real
    lt = OfficialLetter(fiscal_year=2569, subject="ขอเชิญประชุม", to="ผอ.สพป.", body="เนื้อความ",
                        signer_name=real, date=datetime(2026, 1, 5))
    m = OfficeMemo(fiscal_year=2569, subject="ขออนุญาตจัดกิจกรรม", body="รายละเอียด",
                   signer_name="นางครู ทดสอบ", date=datetime(2026, 1, 5))
    db.add_all([lt, m]); db.commit()
    lid, mid = lt.id, m.id
    db.close()
    _approve(c, tid, "/admin/approval", "letter", lid, ref_id=lid)
    _approve(c, tid, "/admin/approval", "memo", mid, ref_id=mid)
    for url in (f"/admin/letters/{lid}/generate", f"/admin/memos/{mid}/generate"):
        xml, has_img = _docx(c.get(url))
        assert has_img and f"( {DIRECTOR} )" in xml and "รักษาราชการแทน" in xml, url
        assert f"( {real} )" not in xml, url
