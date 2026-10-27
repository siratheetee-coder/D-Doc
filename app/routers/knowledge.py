# -*- coding: utf-8 -*-
"""คลังความรู้ /knowledge - บทความสาธารณะ (ไม่ต้องล็อกอิน) สำหรับ SEO
เนื้อหาอยู่ใน app/content/articles/*.html ดูรูปแบบไฟล์ที่ app/services/articles.py"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services import articles
from app.templating import templates

router = APIRouter()


def _can_see_drafts(request: Request) -> bool:
    return request.session.get("role") == "superadmin"


@router.get("/knowledge", response_class=HTMLResponse)
def knowledge_list(request: Request):
    from app.routers.auth import site_url
    drafts = _can_see_drafts(request)
    return templates.TemplateResponse("knowledge_list.html", {
        "request": request, "items": articles.all_articles(include_drafts=drafts),
        "show_drafts": drafts, "site_url": site_url(), "cat_style": articles.style_of,
    })


@router.get("/knowledge/{slug}", response_class=HTMLResponse)
def knowledge_article(slug: str, request: Request):
    from app.routers.auth import site_url
    drafts = _can_see_drafts(request)
    art = articles.get(slug, include_drafts=drafts)
    if not art:      # 404 จริง (ไม่ redirect) ให้ Google รู้ว่าไม่มีหน้านี้
        return templates.TemplateResponse("knowledge_list.html", {
            "request": request, "items": articles.all_articles(include_drafts=drafts),
            "show_drafts": drafts, "site_url": site_url(), "cat_style": articles.style_of, "not_found": True,
        }, status_code=404)
    return templates.TemplateResponse("knowledge_article.html", {
        "request": request, "a": art, "related": articles.related(art), "site_url": site_url(), "cat_style": articles.style_of,
    })
