"""Read variable-length committee rows, including legacy numbered fields."""
import re

PARTY_LABELS = {
    "teacher": "ผู้แทนครู", "parent": "ผู้แทนผู้ปกครอง",
    "community": "ผู้แทนชุมชน", "student": "ผู้แทนนักเรียน",
}


def read_people(form, prefix):
    indices = sorted({int(match.group(1)) for key in form
                      if (match := re.fullmatch(re.escape(prefix) + r"(\d+)_name", key))})
    rows = []
    for index in indices:
        def value(field):
            return str(form.get(f"{prefix}{index}_{field}") or "").strip()
        if value("name"):
            rows.append({"name": value("name"), "position": value("pos"),
                         "role": value("role") or "กรรมการ", "level": value("level"),
                         "kind": value("kind")})
    return rows


def read_parties(form):
    if form.get("parties_editor") == "combined":
        result = {kind: [] for kind in PARTY_LABELS}
        for row in read_people(form, "party"):
            kind = row.pop("kind")
            if kind not in result:
                raise ValueError("กรุณาเลือกฝ่ายของผู้แทนภาคี")
            result[kind].append(row)
        return result
    return {kind: read_people(form, prefix) for kind, prefix in (
        ("teacher", "pt"), ("parent", "pp"), ("community", "pc"), ("student", "ps"))}
