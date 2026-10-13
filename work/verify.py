"""Block-by-block comparison of the delivered polygons against the original scan."""
import numpy as np, json, sys
from PIL import Image
from rasterio import features
from affine import Affine
import geopandas as gpd
from collections import Counter
Image.MAX_IMAGE_PIXELS = None

G = json.load(open('work/georef.json'))
A_LON, B_LON, A_LAT, B_LAT = G['a_lon'], G['b_lon'], G['a_lat'], G['b_lat']
H, W = 3335, 4085
# bring the polygons back into raster-corner pixel space, then burn with identity
from shapely.affinity import affine_transform
offx = A_LON*189 + B_LON; offy = A_LAT*189 + B_LAT
INV = [1/A_LON, 0, 0, 1/A_LAT, -offx/A_LON, -offy/A_LAT]
T = Affine.identity()

lab = np.zeros((H, W), np.uint16); rgb = np.zeros((H, W, 3), np.uint8)
cls = 0
for f in ('output/nigeria_geology.geojson', 'output/nigeria_hydro.geojson'):
    g = gpd.read_file(f)
    for _, r in g.iterrows():
        cls += 1
        c = tuple(int(v) for v in r.RGB.split(','))
        features.rasterize([(affine_transform(r.geometry, INV), cls)], out=lab, transform=T, all_touched=False)
        m = lab == cls
        rgb[m] = c
np.save('work/verify_lab.npy', lab); np.save('work/verify_rgb.npy', rgb)

A = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int64)
B = A[189:3524, 189:4274]
mx, mn = B.max(axis=2), B.min(axis=2); sat = mx - mn; mean = B.mean(axis=2)
ink  = mx < 100
road = np.load('work/road_mask.npy')
paper= (mn >= 232) & (sat <= 12)
testable = lab > 0
print(f'pixels covered by delivered polygons: {100*testable.mean():.2f}% of map body')

BL = 32
gh, gw = H // BL, W // BL
agree = 0; tot = 0; mism = np.zeros((gh, gw), bool)
for r in range(gh):
    for c in range(gw):
        ys, ye = r*BL, (r+1)*BL; xs, xe = c*BL, (c+1)*BL
        m = testable[ys:ye, xs:xe]
        if m.sum() < BL*BL*0.35: continue
        sel = m & (~ink[ys:ye, xs:xe]) & (~road[ys:ye, xs:xe])
        if sel.sum() < 40: continue
        ob = B[ys:ye, xs:xe][sel]
        q = ob // 8
        key = q[:, 0]*1000000 + q[:, 1]*1000 + q[:, 2]
        dcol = np.array(Counter(key.tolist()).most_common(1)[0][0] // np.array([1000000, 1000, 1]) % 1000 * 8, int)
        vcol = rgb[ys:ye, xs:xe][m].reshape(-1, 3)
        vdom = np.bincount((vcol.astype(np.int64)[:, 0]//8*1000000 + vcol.astype(np.int64)[:, 1]//8*1000 + vcol.astype(np.int64)[:, 2]//8)).argmax()
        vd = np.array([vdom//1000000, (vdom//1000) % 1000, vdom % 1000], int)*8
        tot += 1
        if np.abs(dcol - vd).max() <= 24: agree += 1
        else: mism[r, c] = True
print(f'blocks compared: {tot}   dominant-colour agreement: {100*agree/tot:.2f}%')
print('\ndisagreement map (X = mismatch, . = ok, blank = not tested):')
for r in range(0, gh, 2):
    print('  |' + ''.join('X' if mism[r, c] or (r+1 < gh and mism[r+1, c]) else
                          ('.' if (testable[r*BL:(r+1)*BL, 0::BL].mean() > .3) else ' ') for c in range(gw)) + '|')

# ---- what kind of mismatches? -------------------------------------------
print('\nmismatch breakdown (original dominant -> delivered dominant, top 25):')
pairs = Counter()
for r in range(gh):
    for c in range(gw):
        if not mism[r, c]: continue
        ys, ye = r*BL, (r+1)*BL; xs, xe = c*BL, (c+1)*BL
        m = testable[ys:ye, xs:xe]
        sel = m & (~ink[ys:ye, xs:xe]) & (~road[ys:ye, xs:xe])
        ob = B[ys:ye, xs:xe][sel]
        q = ob // 8
        key = q[:, 0]*1000000 + q[:, 1]*1000 + q[:, 2]
        kk = Counter(key.tolist()).most_common(1)[0][0]
        dcol = np.array([kk//1000000, (kk//1000) % 1000, kk % 1000], int)*8
        vcol = rgb[ys:ye, xs:xe][m].reshape(-1, 3).astype(np.int64)
        vd = Counter(map(tuple, vcol.tolist())).most_common(1)[0][0]
        pairs[(tuple(dcol), vd)] += 1
pal = json.load(open('work/palette.json'))
def name_of(rgbv):
    best = min(pal, key=lambda p: sum(abs(a-b) for a, b in zip(p['rgb'], rgbv)))
    return f"{best['code']}({best['rgb'][0]},{best['rgb'][1]},{best['rgb'][2]})"
for (a, b_), n in pairs.most_common(25):
    print(f'   {n:4d}  {name_of(a):28s} -> {name_of(list(b_))}')
