import numpy as np, json, sys
from PIL import Image
from scipy import ndimage
Image.MAX_IMAGE_PIXELS=None
A = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.float32)
X0,X1,Y0,Y1 = 189, 4274, 189, 3524        # neat-line interior
B = A[Y0:Y1, X0:X1]
pal = json.load(open('work/palette.json'))
P = np.array([p['rgb'] for p in pal], dtype=np.float32)
H,W,_ = B.shape
print('body', B.shape)

mx = B.max(axis=2); mn = B.min(axis=2)
outside = mn > 238                     # blank paper outside the mapped area
ink     = mx < 100                     # black line-work (roads, rail, type, contacts, graticule)

# ---- nearest-palette classification -------------------------------------
lab = np.zeros((H,W), np.uint16)
dist = np.full((H,W), 1e9, np.float32)
CH = 400
for y0 in range(0,H,CH):
    y1=min(y0+CH,H)
    blk = B[y0:y1].reshape(-1,1,3)
    d = np.sqrt(((blk-P)**2).sum(axis=2))          # (n, K)
    lab[y0:y1]  = d.argmin(axis=1).reshape(y1-y0,W).astype(np.uint16)
    dist[y0:y1] = d.min(axis=1).reshape(y1-y0,W)
    print('  row block', y0, flush=True)
np.save('work/lab_raw.npy', lab); np.save('work/dist.npy', dist)
np.save('work/masks.npy', np.stack([outside, ink]))

# diagnostics
for thr in (20,30,40,60,80):
    print(f'pixels with nearest-palette distance > {thr}: {100*(dist>thr).mean():.2f}%')
obs = ~outside & ~ink
print('outside %.2f%%  ink %.2f%%  colour %.2f%%'%(100*outside.mean(),100*ink.mean(),100*obs.mean()))
print('mean dist on colour pixels: %.2f'%dist[obs].mean())
# worst colours
q=(B[obs].astype(np.int64)//8); key=q[:,0]*1000000+q[:,1]*1000+q[:,2]
from collections import Counter
c=Counter(key.tolist())
dm = dist[obs]
import collections
acc=collections.defaultdict(list)
kk = key.tolist(); dd = dm.tolist()
for a,b in zip(kk,dd): acc[a].append(b)
worst=sorted(((np.mean(v),k,len(v)) for k,v in acc.items() if len(v)>3000), reverse=True)[:15]
print('  colours with largest residual distance:')
for m,k,n in worst:
    print(f'    d={m:5.1f} n={n:7d} rgb=({(k//1000000)*8:3d},{((k//1000)%1000)*8:3d},{(k%1000)*8:3d})')
