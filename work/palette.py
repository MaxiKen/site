import numpy as np, json
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
A = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int64)
leg = json.load(open('work/legend_rows.json'))

def swatch_halves(ys,ye):
    out=[]
    for a,b in [(5590,5613),(5613,5636)]:
        sub=A[ys:ye,a:b].reshape(-1,3)
        keep=(sub.max(axis=1)>=100)&(sub.min(axis=1)<=240)
        out.append(np.median(sub[keep],axis=0))
    return out

pal=[]   # dicts: rgb, code, name, lith, age, src
for r in leg:
    codes=[c for c in r['code'].split(' / ') if c]
    l,r2 = swatch_halves(r['y0'],r['y1'])
    if len(codes)>=2 and abs(l-r2).max()>25:
        pal.append(dict(rgb=[int(round(v)) for v in l], code=codes[0], name=r['name'], lith=r['lith'], age=r['age'], src='legend'))
        pal.append(dict(rgb=[int(round(v)) for v in r2], code=codes[1], name=r['name'], lith=r['lith'], age=r['age'], src='legend'))
    else:
        pal.append(dict(rgb=r['rgb'], code=(codes[0] if codes else ''), name=r['name'], lith=r['lith'], age=r['age'], src='legend'))
# extra classes detected on the map but absent from the printed legend
pal.append(dict(rgb=[255,120,126], code='OGp', name='Older Granite (porphyritic)',
                lith='Porphyritic biotite/hornblende granite (Pan-African Older Granite Suite)',
                age='Pan-African', src='map-label-only'))
pal.append(dict(rgb=[150,216,240], code='WATER', name='Water (ocean / lagoon / lake)',
                lith='Surface water', age='', src='not-in-legend'))
# de-duplicate near-identical colours (keep first)
keep=[]
for p in pal:
    if all(np.abs(np.array(p['rgb'])-np.array(q['rgb'])).max()>4 for q in keep):
        keep.append(p)
    else:
        for q in keep:
            if np.abs(np.array(p['rgb'])-np.array(q['rgb'])).max()<=4:
                if p['code'] and not q['code']: q['code']=p['code']
                if p['code'] and q['code'] and p['code']!=q['code']: q['code']+='/'+p['code']
                break
pal=keep
print(len(pal),'palette entries')
for i,p in enumerate(pal):
    print(f"{i:3d} {str(p['rgb']):18s} {p['code']:14s} {p['name'][:46]:46s} | {p['lith'][:44]}")
json.dump(pal, open('work/palette.json','w'), indent=1)
