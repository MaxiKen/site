"""Full cleanup: de-speckle, strip the printed road/rail overlay, fill every gap."""
import numpy as np, json, os
from PIL import Image
from scipy import ndimage
Image.MAX_IMAGE_PIXELS = None

PAL = json.load(open('work/palette.json'))
RGBS = np.array([p['rgb'] for p in PAL])
A = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int64)
B = A[189:3524, 189:4274]
lab_raw = np.load('work/lab_raw.npy')
dist    = np.load('work/dist.npy')
H, W = lab_raw.shape
n = lab_raw.size
mx, mn, mean = B.max(axis=2), B.min(axis=2), B.mean(axis=2)
sat = mx - mn
PAPER, UNK, WATER = 201, 0, 94

ink   = mx < 100
paper = (mn >= 232) & (sat <= 12)
# ---- printed road / rail overlay: grey, low-saturation, thin & linear -------
grey = (sat < 34) & (mean > 112) & (mean < 236)
dt   = ndimage.distance_transform_edt(grey)
road = grey & (dt <= 5)
road = ndimage.binary_closing(road, structure=np.ones((7, 7)))
l, k = ndimage.label(road, structure=np.ones((3, 3)))
if k:
    sz = np.bincount(l.ravel()); sz[0] = 0
    road &= ~np.isin(l, np.where(sz < 600)[0])
road = ndimage.binary_dilation(road, structure=np.ones((3, 3)))
hydro = np.load('work/lab_clean.npy') == WATER      # water kept as its own layer
np.save('work/road_mask.npy', road); np.save('work/hydro_mask.npy', hydro)

conf = (~ink) & (~paper) & (dist <= 26) & (~road)
print(f'confident {100*conf.mean():.2f}%  ink {100*ink.mean():.2f}%  paper {100*paper.mean():.2f}%  '
      f'road {100*road.mean():.2f}%  water {100*hydro.mean():.2f}%  '
      f'unknown {100*(~conf&~paper&~road&~hydro).mean():.2f}%', flush=True)

lab = np.where(conf, lab_raw.astype(np.int32) + 1, UNK)
lab[paper] = PAPER

def drop_small(lab, min_area):
    for c in np.unique(lab):
        if c in (PAPER, UNK): continue
        m = lab == c
        l, k = ndimage.label(m)
        if k == 0: continue
        sz = np.bincount(l.ravel()); sz[0] = 0
        bad = np.where(sz < min_area)[0]; bad = bad[bad > 0]
        if bad.size: lab[np.isin(l, bad)] = UNK
    return lab

def edt_fill(lab):
    known = lab > 0
    if known.all(): return lab
    idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
    out = lab.copy(); u = ~known
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
lab = majority(lab, ~conf, win=int(os.environ.get('MWIN','9')), minfrac=0.34)
lab[conf] = lab_raw[conf].astype(np.int32) + 1
lab[paper] = PAPER
lab = edt_fill(drop_small(lab, int(os.environ.get('M1','120'))))
lab = edt_fill(drop_small(lab, int(os.environ.get('M2','220'))))
np.save('work/lab_geo.npy', lab.astype(np.uint16))

uv, uc = np.unique(lab, return_counts=True)
print(f'\n{len(uv)} classes, unknown={int((lab==0).sum())}')
for v, c in sorted(zip(uv, uc), key=lambda t: -t[1])[:16]:
    code = PAL[v-1]['code'] if 1 <= v <= len(PAL) else ('PAPER' if v == PAPER else '?')
    print(f'   {v:4d} {code:12s} {100*c/n:6.3f}%')
