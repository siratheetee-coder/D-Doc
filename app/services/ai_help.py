"""ผู้ช่วย "ถาม AI": ตอบคำถามการใช้ระบบจากคู่มือ app/ai_help/knowledge.md

- บริการเสริม: ผู้ขายเปิดรายโรงเรียนที่คอนโซล (Tenant.ai_help)
- ใช้ได้เฉพาะไอดีเจ้าหน้าที่ (ไม่ใช่บัญชีครู) จำกัดวันละ DAILY_LIMIT คำถามต่อโรงเรียน
- คีย์ API ของผู้ขาย ตั้งใน env ANTHROPIC_API_KEY บนเซิร์ฟเวอร์
"""
import os
from datetime import datetime, time
from functools import lru_cache

MODEL = 'claude-sonnet-5-5'
DAILY_LIMIT = 10
THB = 33.0
PRICE = (2.00, 10.00, 0.20, 2.50)  # ดอลลาร์ต่อ 1 ล้าน token: input, output, cache read, cache write
HISTORY = 6                         # ส่งบทสนทนาก่อนหน้าไปด้วยกี่ข้อความ

SYSTEM = """คุณคือผู้ช่วย "ถาม AI" ของระบบ Easy Ekkasan ตอบคำถามผู้ใช้โดยอิงคู่มือด้านล่างเท่านั้น
ทำตาม "กติกาการตอบ" ในคู่มืออย่างเคร่งครัด
เขียนลิงก์หน้าในระบบเป็น path ในเครื่องหมาย ` เช่น `/finance/accounts` ระบบจะแปลงเป็นปุ่มให้ผู้ใช้กดไปหน้านั้น
ถ้าตอบไม่ได้หรือผู้ใช้ต้องการคนช่วย ให้แนะนำกดปุ่ม "ติดต่อเจ้าหน้าที่" ด้านล่างหน้าต่างแชท

<คู่มือ>
{kb}
</คู่มือ>"""


def configured() -> bool:
    return bool(os.environ.get('ANTHROPIC_API_KEY'))


@lru_cache(maxsize=1)
def system_prompt() -> str:
    from pathlib import Path
    kb = Path(__file__).resolve().parents[1] / 'ai_help' / 'knowledge.md'
    if not kb.exists():
        from app.ai_help.build import build
        build()
    return SYSTEM.format(kb=kb.read_text(encoding='utf-8'))


def used_today(db, tenant_id) -> int:
    from app.accounts import AiQuestion
    start = datetime.combine(datetime.now().date(), time.min)
    return db.query(AiQuestion).filter(AiQuestion.tenant_id == tenant_id, AiQuestion.created_at >= start).count()


def allowed(db, account) -> str:
    """คืนข้อความเหตุผลถ้าใช้ไม่ได้ ('' = ใช้ได้)"""
    from app.accounts import Tenant
    t = db.get(Tenant, account.tenant_id) if account and account.tenant_id else None
    if not t or not t.ai_help:
        return 'off'
    if account.person_id and not account.is_owner:
        return 'teacher'
    return ''


def _cost(u) -> float:
    i, o, cr, cw = PRICE
    return ((u.input_tokens or 0) * i + (u.output_tokens or 0) * o
            + (getattr(u, 'cache_read_input_tokens', 0) or 0) * cr
            + (getattr(u, 'cache_creation_input_tokens', 0) or 0) * cw) / 1e6 * THB


def ask(question: str, history: list, path: str) -> tuple[str, float]:
    import anthropic
    msgs = []
    for h in history[-HISTORY:]:
        role = 'assistant' if h.get('role') == 'ai' else 'user'
        text = str(h.get('text', ''))[:2000]
        if text and (not msgs or msgs[-1]['role'] != role):
            msgs.append({'role': role, 'content': text})
    if msgs and msgs[0]['role'] != 'user':
        msgs.pop(0)
    if msgs and msgs[-1]['role'] == 'user':
        msgs.pop()
    msgs.append({'role': 'user', 'content': f'(ผู้ใช้กำลังเปิดหน้า {path or "/"})\n{question}'})
    client = anthropic.Anthropic(max_retries=2, timeout=60)
    msg = client.messages.create(
        model=MODEL, max_tokens=1200,
        system=[{'type': 'text', 'text': system_prompt(), 'cache_control': {'type': 'ephemeral'}}],
        messages=msgs)
    answer = ''.join(b.text for b in msg.content if b.type == 'text').strip()
    return answer, _cost(msg.usage)
