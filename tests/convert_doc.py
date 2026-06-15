"""แปลงไฟล์ .doc -> .docx ด้วย MS Word (COM) แล้วบันทึกไว้ในโฟลเดอร์เดียวกัน"""
import sys
import os
import win32com.client as win32

src = os.path.abspath(sys.argv[1])
dst = os.path.splitext(src)[0] + "_converted.docx"

word = win32.Dispatch("Word.Application")
word.Visible = False
try:
    doc = word.Documents.Open(src)
    # 16 = wdFormatXMLDocument (.docx)
    doc.SaveAs2(dst, FileFormat=16)
    doc.Close()
    print("converted ->", dst)
finally:
    word.Quit()
