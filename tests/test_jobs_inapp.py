"""งานอัตโนมัติรันในแอปแทน cron แยกโปรเซส (ต้นเหตุ -wal หาย) + ตัวเฝ้า -wal"""
from datetime import datetime

from tests.test_subsidy import env  # noqa: F401
from tests.test_article_editor import _boss


def test_all_jobs_start_disabled_and_due_respects_time(env):
    from app.services import jobs
    st = jobs.load_state()
    assert all(not st[k]["enabled"] for k in jobs.JOBS)
    assert list(jobs.due(datetime(2026, 11, 22, 23, 0), st)) == []          # ปิดอยู่ = ไม่รัน
    st["finance_health"]["enabled"] = True
    assert list(jobs.due(datetime(2026, 11, 22, 4, 59), st)) == []          # ยังไม่ถึงเวลา
    assert list(jobs.due(datetime(2026, 11, 22, 5, 1), st)) == ["finance_health"]
    st["finance_health"]["last_run"] = {"at": "2026-11-22 05:01"}
    assert list(jobs.due(datetime(2026, 11, 22, 9, 0), st)) == []           # วันละครั้ง


def test_run_job_records_output_and_survives_errors(env, monkeypatch):
    from app.services import jobs
    def boom(dry):
        print("เริ่มงาน")
        raise ValueError("พัง")
    monkeypatch.setitem(jobs.JOBS, "finance_health", ("x", "05:00", "y", boom))
    out = jobs.run_job("finance_health", dry_run=True)
    assert "เริ่มงาน" in out and "พัง" in out
    rec = jobs.load_state()["finance_health"]["last_dry"]
    assert rec["ok"] is False and "last_run" not in jobs.load_state()["finance_health"]


def test_wal_watchdog_detects_missing_wal(env, monkeypatch, tmp_path):
    from app.services import jobs
    from app import accounts
    monkeypatch.setattr(accounts, "get_data_dir", lambda: tmp_path)
    monkeypatch.setattr(accounts, "_engine", object())
    (tmp_path / "accounts.db").write_bytes(b"")
    assert str(tmp_path / "accounts.db") in jobs.missing_wal()
    (tmp_path / "accounts.db-wal").write_bytes(b"")
    assert str(tmp_path / "accounts.db") not in jobs.missing_wal()


def test_console_page_and_toggle(env):
    from app.services import jobs
    c = _boss()
    assert "งานอัตโนมัติรายวัน" in c.get("/admin-console/jobs").text
    c.post("/admin-console/jobs/member_notice", data={"act": "on"})
    assert jobs.load_state()["member_notice"]["enabled"] is True
    c.post("/admin-console/jobs/member_notice", data={"act": "dry"})
    assert jobs.load_state()["member_notice"].get("last_dry")
    c.post("/admin-console/jobs/member_notice", data={"act": "off"})
    assert jobs.load_state()["member_notice"]["enabled"] is False
    anon = __import__("tests.test_article_editor", fromlist=["_anon"])._anon()
    assert anon.post("/admin-console/jobs/retention", data={"act": "run"}, follow_redirects=False).status_code in (302, 303, 403)
