import numpy as np, json
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
A = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int64)
leg = json.load(open('work/legend_rows.json'))

def half_med(ys,ye,a,b):
    sub=A[ys:ye,a:b].reshape(-1,3)
    keep=(sub.max(axis=1)>=100)&(sub.min(axis=1)<=240)
    return np.median(sub[keep],axis=0)

pal=[]
for r in leg:
    codes=[c for c in r['code'].split(' / ') if c]
    l,rr = half_med(r['y0'],r['y1'],5590,5613), half_med(r['y0'],r['y1'],5613,5636)
    if len(codes)>=2 and abs(l-rr).max()>25:
        for c,v in zip(codes[:2],[l,rr]):
            pal.append(dict(rgb=[int(round(x)) for x in v], code=c, name=r['name'], lith=r['lith'], age=r['age'], src='legend'))
    else:
        pal.append(dict(rgb=r['rgb'], code=(codes[0] if codes else ''), name=r['name'], lith=r['lith'], age=r['age'], src='legend'))
pal.append(dict(rgb=[255,120,126], code='OGp', name='Older Granite (porphyritic)',
                lith='Porphyritic biotite / hornblende granite (Pan-African Older Granite Suite)',
                age='Pan-African', src='map-label (absent from printed legend)'))
pal.append(dict(rgb=[150,216,240], code='WATER', name='Surface water (ocean, lagoon, lake)',
                lith='Water', age='', src='hydrography - not a rock unit'))
# mark groups of palette entries that share an indistinguishable fill colour
for i,p in enumerate(pal):
    p['amb']=''
amb=[]
for i in range(len(pal)):
    for j in range(i+1,len(pal)):
        if np.abs(np.array(pal[i]['rgb'])-np.array(pal[j]['rgb'])).max()<=6:
            pal[i]['amb'] += f"{pal[j]['code']} "; pal[j]['amb'] += f"{pal[i]['code']} "
for p in pal: p['amb']=p['amb'].strip()
print(len(pal),'entries;  ambiguous colour groups:')
seen=set()
for i,p in enumerate(pal):
    if p['amb']:
        k=tuple(sorted([p['code']]+p['amb'].split()))
        if k not in seen:
            seen.add(k); print('   ', p['rgb'], k)
json.dump(pal, open('work/palette.json','w'), indent=1)
