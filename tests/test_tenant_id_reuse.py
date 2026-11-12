# -*- coding: utf-8 -*-
"""โรงเรียนใหม่ที่ได้เลข id ซ้ำกับโรงเรียนที่ถูกลบ (เช่น ระบบตัวอย่างหมดเวลา) ต้องเริ่มจากข้อมูลว่าง"""
import secrets
import shutil

from app import accounts as ac
from app import tenancy
from app.database import get_data_dir
from app.models import Person


def _folder(tid):
    return get_data_dir() / "schools" / str(tid)


def test_stale_engine_rebuilt_when_file_replaced():
    tok = secrets.token_hex(4)
    tid = ac.provision_tenant(f"เทสต์เก่า {tok}", f"old-{tok}", f"old_{tok}", "Passw0rd!x9", max_users=1)
    try:
        s = tenancy.session_for(tid)
        s.add(Person(name="ครูตัวอย่างเก่า")); s.commit(); s.close()
        # โปรเซสอื่นลบไฟล์ทิ้ง (engine ในโปรเซสนี้ยังค้างอยู่) แล้วสร้างไฟล์ใหม่ที่เลขเดิม
        shutil.rmtree(_folder(tid), ignore_errors=True)
        if _folder(tid).exists():       # Windows ลบไฟล์ที่เปิดอยู่ไม่ได้ ข้ามเคสนี้
            return
        tenancy.school_db_path(tid)
        tenancy.init_school_db(tenancy.create_engine(f"sqlite:///{tenancy.school_db_path(tid)}"))
        s = tenancy.session_for(tid)
        assert s.query(Person).count() == 0
        s.close()
    finally:
        ac.purge_tenant(tid)


def test_create_tenant_wipes_leftover_folder():
    tok = secrets.token_hex(4)
    tid = ac.provision_tenant(f"เทสต์ {tok}", f"t-{tok}", f"t_{tok}", "Passw0rd!x9", max_users=1)
    s = tenancy.session_for(tid)
    s.add(Person(name="ครูตัวอย่าง")); s.commit(); s.close()
    tenancy.dispose_engine(tid)
    leftover = _folder(tid) / "school.db"
    db = ac.acc_session()
    try:
        db.query(ac.Account).filter_by(tenant_id=tid).delete()
        db.query(ac.Tenant).filter_by(id=tid).delete()
        db.commit()
    finally:
        db.close()
    assert leftover.exists()      # จำลองไฟล์ค้างหลังลบโรงเรียน
    tok2 = secrets.token_hex(4)
    tid2 = ac.provision_tenant(f"ใหม่ {tok2}", f"n-{tok2}", f"n_{tok2}", "Passw0rd!x9", max_users=1)
    try:
        if tid2 == tid:
            s = tenancy.session_for(tid2)
            assert s.query(Person).count() == 0
            s.close()
    finally:
        ac.purge_tenant(tid2)
        if tid2 != tid:
            shutil.rmtree(_folder(tid), ignore_errors=True)
