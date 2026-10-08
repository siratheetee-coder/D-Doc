# -*- coding: utf-8 -*-
"""อีเมลเตือนสมาชิกที่จ่ายเงินแล้วว่าใกล้หมดอายุ

ก่อนหน้านี้มีเฉพาะอีเมลเตือนช่วงทดลองใช้ สมาชิกที่จ่ายเงินแล้วไม่เคยได้รับอะไรเลย
ครบปีแล้วเปิดระบบมาเจอหน้า "บัญชีหมดอายุ" ทันที
รัน: .venv\\Scripts\\python.exe -m pytest tests/test_member_notice.py
"""
from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import accounts
from app.services import member_notice as mn

ROOT = Path(__file__).resolve().parents[1]


class MemberNoticeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.engine = create_engine('sqlite:///' + str(Path(self.temp.name) / 'accounts.db'))
        self.addCleanup(self.engine.dispose)
        accounts.AccBase.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        for p in (patch.object(accounts, 'acc_session', self.Session),
                  patch('app.services.mailer.smtp_configured', return_value=True),
                  patch('app.accounts.audit')):
            p.start(); self.addCleanup(p.stop)
        self.sent = []
        p = patch('app.services.mailer.send_email',
                  side_effect=lambda to, subj, html, attachments=None:
                      self.sent.append((to, subj, html)) or True)
        p.start(); self.addCleanup(p.stop)

    def _tenant(self, tid, days_left, plan='member', active=True, expiry=True):
        end = (date.today() + timedelta(days=days_left)) if expiry else None
        with self.Session() as db:
            db.add(accounts.Tenant(id=tid, name=f'โรงเรียนทดสอบ {tid}', plan=plan, active=active,
                                   expiry_date=end, created_at=datetime.now()))
            db.add(accounts.Account(tenant_id=tid, username=f'o{tid}@x.th',
                                    password_hash='x', is_owner=True))
            db.commit()

    def _stage(self, tid):
        with self.Session() as db:
            return db.get(accounts.Tenant, tid).member_notice_stage

    # ---------------- กติกาขั้นการเตือน ----------------
    def test_stage_rules(self):
        self.assertEqual(mn.stage_for(31), 0)
        self.assertEqual(mn.stage_for(30), 1)
        self.assertEqual(mn.stage_for(8), 1)
        self.assertEqual(mn.stage_for(7), 2)
        self.assertEqual(mn.stage_for(2), 2)
        self.assertEqual(mn.stage_for(1), 3)
        self.assertEqual(mn.stage_for(0), 3)        # วันสุดท้ายยังใช้ได้
        self.assertEqual(mn.stage_for(-1), 4)
        self.assertEqual(mn.stage_for(-7), 4)
        self.assertEqual(mn.stage_for(-8), 0)       # หมดนานแล้ว ไม่ส่งย้อนหลัง

    def test_warns_a_month_ahead_so_the_school_can_ask_for_budget(self):
        """โรงเรียนต้องทำเรื่องขออนุมัติงบ เตือน 7 วันไม่ทัน"""
        self._tenant(1, 30)
        mn.run(verbose=False)
        self.assertEqual([to for to, _, _ in self.sent], ['o1@x.th'])
        self.assertIn('ใบเสนอราคา', self.sent[0][2])

    # ---------------- ส่งใคร ไม่ส่งใคร ----------------
    def test_only_paying_members_with_an_expiry_date(self):
        self._tenant(1, 5)                               # สมาชิก ใกล้หมด -> ส่ง
        self._tenant(2, 5, plan='trial')                 # ทดลองใช้ -> trial_notice ดูแล
        self._tenant(3, 5, active=False)                 # ถูกระงับ -> ไม่ส่ง
        self._tenant(4, 90)                              # ยังอีกนาน -> ไม่ส่ง
        self._tenant(5, 0, expiry=False)                 # ไม่จำกัดเวลา -> ไม่ส่ง
        mn.run(verbose=False)
        self.assertEqual([to for to, _, _ in self.sent], ['o1@x.th'])

    def test_sends_once_per_stage(self):
        self._tenant(1, 5)
        mn.run(verbose=False)
        mn.run(verbose=False)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self._stage(1), 2)

    def test_walks_through_the_stages_without_resending(self):
        self._tenant(1, 30)
        today = date.today()
        mn.run(verbose=False, today=today)                          # ขั้น 1
        mn.run(verbose=False, today=today + timedelta(days=25))     # เหลือ 5 วัน -> ขั้น 2
        mn.run(verbose=False, today=today + timedelta(days=30))     # วันสุดท้าย -> ขั้น 3
        mn.run(verbose=False, today=today + timedelta(days=32))     # หมดแล้ว -> ขั้น 4
        self.assertEqual(self._stage(1), 4)
        self.assertEqual(len(self.sent), 4)

    def test_jumping_straight_to_the_latest_stage_sends_one_email_only(self):
        """เพิ่งเริ่มใช้ฟีเจอร์นี้ตอนลูกค้าเหลือ 3 วัน ต้องไม่ส่งย้อนขั้น 1 ตามมาด้วย"""
        self._tenant(1, 3)
        mn.run(verbose=False)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self._stage(1), 2)

    def test_long_expired_accounts_are_not_mailed_on_first_run(self):
        """กันอีเมลย้อนหลังถล่มลูกค้าเก่าทั้งหมดในเช้าวันแรกที่เปิดใช้"""
        self._tenant(1, -60)
        mn.run(verbose=False)
        self.assertEqual(self.sent, [])
        self.assertEqual(self._stage(1), 0)

    def test_renewing_resets_the_stage_so_next_year_warns_again(self):
        self._tenant(1, 5)
        mn.run(verbose=False)
        self.assertEqual(self._stage(1), 2)
        with self.Session() as db:                       # ต่ออายุอีกปี
            t = db.get(accounts.Tenant, 1)
            t.expiry_date = date.today() + timedelta(days=365)
            db.commit()
        mn.run(verbose=False)
        self.assertEqual(self._stage(1), 0, "ต่ออายุแล้วต้องเตือนใหม่ได้ปีหน้า")

    def test_failed_send_is_retried_next_run(self):
        self._tenant(1, 5)
        with patch('app.services.mailer.send_email', return_value=False):
            mn.run(verbose=False)
        self.assertEqual(self._stage(1), 0, "ส่งไม่สำเร็จต้องไม่บันทึกว่าส่งแล้ว")
        mn.run(verbose=False)
        self.assertEqual(len(self.sent), 1)

    def test_dry_run_changes_nothing(self):
        self._tenant(1, 5)
        out = mn.run(verbose=False, dry_run=True)
        self.assertEqual(self.sent, [])
        self.assertEqual(self._stage(1), 0)
        self.assertEqual(len(out["sent"]), 1)

    def test_no_owner_email_is_skipped_quietly(self):
        end = date.today() + timedelta(days=5)
        with self.Session() as db:
            db.add(accounts.Tenant(id=9, name='ไม่มีอีเมล', plan='member', active=True,
                                   expiry_date=end, created_at=datetime.now()))
            db.commit()
        mn.run(verbose=False)
        self.assertEqual(self.sent, [])

    # ---------------- เนื้ออีเมล ----------------
    def test_email_says_the_data_is_safe_when_it_has_expired(self):
        self._tenant(1, -1)
        mn.run(verbose=False)
        subject, html = self.sent[0][1], self.sent[0][2]
        self.assertIn('หมดอายุ', subject)
        self.assertIn('ยังเก็บไว้ครบ', html)
        self.assertIn('/checkout', html)

    def test_school_name_is_escaped(self):
        self._tenant(1, 5)
        with self.Session() as db:
            db.get(accounts.Tenant, 1).name = '<script>x</script>'
            db.commit()
        mn.run(verbose=False)
        self.assertNotIn('<script>', self.sent[0][2])


class WiringTests(unittest.TestCase):
    def test_cron_runs_it_every_morning_at_eight(self):
        sh = (ROOT / 'deploy/setup-cron.sh').read_text(encoding='utf-8')
        self.assertIn('0 8 * * *', sh)
        self.assertIn('app.services.member_notice', sh)

    def test_column_is_migrated_for_existing_installs(self):
        src = (ROOT / 'app/accounts.py').read_text(encoding='utf-8')
        self.assertIn('ALTER TABLE tenant ADD COLUMN member_notice_stage', src)

    def test_mobile_users_see_the_expiry_warning_too(self):
        """ป้ายบนแถบหัวมี class topbar-hide-sm ครูที่ใช้มือถือจึงไม่เห็นอะไรเลย"""
        html = (ROOT / 'app/templates/base.html').read_text(encoding='utf-8')
        self.assertIn("_st.plan == 'member' and _st.days_left is not none", html)


if __name__ == '__main__':
    unittest.main()
