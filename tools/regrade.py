# -*- coding: utf-8 -*-
"""
regrade.py — คิดเกรดจากคะแนนใหม่ทุกโรงเรียน (แก้เกรดที่ล็อกค้างจากบั๊กหน้ากรอกคะแนน ก่อน 3355adf)

บั๊กเดิม: หน้ากรอกคะแนนเติมเกรดที่คิดอัตโนมัติไว้ในช่อง "เลือกเกรดเอง" -> ครูแก้คะแนนแล้วกดบันทึก
เกรดไม่เปลี่ยนตาม · สคริปต์นี้คิดเกรดของทุกแถวใหม่จากคะแนนที่บันทึกไว้ (+ เกรดรายปีประถม)

ไม่แตะ:
  - เกรด ร / มส / ผ / มผ (ครูเลือกเองแน่นอน)
  - แถวที่มีเกรดแต่ไม่มีคะแนนเลย (ครูเลือกเกรดเองโดยไม่กรอกคะแนน)

ใช้:
  python tools/regrade.py            # นับอย่างเดียว ไม่เขียนอะไร (ค่าเริ่มต้น)
  python tools/regrade.py --detail   # นับ + แจกแจงรายวิชา
  python tools/regrade.py --apply    # เขียนจริง (สำรองข้อมูลก่อน: python tools/backup_all.py)
"""
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_data_dir
from app.tenancy import current_school_id, session_for
from app.models import School, AcadSubject, AcadScore, AcadAssignment
from app.services.academic import grade_of, is_secondary, SPECIAL_GRADES
from app.routers.academic import _keep_max, _term_denoms, _annual_result


def _denom(db, subj, t):
    fmax = subj.final_max if (subj.final_max or 0) > 0 else 30
    km = _keep_max(subj, db.query(AcadAssignment).filter_by(subject_id=subj.id, term=t).all())
    return (km + fmax) or 100


def regrade_school(db, apply: bool):
    """คืน (แถวภาคที่เกรดเปลี่ยน, แถวรายปีที่เปลี่ยน, รายละเอียดรายวิชา, ตัวอย่างการเปลี่ยน)"""
    n_term = n_year = 0
    per_subject = []
    moves = Counter()
    for subj in db.query(AcadSubject).all():
        sec = is_secondary(subj.level)
        terms = [subj.term if subj.term in (1, 2) else 1] if sec else [1, 2]
        rows_by = {}
        ch_term = 0
        for t in terms:
            denom = _denom(db, subj, t)
            for r in db.query(AcadScore).filter_by(subject_id=subj.id, term=t).all():
                rows_by[(r.acad_student_id, t)] = r
                old = (r.grade or "").strip()
                if old in SPECIAL_GRADES or r.grade_manual:
                    continue
                if r.score is None:
                    continue                      # ไม่มีคะแนน = ครูเลือกเกรดเอง -> ไม่แตะ
                new = grade_of(r.score * 100.0 / denom)
                if new != old:
                    moves[(old or "(ว่าง)", new)] += 1
                    ch_term += 1
                    r.grade = new
        ch_year = 0
        if not sec:
            denoms = _term_denoms(db, subj)
            ann = {x.acad_student_id: x for x in
                   db.query(AcadScore).filter_by(subject_id=subj.id, term=0).all()}
            for sid in {k[0] for k in rows_by}:
                res = _annual_result(rows_by.get((sid, 1)), rows_by.get((sid, 2)), denoms)
                row = ann.get(sid)
                old = (row.grade or "").strip() if row else ""
                new = res[1] if res else ""
                if new != old:
                    ch_year += 1
                    if res:
                        if row is None:
                            row = AcadScore(acad_student_id=sid, subject_id=subj.id, term=0)
                            db.add(row)
                        row.score, row.grade, row.grade_manual = res[0], res[1], False
                    elif row is not None:
                        row.score, row.grade = None, ""
        if ch_term or ch_year:
            per_subject.append((subj, ch_term, ch_year))
        n_term += ch_term
        n_year += ch_year
    if apply:
        db.commit()
    else:
        db.rollback()
    return n_term, n_year, per_subject, moves


def main():
    apply = "--apply" in sys.argv
    detail = "--detail" in sys.argv
    root = get_data_dir() / "schools"
    ids = sorted((p.name for p in root.iterdir() if (p / "school.db").exists()),
                 key=lambda x: (not x.isdigit(), int(x) if x.isdigit() else 0, x))
    print("โหมด:", "เขียนจริง" if apply else "นับอย่างเดียว (ไม่เขียน)")
    tot_t = tot_y = n_sch = 0
    all_moves = Counter()
    for sid in ids:
        key = int(sid) if sid.isdigit() else sid
        current_school_id.set(key)
        db = session_for(key)
        try:
            t, y, subs, moves = regrade_school(db, apply)
            if not (t or y):
                continue
            n_sch += 1
            tot_t += t; tot_y += y
            all_moves.update(moves)
            sch = db.query(School).first()
            print(f"\n[{sid}] {(sch.name if sch else '') or '-'}: เกรดรายภาค {t} แถว · เกรดรายปี {y} แถว")
            if detail:
                for subj, ct, cy in subs:
                    print(f"    {subj.year} {subj.level} {subj.code or ''} {subj.name}"
                          f" (ภาค {subj.term or '1-2'}): ภาค {ct} · รายปี {cy}")
        finally:
            db.close()
    print(f"\nรวม: {n_sch} โรงเรียน · เกรดรายภาคเปลี่ยน {tot_t} แถว · เกรดรายปีเปลี่ยน {tot_y} แถว")
    if all_moves:
        print("เกรดรายภาคเปลี่ยนจาก -> เป็น (มากสุด 15 แบบ):")
        for (a, b), n in all_moves.most_common(15):
            print(f"    {a} -> {b}: {n}")
    if not apply and (tot_t or tot_y):
        print("\nยังไม่ได้เขียนอะไร · ถ้าจะเขียนจริง: python tools/backup_all.py แล้ว python tools/regrade.py --apply")


if __name__ == "__main__":
    main()
