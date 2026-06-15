"""Smoke crawl: ยิงทุกหน้า + เคสขอบ หา error 500 / พฤติกรรมแปลก"""
from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal
from app.models import (School, Vendor, Procurement, ProcurementItem,
                        DocNumberCounter, Committee, CommitteeMember, Document)
from app.services.render import AVAILABLE_KINDS


def reset():
    db = SessionLocal()
    for M in (Document, CommitteeMember, Committee, ProcurementItem, Procurement,
              DocNumberCounter, Vendor, School, __import__("app.models", fromlist=["Person"]).Person,
              __import__("app.models", fromlist=["Department"]).Department,
              __import__("app.models", fromlist=["Project"]).Project):
        db.query(M).delete()
    db.commit(); db.close()


def main():
    reset()
    c = TestClient(app, raise_server_exceptions=False)
    issues = []

    # 1) ทุกหน้า GET
    for url in ["/", "/settings", "/vendors", "/masters", "/procurement/new"]:
        r = c.get(url)
        if r.status_code != 200:
            issues.append(f"GET {url} -> {r.status_code}")

    # 2) สร้างเรื่องปกติ (ไม่มีผู้ขาย ไม่มีกรรมการ)
    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "ซื้อ", "method": "เฉพาะเจาะจง",
        "subject": "วัสดุทดสอบ", "inspection_mode": "single",
        "item_name": ["ปากกา"], "item_qty": ["2"], "item_unit": ["ด้าม"], "item_price": ["20"],
    })
    if r.status_code != 200:
        issues.append(f"create (no vendor/committee) -> {r.status_code}")
    pid = r.url.path.split("/")[-1]

    # 3) detail + bundle GET/POST + ออกทุกชนิด
    if c.get(f"/procurement/{pid}").status_code != 200:
        issues.append("detail -> ไม่ 200")
    if c.get(f"/procurement/{pid}/bundle").status_code != 200:
        issues.append("bundle GET -> ไม่ 200")
    rb = c.post(f"/procurement/{pid}/bundle", data={"kinds": list(AVAILABLE_KINDS)})
    if rb.status_code != 200:
        issues.append(f"bundle POST (ครบ 10 ใบ ไม่มีผู้ขาย) -> {rb.status_code}")
    for k in AVAILABLE_KINDS:
        rg = c.post(f"/procurement/{pid}/generate", data={"doc_kind": k})
        if rg.status_code != 200:
            issues.append(f"generate '{k}' -> {rg.status_code}")

    # 4) เคสขอบ: ปีงบไม่ใช่ตัวเลข
    r = c.post("/procurement/new", data={
        "fiscal_year": "abc", "proc_type": "ซื้อ", "subject": "x",
        "item_name": ["a"], "item_qty": ["1"], "item_price": ["1"], "item_unit": ["ชิ้น"],
    })
    if r.status_code >= 500:
        issues.append("create ปีงบ='abc' -> 500 (ควรกันไว้)")

    # 5) เคสขอบ: วันที่ผิดรูปแบบ / ราคาไม่ใช่ตัวเลข
    r = c.post(f"/procurement/{pid}/update-refs", data={
        "memo_no": "1/2569", "order_no": "", "command_no": "", "result_memo_no": "",
        "spec_memo_no": "", "inspect_memo_no": "",
        "request_date": "31/13/2569", "order_date": "ไม่ใช่วันที่"})
    if r.status_code >= 500:
        issues.append("update-refs วันที่ผิดรูปแบบ -> 500")

    r = c.post("/procurement/new", data={
        "fiscal_year": "2569", "proc_type": "ซื้อ", "subject": "y",
        "item_name": ["a"], "item_qty": ["สอง"], "item_price": ["x"], "item_unit": ["ชิ้น"],
    })
    if r.status_code >= 500:
        issues.append("create จำนวน/ราคาไม่ใช่ตัวเลข -> 500 (ควรกันไว้)")

    # 6) สร้างเรื่องไม่มี subject (required) -> ควร 4xx ไม่ใช่ 500
    r = c.post("/procurement/new", data={"fiscal_year": "2569", "proc_type": "ซื้อ"})
    if r.status_code >= 500:
        issues.append("create ไม่มี subject -> 500")

    print("=== ผลการตรวจ smoke ===")
    if issues:
        for i in issues:
            print("  [พบปัญหา]", i)
    else:
        print("  ไม่พบ error 500 ในทุกเส้นทางหลัก")
    print(f"รวม {len(issues)} จุด")


if __name__ == "__main__":
    main()
