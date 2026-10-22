"""รวมคู่มือที่ผู้ช่วย AI ใช้ตอบ เป็นไฟล์เดียว app/ai_help/knowledge.md

แหล่ง: core.md (เขียนเอง) + หน้า /guide (ตัด HTML ออก) + docs/*.md ที่เป็นคู่มือผู้ใช้
รัน: python -m app.ai_help.build
"""
import html, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
# เฉพาะคู่มือที่เขียนให้ผู้ใช้อ่าน (เอกสารเทคนิคของนักพัฒนาไม่ต้องส่ง เปลืองค่า AI ทุกคำถาม)
DOCS = ['finance-guide.md', 'finance-openings.md', 'plan-funding.md', 'pp7.md']


def guide_text():
    t = (ROOT / 'app/templates/guide.html').read_text(encoding='utf-8')
    t = re.sub(r'<(script|style)[\s\S]*?</\1>', '', t)
    t = re.sub(r'\{[%#][\s\S]*?[%#]\}|\{\{[\s\S]*?\}\}', '', t)
    t = re.sub(r'<(h[1-4])[^>]*>', lambda m: '\n\n## ' if m.group(1) in ('h1', 'h2') else '\n### ', t)
    t = re.sub(r'<(li|p|div|tr|br)[^>]*>', '\n', t)
    t = html.unescape(re.sub(r'<[^>]+>', ' ', t))
    t = re.sub(r'[ \t]+', ' ', t)
    t = re.sub(r'\s*\n\s*', '\n', t)
    return t.replace(' · ', ' ').strip()


def build():
    parts = [(HERE / 'core.md').read_text(encoding='utf-8'),
             '# คู่มือผู้ใช้ (หน้า /guide)\n\n' + guide_text()]
    for name in DOCS:
        p = ROOT / 'docs' / name
        if p.exists():
            parts.append(f'# เอกสารประกอบ: {name}\n\n' + p.read_text(encoding='utf-8').replace(' · ', ' '))
    out = '\n\n---\n\n'.join(parts) + '\n'
    (HERE / 'knowledge.md').write_text(out, encoding='utf-8')
    return out


if __name__ == '__main__':
    print(f'knowledge.md {len(build()):,} ตัวอักษร')
