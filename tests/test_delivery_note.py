# -*- coding: utf-8 -*-
"""ใบส่งของ (งานซื้อ) กับ ใบส่งมอบงาน (งานจ้าง) ต้องใช้คำให้ถูกประเภท

ของเดิมงานซื้อก็ขึ้นหัวว่า "ใบส่งมอบงาน" และเนื้อความบอกว่าผู้ขาย "รับซื้อ"
จากโรงเรียน ซึ่งกลับด้าน ผู้ขายเป็นคนขายให้โรงเรียน
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_delivery_note.py
"""
import importlib.util
import io
import pathlib
import re
import sys
import tempfile
import zipfile
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


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

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "tools" / "seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    sys.argv = ["seed_demo.py", "--password", "Demo!2569"]
    seed.main()

    from app.models import School, Vendor
    from app.tenancy import session_for
    db = session_for(1)
    v = Vendor(name="ร้านของมีจำกัด", owner_name="นายสมชาย ใจดี")
    db.add(v)
    db.commit()
    return db, db.query(School).first(), v.id


def _make(db, vid, proc_type, subject):
    from app.models import Procurement, ProcurementItem
    p = Procurement(fiscal_year=2569, subject=subject, proc_type=proc_type,
                    method="เฉพาะเจาะจง", budget_source="อุดหนุน", total_amount=335.0,
                    vendor_id=vid, order_no="1/2569", order_date=datetime(2026, 10, 5),
                    delivery_date=datetime(2026, 10, 5), request_date=datetime(2026, 10, 5))
    p.items.append(ProcurementItem(name="รายการตัวอย่าง", quantity=1, unit="ชุด", unit_price=335))
    db.add(p)
    db.commit()
    return p


def _text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return re.sub(r"<[^>]+>", "", re.sub(r"</w:p>", "\n", xml))


def test_purchase_uses_a_goods_delivery_note(env):
    db, school, vid = env
    from app.services.render import render_document
    p = _make(db, vid, "ซื้อ", "วัสดุสำนักงาน")
    text = _text(render_document("ใบส่งมอบงาน", p, school))
    assert text.lstrip().startswith("ใบส่งของ"), text[:80]
    assert "ส่งของและแจ้งหนี้ขอเบิกเงิน" in text
    assert "ขอส่งมอบพัสดุ" in text
    assert "ใบส่งมอบงาน" not in text
    assert "รับซื้อ" not in text, "ผู้ขายเป็นคนขายให้โรงเรียน ไม่ใช่รับซื้อจากโรงเรียน"
    assert "ขายวัสดุสำนักงาน" in text


def test_hire_still_uses_a_work_delivery_note(env):
    db, school, vid = env
    from app.services.render import render_document
    p = _make(db, vid, "จ้าง", "งานซ่อมแซมอาคารเรียน")
    text = _text(render_document("ใบส่งมอบงาน", p, school))
    assert text.lstrip().startswith("ใบส่งมอบงาน"), text[:80]
    assert "ส่งมอบงานจ้างและแจ้งหนี้ขอเบิกเงิน" in text
    assert "รับจ้างงานซ่อมแซมอาคารเรียน" in text
    assert "ใบส่งของ" not in text


def test_button_label_matches_the_job_type():
    from app.services.render import doc_label
    assert doc_label("ใบส่งมอบงาน", "ซื้อ") == "ใบส่งของ"
    assert doc_label("ใบส่งมอบงาน", "จ้าง") == "ใบส่งมอบงาน"
    # งานจ้างยังต้องเปลี่ยนคำว่าพัสดุเป็นงานจ้างเหมือนเดิม
    assert doc_label("ใบตรวจรับพัสดุ", "จ้าง") == "ใบตรวจรับงานจ้าง"
    assert doc_label("ใบตรวจรับพัสดุ", "ซื้อ") == "ใบตรวจรับพัสดุ"
