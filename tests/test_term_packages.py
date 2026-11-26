"""แพ็กเกจ 3 ปี / 5 ปี: ราคา, เพดานราคาครบทุกงาน, ซื้อเพิ่มกลางสัญญา, ต่ออายุตามจำนวนปี"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import accounts
from app import seller_config as prices
from app.modules import MODULE_KEYS


@pytest.fixture(autouse=True)
def no_promo(monkeypatch):
    monkeypatch.setitem(prices.SELLER, 'promo', {'enabled': False})


@pytest.mark.parametrize('mods,years,total', [
    (MODULE_KEYS, 1, 3190), (MODULE_KEYS, 3, 7990), (MODULE_KEYS, 5, 11990),
    (['procurement'], 3, 2490), (['procurement'], 5, 3690),
    (['lunch'], 3, 1690), (['lunch'], 5, 2590),
    (['admin'], 3, 990), (['admin'], 5, 1490),
    (['procurement', 'finance'], 3, 4690), (['procurement', 'finance'], 5, 7090),
    (['procurement', 'admin'], 3, 3190), (['admin', 'hr'], 5, 2590),
    (['procurement', 'finance', 'academic'], 3, 6890),
    (['procurement', 'finance', 'academic'], 5, 10390),
])
def test_term_prices(mods, years, total):
    r = prices.price_for(set(mods), years)
    assert r['total'] == total and r['years'] == years


def test_bad_years_fall_back_to_one_year():
    assert prices.price_for(set(MODULE_KEYS), 2)['total'] == 3190
    assert prices.price_for(set(MODULE_KEYS), 'x')['years'] == 1


@pytest.mark.parametrize('years,total', [(1, 3190), (3, 7990), (5, 11990)])
def test_price_never_above_bundle(years, total):
    r = prices.price_for({'procurement', 'finance', 'academic', 'lunch'}, years)
    assert r['total'] == total and r['capped'] and r['count'] == len(MODULE_KEYS)
    assert set(r['modules'].split(',')) == set(MODULE_KEYS)


def test_addon_mid_term_uses_term_discount():
    assert prices.price_addon({'finance'}, 365)['total'] == 990
    assert prices.price_addon({'finance'}, 4 * 365)['total'] == 2970     # 4 ปี x 990 x 0.75
    assert prices.price_addon({'finance'}, 2 * 365)['total'] == 1650     # 2 ปี x 990 x 2.5/3


@pytest.fixture
def acc_db(tmp_path):
    engine = create_engine('sqlite:///' + str(tmp_path / 'a.db'), connect_args={'check_same_thread': False})
    accounts.AccBase.metadata.create_all(engine)
    S = sessionmaker(bind=engine)
    with patch('app.accounts.acc_session', S):
        yield S
    engine.dispose()


@pytest.mark.parametrize('years', [1, 3, 5])
def test_renew_lead_extends_by_years(acc_db, years):
    with acc_db() as db:
        db.add(accounts.Tenant(id=1, name='S', plan='trial'))
        db.add(accounts.Account(id=1, tenant_id=1, username='o@example.test', password_hash='x', is_owner=True))
        db.commit()
    lid = accounts.add_lead(kind='order', email='o@example.test', tenant_id=1, modules=','.join(MODULE_KEYS),
                            packages='ครบทุกงาน', amount=7990.0, years=years)
    res = accounts.renew_lead(lid)
    assert res['expiry'] == (date.today() + timedelta(days=365 * years)).isoformat()
