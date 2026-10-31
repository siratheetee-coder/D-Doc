"""Explicit one-time content update. Preview by default; --apply saves a backup first.
Run from the project root: python tools/update_w804_article.py --apply
Preserves the console article's title, cover, sources, slug and publication status.
"""
from pathlib import Path
from datetime import datetime
import argparse
import re
import sys
import shutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    from app.services import articles, article_clean
    slug = 'w804-purchase-under-50000'
    target = articles.store_dir() / (slug + '.html')
    if not target.exists():
        print('No console override. The updated bundled draft is already available.'); return
    old = target.read_text(encoding='utf-8')
    match = re.match(r'\s*<!--(.*?)-->', old, re.S)
    if not match or re.search(r'^\s*deleted:\s*true', match[1], re.M):
        raise SystemExit('Not an active article; no changes made.')
    source = articles._parse(articles.DIR / (slug + '.html'))
    body = article_clean.clean(source['raw_body'])[0]
    header = match[1]
    for key, value in [('description', source['description']), ('updated', '2026-10-31'), ('reviewed', '2026-10-31')]:
        pattern = rf'^\s*{key}:.*$'
        if re.search(pattern, header, re.M):
            header = re.sub(pattern, key + ': ' + value, header, flags=re.M)
        else:
            header += '\n' + key + ': ' + value
    if 'https://cpb.ddc.moph.go.th/ddc-pic/doc/201/pdf' not in header:
        header += '\nsource: หนังสือ ว.804 ฉบับต้นทาง | https://cpb.ddc.moph.go.th/ddc-pic/doc/201/pdf'
    updated = '<!--' + header.rstrip() + '\n-->\n' + body + '\n'
    print('Target:', target)
    print('Updates W.804 body and summary; preserves cover, title and publication status.')
    if not args.apply:
        print('Preview only. Use --apply to write with a backup.'); return
    if target.read_text(encoding='utf-8') != old:
        raise SystemExit('Article changed while preparing; retry.')
    backup = target.parent / '_backups' / (slug + '-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.html')
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, backup)
    temp = target.with_suffix('.update.tmp')
    temp.write_text(updated, encoding='utf-8'); temp.replace(target)
    print('Updated. Backup:', backup)

if __name__ == '__main__':
    main()
