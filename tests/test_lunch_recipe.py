import json
from datetime import datetime
from tests.test_subsidy import env
from tests.test_lunch_claim import make, session
from app.models import LunchClass, LunchMenu, LunchIngredient, LunchProgram


def _prep(env):
    x = make(env)
    with session() as s:
        p = s.get(LunchProgram, x['pid'])
        s.query(LunchClass).filter_by(program_id=p.id).delete()
        s.add_all([LunchClass(program_id=p.id, level='อ.2', num_students=20),
                   LunchClass(program_id=p.id, level='ป.1', num_students=86)])
        s.add(LunchMenu(program_id=p.id, date=datetime(2026, 12, 14), main='ผัดกะเพราไก่ ไข่ดาว'))
        s.commit()
    return x


def test_recipe_calc_fill_and_shopping(env):
    x = _prep(env); pid = x['pid']
    r = env.post(f'/lunch/{pid}/recipes/save', data={'name': 'ผัดกะเพราไก่',
        'i_name': ['อกไก่', 'ไข่ไก่'], 'i_unit': ['กก.', 'ฟอง'], 'i_k': ['0.6', '10'],
        'i_p': ['0.8', '10'], 'i_m': ['1', '10'], 'i_lock': ['1']}, follow_redirects=False)
    assert r.status_code == 303
    assert env.get(f'/lunch/{pid}/recipes').status_code == 200
    j = env.get(f'/lunch/{pid}/recipes/calc?d=14/12/2569').json()
    assert j['recipe']['name'] == 'ผัดกะเพราไก่' and j['tiers'] == [20, 86, 0]
    rows = {r['name']: r for r in j['rows']}
    assert rows['อกไก่']['raw'] == 8.08 and rows['อกไก่']['qty'] == 8.5
    assert rows['ไข่ไก่']['qty'] == 110 and rows['ไข่ไก่']['locked']
    r = env.post(f'/lunch/{pid}/recipes/fill', data={'date': '14/12/2569', 'rows': json.dumps(j['rows'])},
                 follow_redirects=False)
    assert 'added=2' in r.headers['location']
    r = env.post(f'/lunch/{pid}/recipes/fill', data={'date': '14/12/2569', 'rows': json.dumps(j['rows'])},
                 follow_redirects=False)
    assert 'added=0' in r.headers['location']          # ไม่เติมซ้ำ
    with session() as s:
        assert s.query(LunchIngredient).filter_by(program_id=pid, name='อกไก่').count() == 1
    page = env.get(f'/lunch/{pid}/shopping?w=14/12/2569')
    assert page.status_code == 200 and 'อกไก่' in page.text and '8.5' in page.text
    assert env.get(f'/lunch/{pid}/ingredients').status_code == 200


def test_search_shortcuts_open_latest_program(env):
    x = _prep(env)
    assert env.get('/lunch/recipes', follow_redirects=False).headers['location'] == f"/lunch/{x['pid']}/recipes"
    assert env.get('/lunch/shopping', follow_redirects=False).headers['location'] == f"/lunch/{x['pid']}/shopping"
