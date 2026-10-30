"""หน้าตั้งค่าแบบใหม่: แถบเมนูการ์ด, นำเข้า Excel แบบตรวจก่อนนำเข้า, กู้คืน 2 ขั้น
และกติกากันสมัครบัญชีทดลองใหม่แล้วกู้คืนไฟล์ของโรงเรียนอื่นเพื่อใช้ฟรีต่อ (เจ้าของเลือก 2026-10-30)"""
import io
import json
import re
import zipfile

from tests.test_subsidy import env  # noqa: F401


def _db():
    import app.tenancy as tn
    return tn.session_for(next(iter(tn._engines)))


def _tid():
    import app.tenancy as tn
    return next(iter(tn._engines))


def _set_plan(plan):
    import app.accounts as ac
    s = ac.acc_session()
    try:
        t = s.get(ac.Tenant, _tid())
        t.plan = plan
        s.commit()
    finally:
        s.close()


def test_settings_page_sections_and_tabs(env):
    html = env.get("/settings").text
    for t in ("ข้อมูลโรงเรียน", "นำเข้าข้อมูล", "บุคลากรและฝ่าย", "สำรอง / กู้คืนข้อมูล"):
        assert t in html
    assert "ผู้บริหารและเจ้าหน้าที่" in html and "อีเมลรับแจ้งเตือน" in html and 'id="sfDirty"' in html
    r = env.post("/settings", data={"name": "โรงเรียนทดสอบตั้งค่า", "director_name": "นายผอ ทดสอบ"},
                 follow_redirects=False)
    assert r.headers["location"].startswith("/settings")
    assert "โรงเรียนทดสอบตั้งค่า" in env.get("/settings").text


def test_excel_import_previews_before_saving(env):
    from openpyxl import load_workbook
    from app.models import Person
    from app.services.bulk_io import build_import_template
    wb = load_workbook(build_import_template())
    wb["บุคลากร"]["A3"] = "นางสาวนำเข้า ตรวจก่อน"
    buf = io.BytesIO(); wb.save(buf)
    xlsx = ("p.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    page = env.post("/masters/import", files={"file": xlsx}).text
    assert "ตรวจไฟล์" in page and "บุคลากร: เพิ่ม 1 รายการ" in page
    with _db() as s:
        assert s.query(Person).filter_by(name="นางสาวนำเข้า ตรวจก่อน").count() == 0     # ยังไม่บันทึก
    token = re.search(r'name="token" value="([^"]+)"', page).group(1)
    r = env.post("/masters/import/confirm", data={"token": token}, follow_redirects=False)
    assert "imported=" in r.headers["location"]
    with _db() as s:
        assert s.query(Person).filter_by(name="นางสาวนำเข้า ตรวจก่อน").count() == 1
    # โทเคนใช้ซ้ำไม่ได้
    r = env.post("/masters/import/confirm", data={"token": token}, follow_redirects=False)
    assert "import_err=expired" in r.headers["location"]


def test_backup_is_signed_and_restore_needs_confirm(env):
    data = env.get("/backup").content
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        meta = json.loads(z.read("meta.json"))
    assert meta["sig"] and meta["tenant_id"] == _tid() and meta["db_sha256"]

    page = env.post("/restore", files={"file": ("b.zip", data, "application/zip")}).text
    assert "ตรวจไฟล์ก่อนกู้คืน" in page and "บัญชีนี้" in page and "ยืนยันกู้คืนข้อมูล" in page
    token = re.search(r'name="token" value="([^"]+)"', page).group(1)
    r = env.post("/restore/confirm", data={"token": token}, follow_redirects=False)
    assert "restored=1" in r.headers["location"]


def test_trial_can_restore_only_its_own_file(env):
    from app.services import backup_file
    own = env.get("/backup").content
    # ไฟล์ของโรงเรียนอื่น: แก้เลขโรงเรียนใน meta -> ลายเซ็นไม่ตรง
    zin = zipfile.ZipFile(io.BytesIO(own))
    meta = json.loads(zin.read("meta.json")); meta["tenant_id"] = 999999
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for n in zin.namelist():
            z.writestr(n, json.dumps(meta) if n == "meta.json" else zin.read(n))
    forged = out.getvalue()
    # ไฟล์ที่เซ็นถูกต้อง แต่มาจากโรงเรียนอื่น
    other = backup_file.build(999999, "โรงเรียนอื่น", _db_path(), [])
    legacy = zin.read("school.db")

    _set_plan("trial")
    for f in (forged, other, legacy):
        page = env.post("/restore", files={"file": ("x.zip", f, "application/zip")}).text
        assert "ยืนยันกู้คืนข้อมูล" not in page and "บัญชีทดลองใช้กู้คืนได้เฉพาะไฟล์" in page
    page = env.post("/restore", files={"file": ("x.zip", own, "application/zip")}).text
    assert "ยืนยันกู้คืนข้อมูล" in page                        # ไฟล์ของตัวเองยังกู้ได้

    _set_plan("member")
    page = env.post("/restore", files={"file": ("x.zip", other, "application/zip")}).text
    assert "ยืนยันกู้คืนข้อมูล" in page and "บัญชีอื่น" in page   # สมาชิกย้ายบัญชีได้


def _db_path():
    import app.tenancy as tn
    return tn.get_data_dir() / "schools" / str(_tid()) / "school.db"
