"""ค้นหารวมทุกงาน (หน้า /search และกล่องแนะนำผลระหว่างพิมพ์ในแถบบน)

- ค้นเมนู/หน้าในระบบ + ข้อมูลของโรงเรียน (เรื่องพัสดุ หนังสือ เงิน โครงการ บุคลากร นักเรียน ฯลฯ)
- พิมพ์ตัวเลข เช่น 127200 หรือ 127,200 จะค้นตามจำนวนเงินด้วย
- แสดงเฉพาะงานที่บัญชีนี้เข้าได้ (ตรรกะเดียวกับเมนูซ้าย)
"""
from sqlalchemy import or_

from app.modules import MODULE_LABELS

# เมนู/หน้า: (ชื่อ, ลิงก์, งาน หรือ None = หน้าระบบ, คำค้นเพิ่ม)
PAGES = [
    ('หน้าหลักงานพัสดุ', '/procurement', 'procurement', 'จัดซื้อ จัดจ้าง'),
    ('สร้างเรื่องจัดซื้อ/จัดจ้างใหม่', '/procurement/new', 'procurement', 'ซื้อ จ้าง เพิ่มเรื่อง'),
    ('สร้างเรื่องจากไฟล์ใบเสนอราคา', '/procurement/from-file', 'procurement', 'pdf อ่านไฟล์ ใบเสนอราคา'),
    ('แผนการจัดซื้อจัดจ้าง', '/procurement/plan', 'procurement', 'แผนจัดซื้อ'),
    ('ทะเบียนคุมสัญญา', '/procurement/contracts', 'procurement', 'สัญญา ใบสั่ง'),
    ('ครุภัณฑ์', '/assets', 'procurement', 'ทะเบียนครุภัณฑ์'),
    ('ตรวจนับครุภัณฑ์', '/assets/audit', 'procurement', 'ตรวจสอบพัสดุประจำปี'),
    ('จำหน่ายครุภัณฑ์', '/assets/disposal', 'procurement', 'ชำรุด แทงจำหน่าย'),
    ('วัสดุคงคลัง', '/materials', 'procurement', 'บัญชีวัสดุ'),
    ('เบิกวัสดุ', '/requisitions', 'procurement', 'ใบเบิก'),
    ('หนังสือเรียน', '/textbooks', 'procurement', 'ซื้อหนังสือเรียน'),
    ('หน้าหลักงานธุรการ', '/admin', 'admin', 'สารบรรณ'),
    ('หนังสือรับ', '/admin/incoming', 'admin', 'ทะเบียนหนังสือรับ'),
    ('บัญชีครูและอีเมล', '/admin/staff-accounts', 'admin', 'สร้างบัญชีครู อีเมลครู เวียนหนังสือ'),
    ('หนังสือส่ง', '/admin/outgoing', 'admin', 'ทะเบียนหนังสือส่ง'),
    ('บันทึกข้อความ', '/admin/memos', 'admin', 'บันทึก'),
    ('คำสั่งโรงเรียน', '/admin/orders', 'admin', 'คำสั่ง แต่งตั้ง'),
    ('หนังสือภายนอก', '/admin/letters', 'admin', 'หนังสือราชการ'),
    ('เกียรติบัตร', '/admin/certificates', 'admin', 'วุฒิบัตร'),
    ('หน้าหลักงานการเงิน', '/finance', 'finance', 'การเงิน'),
    ('ทะเบียนคุมเงิน', '/finance/accounts', 'finance', 'บัญชี ยอดยกมา ยกยอด'),
    ('ทะเบียนคุมโครงการ', '/finance/projects', 'finance', 'โครงการ'),
    ('บันทึกขอเบิกจ่าย', '/finance/disburse', 'finance', 'เบิกจ่าย ขอเบิก'),
    ('ใบเสร็จรับเงิน', '/finance/receipts', 'finance', 'ใบเสร็จ'),
    ('สมุดเงินสด', '/finance/cashbook', 'finance', 'เงินสด'),
    ('เงินคงเหลือประจำวัน', '/finance/cash-report', 'finance', 'รายงานเงินคงเหลือ'),
    ('เงินยืม', '/finance/loans', 'finance', 'ลูกหนี้ สัญญายืม'),
    ('นำส่งเงินรายได้แผ่นดิน', '/finance/revenue', 'finance', 'รายได้แผ่นดิน ดอกเบี้ย ส่งคลัง'),
    ('ทะเบียนคุมเช็ค', '/finance/checks', 'finance', 'เช็ค'),
    ('งบกระทบยอดธนาคาร', '/finance/bank-recon', 'finance', 'ธนาคาร กระทบยอด'),
    ('รายงานการเงิน', '/finance/report', 'finance', 'รายงาน'),
    ('คำนวณเงินอุดหนุน', '/finance/subsidy', 'finance', 'อุดหนุน รายหัว DMC'),
    ('e-Budget', '/finance/ebudget', 'finance', 'อีบัดเจ็ท'),
    ('ตรวจสุขภาพข้อมูลการเงิน', '/finance/health', 'finance', 'ตรวจ ผิดปีงบ'),
    ('เรื่องพัสดุที่ทำก่อนเริ่มใช้ระบบและจ่ายไปแล้ว', '/finance/paid-before', 'finance', 'จ่ายแล้วก่อนเริ่มใช้ระบบ'),
    ('อาหารกลางวัน', '/lunch', 'lunch', 'อาหาร'),
    ('ตั้งค่าอาหารกลางวัน', '/lunch/setup', 'lunch', 'วัตถุดิบ แม่ครัว'),
    ('หน้าหลักงานบุคคล', '/hr', 'hr', 'บุคลากร'),
    ('คำขอลา', '/hr/leave-requests', 'hr', 'ใบลา ลาป่วย ลากิจ'),
    ('คำขอไปราชการ', '/hr/travel-requests', 'hr', 'ไปราชการ'),
    ('หน้าหลักงานวิชาการ', '/academic', 'academic', 'วิชาการ'),
    ('ห้องเรียน', '/academic/classes', 'academic', 'ชั้นเรียน ครูประจำชั้น'),
    ('รายวิชา', '/academic/subjects', 'academic', 'วิชา'),
    ('กำหนดครูผู้สอน', '/academic/assign-teachers', 'academic', 'ครูสอน'),
    ('เวลาเรียน', '/academic/attendance', 'academic', 'เช็กชื่อ'),
    ('ตารางเรียน', '/academic/timetable', 'academic', 'ตารางสอน'),
    ('ปพ.5 คะแนนและเกรด', '/academic/grades', 'academic', 'คะแนน เกรด ปพ5'),
    ('ปพ.6 ประเมิน', '/academic/eval', 'academic', 'ปพ6'),
    ('ปพ.7 ใบรับรองผลการเรียน', '/academic/pp7', 'academic', 'ปพ7'),
    ('แผนการสอน', '/academic/lesson-plans', 'academic', 'แผน'),
    ('นิเทศภายใน', '/academic/supervision', 'academic', 'นิเทศ'),
    ('บัญชีครู', '/academic/teacher-accounts', 'academic', 'ไอดีครู'),
    ('งานบริหารทั่วไป', '/general', None, ''),
    ('บันทึกการมาเรียน', '/general/arrival', None, 'มาเรียน'),
    ('โครงการ/แผนงบ', '/projects', None, 'โครงการ แผนปฏิบัติการ'),
    ('ผู้ขาย/ผู้รับจ้าง', '/vendors', None, 'ร้านค้า'),
    ('บุคลากร/ฝ่าย', '/masters', None, 'ครู ผู้ลงนาม ลายเซ็น'),
    ('ข้อมูลนักเรียน', '/students', None, 'นักเรียน'),
    ('ตั้งค่าโรงเรียน', '/settings', None, 'ผอ. โลโก้ ปีการศึกษา'),
    ('จัดการผู้ใช้', '/users', None, 'ไอดี รหัสผ่าน'),
    ('ทะเบียนเลขหนังสือ', '/docnos', None, 'เลขที่หนังสือ'),
    ('วิธีใช้งาน', '/guide', None, 'คู่มือ วิดีโอ'),
]

MOD_SHORT = {'procurement': 'พัสดุ', 'admin': 'ธุรการ', 'finance': 'การเงิน', 'lunch': 'อาหารกลางวัน',
             'hr': 'บุคคล', 'academic': 'วิชาการ', None: 'ระบบ'}


def allowed_modules(session, tid) -> set:
    """งานที่บัญชีนี้เปิดได้ (ซื้อแล้ว/ยังมีโควตา และได้รับสิทธิ์) เหมือนเมนูซ้าย"""
    from app.templating import can_use
    mods = set((session.get('mods') or '').split(','))
    everything = session.get('owner') or session.get('director')
    return {k for k in MODULE_LABELS if can_use(tid, k) and (everything or k in mods)}


def _money(q):
    s = q.replace(',', '').replace('บาท', '').strip()
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _fmt(v):
    return '{:,.2f}'.format(v or 0)


def _d(x):
    try:
        from app.templating import thai_date_short
        return thai_date_short(x) if x else ''
    except Exception:  # noqa: BLE001
        return ''


def search(db, q, allowed, limit=20, data=True):
    """คืน [dict(label, mod, items=[dict(title, sub, url)])] ตามลำดับความสำคัญ
    data=False ค้นแค่เมนู (บัญชีครูไม่เห็นข้อมูลทั้งโรงเรียน)"""
    from app import models as m
    q = (q or '').strip()
    if not q:
        return []
    like, amt, out = f'%{q}%', _money(q), []

    def add(label, mod, items):
        if items and (mod in (None, 'page') or mod in allowed):
            out.append(dict(label=label, mod=mod, items=items))

    ql = q.lower()
    add('เมนูและหน้าในระบบ', 'page', [dict(title=t, sub=MOD_SHORT[mod], url=u) for t, u, mod, kw in PAGES
        if (mod is None or mod in allowed) and (ql in t.lower() or ql in kw.lower())][:limit])
    if data is False:
        return out

    def amount_or(col, *cols):
        conds = [c.ilike(like) for c in cols]
        if amt is not None and col is not None:
            conds.append(col.between(amt - 0.005, amt + 0.005))
        return or_(*conds)

    # ---- พัสดุ ----
    if 'procurement' in allowed:
        P = m.Procurement
        rows = (db.query(P).outerjoin(P.vendor)
                .filter(amount_or(P.total_amount, P.subject, P.memo_no, P.order_no, m.Vendor.name))
                .order_by(P.id.desc()).limit(limit).all())
        add('เรื่องจัดซื้อจัดจ้าง', 'procurement', [dict(
            title=f"{p.memo_no or p.order_no or '-'} {p.proc_type or ''}{p.subject or ''}",
            sub=' | '.join(x for x in [p.vendor.name if p.vendor else '', p.status or '', _fmt(p.total_amount) + ' บาท'] if x),
            url=f'/procurement/{p.id}') for p in rows])
        C = m.Contract
        rows = db.query(C).filter(amount_or(None, C.contract_no, C.party, C.subject)).order_by(C.id.desc()).limit(limit).all()
        add('สัญญา', 'procurement', [dict(title=f'{c.contract_no or "-"} {c.subject or ""}', sub=c.party or '',
            url=f'/procurement/contracts?year={c.fiscal_year}') for c in rows])
        A = m.Asset
        rows = db.query(A).filter(or_(A.name.ilike(like), A.asset_code.ilike(like))).order_by(A.id.desc()).limit(limit).all()
        add('ครุภัณฑ์', 'procurement', [dict(title=f'{a.asset_code or "-"} {a.name}', sub=a.category or '', url='/assets') for a in rows])
        rows = db.query(m.MaterialItem).filter(m.MaterialItem.name.ilike(like)).order_by(m.MaterialItem.name).limit(limit).all()
        add('วัสดุ', 'procurement', [dict(title=i.name, sub=i.unit or '', url=f'/materials/{i.id}') for i in rows])

    # ---- ธุรการ ----
    if 'admin' in allowed:
        M = m.OfficeMemo
        rows = db.query(M).filter(or_(M.subject.ilike(like), M.memo_no.ilike(like))).order_by(M.id.desc()).limit(limit).all()
        add('บันทึกข้อความ', 'admin', [dict(title=f'{r.memo_no or "-"} {r.subject or ""}', sub=r.to_person or '', url=f'/admin/memos/{r.id}') for r in rows])
        O = m.SchoolOrder
        rows = db.query(O).filter(or_(O.subject.ilike(like), O.order_no.ilike(like))).order_by(O.id.desc()).limit(limit).all()
        add('คำสั่งโรงเรียน', 'admin', [dict(title=f'{r.order_no or "-"} {r.subject or ""}', sub='', url=f'/admin/orders/{r.id}') for r in rows])
        I = m.IncomingLetter
        rows = (db.query(I).filter(or_(I.subject.ilike(like), I.letter_no.ilike(like), I.from_org.ilike(like)))
                .order_by(I.id.desc()).limit(limit).all())
        add('หนังสือรับ', 'admin', [dict(title=f'รับที่ {r.recv_no} {r.subject or ""}',
            sub=' | '.join(x for x in [r.letter_no or '', r.from_org or ''] if x), url='/admin/incoming') for r in rows])
        G = m.OutgoingLetter
        rows = (db.query(G).filter(or_(G.subject.ilike(like), G.send_no.ilike(like), G.to_org.ilike(like)))
                .order_by(G.id.desc()).limit(limit).all())
        add('หนังสือส่ง', 'admin', [dict(title=f'{r.send_no or "-"} {r.subject or ""}', sub=r.to_org or '', url='/admin/outgoing') for r in rows])
        L = m.OfficialLetter
        rows = (db.query(L).filter(or_(L.subject.ilike(like), L.doc_no.ilike(like), L.to.ilike(like)))
                .order_by(L.id.desc()).limit(limit).all())
        add('หนังสือภายนอก', 'admin', [dict(title=f'{r.doc_no or "-"} {r.subject or ""}', sub=r.to or '', url=f'/admin/letters/{r.id}') for r in rows])

    # ---- การเงิน ----
    if 'finance' in allowed:
        D = m.DisburseMemo
        rows = (db.query(D).filter(amount_or(D.amount, D.subject, D.memo_no, D.payee))
                .order_by(D.id.desc()).limit(limit).all())
        add('บันทึกขอเบิกจ่าย', 'finance', [dict(title=f'{d.memo_no or "-"} {d.subject or ""}',
            sub=f'{d.payee or ""} | {_fmt(d.amount)} บาท', url=f'/finance/disburse/{d.id}') for d in rows])
        T = m.FinanceTxn
        rows = (db.query(T).filter(amount_or(T.amount, T.category, T.ref, T.note))
                .order_by(T.date.desc(), T.id.desc()).limit(limit).all())
        add('รายการรับ-จ่ายในทะเบียนคุมเงิน', 'finance', [dict(
            title=f'{"รับ" if t.kind == "in" else "จ่าย"} {_fmt(t.amount)} บาท {t.note or t.category or ""}'.strip(),
            sub=' | '.join(x for x in [_d(t.date), t.ref or '', f'ปีงบ {t.fiscal_year}'] if x),
            url=f'/finance/accounts/{t.account_id}?year={t.fiscal_year}#t{t.id}') for t in rows])
        R = m.Receipt
        rows = db.query(R).filter(amount_or(R.amount, R.receipt_no, R.party, R.note)).order_by(R.id.desc()).limit(limit).all()
        add('ใบเสร็จรับเงิน', 'finance', [dict(title=f'เลขที่ {r.receipt_no or "-"} {r.party or ""}',
            sub=f'{_d(r.date)} | {_fmt(r.amount)} บาท', url=f'/finance/receipts?year={r.fiscal_year}') for r in rows])
        N = m.MoneyLoan
        rows = (db.query(N).filter(amount_or(N.amount, N.contract_no, N.borrower, N.purpose))
                .order_by(N.id.desc()).limit(limit).all())
        add('เงินยืม', 'finance', [dict(title=f'สัญญา {r.contract_no or "-"} {r.borrower or ""}',
            sub=f'{r.purpose or ""} | {_fmt(r.amount)} บาท', url=f'/finance/loans?year={r.fiscal_year}') for r in rows])

    # ---- บุคคล ----
    if 'hr' in allowed:
        V = m.LeaveRequest
        rows = (db.query(V).join(m.Person, m.Person.id == V.person_id)
                .filter(or_(m.Person.name.ilike(like), V.leave_type.ilike(like), V.reason.ilike(like)))
                .order_by(V.id.desc()).limit(limit).all())
        add('คำขอลา', 'hr', [dict(title=f'{r.leave_type or "ลา"} {db.get(m.Person, r.person_id).name}',
            sub=r.status or '', url=f'/hr/leave-requests/{r.id}') for r in rows])

    # ---- วิชาการ ----
    if 'academic' in allowed:
        S = m.AcadSubject
        rows = db.query(S).filter(or_(S.name.ilike(like), S.code.ilike(like))).order_by(S.id.desc()).limit(limit).all()
        add('รายวิชา', 'academic', [dict(title=f'{s.code or ""} {s.name}'.strip(), sub=s.level or '', url='/academic/subjects') for s in rows])

    # ---- ข้อมูลกลาง (ทุกงานใช้ร่วม) ----
    J = m.Project
    rows = db.query(J).filter(or_(J.name.ilike(like), J.responsible.ilike(like))).order_by(J.id.desc()).limit(limit).all()
    add('โครงการ', None, [dict(title=p.name, sub=' | '.join(x for x in [p.responsible or '', f'ปี {p.plan_year}' if p.plan_year else ''] if x),
        url=f'/projects/{p.id}') for p in rows])
    Vd = m.Vendor
    rows = db.query(Vd).filter(or_(Vd.name.ilike(like), Vd.tax_id.ilike(like), Vd.owner_name.ilike(like))).order_by(Vd.name).limit(limit).all()
    add('ผู้ขาย/ผู้รับจ้าง', None, [dict(title=v.name, sub=v.tax_id or '', url='/vendors') for v in rows])
    Pe = m.Person
    rows = db.query(Pe).filter(or_(Pe.name.ilike(like), Pe.position.ilike(like))).order_by(Pe.name).limit(limit).all()
    add('บุคลากร', None, [dict(title=p.name, sub=p.position or '', url=f'/hr/staff/{p.id}' if 'hr' in allowed else '/masters') for p in rows])
    St = m.Student
    rows = db.query(St).filter(or_(St.name.ilike(like), St.student_no.ilike(like))).order_by(St.name).limit(limit).all()
    add('นักเรียน', None, [dict(title=s.name, sub=' '.join(x for x in [s.student_no and f'เลขประจำตัว {s.student_no}', s.level and f'{s.level}/{s.room or ""}'] if x),
        url=f'/students/{s.id}') for s in rows])
    return out
