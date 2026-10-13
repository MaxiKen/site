import numpy as np
from PIL import Image
from scipy import ndimage
from collections import Counter
Image.MAX_IMAGE_PIXELS=None

a = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int16)
LX0,LX1,LY0,LY1 = 4285, 6300, 185, 3510
reg = a[LY0:LY1, LX0:LX1]
# median filter to kill jpeg noise
reg = ndimage.median_filter(reg, size=(3,3,1))
h,w,_ = reg.shape
mx=reg.max(axis=2); mn=reg.min(axis=2); sat=mx-mn
bg = (mn>232) | (mx<95) | ((sat<22)&(mx>=95)&(mn<=232))
Q = 5
q = (reg//Q)
key = q[:,:,0]*10000 + q[:,:,1]*100 + q[:,:,2]
key2 = np.where(bg, -1, key)
c = Counter(key2[~bg].ravel().tolist())
sw=[]
for k,v in c.most_common(400):
    if v < 400: continue
    m = (key2==k)
    m = ndimage.binary_closing(m, structure=np.ones((5,5)))
    m = ndimage.binary_fill_holes(m)
    lab,n = ndimage.label(m)
    if n==0 or n>400: continue
    objs = ndimage.find_objects(lab)
    sizes = ndimage.sum(m,lab,range(1,n+1))
    for i,sl in enumerate(objs):
        ar=sizes[i]
        if ar<400: continue
        hh=sl[0].stop-sl[0].start; ww=sl[1].stop-sl[1].start
        if ww<18 or hh<9: continue
        fill=ar/(hh*ww)
        if fill<0.80: continue
        comp=(lab[sl]==i+1)
        px=reg[sl][comp]
        med=np.median(px,axis=0)
        sw.append(dict(x=sl[1].start+LX0, y=sl[0].start+LY0, w=ww, h=hh, area=int(ar),
                       fill=round(float(fill),3), rgb=(int(med[0]),int(med[1]),int(med[2])), npx=int(ar)))
# dedupe overlaps (keep larger)
sw.sort(key=lambda s:-s['area'])
kept=[]
for s in sw:
    ok=True
    for t in kept:
        ox = min(s['x']+s['w'], t['x']+t['w']) - max(s['x'], t['x'])
        oy = min(s['y']+s['h'], t['y']+t['h']) - max(s['y'], t['y'])
        if ox>0 and oy>0:
            inter = ox*oy
            if inter > 0.5*min(s['area'], t['area']): ok=False; break
    if ok: kept.append(s)
kept.sort(key=lambda s:(s['y'], s['x']))
print('swatches:', len(kept))
for s in kept:
    print(f"x={s['x']:4d} y={s['y']:4d} w={s['w']:3d} h={s['h']:3d} area={s['area']:6d} fill={s['fill']} rgb={s['rgb']}")
import json
json.dump(kept, open('work/swatches.json','w'), indent=1)
