"""Build a gap-free, de-speckled unit raster from the scanned map."""
import numpy as np, json, sys
from PIL import Image
from scipy import ndimage
Image.MAX_IMAGE_PIXELS = None

PAL  = json.load(open('work/palette.json'))
RGBS = np.array([p['rgb'] for p in PAL])
A    = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int64)
B    = A[189:3524, 189:4274]
lab_raw = np.load('work/lab_raw.npy')
dist    = np.load('work/dist.npy')
H, W = lab_raw.shape
mx, mn = B.max(axis=2), B.min(axis=2)
PAPER, UNK = 201, 0

ink   = mx < 100
paper = (mn >= 232) & ((mx - mn) <= 12)
conf  = (~ink) & (~paper) & (dist <= 26)
n = lab_raw.size
print(f'confident {100*conf.mean():.2f}%   ink {100*ink.mean():.2f}%   '
      f'paper {100*paper.mean():.2f}%   unknown {100*(~conf&~paper).mean():.2f}%', flush=True)
for i, c in enumerate(RGBS):
    if c.min() >= 232 and (c.max()-c.min()) <= 12:
        print('  !! palette colour looks like paper:', i+1, PAL[i]['code'], c)

lab = np.where(conf, lab_raw.astype(np.int32) + 1, UNK)
lab[paper] = PAPER

def drop_small(lab, min_area):
    for c in np.unique(lab):
        if c in (PAPER, UNK): continue
        m = lab == c
        l, k = ndimage.label(m)
        if k == 0: continue
        sz = np.bincount(l.ravel())
        bad = np.where(sz < min_area)[0]; bad = bad[bad > 0]
        if bad.size: lab[np.isin(l, bad)] = UNK
    return lab

def edt_fill(lab):
    known = lab > 0
    if known.all(): return lab
    idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    out = lab.copy()
    u = ~known
    out[u] = lab[idx[0][u], idx[1][u]]
    return out

def majority(lab, moveable, win=9, minfrac=0.34):
    best  = np.zeros(lab.size, np.int32); bestf = np.zeros(lab.size, np.float32)
    mv = moveable.ravel()
    for c in np.unique(lab):
        if c in (PAPER, UNK): continue
        f = ndimage.uniform_filter((lab == c).astype(np.float32), size=win, mode='nearest').ravel()
        m = (f > bestf) & mv
        bestf[m] = f[m]; best[m] = c
    out = lab.copy()
    sel = (mv & (bestf >= minfrac)).reshape(lab.shape)
    out[sel] = best.reshape(lab.shape)[sel]
    return out

lab = edt_fill(drop_small(lab, 40))
lab = edt_fill(drop_small(lab, 90))
np.save('work/lab_s1.npy', lab.astype(np.uint16))

lab2 = majority(lab, ~conf, win=9, minfrac=0.34)
lab2[conf] = lab_raw[conf].astype(np.int32) + 1; lab2[paper] = PAPER
lab2 = edt_fill(drop_small(lab2, 120))
lab2 = edt_fill(drop_small(lab2, 200))
np.save('work/lab_clean.npy', lab2.astype(np.uint16))

for tag, L in (('stage1', lab), ('clean', lab2)):
    uv, uc = np.unique(L, return_counts=True)
    print(f'\n{tag}: {len(uv)} classes, unknown={int((L==0).sum())}')
    for v, c in sorted(zip(uv, uc), key=lambda t: -t[1])[:12]:
        code = PAL[v-1]['code'] if 1 <= v <= len(PAL) else ('PAPER' if v == PAPER else '?')
        print(f'   {v:4d} {code:12s} {100*c/n:6.3f}%')
