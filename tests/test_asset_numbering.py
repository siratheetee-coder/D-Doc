import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.models import Asset, AssetNumberSeries, AssetNumberCounter, AssetNumberUsed
from app.services.asset_numbering import lock_numbers, next_number, manual_number


class NumberingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine('sqlite:///' + str(Path(self.tmp.name) / 'school.db'), connect_args={'timeout': 20})
        for model in (Asset, AssetNumberSeries, AssetNumberCounter, AssetNumberUsed):
            model.__table__.create(self.engine)
        self.form = dict(number_prefix='7440-001', number_digits='4', number_year='2569', number_start='1', number_reset='yearly', number_append='yes')

    def tearDown(self):
        self.engine.dispose()
        self.tmp.cleanup()

    def allocate(self, form=None):
        with Session(self.engine) as db:
            lock_numbers(db)
            code = next_number(db, form or self.form, reserve=True)
            db.add(Asset(name='test', asset_code=code))
            db.commit()
            return code

    def test_concurrent_and_deleted_codes(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(lambda _: self.allocate(), range(8)))
        self.assertEqual(len(set(codes)), 8)
        with Session(self.engine) as db:
            db.query(Asset).delete()
            db.commit()
        self.assertEqual(self.allocate(), '7440-001-0009/2569')

    def test_legacy_year_start_and_manual_duplicate(self):
        with Session(self.engine) as db:
            db.add(Asset(name='old', asset_code='7440-001-0042/2569', status='จำหน่ายแล้ว'))
            db.commit()
            self.assertEqual(next_number(db, self.form), '7440-001-0043/2569')
        self.assertEqual(self.allocate(), '7440-001-0043/2569')
        self.assertEqual(self.allocate(dict(self.form, number_year='2570', number_start='10')), '7440-001-0010/2570')
        with Session(self.engine) as db:
            lock_numbers(db)
            with self.assertRaises(ValueError):
                manual_number(db, '7440-001-0042/2569')
            manual_number(db, '7440-001-0042/2569', '7440-001-0042/2569')

    def test_continuous_rollback_and_format(self):
        form = dict(self.form, number_reset='continuous')
        self.assertEqual(self.allocate(form), '7440-001-0001/2569')
        self.assertEqual(self.allocate(dict(form, number_year='2570')), '7440-001-0002/2570')
        with Session(self.engine) as db:
            lock_numbers(db)
            next_number(db, form, reserve=True)
            db.rollback()
        self.assertEqual(self.allocate(form), '7440-001-0003/2569')
        with Session(self.engine) as db:
            with self.assertRaises(ValueError):
                next_number(db, self.form)
            with self.assertRaises(ValueError):
                next_number(db, dict(self.form, number_append='no'))


if __name__ == '__main__':
    unittest.main()
