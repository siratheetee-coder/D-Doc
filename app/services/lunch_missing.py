"""ข้อมูลที่ยังไม่ครบ ของรอบแม่ครัว/ซื้อวัตถุดิบ (เตือนเฉยๆ ไม่บังคับ) แต่ละข้อมีลิงก์ไปช่องที่ต้องกรอก"""


def buy_missing(rnd, committees, com_kinds, doc_rows, loan, ing_total, bk_days):
    out = []
    if rnd.program.operate_mode == "person" and not rnd.vendor_id:
        out.append({"msg": "ยังไม่ได้ระบุแม่ครัว (ผู้รับจ้าง)", "href": "#round-info"})
    for k, label in dict(com_kinds).items():
        if not committees.get(k):
            out.append({"msg": "ยังไม่ได้แต่งตั้ง" + ("" if label.startswith("ผู้") else "กรรมการ") + label, "href": "#committee"})
    if not ing_total:
        out.append({"msg": "ยังไม่ได้กรอกวัตถุดิบ", "href": "#menus"})
    if loan and loan.get("loan") and not (loan["loan"].contract_no or "").strip():
        out.append({"msg": "เลขที่สัญญายืมยังว่าง", "href": "#loan"})
    n_bk = sum(1 for d in bk_days or [] if not d["no"])
    if n_bk:
        out.append({"msg": f"เลข บค. ยังไม่ได้ออก {n_bk} วัน", "href": "#bk-days"})
    gaps = [d for d in doc_rows if any(not f["value"] for f in d["fields"])]
    if gaps:
        out.append({"msg": f"เอกสาร {len(gaps)} ฉบับยังไม่มีเลขที่และวันที่ครบ", "href": f"#dn-{gaps[0]['kind']}",
                    "hl": ",".join("#dn-" + d["kind"] for d in gaps)})
    return out
