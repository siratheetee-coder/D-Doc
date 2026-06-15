"""ดึงรูปจาก .docx ออกมาดู"""
import zipfile, sys, shutil
from pathlib import Path

src = Path(sys.argv[1])
member = sys.argv[2]                       # เช่น word/media/image1.jpeg
out = Path(sys.argv[3])                     # ที่บันทึก

z = zipfile.ZipFile(str(src))
with z.open(member) as f, open(out, "wb") as o:
    shutil.copyfileobj(f, o)
print("extracted ->", out, out.stat().st_size, "bytes")
