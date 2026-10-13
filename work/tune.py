import numpy as np, sys, time, json
sys.path.insert(0,'work')
import vectorize as V
from shapely.geometry import LineString
from shapely.ops import polygonize
from rasterio import features
from affine import Affine
L=np.load('work/lab_final.npy').astype(np.int32); H,W=L.shape; W1=W+1
src,dst,N,_=V.build_graph(L); arcs,*_=V.chain_arcs(src,dst,N)
print('edges',len(src)//2,'arcs',len(arcs))
for tol,it,dens,et in ((0.0,0,3,0),(0.8,2,3,.25),(0.9,2,4,.25),(1.0,2,5,.3),(1.2,3,6,.3),(1.5,3,8,.35)):
    t=time.time()
    lines=[LineString(V.smooth_arc(np.asarray(a,np.int64),W1,tol,it,dens,et)) for a in arcs if len(a)>=2]
    raw=list(polygonize(lines)); polys=[p for p in raw if p.is_valid]
    idx=np.zeros((H,W),np.int32)
    features.rasterize(((g,i+1) for i,g in enumerate(polys)), out=idx, transform=Affine.identity(), all_touched=False)
    verts=sum(len(p.exterior.coords)+sum(len(r.coords) for r in p.interiors) for p in polys)
    print(f'tol={tol} it={it} dens={dens} et={et}: cells {len(polys)} invalid {len(raw)-len(polys)} '
          f'coverage {100*(idx>0).mean():.3f}% verts {verts} ({time.time()-t:.0f}s)')
