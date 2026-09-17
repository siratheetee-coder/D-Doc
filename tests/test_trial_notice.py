from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import accounts
from app.services import trial_notice as tn


class TrialNoticeTests(unittest.TestCase):
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
                  side_effect=lambda to, subj, html, attachments=None: self.sent.append((to, subj)) or True)
        p.start(); self.addCleanup(p.stop)

    def _tenant(self, tid, days_left, plan='trial', active=True):
        end = date.today() + timedelta(days=days_left)
        with self.Session() as db:
            db.add(accounts.Tenant(id=tid, name=f'S{tid}', plan=plan, active=active, expiry_date=end,
                                   trial_expiry_date=end, created_at=datetime.now()))
            db.add(accounts.Account(tenant_id=tid, username=f'o{tid}@x.th', password_hash='x', is_owner=True))
            db.commit()

    def _stage(self, tid):
        with self.Session() as db:
            return db.get(accounts.Tenant, tid).trial_notice_stage

    def test_stage_rules(self):
        self.assertEqual(tn.stage_for(8), 0)
        self.assertEqual(tn.stage_for(7), 1)
        self.assertEqual(tn.stage_for(2), 1)
        self.assertEqual(tn.stage_for(1), 2)
        self.assertEqual(tn.stage_for(0), 2)        # วันสุดท้ายยังใช้ได้
        self.assertEqual(tn.stage_for(-1), 3)
        self.assertEqual(tn.stage_for(-7), 3)
        self.assertEqual(tn.stage_for(-8), 0)       # หมดนานแล้ว ไม่ส่งย้อนหลัง

    def test_sends_once_per_stage_and_skips_members(self):
        self._tenant(1, 5)
        self._tenant(2, 5, plan='member')
        self._tenant(3, 5, active=False)
        self._tenant(4, 20)
        tn.run(verbose=False)
        self.assertEqual([to for to, _ in self.sent], ['o1@x.th'])
        self.assertEqual(self._stage(1), 1)
        tn.run(verbose=False)                        # รันซ้ำวันเดียวกัน ไม่ส่งซ้ำ
        self.assertEqual(len(self.sent), 1)

    def test_progression_and_jump(self):
        self._tenant(1, 5)
        today = date.today()
        tn.run(verbose=False, today=today)
        tn.run(verbose=False, today=today + timedelta(days=4))    # เหลือ 1 วัน
        tn.run(verbose=False, today=today + timedelta(days=6))    # หมดแล้ว
        self.assertEqual(self._stage(1), 3)
        self.assertEqual(len(self.sent), 3)
        self._tenant(2, 0)                                        # เจอครั้งแรกตอนวันสุดท้าย -> ส่งขั้น 2 ขั้นเดียว
        tn.run(verbose=False, today=today)
        self.assertEqual(self._stage(2), 2)
        self.assertEqual(len(self.sent), 4)

    def test_failed_send_retries_and_extension_resets(self):
        self._tenant(1, 3)
        with patch('app.services.mailer.send_email', return_value=False):
            r = tn.run(verbose=False)
        self.assertEqual(r['failed'], ['S1'])
        self.assertEqual(self._stage(1), 0)
        tn.run(verbose=False)
        self.assertEqual(self._stage(1), 1)
        with self.Session() as db:                  # ผู้ดูแลขยายเวลาทดลอง
            t = db.get(accounts.Tenant, 1)
            t.trial_expiry_date = date.today() + timedelta(days=30)
            db.commit()
        tn.run(verbose=False)
        self.assertEqual(self._stage(1), 0)

    def test_dry_run_sends_nothing(self):
        self._tenant(1, 3)
        r = tn.run(dry_run=True, verbose=False)
        self.assertEqual(r['sent'], [('S1', 1)])
        self.assertEqual(self.sent, [])
        self.assertEqual(self._stage(1), 0)

    def test_email_content(self):
        subj, html = tn.build_email('โรงเรียน <ทดสอบ>', 3, date(2026, 9, 1), -2, 'https://x.th')
        self.assertIn('สิ้นสุดแล้ว', subj)
        self.assertIn('&lt;ทดสอบ&gt;', html)
        self.assertIn('https://x.th/checkout', html)
        self.assertIn('ยังเก็บไว้ครบ', html)


if __name__ == '__main__':
    unittest.main()
