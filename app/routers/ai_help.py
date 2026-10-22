"""ปุ่ม "ถาม AI" (ดู app/services/ai_help.py)"""
import json
from urllib.parse import urlsplit
from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.concurrency import run_in_threadpool
from app.accounts import acc_session, Account, AiQuestion
from app.services import ai_help as ai

router = APIRouter()


def _account(db, request):
    user = db.get(Account, request.session.get('uid'))
    if not user or not user.active or user.role == 'superadmin':
        raise HTTPException(401, 'กรุณาเข้าสู่ระบบใหม่')
    return user


@router.get('/ai/status')
def status(request: Request):
    with acc_session() as db:
        user = _account(db, request)
        why = ai.allowed(db, user) or ('' if ai.configured() else 'nokey')
        return {'ok': not why, 'why': why, 'left': max(ai.MONTHLY_LIMIT - ai.used_this_month(db, user.tenant_id), 0),
                'limit': ai.MONTHLY_LIMIT}


@router.post('/ai/ask')
async def ask(request: Request, q: str = Form(''), path: str = Form(''), history: str = Form('[]')):
    origin = request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403)
    q = q.strip()
    if not q or len(q) > 1000:
        raise HTTPException(400, 'พิมพ์คำถาม 1 ถึง 1,000 ตัวอักษรครับ')
    with acc_session() as db:
        user = _account(db, request)
        why = ai.allowed(db, user)
        if why == 'off':
            raise HTTPException(403, 'โรงเรียนยังไม่ได้เปิดบริการถาม AI ครับ')
        if why == 'teacher':
            raise HTTPException(403, 'ถาม AI ใช้ได้เฉพาะไอดีเจ้าหน้าที่ครับ')
        if ai.used_this_month(db, user.tenant_id) >= ai.MONTHLY_LIMIT:
            raise HTTPException(429, f'เดือนนี้โรงเรียนถามครบ {ai.MONTHLY_LIMIT} คำถามแล้ว ถามใหม่ได้วันที่ 1 เดือนหน้าครับ หรือกดติดต่อเจ้าหน้าที่')
        tid, uid = user.tenant_id, user.id
    if not ai.configured():
        raise HTTPException(503, 'ระบบถาม AI ยังไม่พร้อมใช้งาน กรุณาติดต่อเจ้าหน้าที่ครับ')
    try:
        hist = json.loads(history)
        hist = [h for h in hist if isinstance(h, dict)] if isinstance(hist, list) else []
    except ValueError:
        hist = []
    path = (path or '/')[:200]
    try:
        answer, cost = await run_in_threadpool(ai.ask, q, hist, path)
    except Exception as e:  # noqa: BLE001
        print('[ai-help] ตอบไม่ได้:', type(e).__name__, str(e)[:200])
        raise HTTPException(502, 'ตอนนี้ AI ตอบไม่ได้ ลองใหม่อีกครั้ง หรือกดติดต่อเจ้าหน้าที่ครับ')
    with acc_session() as db:
        db.add(AiQuestion(tenant_id=tid, account_id=uid, path=path, question=q, answer=answer, cost_thb=round(cost, 4)))
        db.commit()
        left = max(ai.MONTHLY_LIMIT - ai.used_this_month(db, tid), 0)
    return {'answer': answer, 'left': left}
