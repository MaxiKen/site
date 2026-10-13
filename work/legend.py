import numpy as np, json
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
A = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int64)
OCR = json.load(open('work/legend_ocr.json'))

def swatch_bands(x0,x1,y0,y1,minlen=12,gap=3):
    col = np.median(A[y0:y1, x0:x1], axis=1)
    mx=col.max(axis=1); mn=col.min(axis=1)
    ok = (mx>=70) & (mn<=236)
    out=[];s=None
    for i,v in enumerate(ok):
        if v and s is None: s=i
        elif not v and s is not None:
            if i-s>=minlen: out.append([s+y0,i+y0])
            s=None
    if s is not None and len(ok)-s>=minlen: out.append([s+y0,len(ok)+y0])
    m=[]
    for b in out:
        if m and b[0]-m[-1][1] <= gap: m[-1][1]=b[1]
        else: m.append(b)
    return [b for b in m if b[1]-b[0]>=16]

def swatch_color(x0,x1,ys,ye):
    sub=A[ys:ye,x0:x1].reshape(-1,3)
    keep=(sub.max(axis=1)>=100)&(sub.min(axis=1)<=240)
    if keep.sum()<30: keep=np.ones(len(sub),bool)
    return np.median(sub[keep],axis=0), int(keep.sum()), len(sub)

def text(y0,y1,x0,x1):
    c=[t for cx,cy,t,s in OCR if y0-3<=cy<=y1+3 and x0<=cx<=x1]
    return ' / '.join(dict.fromkeys(c))

rows=[]
for ys,ye in swatch_bands(5590,5636,190,3510):
    c,n,tot=swatch_color(5590,5636,ys,ye)
    rec=dict(y0=ys,y1=ye,rgb=[int(round(v)) for v in c],kept=f'{n}/{tot}',
             code=text(ys,ye,5570,5650), lith=text(ys,ye,5640,5920),
             name=text(ys,ye,5940,6340), age=text(ys,ye,5300,5540))
    rows.append(rec)
print(len(rows),'rows')
for r in rows:
    print(f"{r['y0']:4d}-{r['y1']:4d} {str(r['rgb']):18s} {r['kept']:>9s} | {r['age'][:24]:24s} | {r['code'][:12]:12s} | {r['name'][:32]:32s} | {r['lith'][:34]}")
json.dump(rows, open('work/legend_rows.json','w'), indent=1)
