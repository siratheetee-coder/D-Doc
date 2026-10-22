"""ทดสอบเทียบ 3 โมเดลสำหรับผู้ช่วย AI "ถาม AI"

ใช้คู่มือ app/ai_help/knowledge.md เป็น system prompt (แคชไว้ ถามข้อต่อไปถูกลง)
ถามทุกข้อใน questions.jsonl แล้วให้ Opus ตรวจว่าคำตอบครบประเด็นที่คาดไว้ไหม
ผลออกที่ tools/ai_eval/out/report.html (เปิดดูเทียบกันทีละข้อ) และ results.jsonl

ต้องตั้ง ANTHROPIC_API_KEY ในเครื่องก่อนรัน
รัน:  .venv\\Scripts\\python tools\\ai_eval\\run_eval.py
ลองไม่กี่ข้อก่อน:  ... run_eval.py --limit 3
"""
import argparse, html, json, os, sys, time
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
OUT = HERE / 'out'
THB = 33.0  # บาทต่อดอลลาร์ (ประมาณ)

# ราคาต่อ 1 ล้าน token (ดอลลาร์): input, output, cache read, cache write
MODELS = {
    'claude-opus-5-5':   dict(name='Opus 5.5',   price=(4.00, 20.00, 0.20, 5.00)),
    'claude-sonnet-5-5': dict(name='Sonnet 5.5', price=(2.00, 10.00, 0.20, 2.50)),
    'claude-haiku-5-5':  dict(name='Haiku 5.5',  price=(0.10, 0.50, 0.01, 0.125)),
}
JUDGE = 'claude-opus-5-5'

ASK = """คุณคือผู้ช่วย "ถาม AI" ของระบบ Easy Ekkasan ตอบคำถามผู้ใช้โดยอิงคู่มือด้านล่างเท่านั้น
ทำตาม "กติกาการตอบ" ในคู่มืออย่างเคร่งครัด

<คู่มือ>
{kb}
</คู่มือ>"""

GRADE = """ตรวจคำตอบของผู้ช่วย AI ระบบโรงเรียน เทียบกับประเด็นที่คาดหวัง
คำถาม: {q}
ประเด็นที่คาดหวัง: {expect}
คำตอบ:
<answer>
{a}
</answer>

ให้คะแนน 0 ถึง 10 ตามความครบและถูกต้องของประเด็น หักคะแนนถ้ามีข้อมูลที่แต่งขึ้นเอง (เมนูหรือปุ่มที่ไม่มีในประเด็นและดูไม่น่าจริง) หรือยาวเกินจำเป็น
ตอบเป็น JSON บรรทัดเดียวเท่านั้น: {{"score": ตัวเลข, "missing": "ประเด็นที่ขาดหรือผิด สั้น ๆ"}}"""


def cost(model, u):
    i, o, cr, cw = MODELS[model]['price']
    return ((u.input_tokens or 0) * i + (u.output_tokens or 0) * o
            + (getattr(u, 'cache_read_input_tokens', 0) or 0) * cr
            + (getattr(u, 'cache_creation_input_tokens', 0) or 0) * cw) / 1e6


def text_of(msg):
    return ''.join(b.text for b in msg.content if b.type == 'text').strip()


def ask(client, model, system, q):
    t = time.time()
    msg = client.messages.create(
        model=model, max_tokens=1500,
        system=[{'type': 'text', 'text': system, 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content': q}])
    return text_of(msg), msg.usage, time.time() - t


def grade(client, row):
    msg = client.messages.create(
        model=JUDGE, max_tokens=400,
        messages=[{'role': 'user', 'content': GRADE.format(q=row['q'], expect=' / '.join(row['expect']), a=row['answer'])}])
    raw = text_of(msg)
    try:
        g = json.loads(raw[raw.find('{'):raw.rfind('}') + 1])
    except ValueError:
        g = {'score': None, 'missing': raw[:200]}
    return g, cost(JUDGE, msg.usage)


def report(rows, questions, totals):
    by = {(r['model'], r['id']): r for r in rows}
    models = [m for m in MODELS if any(r['model'] == m for r in rows)]
    head = ''.join(f'<th>{MODELS[m]["name"]}</th>' for m in models)
    summ = ''
    for m in models:
        rs = [r for r in rows if r['model'] == m]
        sc = [r['score'] for r in rs if r.get('score') is not None]
        summ += (f'<tr><td><b>{MODELS[m]["name"]}</b></td><td>{sum(sc) / len(sc) if sc else 0:.1f}</td>'
                 f'<td>{totals[m] * THB / max(len(rs), 1):.2f}</td><td>{totals[m] * THB:.2f}</td>'
                 f'<td>{sum(r["secs"] for r in rs) / max(len(rs), 1):.1f}</td></tr>')
    body = ''
    for q in questions:
        cells = ''
        for m in models:
            r = by.get((m, q['id']))
            if not r:
                cells += '<td>-</td>'; continue
            cells += (f'<td><div class="sc">{r.get("score", "-")}/10</div><div class="a">{html.escape(r["answer"])}</div>'
                      f'<div class="miss">{html.escape(str(r.get("missing", "")))}</div></td>')
        body += (f'<tr><td class="q"><b>{q["id"]}. {html.escape(q["q"])}</b><div class="mod">{q["module"]}</div>'
                 f'<ul>{"".join(f"<li>{html.escape(e)}</li>" for e in q["expect"])}</ul></td>{cells}</tr>')
    return f"""<!doctype html><html lang="th"><meta charset="utf-8"><title>ผลทดสอบถาม AI</title>
<style>body{{font-family:Sarabun,Tahoma,sans-serif;margin:20px;background:#f8fafc;color:#0f172a}}
table{{border-collapse:collapse;width:100%;background:#fff}}td,th{{border:1px solid #e2e8f0;padding:10px;vertical-align:top;text-align:left}}
th{{background:#eef2ff}}.q{{width:22%}}.q ul{{margin:6px 0 0;padding-left:18px;color:#475569;font-size:13px}}.mod{{color:#6366f1;font-size:12px}}
.a{{white-space:pre-wrap;font-size:14px;line-height:1.6}}.sc{{font-weight:700;color:#0d9488}}.miss{{color:#b45309;font-size:12.5px;margin-top:6px}}</style>
<h1>ผลทดสอบเทียบโมเดล ถาม AI</h1>
<table style="width:auto;margin-bottom:20px"><tr><th>โมเดล</th><th>คะแนนเฉลี่ย</th><th>บาท/คำถาม</th><th>รวม (บาท)</th><th>วินาที/คำถาม</th></tr>{summ}</table>
<p>ค่าตรวจคะแนน (Opus) ไม่รวมในตาราง ราคาใช้เรต {THB:.0f} บาท/ดอลลาร์</p>
<table><tr><th>คำถาม และประเด็นที่คาดหวัง</th>{head}</tr>{body}</table></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=0, help='ถามแค่ N ข้อแรก')
    ap.add_argument('--models', default=','.join(MODELS), help='คั่นด้วยจุลภาค')
    ap.add_argument('--no-judge', action='store_true', help='ไม่ให้ Opus ตรวจคะแนน')
    ap.add_argument('--budget', type=float, default=300, help='หยุดเมื่อค่าใช้จ่ายถึงกี่บาท')
    a = ap.parse_args()
    if not os.environ.get('ANTHROPIC_API_KEY'):
        sys.exit('ยังไม่ได้ตั้ง ANTHROPIC_API_KEY')

    sys.path.insert(0, str(ROOT))
    from app.ai_help.build import build
    system = ASK.format(kb=build())
    questions = [json.loads(l) for l in (HERE / 'questions.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    if a.limit: questions = questions[:a.limit]
    models = [m.strip() for m in a.models.split(',') if m.strip() in MODELS]

    client = anthropic.Anthropic()
    OUT.mkdir(exist_ok=True)
    rows, totals, spent = [], {m: 0.0 for m in models}, 0.0
    log = open(OUT / 'results.jsonl', 'w', encoding='utf-8')
    jobs = [(m, q) for m in models for q in questions]  # ถามโมเดลเดียวให้ครบก่อน แคชคู่มือจะได้ไม่หลุด
    for m, q in jobs:
        if spent * THB >= a.budget:
            print(f'หยุด: ถึงงบ {a.budget:.0f} บาทแล้ว'); break
        ans, usage, secs = ask(client, m, system, q['q'])
        c = cost(m, usage)
        totals[m] += c; spent += c
        row = dict(model=m, id=q['id'], q=q['q'], expect=q['expect'], answer=ans, secs=round(secs, 1),
                   usage=dict(input=usage.input_tokens, output=usage.output_tokens,
                              cache_read=getattr(usage, 'cache_read_input_tokens', 0),
                              cache_write=getattr(usage, 'cache_creation_input_tokens', 0)),
                   thb=round(c * THB, 3))
        if not a.no_judge:
            g, jc = grade(client, row)
            row.update(score=g.get('score'), missing=g.get('missing', '')); spent += jc
        rows.append(row)
        log.write(json.dumps(row, ensure_ascii=False) + '\n'); log.flush()
        print(f'{MODELS[m]["name"]:<11} ข้อ {q["id"]:>2}  {row.get("score", "-")}/10  {row["thb"]:.2f} บาท  {secs:.1f} วิ')
    log.close()
    (OUT / 'report.html').write_text(report(rows, questions, totals), encoding='utf-8')
    print(f'\nใช้ไปทั้งหมดประมาณ {spent * THB:.2f} บาท')
    print(f'เปิดดูผล: {OUT / "report.html"}')


if __name__ == '__main__':
    main()
