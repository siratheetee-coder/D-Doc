"""คะแนนความประพฤตินักเรียน (งานบริหารทั่วไป / กิจการนักเรียน)

อ้างอิง: ระเบียบกระทรวงศึกษาธิการว่าด้วยการลงโทษนักเรียนหรือนักศึกษา พ.ศ. 2548
- ข้อ 5 โทษมี 4 สถาน: ว่ากล่าวตักเตือน ทำทัณฑ์บน ตัดคะแนนความประพฤติ ทำกิจกรรมปรับเปลี่ยนพฤติกรรม
- ข้อ 8 ทัณฑ์บนทำเป็นหนังสือ เชิญผู้ปกครองมาบันทึกรับทราบ
- ข้อ 9 การตัดคะแนนเป็นไปตามระเบียบของแต่ละสถานศึกษา และให้บันทึกข้อมูลไว้เป็นหลักฐาน
ไม่เกี่ยวกับคะแนน/เกรดรายวิชา (ระเบียบไม่ได้กำหนด) ระบบจึงไม่แตะงานวิชาการ
"""
from datetime import date

from app.models import BehaviorSetting, BehaviorRule, BehaviorRecord, Arrival

DEFAULT_RULES = [
    ("minus", "มาสาย", 5), ("minus", "แต่งกายผิดระเบียบ", 5), ("minus", "ทรงผมผิดระเบียบ", 5),
    ("minus", "ไม่เข้าแถว / โดดแถว", 5), ("minus", "หนีเรียน", 10), ("minus", "ทะเลาะวิวาท", 20),
    ("minus", "สูบบุหรี่ / บุหรี่ไฟฟ้า", 20), ("minus", "ทำลายทรัพย์สินของโรงเรียน", 20),
    ("plus", "ทำความดี / ช่วยเหลือผู้อื่น", 5), ("plus", "เก็บของได้ส่งคืน", 10),
    ("plus", "ซ่อมความประพฤติ (ทำกิจกรรมปรับพฤติกรรม)", 10),
]


def setting(db) -> BehaviorSetting:
    s = db.query(BehaviorSetting).first()
    if not s:
        s = BehaviorSetting()
        db.add(s)
        db.commit()
    return s


def rules(db, active_only=True):
    q = db.query(BehaviorRule)
    if not q.first():
        for i, (k, n, p) in enumerate(DEFAULT_RULES):
            db.add(BehaviorRule(kind=k, name=n, points=p, seq=i))
        db.commit()
    if active_only:
        q = q.filter(BehaviorRule.active == True)  # noqa: E712
    return q.order_by(BehaviorRule.kind.desc(), BehaviorRule.seq, BehaviorRule.id).all()


def scores(db, year, student_ids) -> dict:
    """{student_id: คะแนนคงเหลือ} ปีการศึกษานั้น (ไม่มีรายการ = เต็ม)"""
    full = setting(db).full or 100
    out = {sid: full for sid in student_ids}
    if not student_ids:
        return out
    for r in (db.query(BehaviorRecord.student_id, BehaviorRecord.points)
              .filter(BehaviorRecord.year == year, BehaviorRecord.student_id.in_(list(student_ids)))):
        out[r[0]] = out.get(r[0], full) + r[1]
    return out


def level(score, st) -> str:
    """ok / parent (เชิญผู้ปกครอง) / probation (ทัณฑ์บน)"""
    if score < (st.warn_probation or 0):
        return "probation"
    if score < (st.warn_parent or 0):
        return "parent"
    return "ok"


LEVEL_LABEL = {"ok": "ปกติ", "parent": "ควรเชิญผู้ปกครองพบ", "probation": "ควรทำทัณฑ์บน"}


def history(db, year, student_id):
    return (db.query(BehaviorRecord)
            .filter(BehaviorRecord.year == year, BehaviorRecord.student_id == student_id)
            .order_by(BehaviorRecord.date.desc(), BehaviorRecord.id.desc()).all())


def add(db, *, year, student_id, points, label, day=None, rule_id=None, source="manual",
        note="", by_name="", by_pid=None):
    r = BehaviorRecord(year=year, student_id=student_id, points=int(points), label=(label or "")[:200],
                       date=day or date.today().isoformat(), rule_id=rule_id, source=source,
                       note=(note or "")[:500], by_name=(by_name or "")[:120], by_pid=by_pid)
    db.add(r)
    return r


def sync_arrival(db, year, student_id, day):
    """หักอัตโนมัติจากการเข้าแถว (ถ้าเปิดไว้): สาย / โดดแถว 1 รายการต่อวัน
    แก้สถานะการเข้าแถวทีหลัง รายการหักจะเปลี่ยนตาม (ลบ/เปลี่ยนจำนวน)"""
    st = setting(db)
    rec = db.query(Arrival).filter(Arrival.student_id == student_id, Arrival.date == day).first()
    want = None
    if rec and rec.status == "late" and st.auto_late:
        want = ("late", "มาสาย (จากการเข้าแถว)", -abs(st.auto_late))
    elif rec and rec.status == "skip" and st.auto_skip:
        want = ("skip", "โดดแถว (จากการเข้าแถว)", -abs(st.auto_skip))
    old = (db.query(BehaviorRecord)
           .filter(BehaviorRecord.student_id == student_id, BehaviorRecord.date == day,
                   BehaviorRecord.source.in_(("late", "skip"))).all())
    for o in old:
        if not want or o.source != want[0]:
            db.delete(o)
    if want and not any(o.source == want[0] for o in old):
        add(db, year=year, student_id=student_id, points=want[2], label=want[1], day=day,
            source=want[0], by_name="ระบบ (จากการเข้าแถว)")
