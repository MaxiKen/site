"""Absorb small water bodies into the geology raster, keep the big ones."""
import numpy as np
from scipy import ndimage

WATER, MIN_BIG = 94, 20000
L = np.load('work/lab_geo.npy').astype(np.int32)
m = (L == WATER)
l, k = ndimage.label(m, structure=np.ones((3, 3)))
sz = np.bincount(l.ravel()); sz[0] = 0
big = np.isin(l, np.where(sz >= MIN_BIG)[0])
small = m & ~big
print(f'water {100*m.mean():.2f}%  big {100*big.mean():.2f}% ({(sz>=MIN_BIG).sum()} blobs)  '
      f'small {100*small.mean():.2f}%')
L2 = L.copy(); L2[small] = 0
known = L2 > 0
idx = ndimage.distance_transform_edt(~known, return_distances=False, return_indices=True)
u = ~known; L2[u] = L2[idx[0][u], idx[1][u]]
np.save('work/lab_final.npy', L2.astype(np.uint16))
np.save('work/water_big.npy', big)
print('wrote work/lab_final.npy  (unknown pixels:', int((L2 == 0).sum()), ')')
