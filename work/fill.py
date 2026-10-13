import numpy as np
from scipy import ndimage
Image_MAX=None
lab = np.load('work/lab_raw.npy')          # 0..93 palette index
dist= np.load('work/dist.npy')
m   = np.load('work/masks.npy')
outside, ink = m[0].astype(bool), m[1].astype(bool)

H,W = lab.shape
NONE   = 200          # unknown / line-work, to be filled
OUTSIDE= 201
lbl = lab.astype(np.uint16) + 1            # palette idx 0..93 -> 1..94
lbl[outside] = OUTSIDE

# every dark (line-work, type, road, rail, graticule) or poorly-matching pixel becomes unknown
unknown = ink | (dist > 28)
unknown &= ~outside
lbl[unknown] = NONE
print('unknown %.3f%%   outside %.3f%%'%(100*unknown.mean(), 100*outside.mean()))

known = (lbl != NONE)
idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
filled = lbl[tuple(idx)]
# never let the fill disturb already-known pixels
filled[known] = lbl[known]
np.save('work/lab_filled.npy', filled)
print('classes after fill:', np.unique(filled).size)
vals, cnts = np.unique(filled, return_counts=True)
for v,c in sorted(zip(vals.tolist(), cnts.tolist()), key=lambda t:-t[1])[:20]:
    print(f'   class {v:3d}: {100*c/filled.size:6.3f}%')
