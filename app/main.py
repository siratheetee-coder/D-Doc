"""
main.py
-------
จุดเริ่มต้นของโปรแกรม (ระบบคลาวด์หลายโรงเรียน)
- bootstrap ฐานข้อมูลกลาง (บัญชีผู้ใช้/โรงเรียน) + ย้ายข้อมูลเดิมเป็นโรงเรียนแรก
- middleware: บังคับล็อกอิน + เลือกฐานข้อมูลของโรงเรียน + ตรวจวันหมดอายุ/ระงับ

รันตอนพัฒนา:  uvicorn app.main:app --reload
รันบนคลาวด์:  uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""
import os
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.accounts import bootstrap, get_secret_key, tenant_state
from app.tenancy import current_school_id
from app.templating import templates
from app.routers import pages, admin, finance, lunch, auth, superadmin, account, textbooks, sales

app = FastAPI(title="D-Doc : ระบบจัดการเอกสารและพัสดุโรงเรียน")

# เตรียมฐานข้อมูลกลาง + superadmin + ย้ายข้อมูลเดิม (ถ้ามี)
bootstrap()

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# เส้นทางที่เข้าได้โดยไม่ต้องล็อกอิน
PUBLIC_PATHS = {"/login", "/logout", "/healthz", "/favicon.ico", "/landing",
                "/quote", "/checkout", "/checkout/promptpay.png", "/sale-thanks",
                "/trial", "/register", "/register/resend", "/verify"}


@app.middleware("http")
async def tenant_auth(request: Request, call_next):
    """บังคับล็อกอิน + ตั้งฐานข้อมูลของโรงเรียนที่ล็อกอิน + ตรวจหมดอายุ/ระงับ"""
    # กัน CSRF: ปฏิเสธ POST/แก้ไข ที่มาจากโดเมนอื่น (เทียบ Origin กับ Host) + คุกกี้ SameSite=Lax อีกชั้น
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin:
            oh = urlparse(origin).netloc
            if oh and oh != request.headers.get("host"):
                return PlainTextResponse("ปฏิเสธคำขอข้ามโดเมน (CSRF)", status_code=403)

    path = request.url.path
    if path.startswith("/static") or path in PUBLIC_PATHS:
        return await call_next(request)

    sess = request.session
    if not sess.get("uid"):
        return RedirectResponse("/login", status_code=303)

    # บังคับเปลี่ยนรหัสผ่านครั้งแรก (ก่อนใช้งานอื่นใด)
    if sess.get("must_change") and not path.startswith("/account"):
        return RedirectResponse("/account/password", status_code=303)

    # หน้าบัญชีตัวเอง (เปลี่ยนรหัสผ่าน) ใช้ได้ทุกบทบาท ไม่ต้องผูกฐานข้อมูลโรงเรียน
    if path.startswith("/account"):
        return await call_next(request)

    # ผู้ดูแลระบบ (ผู้ขาย): ใช้เฉพาะหน้าคอนโซล ไม่มีฐานข้อมูลโรงเรียน
    if sess.get("role") == "superadmin":
        if not path.startswith("/admin-console"):
            return RedirectResponse("/admin-console", status_code=303)
        token = current_school_id.set(None)
        try:
            return await call_next(request)
        finally:
            current_school_id.reset(token)

    # กันผู้ใช้โรงเรียน (ไม่ใช่ superadmin) แอบเข้าคอนโซลผู้ดูแลระบบ
    if path.startswith("/admin-console"):
        return RedirectResponse("/", status_code=303)

    # ผู้ใช้โรงเรียน: ตรวจสถานะโรงเรียนก่อน
    tid = sess.get("tid")
    st = tenant_state(tid)
    if not st or not st["active"] or st["expired"]:
        reason = ("บัญชีถูกระงับการใช้งาน" if (st and not st["active"])
                  else "บัญชีหมดอายุการใช้งาน" if st else "ไม่พบข้อมูลโรงเรียน")
        return templates.TemplateResponse("account_blocked.html", {
            "request": request, "reason": reason,
            "school": st["name"] if st else "", "expiry": st["expiry_date"] if st else None,
        }, status_code=403)

    token = current_school_id.set(tid)
    try:
        return await call_next(request)
    finally:
        current_school_id.reset(token)


# SessionMiddleware เพิ่มทีหลัง -> เป็นชั้นนอกสุด (request.session พร้อมใช้ใน tenant_auth)
# บนคลาวด์ที่เป็น HTTPS ตั้ง env DDOC_HTTPS=1 เพื่อบังคับคุกกี้ Secure
app.add_middleware(
    SessionMiddleware, secret_key=get_secret_key(),
    session_cookie="ddoc_session", same_site="lax",
    https_only=(os.environ.get("DDOC_HTTPS") == "1"),
    max_age=60 * 60 * 12,   # session 12 ชั่วโมง
)


@app.api_route("/healthz", methods=["GET", "HEAD"])
def healthz():
    return {"ok": True}


def _start_auto_backup():
    """ตัวจับเวลาสำรองข้อมูลอัตโนมัติทุกวัน (รันในโปรเซสแอป — เหมาะกับ Render)
    เปิดด้วย env DDOC_AUTO_BACKUP=1 ; อัปขึ้นคลาวด์ถ้าตั้งค่า BACKUP_S3_* ไว้"""
    if os.environ.get("DDOC_AUTO_BACKUP") != "1":
        return
    import time
    from app.services.backup import run_backup

    # ความถี่สำรอง (นาที) — ฟรีทีเออร์ควรตั้งถี่ เช่น 15 เพราะเครื่องอาจถูกล้างได้ตลอด
    try:
        interval = max(5, int(os.environ.get("DDOC_BACKUP_INTERVAL_MIN", "1440")))
    except ValueError:
        interval = 1440

    def loop():
        time.sleep(30)            # รอระบบพร้อมก่อน แล้วสำรองครั้งแรก
        while True:
            try:
                run_backup()
            except Exception as e:
                print("[auto-backup] ผิดพลาด:", e)
            time.sleep(interval * 60)

    threading.Thread(target=loop, daemon=True).start()
    print(f"[D-Doc] เปิดสำรองข้อมูลอัตโนมัติ (ทุก {interval} นาที)")


_start_auto_backup()


app.include_router(auth.router)
app.include_router(account.router)
app.include_router(superadmin.router)
app.include_router(pages.router)
app.include_router(admin.router)
app.include_router(finance.router)
app.include_router(lunch.router)
app.include_router(textbooks.router)
app.include_router(sales.router)


def _open_browser():
    webbrowser.open("http://127.0.0.1:8000")


def run():
    """ใช้ตอนรันในเครื่อง (double-click) — เปิดเซิร์ฟเวอร์ + เบราว์เซอร์"""
    import uvicorn
    threading.Timer(1.5, _open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
