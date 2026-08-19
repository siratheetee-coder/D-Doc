# -*- coding: utf-8 -*-
"""ดึงตัวชี้วัดหลักสูตรแกนกลาง 2551 จาก .doc -> app/data/curriculum/<กลุ่มสาระ>.json
ใช้: .venv/Scripts/python.exe tools/extract_indicators.py <อักษร> <ชื่อกลุ่มสาระ>
เช่น:  ... ว วิทยาศาสตร์และเทคโนโลยี
"""
import pythoncom, win32com.client as win32, time, re, json, os, sys
pythoncom.CoInitialize()
SRC=r'C:\Users\Lenovo_\Desktop\หลักสูตรแกนกลาง.doc'
OUT=r'C:\Users\Lenovo_\Desktop\งานระบบพัสดุ\app\data\curriculum'
TH='๐๑๒๓๔๕๖๗๘๙'
def th2ar(s): return ''.join(str(TH.index(c)) if c in TH else c for c in s)
def pc(x): return re.sub(r'\s+',' ',x.replace('\x07',' ').replace('\a',' ')).strip()
def clean_item(seg):
    parts=re.split(r'[\r\x0b]', seg)
    j=''.join(p.strip() for p in parts).replace('\x07','').replace('\a','')
    return re.sub(r' +',' ',j).strip()
def _thnum(n): return ''.join(TH[int(d)] for d in str(n))
BREAK=set('\r\x0b\x07\a')
def _find_marker(cell, n, start):
    """ตำแหน่งเลขข้อ n (เลขไทย) ตามด้วย '.' หรือช่องว่าง และ *ขึ้นต้นบรรทัด*
    (หน้าเลข-ข้ามช่องว่าง-ต้องเป็นตัวขึ้นบรรทัด/ต้น cell) กันเลขที่อยู่กลางประโยค
    และกัน ๑๐ ไปชน ๑ · คืน (pos, marker_len) หรือ (-1,0)"""
    num=_thnum(n)
    for m in re.finditer(re.escape(num)+r'[.\s]', cell):
        i=m.start()
        if i<start: continue
        if i>0 and cell[i-1] in TH: continue          # เป็นส่วนของเลขหลายหลัก
        j=i-1
        while j>=0 and cell[j] in ' \t': j-=1
        if j<0 or cell[j] in BREAK:                    # ขึ้นต้นบรรทัด/ต้น cell เท่านั้น
            return i, (m.end()-i)
    return -1,0
def split_raw(cell):
    segs=[]; n=1
    i,ml=_find_marker(cell,1,0)
    if i<0: return segs
    while True:
        jx,_=_find_marker(cell,n+1,i+ml)
        segs.append(cell[i+ml:(jx if jx>=0 else len(cell))])
        if jx<0: break
        i=jx; ml=_find_marker(cell,n+1,jx)[1]; n+=1
    return segs
GRADE={'ป.๑':'ป.1','ป.๒':'ป.2','ป.๓':'ป.3','ป.๔':'ป.4','ป.๕':'ป.5','ป.๖':'ป.6','ม.๑':'ม.1','ม.๒':'ม.2','ม.๓':'ม.3'}
def ct(t,r,c):
    try: return t.Cell(r,c).Range.Text
    except Exception: return None
def row_by_colindex(t,r):
    """คืน {ColumnIndex: text} ของแถว r โดยวนเซลล์จริง (รองรับแถว merge/แบ่งหน้า
    ที่ Cell(r,c) เข้าไม่ได้) · ใช้ .ColumnIndex แมปกลับคอลัมน์เดิม"""
    out={}
    try:
        for cell in t.Rows(r).Cells:
            try: out[cell.ColumnIndex]=cell.Range.Text
            except Exception: pass
    except Exception: pass
    return out
def items_for(t,drow,c):
    cell=ct(t,drow,c) or ''
    segs=split_raw(cell)
    if not segs: return []
    r=drow+1
    if r<=t.Rows.Count:
        x=ct(t,r,c)
        if x is not None and (TH[1]+'.') not in x and re.search(r'[ก-ฮ]', x):
            segs[-1]=segs[-1]+x   # ต่อส่วนท้ายที่ถูกแบ่งข้ามหน้า (ครั้งเดียว)
    return [clean_item(s) for s in segs]
def is_grade(x): return x is not None and pc(x).replace(' ','') in GRADE
def col_levels(x):
    n=pc(x or '').replace(' ','')
    if n in GRADE: return [GRADE[n]]
    if 'ม.๔' in n: return ['ม.4','ม.5','ม.6']
    return None
def extract(d,LETTER,AREA):
    levels={}
    def add(level,std,seq,text):
        if text: levels.setdefault(level,[]).append({'code':f'{LETTER} {std} {level}/{seq}','std':f'{LETTER} {std}','seq':seq,'text':text})
    for i in range(1,d.Tables.Count+1):
        t=d.Tables(i); st=t.Range.Start
        pre=pc(d.Range(max(0,st-600),st).Text)
        m=re.findall(r'มาตรฐาน\s*([ก-ฮ])\s*([๐-๙]+\.[๐-๙]+)',pre)
        if not m or m[-1][0]!=LETTER: continue
        std=th2ar(m[-1][1]); ncol=t.Columns.Count
        # อ่านทุกแถว: แถวหัว(มีชื่อชั้น) กำหนด colmap · แถวข้อมูล ต่อ fragment ต่อคอลัมน์
        # (ตารางยาวถูกแบ่งข้ามหน้า + Word ใส่หัวซ้ำทุกหน้า -> ข้ามหัวซ้ำ, ต่อ fragment)
        colmap={}; per_col={}
        for r in range(1,t.Rows.Count+1):
            rowcells={c:ct(t,r,c) for c in range(1,ncol+1)}
            is_hdr=any(is_grade(x) for x in rowcells.values())
            is_meta=any((x and 'ตัวชี้วัด' in x) for x in rowcells.values())
            if is_hdr:
                if not colmap:
                    for c in range(1,ncol+1):
                        lv=col_levels(rowcells.get(c))
                        if lv: colmap[c]=lv
                continue                          # ข้ามแถวชื่อชั้น (หัวแรก+หัวซ้ำ)
            if is_meta: continue                  # ข้ามแถว "ตัวชี้วัดชั้นปี/ช่วงชั้น" (หัวบน)
            if not colmap: continue               # ยังไม่เจอหัว -> ข้ามแถว intro
            for c in colmap:
                x=rowcells.get(c)
                if x is not None:
                    per_col[c]=per_col.get(c,'')+x
        for c,lvls in colmap.items():
            items=[clean_item(s) for s in split_raw(per_col.get(c,''))]
            items=[it for it in items if it]
            for lv in lvls:
                for k,it in enumerate(items,1): add(lv,std,k,it)
    return levels
def scan_trunc(levels):
    bad=('ถึง','และ','ของ','ที่','ใน','โดย','เพื่อ','กับ','หรือ','เป็น','ให้','จาก','ตาม','พร้อมทั้ง','ระหว่าง')
    out=[]
    for lv,items in levels.items():
        for x in items:
            w=x['text'].split()[-1] if x['text'] else ''
            if x['text'].endswith(bad) or w in bad: out.append((x['code'],x['text'][-42:]))
    return out
if __name__=='__main__':
    LETTER,AREA=sys.argv[1],sys.argv[2]
    w=win32.DispatchEx('Word.Application'); w.Visible=False
    try:
        d=w.Documents.Open(SRC, ReadOnly=True); time.sleep(0.5)
        lv=extract(d,LETTER,AREA)
        os.makedirs(OUT,exist_ok=True)
        json.dump({'area':AREA,'levels':lv}, open(os.path.join(OUT,AREA+'.json'),'w',encoding='utf-8'), ensure_ascii=False, indent=1)
        d.Close(False)
    finally:
        w.Quit()
    print('counts:', {k:len(v) for k,v in sorted(lv.items())})
    stds=[]
    for x in lv.get('ป.6',[]) or lv.get('ม.6',[]):
        if x['std'] not in stds: stds.append(x['std'])
    print('มาตรฐาน:', stds)
    print('อาจถูกตัด:', scan_trunc(lv))
