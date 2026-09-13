"""Shared classification for manually created and imported finance accounts."""
FUND_TYPES = ["เงินงบประมาณ", "เงินรายได้แผ่นดิน", "เงินนอกงบประมาณ"]
FUND_DEFAULT = "เงินนอกงบประมาณ"


def resolve_fund_type(name, selected=""):
    selected = (selected or "").strip()
    name = (name or "").strip()
    return selected if selected in FUND_TYPES else (name if name in FUND_TYPES else FUND_DEFAULT)
