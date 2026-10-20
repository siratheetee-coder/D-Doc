from app import seller_config as prices
from app.modules import MODULE_KEYS


def test_current_finance_bundle_and_addon(monkeypatch):
    monkeypatch.setitem(prices.SELLER, 'promo', {'enabled': False})
    ctx = prices.pricing_context()
    assert ctx['prices']['p_fin'] == 990
    assert ctx['full_sum'] == 4440
    assert ctx['bundle_save'] == 1250
    assert prices.price_for({'finance'})['total'] == 990
    assert prices.price_for({'finance', 'procurement'})['total'] == 1880
    assert prices.price_for(set(MODULE_KEYS))['total'] == 3190
    assert prices.price_addon({'finance'}, 365)['total'] == 990

    assert prices.price_for({"academic"})["total"] == 990
    assert prices.price_for({"procurement"})["total"] == 990
    assert prices.price_for({"finance", "procurement", "academic"})["total"] == 2770
