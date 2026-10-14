from types import SimpleNamespace
from unittest.mock import patch
import dns.resolver
import dns.exception
from app.services.signup_guard import email_problem, throttle


def test_domains():
    assert email_problem("kru@example.com")
    assert email_problem("bad")
    with patch("dns.resolver.Resolver.resolve", return_value=[SimpleNamespace(exchange="mail.school.ac.th.")]):
        assert email_problem("teacher@school.ac.th") is None
    for error in (dns.resolver.NoAnswer, dns.exception.Timeout, dns.resolver.NoNameservers):
        with patch("dns.resolver.Resolver.resolve", side_effect=error):
            assert email_problem("teacher@school.ac.th") is None
    with patch("dns.resolver.Resolver.resolve", side_effect=dns.resolver.NXDOMAIN):
        assert email_problem("teacher@missing.ac.th")
    with patch("dns.resolver.Resolver.resolve", return_value=[SimpleNamespace(exchange=".")]):
        assert email_problem("teacher@school.ac.th")


def test_shared_limits(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import accounts
    engine = create_engine("sqlite:///" + str(tmp_path / "limits.db"))
    accounts.SignupThrottle.__table__.create(engine)
    monkeypatch.setattr(accounts, "acc_session", sessionmaker(bind=engine))
    request = SimpleNamespace(client=SimpleNamespace(host="192.0.2.1"))
    with patch("app.services.signup_guard.time.time", return_value=10000):
        assert throttle(request, "teacher@school.ac.th") == 0
        assert throttle(request, "TEACHER@school.ac.th") == 120
        # Other teachers behind the same school connection are allowed.
        for i in range(29):
            assert throttle(request, f"teacher{i}@school.ac.th") == 0
        assert throttle(request, "new@school.ac.th") == 900
    with patch("app.services.signup_guard.time.time", return_value=10901):
        assert throttle(request, "teacher@school.ac.th") == 0
    engine.dispose()
