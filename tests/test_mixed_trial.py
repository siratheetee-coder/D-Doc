from datetime import date, datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app import accounts
from app.modules import MODULE_KEYS


class MixedTrialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = create_engine('sqlite:///' + str(self.root / 'accounts.db'))
        self.addCleanup(self.engine.dispose)
        accounts.AccBase.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        p = patch.object(accounts, 'acc_session', self.Session); p.start(); self.addCleanup(p.stop)

    def test_approval_preserves_remaining_trial_until_original_deadline(self):
        deadline = date.today() + timedelta(days=20)
        with self.Session() as db:
            db.add(accounts.Tenant(id=1, name='School', plan='trial', expiry_date=deadline,
                trial_expiry_date=deadline, created_at=datetime.now()-timedelta(days=10)))
            db.add(accounts.Lead(id=1, kind='order', tenant_id=1, modules=','.join(MODULE_KEYS[:3]), amount=1200))
            db.commit()
        accounts.renew_lead(1)
        for key in MODULE_KEYS:
            self.assertTrue(accounts.can_use_module(1, key))
            self.assertTrue(accounts.consume_doc_quota(1, key)[0])
        self.assertEqual(accounts.tenant_status(1)['trial_expiry_date'], deadline)
        self.assertEqual(accounts.tenant_status(1)['trial_days_left'], 20)
        with self.Session() as db:
            tenant = db.get(accounts.Tenant, 1)
            tenant.trial_expiry_date = date.today()-timedelta(days=1)
            db.commit()
        for key in MODULE_KEYS[:3]:
            self.assertTrue(accounts.can_use_module(1, key))
            self.assertTrue(accounts.consume_doc_quota(1, key)[0])
        for key in MODULE_KEYS[3:]:
            self.assertFalse(accounts.can_use_module(1, key))
            self.assertFalse(accounts.consume_doc_quota(1, key)[0])

    def test_addon_does_not_restart_trial(self):
        deadline = date.today()-timedelta(days=2)
        with self.Session() as db:
            db.add(accounts.Tenant(id=1, name='School', plan='member', modules=MODULE_KEYS[0],
                expiry_date=date.today()+timedelta(days=200), trial_expiry_date=deadline))
            db.add(accounts.Lead(id=1, tenant_id=1, modules=MODULE_KEYS[1], amount=200))
            db.commit()
        accounts.renew_lead(1)
        self.assertEqual(accounts.tenant_status(1)['trial_expiry_date'], deadline)
        self.assertTrue(accounts.can_use_module(1, MODULE_KEYS[1]))
        self.assertFalse(accounts.can_use_module(1, MODULE_KEYS[2]))

    def test_migration_restores_original_trial_only_for_registered_schools(self):
        created = datetime.now()-timedelta(days=10)
        with self.Session() as db:
            for tid in [1,2]:
                db.add(accounts.Tenant(id=tid, name='School', plan='member', modules=MODULE_KEYS[0],
                    created_at=created, expiry_date=date.today()+timedelta(days=365)))
            db.add(accounts.Lead(kind='trial', tenant_id=1, created_at=created+timedelta(seconds=1)))
            db.commit()
        with self.engine.begin() as connection:
            connection.execute(text('ALTER TABLE tenant DROP COLUMN trial_expiry_date'))
        with patch.object(accounts, '_engine', None), patch.object(accounts, '_Session', None), patch.object(accounts, 'get_data_dir', return_value=self.root):
            engine = accounts._ensure_engine()
            engine.dispose()
        with self.Session() as db:
            self.assertEqual(db.get(accounts.Tenant, 1).trial_expiry_date, created.date()+timedelta(days=30))
            self.assertIsNone(db.get(accounts.Tenant, 2).trial_expiry_date)


if __name__ == '__main__': unittest.main()
