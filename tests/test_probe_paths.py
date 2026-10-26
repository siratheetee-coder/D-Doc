from tests.test_subsidy import env


def test_secret_probe_paths_are_404_and_not_shown_as_current_page(env):
    from app.accounts import acc_session, Account, _seen_page
    with acc_session() as db:
        uid = db.query(Account).filter_by(username='demo').one().id
    for p in ('/.env', '/.env.prod', '/core', '/.git/config', '/wp-login.php', '/static/../.env'):
        r = env.get(p, headers={'accept': 'text/html'})
        assert r.status_code in (404, 405), (p, r.status_code)
        assert 'DDOC_' not in r.text and 'SECRET' not in r.text.upper()
        assert _seen_page.get(uid) != p
    env.get('/finance', headers={'accept': 'text/html'})
    assert _seen_page.get(uid) == '/finance'
