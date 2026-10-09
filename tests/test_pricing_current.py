from app import seller_config as prices
from app.modules import MODULE_KEYS


def test_current_finance_bundle_and_addon(monkeypatch):
    monkeypatch.setitem(prices.SELLER, 'promo', {'enabled': False})
    ctx = prices.pricing_context()
    assert ctx['prices']['p_fin'] == 690
    assert ctx['full_sum'] == 3940
    assert ctx['bundle_save'] == 750
    assert prices.price_for({'finance'})['total'] == 690
    assert prices.price_for({'finance', 'procurement'})['total'] == 1480
    assert prices.price_for(set(MODULE_KEYS))['total'] == 3190
    assert prices.price_addon({'finance'}, 365)['total'] == 690
