from types import SimpleNamespace as N


def test_period_gaps_flags_missing_periods():
    from app.routers.academic import _period_gaps
    ps = [N(id=1, seq=1, name="คาบ 1", time_label="08:30-09:20"),
          N(id=2, seq=2, name="คาบ 2", time_label="09:20-10:10"),
          N(id=3, seq=3, name="พักเที่ยง", time_label="11:50-12:40"),
          N(id=4, seq=4, name="คาบ 5", time_label="12:40-13:30")]
    gaps = _period_gaps(ps)
    assert len(gaps) == 1 and gaps[0][0].name == "คาบ 2" and gaps[0][2] == 100
    assert _period_gaps(ps[:2]) == []        # ต่อกันพอดี ไม่เตือน
    assert _period_gaps([N(id=9, seq=1, name="x", time_label="")]) == []


def test_mark_until_today(monkeypatch):
    from datetime import date
    import app.thai_utils as tu
    from app.routers.academic import _mark_until
    monkeypatch.setattr(tu, "thai_today", lambda: date(2026, 11, 21))
    assert _mark_until(2569, 11) == 21
    assert _mark_until(2569, 12) == 0 and _mark_until(2569, 1) == 0
    assert _mark_until(2569, 10) == 31 and _mark_until(2568, 1) == 31
