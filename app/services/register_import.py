from sqlalchemy.dialects.sqlite import insert
from app.models import ProcurementRegisterImport, MaterialTxn, MaterialItem, Asset


def import_history(db, proc):
    done = {x.item_id for x in db.query(ProcurementRegisterImport).filter_by(procurement_id=proc.id).all()}
    # Old imports had only a human-readable reference, so treat these as possible matches.
    ref = f"เรื่องจัดซื้อ {proc.memo_no or proc.id}"
    names = {name for name, in db.query(MaterialItem.name).join(MaterialTxn, MaterialTxn.material_id == MaterialItem.id).filter(MaterialTxn.kind == 'in', MaterialTxn.ref == ref).all()}
    names.update(name for name, in db.query(Asset.name).filter_by(procurement_id=proc.id).all())
    suspected = {item.id for item in proc.items if item.name in names} - done
    return done, suspected


def reserve_import(db, proc_id, item_id, destination):
    result = db.execute(insert(ProcurementRegisterImport).values(key=f'{proc_id}:{item_id}', procurement_id=proc_id, item_id=item_id, destination=destination).on_conflict_do_nothing())
    return result.rowcount == 1
