"""ค้นหา .docx บน Desktop ที่มีรูปภาพฝังอยู่ (อาจเป็นตราครุฑ) เพื่อดึงมาใช้"""
import zipfile
from pathlib import Path

DESKTOP = Path(r"C:\Users\Lenovo_\Desktop")
found = []
for f in DESKTOP.rglob("*.docx"):
    if ".venv" in str(f) or "~$" in f.name:
        continue
    try:
        z = zipfile.ZipFile(str(f))
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        imgs = [n for n in media if n.lower().endswith((".png", ".jpeg", ".jpg", ".emf", ".wmf", ".gif"))]
        if imgs:
            sizes = [(n.split("/")[-1], z.getinfo(n).file_size) for n in imgs]
            # สนใจรูปเล็ก ๆ (ครุฑมักเล็ก < 200KB) และมีไม่กี่รูป
            small = [s for s in sizes if s[1] < 250_000]
            if small and len(imgs) <= 4:
                found.append((str(f), small))
    except Exception:
        pass

for path, sizes in found[:40]:
    print(path)
    for nm, sz in sizes:
        print(f"    {nm}  ({sz} bytes)")
print(f"\nรวม {len(found)} ไฟล์ที่มีรูปเล็กฝังอยู่")
