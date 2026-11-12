from datetime import datetime, timedelta
from sqlalchemy import func, or_, and_
from sqlalchemy.orm import selectinload
from app.models import Approval, IncomingLetter, LetterRecipient
from app.services import approval as ap

UPDATES=[dict(date='9 พ.ย. 2569',title='หน้าหลักแยกตามบทบาท',text='แอดมินติดตามภาพรวม ครูเห็นหนังสือและงานที่ส่งถึงตนเอง'),dict(date='8 พ.ย. 2569',title='เทียบวันที่งวดอาหารกลางวัน',text='แยกสีวันเดิมกับวันตามปฏิทิน พร้อมปุ่มแก้วันสิ้นสุดรอบเมื่อจำเป็น'),dict(date='7 พ.ย. 2569',title='แจ้งผลอนุมัติถึงบัญชีผู้ส่ง',text='แจ้งผ่านกระดิ่ง และอีเมลเมื่อมีอีเมลผู้ส่งและตั้งค่าการส่งพร้อมใช้งาน')]
GROUPS={'พัสดุ':'procurement','การเงิน':'finance','ธุรการ':'admin','โครงการ':'projects','อาหารกลางวัน':'lunch'}

def approvals(db,sess,allowed):
    latest=db.query(func.max(Approval.id)).group_by(Approval.kind,Approval.ref_id)
    q=db.query(Approval).filter(Approval.id.in_(latest),Approval.status.in_(['pending','approved','returned']))
    personal=not sess.get('owner')
    if personal:
        filters=[Approval.sent_uid==sess.get('uid')]
        if sess.get('person_id'):filters.append(and_(Approval.sent_uid.is_(None),Approval.sent_pid==sess['person_id']))
        q=q.filter(or_(*filters))
    result={k:[] for k in ('pending','approved','returned','stale')}
    for a in q.order_by(Approval.sent_at.desc()).all():
        spec=ap.KINDS.get(a.kind)
        if not spec or (not personal and spec['group']!='โครงการ' and GROUPS.get(spec['group']) not in allowed):continue
        obj=spec['get'](db,a.ref_id)
        if obj is None:continue
        state=ap.state(db,a.kind,a.ref_id,obj)['code']
        code='approved' if state in ('approved','signed') else state
        if code not in result:continue
        if code=='approved' and (not a.decided_at or a.decided_at<datetime.now()-timedelta(days=7)):continue
        result[code].append(dict(title=a.title,href=f'/approvals/doc/{a.id}',group=spec['group']))
    return result

def build(db,sess):
    from app.models import School
    from app.thai_utils import current_fiscal_year,current_academic_year
    from app.services.search import allowed_modules
    from app.services.letter_tracking import overdue
    allowed=allowed_modules(sess,sess.get('tid'))
    teacher=bool(sess.get('person_id')) and not sess.get('owner')
    school=db.query(School).first()
    result=dict(fiscal_year=current_fiscal_year(),academic_year=(school.academic_year if school else None) or current_academic_year(),teacher=teacher,allowed=allowed,updates=UPDATES,actions=[],letters=[],letter_counts=[],approval=approvals(db,sess,allowed))
    if teacher:
        from app.models import Person
        from app.services.nav import my_notices
        person=db.get(Person,sess['person_id'])
        result['name']=person.name if person else 'คุณครู'
        result['personal_notices']=my_notices(sess['person_id'],sess.get('uid'))[:5]
        rows=(db.query(LetterRecipient).options(selectinload(LetterRecipient.letter),selectinload(LetterRecipient.task))
              .join(IncomingLetter).filter(LetterRecipient.person_id==sess['person_id'],IncomingLetter.route_status=='sent').order_by(LetterRecipient.id.desc()).all())
        pending=[r for r in rows if not r.ack_at]
        tasks=[r for r in rows if r.task and r.task.status in ('pending','returned')]
        late=[r for r in tasks if overdue(r.task)]
        result['letter_counts']=[('หนังสือรอรับทราบ',len(pending)),('งานรอรายงานผล',len(tasks)),('งานเลยกำหนด',len(late))]
        for r in sorted(rows,key=lambda r:(not overdue(r.task) if r.task else True,r.ack_at is not None,-r.id)):
            if r.ack_at and r not in tasks:continue
            result['letters'].append(dict(title=r.letter.subject,href=f'/me/letters/{r.id}',tag='เลยกำหนดรายงาน' if r in late else 'รอรายงานผล' if r in tasks else 'รอรับทราบ',note=r.task.instruction if r.task else r.letter.from_org))
        result['letters']=result['letters'][:6]
        from app.services import teacher_home
        result['th']=teacher_home.build(db,sess['person_id'],year=result['academic_year'],letters=result['letters'],
                                        letter_pending=len(pending))
        from app.services import teacher_home_acad
        result['ta']=teacher_home_acad.build(db,sess['person_id'])
    elif 'admin' in allowed:
        rows=db.query(IncomingLetter).options(selectinload(IncomingLetter.recipients).selectinload(LetterRecipient.task)).all()
        waiting=[r for r in rows if r.route_status=='director']
        unacked=[r for r in rows if r.route_status=='sent' and any(not c.ack_at for c in r.recipients)]
        late=[r for r in rows if r.route_status=='sent' and any(c.task and overdue(c.task) for c in r.recipients)]
        draft=[r for r in rows if r.route_status=='' and r.recipients]
        result['letter_counts']=[('รอ ผอ. สั่งการ',len(waiting)),('ยังมีผู้ไม่รับทราบ',len(unacked)),('เลยกำหนดรายงานผล',len(late))]
        for title,items in [('หนังสือรับรอเสนอหรือส่งต่อ',draft),('หนังสือรับรอ ผอ. สั่งการ',waiting),('หนังสือที่ยังมีผู้ไม่รับทราบ',unacked),('หนังสือเลยกำหนดรายงานผล',late)]:
            if items:result['actions'].append(dict(title=title,count=len(items),href='/home/letters?group='+('draft' if items is draft else 'waiting' if items is waiting else 'unacked' if items is unacked else 'overdue')))
        result['letter_groups']=dict(draft=draft,waiting=waiting,unacked=unacked,overdue=late)
    if not teacher:
        from app.services.nav import nav_alerts
        result['alerts']=nav_alerts(sess)
    else:result['alerts']=[]
    return result
