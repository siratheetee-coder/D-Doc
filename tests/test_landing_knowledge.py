"""Public landing previews follow publication and thumbnails in the article console."""
from datetime import date
from pathlib import Path
import os
import re
import pytest
from tests.test_subsidy import env
from tests.test_article_editor import _anon, _boss, _form, _png

@pytest.fixture(autouse=True)
def isolated_articles(monkeypatch,tmp_path):
    from app.services import articles
    bundled=tmp_path/'bundled';bundled.mkdir()
    stored=tmp_path/'stored'
    monkeypatch.setattr(articles,'DIR',bundled)
    monkeypatch.setattr(articles,'store_dir',lambda:stored)
    monkeypatch.setattr(articles,'_cache',{})
    monkeypatch.setattr('app.services.public_stats.landing_stats',lambda:None)
    monkeypatch.setattr('app.services.mailer.send_email',lambda *a,**kw:True)
    return articles

def card_links(html):
    return re.findall(r'class="lk-card-link" href="([^"]+)"',html)

def save(service,slug,title,**kw):
    service.save(slug,title=title,body='<p>เนื้อหาทดสอบ</p>',description=kw.pop('description','คำอธิบายประกอบบทความ'),
                 category='งานพัสดุ',draft=False,**kw)

def test_public_preview_is_latest_three_and_drafts_never_leak(env,isolated_articles):
    articles=isolated_articles
    save(articles,'w119-preview','ว.119 ตาราง 1 กับ ตาราง 2 ต่างกันยังไง ใช้กับค่าใช้จ่ายแบบไหน',cover='ว.119',description='สรุปความต่างของตาราง 1 และตาราง 2 พร้อมแนวทางเลือกใช้ให้ตรงกับค่าใช้จ่ายของโรงเรียน',created=date(2026,10,31))
    save(articles,'w804-preview','ว.804 จัดซื้อไม่เกิน 50,000 บาท ใช้ยังไง ต้องมีเอกสารอะไรบ้าง',cover='ว.804',description='ขั้นตอนจัดซื้อ เอกสารจากผู้ขาย และหลักฐานที่ต้องเตรียมให้ครบก่อนสรุปรายงาน',created=date(2026,11,1))
    save(articles,'urgent-preview','ข้อ 79 วรรคสอง จัดซื้อจัดจ้างกรณีเร่งด่วน ใช้ได้เมื่อไร',cover='ข้อ 79',description='กรณีจำเป็นเร่งด่วนแบบไหนที่ใช้ได้ พร้อมสิ่งที่ควรตรวจสอบและหลักฐานประกอบ',created=date(2026,10,30))
    save(articles,'fourth-preview','บทความที่เกินจำนวนตัวอย่าง',featured=True,created=date(2026,10,1))
    articles.save('draft-secret',title='บทความลับยังไม่เผยแพร่',body='<p>secret</p>',draft=True,featured=True,created=date(2026,11,2))
    anon=_anon();response=anon.get('/landing');assert response.status_code==200
    assert card_links(response.text)==['/knowledge/w804-preview','/knowledge/w119-preview','/knowledge/urgent-preview']
    assert 'บทความลับยังไม่เผยแพร่' not in response.text and 'บทความที่เกินจำนวนตัวอย่าง' not in response.text
    assert response.text.index('id="modules"')<response.text.index('id="knowledge"')<response.text.index('id="pricing"')
    assert 'href="#knowledge"' in response.text and 'ดูบทความทั้งหมด' in response.text
    assert card_links(anon.get('/').text)==card_links(response.text)
    for link in card_links(response.text): assert anon.get(link).status_code==200
    capture=os.environ.get('LANDING_KNOWLEDGE_CAPTURE')
    if capture:
        folder=Path(capture);folder.mkdir(parents=True,exist_ok=True)
        (folder/'preview.html').write_text(response.text,encoding='utf-8')

def test_console_publish_and_withdraw_updates_landing_without_deploy(env):
    boss=_boss();anon=_anon()
    assert 'id="knowledge"' not in anon.get('/landing').text
    form=_form('from-console',action='publish',title='บทความจาก Console',description='คำอธิบายที่แก้ใน Console')
    result=boss.post('/admin-console/articles/save',data=form).json()
    assert result['ok'] and not result['draft']
    page=anon.get('/landing').text
    assert card_links(page)==['/knowledge/from-console'] and 'คำอธิบายที่แก้ใน Console' in page
    result=boss.post('/admin-console/articles/save',data=_form('',orig_slug='from-console',action='draft',title='บทความจาก Console')).json()
    assert result['ok'] and result['draft']
    page=anon.get('/landing').text
    assert 'id="knowledge"' not in page and 'บทความจาก Console' not in page and 'href="#knowledge"' not in page

def test_cover_metadata_and_escaping_and_empty_state(env,isolated_articles):
    anon=_anon();page=anon.get('/landing')
    assert page.status_code==200 and not card_links(page.text)
    assert 'id="knowledge"' not in page.text
    boss=_boss()
    uploaded=boss.post('/admin-console/articles/upload',files={'file':('cover.png',_png(),'image/png')}).json()
    assert uploaded['ok']
    image=uploaded['url']
    assert anon.get(image).status_code==200
    save(isolated_articles,'image-preview','ชื่อบทความ <script>bad()</script>',image=image,image_alt='ภาพ "ปก" บทความ')
    page=anon.get('/landing').text
    assert card_links(page)==['/knowledge/image-preview']
    assert f'class="lk-cover-image" src="{image}"' in page
    assert '<script>bad()</script>' not in page and '&lt;script&gt;bad()&lt;/script&gt;' in page
    assert 'alt="ภาพ &#34;ปก&#34; บทความ"' in page
    library=anon.get('/knowledge').text
    article=anon.get('/knowledge/image-preview').text
    for html in (page,library,article):
        assert f'src="{image}"' in html
