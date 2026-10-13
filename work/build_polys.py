"""Raster -> topologically exact polygon mosaic (shared, pre-smoothed arcs)."""
import numpy as np, json, sys, time, pickle
from shapely.geometry import LineString, MultiPolygon
from shapely.ops import polygonize
from shapely import prepare
from rasterio import features
from affine import Affine
import vectorize as V

TOL   = float(sys.argv[1]) if len(sys.argv) > 1 else 0.9
ITERS = int(sys.argv[2])   if len(sys.argv) > 2 else 2
SRC   = sys.argv[3]        if len(sys.argv) > 3 else 'work/lab_clean.npy'
OUT   = sys.argv[4]        if len(sys.argv) > 4 else 'work/cells.pkl'

t0 = time.time()
L = np.load(SRC).astype(np.int32)
H, W = L.shape; W1 = W + 1
print(f'raster {H}x{W}, {len(np.unique(L))} labels', flush=True)

src, dst, N, _ = V.build_graph(L)
print(f'  {len(src)//2} boundary edges  ({time.time()-t0:.0f}s)', flush=True)
arcs, *_ = V.chain_arcs(src, dst, N)
print(f'  {len(arcs)} arcs  ({time.time()-t0:.0f}s)', flush=True)

lines = []
for nd in arcs:
    if len(nd) < 2: continue
    p = V.smooth_arc(np.asarray(nd, np.int64), W1, TOL, ITERS)
    if len(p) >= 2: lines.append(LineString(p))
print(f'  {len(lines)} smoothed arcs  ({time.time()-t0:.0f}s)', flush=True)

polys = [p for p in polygonize(lines) if p.is_valid]
print(f'  {len(polys)} cells  ({time.time()-t0:.0f}s)', flush=True)

# exact labelling: burn the cells, take the majority raster label per cell
idx = np.zeros((H, W), np.int32)
features.rasterize(((g, i + 1) for i, g in enumerate(polys)), out=idx,
                   transform=Affine.identity(), all_touched=False)
ok = idx > 0
print(f'  rasterised: {100*ok.mean():.3f}% of pixels covered', flush=True)
n = len(polys)
flat = (idx[ok].astype(np.int64) * 1000 + L[ok].astype(np.int64))
uniq, cnt = np.unique(flat, return_counts=True)
cell_of, lab_of = (uniq // 1000).astype(int) - 1, (uniq % 1000).astype(int)
best = np.zeros(n, np.int32); bestc = np.zeros(n, np.int64)
m = cnt > bestc[cell_of]
np.maximum.at(bestc, cell_of[m], cnt[m])
sel = cnt >= bestc[cell_of]
best[cell_of[sel]] = lab_of[sel]
areas = np.bincount(idx[ok], minlength=n + 1)[1:]

print(f'  areas px: min {areas.min()} median {np.median(areas):.0f} max {areas.max()}', flush=True)
for th in (5, 10, 25, 50, 100, 250, 1000):
    print(f'    cells < {th:5d}px: {(areas < th).sum():7d}   (area share {100*areas[areas<th].sum()/areas.sum():.3f}%)')

with open(OUT, 'wb') as f:
    pickle.dump(dict(labels=best, areas=areas, geoms=polys, shape=(H, W),
                     tol=TOL, iters=ITERS), f, protocol=4)
print(f'  saved {OUT}  ({time.time()-t0:.0f}s)', flush=True)
