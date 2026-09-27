import ast
import asyncio
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from starlette.datastructures import FormData
from starlette.responses import RedirectResponse
from app.models import Base, Procurement, ProcurementItem, MaterialItem, MaterialTxn, Asset
from app.services.register_import import reserve_import, import_history

class ImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.engine=create_engine('sqlite:///'+str(Path(self.tmp.name)/'test.db'),connect_args={'timeout':20})
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            p=Procurement(subject='test',memo_no='1/2569',fiscal_year=2569)
            p.items=[ProcurementItem(name='Paper',quantity=5,unit='box',unit_price=20),ProcurementItem(name='Pen',quantity=3,unit='piece',unit_price=10)]
            db.add(p);db.commit();self.pid=p.id
        tree=ast.parse(Path('app/routers/pages.py').read_text(encoding='utf-8'))
        node=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='to_register_save')
        node.decorator_list=[]
        for arg in node.args.args: arg.annotation=None
        node.args.defaults=[]
        scope=dict(Procurement=Procurement,MaterialItem=MaterialItem,MaterialTxn=MaterialTxn,Asset=Asset,RedirectResponse=RedirectResponse)
        exec(compile(ast.Module(body=[node],type_ignores=[]),'route','exec'),scope)
        self.route=scope['to_register_save']
    def tearDown(self):
        self.engine.dispose();self.tmp.cleanup()
    def post(self,**fields):
        async def form(): return FormData(fields)
        with Session(self.engine) as db:
            return asyncio.run(self.route(self.pid,SimpleNamespace(form=form),db))
    def test_repeat_partial_and_concurrent(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _:self.post(dest_0='material'),range(2)))
        self.post(dest_0='material',dest_1='material')
        with Session(self.engine) as db:
            self.assertEqual(db.query(MaterialTxn).count(),2)
            self.assertEqual(sum(x.qty for x in db.query(MaterialTxn)),8)
            done,suspected=import_history(db,db.get(Procurement,self.pid))
            self.assertEqual(len(done),2);self.assertFalse(suspected)
            db.query(MaterialTxn).delete();db.commit()
        self.post(dest_0='material')
        with Session(self.engine) as db: self.assertEqual(db.query(MaterialTxn).count(),0)
    def test_legacy_requires_confirmation(self):
        with Session(self.engine) as db:
            m=MaterialItem(name='Paper',unit='box');db.add(m);db.flush()
            db.add(MaterialTxn(material_id=m.id,kind='in',qty=5,ref='เรื่องจัดซื้อ 1/2569'));db.commit()
        response=self.post(dest_0='material')
        self.assertIn('warning=legacy',response.headers['location'])
        with Session(self.engine) as db: self.assertEqual(db.query(MaterialTxn).count(),1)
        self.post(dest_0='material',confirm_legacy='1')
        with Session(self.engine) as db: self.assertEqual(db.query(MaterialTxn).count(),2)
    def test_reservation_rollback_and_separate_procurement(self):
        with Session(self.engine) as db:
            self.assertTrue(reserve_import(db,10,20,'material'));db.rollback()
            self.assertTrue(reserve_import(db,10,20,'material'));db.commit()
            self.assertFalse(reserve_import(db,10,20,'asset'))
            self.assertTrue(reserve_import(db,11,20,'material'))

if __name__=='__main__': unittest.main()

