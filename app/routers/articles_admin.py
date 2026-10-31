# -*- coding: utf-8 -*-
"""เขียนบทความคลังความรู้จากคอนโซล (เฉพาะ superadmin) ไม่ต้องแก้โค้ดหรือ deploy
เก็บที่ data/knowledge/ ดู app/services/articles.py เนื้อหาผ่าน article_clean.clean() ทุกครั้งก่อนบันทึก"""
import io
import secrets
from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.services import article_clean, articles
from app.templating import templates
from app.thai_utils import be_date_input, parse_be_date

IMAGE_MAX = 15 * 1024 * 1024
PDF_MAX = 25 * 1024 * 1024
IMAGE_SIDE = 1600        # ด้านยาวสุด ย่อให้หน้าเว็บโหลดเร็ว


def require_superadmin(request: Request):
    if request.session.get("role") != "superadmin":
        raise HTTPException(status_code=403, detail="เฉพาะผู้ดูแลระบบเท่านั้น")


router = APIRouter(dependencies=[Depends(require_superadmin)])


@router.get("/admin-console/articles", response_class=HTMLResponse)
def article_list(request: Request):
    items = articles.all_articles(include_drafts=True)
    return templates.TemplateResponse("superadmin_articles.html", {
        "request": request, "items": items, "n_draft": sum(1 for a in items if a["draft"]),
        "msg": request.query_params.get("msg", "")})


def _edit_page(request, a):
    return templates.TemplateResponse("superadmin_article_edit.html", {
        "request": request, "a": a, "slug": a["slug"] if a else articles.new_slug(),
        "tabs": articles.CATEGORY_TABS, "types": articles.TYPES,
        "reviewed": be_date_input(a["reviewed"]) if a and a["reviewed"] else ""})


@router.get("/admin-console/articles/new", response_class=HTMLResponse)
def article_new(request: Request):
    return _edit_page(request, None)


@router.get("/admin-console/articles/{slug}/edit", response_class=HTMLResponse)
def article_edit(slug: str, request: Request):
    a = articles.get(slug, include_drafts=True)
    if not a:
        return RedirectResponse("/admin-console/articles?msg=ไม่พบบทความนี้", status_code=303)
    return _edit_page(request, a)


def _cover(value: str) -> str:
    """รูปปกต้องเป็นไฟล์ในเว็บเรา ค่าเดิมในไฟล์ repo เป็นชื่อไฟล์เปล่าใน /static/knowledge/"""
    v = (value or "").strip()
    if not v or ".." in v:
        return ""
    if v.startswith(article_clean.IMG_PREFIX):
        return v
    return v if "/" not in v else ""


@router.post("/admin-console/articles/save")
async def article_save(request: Request):
    """action: draft = เก็บเป็นร่าง, publish = เผยแพร่, keep = บันทึกโดยคงสถานะเดิม"""
    from app.accounts import audit
    form = await request.form()
    orig = (form.get("orig_slug") or "").strip()
    action = form.get("action") or "keep"
    old = articles.get(orig, include_drafts=True) if orig else None
    if orig and not old:
        return JSONResponse({"ok": False, "err": "ไม่พบบทความนี้ อาจถูกลบไปแล้ว"})
    slug = orig if old else (form.get("slug") or "").strip().lower()
    if not articles.slug_ok(slug):
        return JSONResponse({"ok": False, "err": "ลิงก์ใช้ได้เฉพาะ a-z ตัวเลข และขีด - ยาว 3 ถึง 80 ตัว"})
    if not old and articles.slug_taken(slug):
        return JSONResponse({"ok": False, "err": "ลิงก์นี้มีบทความอื่นใช้แล้ว เปลี่ยนเป็นคำอื่น"})
    title = " ".join((form.get("title") or "").split())
    if not title:
        return JSONResponse({"ok": False, "err": "ใส่ชื่อเรื่องก่อน"})
    body, dropped = article_clean.clean(form.get("body") or "")
    draft = {"draft": True, "publish": False}.get(action, old["draft"] if old else True)
    if not draft and not article_clean.plain_len(body):
        return JSONResponse({"ok": False, "err": "ยังไม่มีเนื้อหา เผยแพร่ไม่ได้"})
    reviewed = parse_be_date(form.get("reviewed") or "")
    names, urls = form.getlist("source_name"), form.getlist("source_url")
    sources = [{"name": n, "url": article_clean.safe_url(u)} for n, u in zip(names, urls) if (n or "").strip()]
    today = date.today()
    updated = None
    if old:
        updated = today if not draft and old["date"] != today else (old["updated"] if old["updated"] != old["date"] else None)
    articles.save(slug, title=title, body=body, description=form.get("description") or "",
                  category=form.get("category") or "", type_=form.get("type") or "",
                  cover=form.get("cover") or "", image=_cover(form.get("image")),
                  image_alt=form.get("image_alt") or title, featured=form.get("featured") == "1",
                  reviewed=reviewed.date() if reviewed else None, sources=sources, draft=draft,
                  created=old["date"] if old else today, updated=updated)
    audit("article.save", request=request, detail=f"{'ร่าง' if draft else 'เผยแพร่'} {slug}: {title}")
    return JSONResponse({"ok": True, "slug": slug, "draft": draft, "dropped": dropped,
                         "url": f"/knowledge/{slug}", "edit": f"/admin-console/articles/{slug}/edit"})


@router.post("/admin-console/articles/{slug}/delete")
def article_delete(slug: str, request: Request):
    from app.accounts import audit
    if articles.slug_ok(slug) and articles.get(slug, include_drafts=True):
        articles.delete(slug)
        audit("article.delete", request=request, detail=slug)
    return RedirectResponse("/admin-console/articles?msg=ลบบทความแล้ว", status_code=303)


@router.post("/admin-console/articles/clean")
def article_clean_paste(html: str = Form("")):
    """กรองข้อความที่วางจาก Word / Google Docs ก่อนใส่ลงกล่องเขียน"""
    body, dropped = article_clean.clean(html)
    return {"html": body, "dropped": dropped}


def _save_image(data: bytes) -> str:
    from PIL import Image, ImageOps
    Image.open(io.BytesIO(data)).verify()        # verify แล้วต้องเปิดใหม่
    im = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    im.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
    alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
    d = articles.media_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(8) + (".png" if alpha else ".jpg")
    if alpha:
        im.convert("RGBA").save(d / name, optimize=True)
    else:
        im.convert("RGB").save(d / name, quality=85, optimize=True)   # เขียนใหม่ = ตัด EXIF และของแฝงในไฟล์ออก
    return name


@router.post("/admin-console/articles/upload")
async def article_upload(kind: str = Form("image"), file: UploadFile = File(...)):
    """อัปโหลดรูปในเนื้อหา/รูปปก หรือ PDF ต้นฉบับระเบียบ"""
    data = await file.read()
    if kind == "pdf":
        if data[:5] != b"%PDF-":
            return JSONResponse({"ok": False, "err": "ไฟล์นี้ไม่ใช่ PDF"})
        if len(data) > PDF_MAX:
            return JSONResponse({"ok": False, "err": "PDF ใหญ่เกิน 25MB"})
        d = articles.media_dir()
        d.mkdir(parents=True, exist_ok=True)
        name = secrets.token_hex(8) + ".pdf"
        (d / name).write_bytes(data)
    else:
        if len(data) > IMAGE_MAX:
            return JSONResponse({"ok": False, "err": "รูปใหญ่เกิน 15MB"})
        try:
            name = _save_image(data)
        except Exception:
            return JSONResponse({"ok": False, "err": "เปิดไฟล์รูปนี้ไม่ได้ ใช้ไฟล์ .jpg หรือ .png"})
    return {"ok": True, "url": f"/knowledge/media/{name}"}
