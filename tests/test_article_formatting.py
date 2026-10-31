from tests.test_subsidy import env
from tests.test_article_editor import _boss, _form


def test_text_styles_survive_save_reopen_and_public_page(env):
    boss = _boss()
    body = '<h2>หัวข้อ</h2><p><font size="5" color="#cc1122">ข้อความสี</font><span style="font-size:999px;color:expression(alert(1));background:url(javascript:alert(1))" onclick="alert(1)">ปกติ</span></p>'
    result = boss.post('/admin-console/articles/save', data=_form('format-roundtrip', action='publish', body=body)).json()
    assert result['ok']
    from app.services import articles, article_clean
    saved = articles.get('format-roundtrip')['raw_body']
    assert 'font-size:24px' in saved and 'color:#cc1122' in saved
    assert '999px' not in saved and 'alert(1)' not in saved and 'onclick' not in saved
    assert article_clean.clean(saved)[0] == saved
    assert saved in boss.get('/admin-console/articles/format-roundtrip/edit').text
    public = boss.get('/knowledge/format-roundtrip').text
    assert 'font-size:24px' in public and 'color:#cc1122' in public
