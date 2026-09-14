import ast
import asyncio
import re
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from fastapi import HTTPException
from starlette.datastructures import FormData
from starlette.requests import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.database import Base
from app.models import ClassroomVisit, Supervision
from app.modules import module_for_path
from docx import Document
from app.services.book_select_doc import _member_rows

ROOT=Path(__file__).parents[1]


def supervision_scope():
    tree=ast.parse((ROOT/'app/routers/academic_supervision.py').read_text(encoding='utf-8'))
    tree.body=[node for node in tree.body if not (isinstance(node,ast.ImportFrom) and node.module in ('app.templating','app.routers.pages'))]
    scope={'templates':NS(TemplateResponse=lambda name,data: data),
           'get_school':lambda db:NS(name='test',academic_year=2569,director_name='test'),
           '_to_int':lambda value,default:int(value) if value else default,'serve_generated':lambda *args:args}
    exec(compile(tree,'academic_supervision','exec'),scope)
    return scope


class SupervisionMoveTests(unittest.TestCase):
    def test_module_paths_and_legacy_redirect(self):
        scope=supervision_scope()
        for area in ('supervision','supervision-form','classroom-visit'):
            self.assertEqual(module_for_path('/academic/'+area),'academic')
            self.assertEqual(module_for_path('/hr/'+area),'academic')
        self.assertEqual(module_for_path('/hr/staff'),'hr')
        request=Request({'type':'http','method':'GET','path':'/hr/classroom-visit','query_string':b'edit=12&year=2569','headers':[]})
        response=asyncio.run(scope['legacy_supervision'](request))
        self.assertEqual(response.status_code,307)
        self.assertEqual(response.headers['location'],'/academic/classroom-visit?edit=12&year=2569')
        paths={route.path for route in scope['router'].routes}
        self.assertIn('/academic/classroom-visit/save',paths)
        self.assertIn('/academic/supervision-form/{vid}/print.docx',paths)

    def test_director_access_and_teacher_boundary(self):
        guard=supervision_scope()['require_supervision_manager']
        for session in ({'owner':True,'person_id':1},{'director':True,'person_id':1},{}): guard(NS(session=session))
        with self.assertRaises(HTTPException): guard(NS(session={'person_id':1}))
        tree=ast.parse((ROOT/'app/main.py').read_text(encoding='utf-8'))
        assignment=next(n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_DIRECTOR_WRITE_ALLOW' for t in n.targets))
        scope={'re':re};exec(compile(ast.Module(body=[assignment],type_ignores=[]),'director','exec'),scope)
        for path in ('/academic/classroom-visit/save','/academic/supervision-form/12/delete'):
            self.assertTrue(any(rule.match(path) for rule in scope['_DIRECTOR_WRITE_ALLOW']))

    def test_save_existing_records_without_copying_tables(self):
        engine=create_engine('sqlite://');Base.metadata.create_all(engine)
        scope=supervision_scope()
        class FakeRequest:
            async def form(self):return FormData({'id':'1','topic':'updated','round_no':'2','year':'2569'})
        with Session(engine) as db:
            db.add_all([ClassroomVisit(id=1,topic='old'),Supervision(id=1,round_no=1)]);db.commit()
            cv=asyncio.run(scope['cv_save'](FakeRequest(),db))
            sup=asyncio.run(scope['sup_save'](FakeRequest(),db))
            self.assertEqual(db.query(ClassroomVisit).count(),1)
            self.assertEqual(db.get(ClassroomVisit,1).topic,'updated')
            self.assertEqual(db.get(Supervision,1).round_no,2)
            self.assertTrue(cv.headers['location'].startswith('/academic/'))
            self.assertTrue(sup.headers['location'].startswith('/academic/'))
        engine.dispose()

    def test_selection_number_name_and_level_share_row(self):
        doc=Document()
        table=_member_rows(doc,[{'name':'นางกันตินันท์ รัตนสีหา','level':'ป.1'}],selection=True)
        self.assertEqual(table.rows[0].cells[0].text,'2.1')
        self.assertIn('นางกันตินันท์ รัตนสีหา',table.rows[0].cells[1].text)
        self.assertIn('ป.1',table.rows[0].cells[1].text)
        self.assertIn('cantSplit',table.rows[0]._tr.xml)


if __name__=='__main__':unittest.main()
