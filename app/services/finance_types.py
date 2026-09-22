"""Shared classification for manually created and imported finance accounts."""
FUND_TYPES = ["เงินงบประมาณ", "เงินรายได้แผ่นดิน", "เงินนอกงบประมาณ"]
FUND_DEFAULT = "เงินนอกงบประมาณ"


def resolve_fund_type(name, selected=""):
    selected = (selected or "").strip()
    name = (name or "").strip()
    return selected if selected in FUND_TYPES else (name if name in FUND_TYPES else FUND_DEFAULT)


# สีประจำหมวดเงิน (ใช้ในหน้าทะเบียนคุมเงิน ให้แยกหมวดด้วยสายตาได้เร็ว)
# g1/g2 = สีไล่ระดับของแถบหัวกลุ่ม · tint = พื้นหลังจาง ๆ ของแถวในกลุ่ม · ink = สีตัวอักษรบนพื้นจาง
FUND_COLORS = {
    "เงินงบประมาณ":      {"g1": "#2563eb", "g2": "#60a5fa", "tint": "#eff5ff", "ink": "#1d4ed8"},
    "เงินรายได้แผ่นดิน": {"g1": "#b45309", "g2": "#f59e0b", "tint": "#fff8ed", "ink": "#b45309"},
    "เงินนอกงบประมาณ":   {"g1": "#0d9488", "g2": "#5eead4", "tint": "#eefbf8", "ink": "#0f766e"},
}


def fund_color(fund_type):
    """สีของหมวดเงิน (ชื่อที่ไม่รู้จัก = ใช้สีของเงินนอกงบประมาณ)"""
    return FUND_COLORS.get((fund_type or "").strip(), FUND_COLORS[FUND_DEFAULT])
