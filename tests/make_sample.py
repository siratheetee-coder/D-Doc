# -*- coding: utf-8 -*-
from app.database import SessionLocal
from app.models import School, Procurement
from app.services.render import render_bundle, DOC_ORDER
db = SessionLocal()
sc = db.query(School).first()
pr = db.query(Procurement).first()
if sc and pr:
    print("BUNDLE:", render_bundle(DOC_ORDER, pr, sc))
else:
    print("no data; school=", bool(sc), "proc=", bool(pr))
db.close()
