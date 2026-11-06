"""Requisition links and instant search UI, isolated from school data."""
import json, os
from pathlib import Path
from tests.test_subsidy import env
from app.models import MaterialItem, MaterialTxn, Requisition, RequisitionItem

def test_capture_material_search_and_requisition_forms(env):
    from app.tenancy import session_for, _engines
    with session_for(next(iter(_engines))) as db:
        defs=[('กระดาษ A4 80 แกรม','รีม','สำนักงาน','PAPER-A4',20),
              ('กระดาษสี A4','ห่อ','สำนักงาน','COLOR-A4',12),
              ('ปากกาน้ำเงิน','ด้าม','สำนักงาน','PEN-01',30),
              ('ปากกาน้ำเงิน','กล่อง','สำนักงาน','PEN-BOX',5),
              ('ไม้กวาดทางมะพร้าว','อัน','ทำความสะอาด','CLEAN-01',8),
              ('<img src=x onerror=alert(1)>','ชิ้น','ทดสอบ','SAFE-01',1)]
        ids=[]
        for name,unit,cat,code,qty in defs:
            item=MaterialItem(name=name,unit=unit,category=cat,code=code);db.add(item);db.flush()
            db.add(MaterialTxn(material_id=item.id,kind='in',qty=qty));ids.append(item.id)
        db.commit()
    for name,url in [('materials','/materials'),('requisition','/requisitions/new'),
                     ('preselected',f'/requisitions/new?material_id={ids[0]}&material_id={ids[4]}')]:
        response=env.get(url);assert response.status_code==200
        if os.environ.get('MATERIAL_UI_CAPTURE'):
            out=Path(os.environ['MATERIAL_UI_CAPTURE']);out.mkdir(exist_ok=True,parents=True)
            (out/(name+'.html')).write_text(response.text,encoding='utf-8')
            (out/'fixture.json').write_text(json.dumps(dict(ids=ids)),encoding='utf-8')
    response=env.post('/requisitions/new',data=dict(req_no='UI/2570',requester='ครูทดสอบ',
        item_name=['กระดาษ A4 80 แกรม','วัสดุชื่อใหม่'],item_mid=[str(ids[0]),''],
        item_qty=['2','3'],item_unit=['รีม','ชุด']),follow_redirects=False)
    assert response.status_code==303
    rid=int(response.headers['location'].split('/')[-1])
    with session_for(next(iter(_engines))) as db:
        rows=db.query(RequisitionItem).filter_by(requisition_id=rid).all()
        assert [(r.name,r.material_id,r.qty,r.unit) for r in rows]==[
            ('กระดาษ A4 80 แกรม',ids[0],2,'รีม'),('วัสดุชื่อใหม่',None,3,'ชุด')]
    env.post(f'/requisitions/{rid}/issue')
    with session_for(next(iter(_engines))) as db:
        txns=db.query(MaterialTxn).filter_by(requisition_id=rid).all()
        assert [(t.material_id,t.qty) for t in txns]==[(ids[0],2)]
