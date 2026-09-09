# -*- coding: utf-8 -*-
"""
users.py - จัดการผู้ใช้ในโรงเรียน (เฉพาะ "ไอดีหลัก" ของโรงเรียน)
เพิ่มไอดีย่อย + กำหนดสิทธิ์งาน + รีเซ็ตรหัส + ปิด/เปิด + ลบ
สิทธิ์งานบังคับจริงที่ middleware (app/main.py) หน้านี้แค่ตั้งค่า
"""
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from app.accounts import (
    audit, audit_list, AUDIT_KEEP_DAYS, AUDIT_LABELS,
    list_tenant_users, add_tenant_user, set_user_modules, reset_user_password,
    toggle_user_active, toggle_user_director, delete_tenant_user, tenant_max_users,
    totp_reset_for,
    mark_welcomed, sync_seen_modules,
)
from app.database import get_db
from app.templating import templates
from app.thai_utils import thai_date

router = APIRouter()


def _is_owner(request: Request) -> bool:
    """เฉพาะไอดีหลักของโรงเรียน (ไม่ใช่ superadmin ผู้ขาย)"""
    return bool(request.session.get("uid") and request.session.get("owner")
                and request.session.get("role") != "superadmin")


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request, msg: str = "", err: str = ""):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    # เปิดหน้าจัดการผู้ใช้ = ผ่านการต้อนรับแล้ว (ไม่ต้องเด้งการ์ดต้อนรับอีก)
    uid = request.session.get("uid")
    if uid and not request.session.get("welcomed"):
        mark_welcomed(uid); sync_seen_modules(uid); request.session["welcomed"] = True
    tid = request.session.get("tid")
    return templates.TemplateResponse("users.html", {
        "request": request, "users": list_tenant_users(tid),
        "max_users": tenant_max_users(tid), "msg": msg, "err": err,
    })


def _back(msg: str = "", err: str = ""):
    from urllib.parse import urlencode
    q = urlencode({k: v for k, v in (("msg", msg), ("err", err)) if v})
    return RedirectResponse("/users" + ("?" + q if q else ""), status_code=303)


def _uname(request, uid) -> str:
    """ชื่อผู้ใช้ของ uid นี้ - log ต้องอ่านออกโดยไม่ต้องไปเปิดตารางเทียบ uid เอง"""
    try:
        for u in list_tenant_users(request.session.get("tid")):
            if u["id"] == uid:
                return u["username"]
    except Exception:
        pass
    return f"uid={uid}"


@router.post("/users/add")
def users_add(request: Request, username: str = Form(""), password: str = Form(""),
              display_name: str = Form(""), modules: list[str] = Form(default=[])):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    r = add_tenant_user(request.session.get("tid"), username, password,
                        ",".join(modules), display_name)
    if r.get("error"):
        return _back(err=r["error"])
    audit("user.add", request=request, target=username.strip(),
          detail="สิทธิ์งาน: " + (",".join(modules) or "(ยังไม่กำหนด)"))
    return _back(msg="เพิ่มผู้ใช้แล้ว")


@router.post("/users/{uid}/modules")
def users_modules(request: Request, uid: int, modules: list[str] = Form(default=[])):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    who = _uname(request, uid)
    r = set_user_modules(request.session.get("tid"), uid, ",".join(modules))
    if r.get("error"):
        return _back(err=r["error"])
    audit("user.modules", request=request, target=who,
          detail="สิทธิ์งานใหม่: " + (",".join(modules) or "(ไม่มี)"))
    return _back(msg="บันทึกสิทธิ์งานแล้ว")


@router.post("/users/{uid}/reset")
def users_reset(request: Request, uid: int, new_password: str = Form("")):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    who = _uname(request, uid)
    r = reset_user_password(request.session.get("tid"), uid, new_password)
    if r.get("error"):
        return _back(err=r["error"])
    audit("user.reset_password", request=request, target=who)   # ไม่บันทึกรหัสผ่าน
    return _back(msg="ตั้งรหัสผ่านใหม่แล้ว")


@router.post("/users/{uid}/toggle")
def users_toggle(request: Request, uid: int):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    who = _uname(request, uid)
    r = toggle_user_active(request.session.get("tid"), uid)
    if r.get("error"):
        return _back(err=r["error"])
    audit("user.active", request=request, target=who,
          detail="เปิดใช้งาน" if r.get("active") else "ปิดใช้งาน")
    return _back(msg="เปิดใช้งานผู้ใช้แล้ว" if r.get("active") else "ปิดใช้งานผู้ใช้แล้ว")


@router.post("/users/{uid}/director")
def users_director(request: Request, uid: int):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    who = _uname(request, uid)
    r = toggle_user_director(request.session.get("tid"), uid)
    if r.get("error"):
        return _back(err=r["error"])
    audit("user.director", request=request, target=who,
          detail="ตั้งเป็น ผอ./รองผอ." if r.get("is_director") else "ยกเลิกสิทธิ์ ผอ.")
    return _back(msg="ตั้งเป็น ผอ./รองผอ. แล้ว" if r.get("is_director") else "ยกเลิกสิทธิ์ ผอ. แล้ว")


@router.post("/users/{uid}/delete")
def users_delete(request: Request, uid: int):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    who = _uname(request, uid)
    r = delete_tenant_user(request.session.get("tid"), uid)
    if r.get("error"):
        return _back(err=r["error"])
    audit("user.delete", request=request, target=who)
    return _back(msg="ลบผู้ใช้แล้ว")


# ---------------- บันทึกการใช้งาน (audit log) ----------------
# ให้เฉพาะไอดีหลักดู - เป็นข้อมูลว่าใครทำอะไร ไม่ควรให้ทุกคนในโรงเรียนเห็น
_AUDIT_PILL = {
    "login.fail": "pill-bad", "login.blocked": "pill-bad",
    "user.delete": "pill-bad", "admin.tenant_delete": "pill-bad",
    "data.restore": "pill-warn", "data.download": "pill-warn",
    "user.reset_password": "pill-warn", "user.modules": "pill-warn",
    "user.active": "pill-warn", "user.director": "pill-warn",
    "login.ok": "pill-ok", "user.add": "pill-ok", "teacher.add": "pill-ok",
}


@router.post("/users/{uid}/2fa-reset")
def users_2fa_reset(request: Request, uid: int):
    """ไอดีหลักปลดล็อกยืนยัน 2 ชั้นให้ผู้ใช้ในโรงเรียนตัวเอง (กรณีมือถือหาย/รหัสสำรองหมด)"""
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    who = _uname(request, uid)
    r = totp_reset_for(uid, tenant_id=request.session.get("tid"))
    if r.get("error"):
        return _back(err=r["error"])
    audit("2fa.reset", request=request, target=who,
          detail="ปลดล็อกให้ตั้งค่าใหม่ได้ (เจ้าตัวควรเปิดใช้ใหม่ทันที)")
    return _back(msg=f"ปลดล็อกยืนยัน 2 ชั้นของ {who} แล้ว")


@router.get("/audit", response_class=HTMLResponse)
def audit_page(request: Request, db=Depends(get_db), offset: int = 0,
               action: str = "", q: str = ""):
    if not _is_owner(request):
        return RedirectResponse("/", status_code=303)
    from app.routers.pages import get_school
    limit = 100
    offset = max(0, offset)
    rows, total = audit_list(request.session.get("tid"), limit=limit, offset=offset,
                             action=action.strip(), q=q.strip())

    def thai_dt(dt):
        if not dt:
            return "-"
        return f"{thai_date(dt)} {dt:%H:%M}"

    return templates.TemplateResponse("audit.html", {
        "request": request, "school": get_school(db), "rows": rows, "total": total,
        "limit": limit, "offset": offset, "action": action.strip(), "q": q.strip(),
        "labels": sorted(AUDIT_LABELS.items(), key=lambda kv: kv[1]),
        "keep_days": AUDIT_KEEP_DAYS, "thai_dt": thai_dt,
        "pill": lambda a: _AUDIT_PILL.get(a, "pill-mute"),
    })
