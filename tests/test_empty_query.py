"""
ทดสอบบั๊ก: dropdown ส่งค่าว่าง (?cid=) ทำให้พารามิเตอร์ชนิด int|None error 422
แก้ด้วย middleware ตัดพารามิเตอร์ query ที่ค่าว่างทิ้งก่อน validate
รัน: .venv\\Scripts\\python.exe -m tests.test_empty_query
"""
import app.routers.auth as auth_mod
import app.main as main_mod
from fastapi.testclient import TestClient
from app.main import app


def main():
    auth_mod.authenticate = lambda u, p: {
        "uid": 1, "username": "t", "role": "owner", "tenant_id": 1,
        "display_name": "x", "must_change": False}
    main_mod.can_use_module = lambda tid, mod: True
    c = TestClient(app, raise_server_exceptions=False)
    c.post("/login", data={"username": "t", "password": "x"})

    # เดิม 422 (int|None ไม่รับสตริงว่าง) -> ต้องเป็น 200
    empty = [
        "/academic/grades?year=2567&cid=&sid=",
        "/academic/grades?year=2567&cid=2&sid=",
        "/academic/eval?cid=&year=2567",
        "/finance/accounts?year=",
        "/academic/attendance?cid=&year=&month=",
    ]
    for url in empty:
        r = c.get(url)
        assert r.status_code != 422, f"ยัง 422: {url}"
        assert r.status_code < 500, f"500: {url}"
    print(f"[ok] พารามิเตอร์ query ค่าว่าง {len(empty)} จุด ไม่ error แล้ว")

    # ค่าปกติยังทำงาน
    for url in ["/academic/grades?year=2567", "/academic/grades", "/students"]:
        assert c.get(url).status_code == 200, url
    print("[ok] ค่าพารามิเตอร์ปกติยังทำงานถูกต้อง")
    print("\nบั๊ก empty-query ผ่าน")


if __name__ == "__main__":
    main()
