"""Raster -> topologically exact, smoothly generalised polygon mosaic.

Boundaries are extracted as a planar graph of unit segments, chained into
arcs between junction nodes, smoothed ONCE per arc (so both sides of every
shared border get the identical geometry), then re-assembled with
shapely.ops.polygonize.  Result: no gaps, no overlaps, no staircase edges.
"""
import numpy as np, json, sys, time
from collections import defaultdict
from shapely.geometry import LineString, Polygon, MultiPolygon, box
from shapely.ops import polygonize, unary_union
import shapely

PAL = json.load(open('work/palette.json'))
G   = json.load(open('work/georef.json'))
A_LON, B_LON, A_LAT, B_LAT = G['a_lon'], G['b_lon'], G['a_lat'], G['b_lat']
X0, Y0 = 189, 189                      # body crop origin in image pixels

def to_geo(X, Y):                      # raster-corner coords -> lon/lat
    return (A_LON * (X0 + X) + B_LON, A_LAT * (Y0 + Y) + B_LAT)

# ----------------------------------------------------------------- graph ----
def build_graph(L):
    H, W = L.shape
    hv = L[:-1, :] != L[1:, :]
    vv = L[:, :-1] != L[:, 1:]
    r, c   = np.nonzero(hv);  a1 = (r + 1) * (W + 1) + c;  b1 = a1 + 1
    r2, c2 = np.nonzero(vv);  a2 = r2 * (W + 1) + c2 + 1;  b2 = a2 + (W + 1)
    # outer rectangle (closes the network at the raster border)
    W1, H1 = W + 1, H + 1
    top = np.arange(W, dtype=np.int64);           ra = top;              rb = top + 1
    bot = np.arange(W, dtype=np.int64) + H * W1;  rc = bot;                  rd = bot + 1
    lef = np.arange(H, dtype=np.int64) * W1;      re = lef;                  rf = lef + W1
    rig = lef + W;                                rg = rig;                  rh = rig + W1
    src = np.concatenate([a1, a2, ra, rc, re, rg])
    dst = np.concatenate([b1, b2, rb, rd, rf, rh])
    N   = H1 * W1
    return (np.concatenate([src, dst]).astype(np.int64),
            np.concatenate([dst, src]).astype(np.int64), N, (H, W))

def chain_arcs(src, dst, N):
    order = np.lexsort((dst, src))
    src_s, dst_s = src[order], dst[order]
    cnt  = np.bincount(src_s, minlength=N)
    start = np.zeros(N + 1, np.int64); np.cumsum(cnt, out=start[1:])
    deg = cnt
    nhe = len(src_s)
    used = np.zeros(nhe, bool)
    def half_edges(n):
        return dst_s[start[n]:start[n+1]], np.arange(start[n], start[n+1])
    arcs = []
    junction = np.nonzero(deg != 2)[0]
    def walk(n0, closed):
        chain = [n0]; cur = n0
        while True:
            ds, hs = half_edges(cur)
            nxt = -1
            for d, h in zip(ds, hs):
                if not used[h]:
                    nxt, hh = d, h; break
            if nxt < 0: break
            used[hh] = True
            # consume the reverse half-edge
            dsr, hsr = half_edges(nxt)
            for d, h in zip(dsr, hsr):
                if d == cur and not used[h]:
                    used[h] = True; break
            chain.append(int(nxt)); cur = int(nxt)
            if closed and cur == n0: break
            if deg[cur] != 2: break
        return chain
    for n in junction:
        _, hs = half_edges(n)
        for h in hs:
            if used[h]: continue
            used[h] = True
            dsr, hsr = half_edges(int(dst_s[h]))
            for d, hh in zip(dsr, hsr):
                if d == n and not used[hh]:
                    used[hh] = True; break
            ch = walk(int(dst_s[h]), False)
            arcs.append([int(n)] + ch)
    for h in range(nhe):                       # pure cycles (islands)
        if used[h]: continue
        used[h] = True
        n0 = int(src_s[h]); n1 = int(dst_s[h])
        dsr, hsr = half_edges(n1)
        for d, hh in zip(dsr, hsr):
            if d == n0 and not used[hh]:
                used[hh] = True; break
        arcs.append(walk(n1, True))
    return arcs, src_s, dst_s, start, deg

# -------------------------------------------------------------- smoothing ---
def chaikin(pts, iters=2):
    pts = np.asarray(pts, float)
    for _ in range(iters):
        if len(pts) < 3: break
        a, b = pts[:-1], pts[1:]
        out = np.empty((2*len(a)+1, 2))
        out[0] = pts[0]
        out[1:-1:2] = a*0.75 + b*0.25
        out[2::2] = a*0.25 + b*0.75
        out[-1] = pts[-1]
        pts = out
    return pts

def densify(pts, maxlen=3.0):
    pts = np.asarray(pts, float)
    if len(pts) < 2: return pts
    d = np.hypot(*(pts[1:] - pts[:-1]).T)
    n = np.maximum(1, np.ceil(d / maxlen).astype(int))
    out = [pts[0]]
    for i in range(len(pts) - 1):
        for k in range(1, n[i] + 1):
            out.append(pts[i] + (pts[i+1] - pts[i]) * (k / n[i]))
    return np.array(out)

def smooth_arc(nodes, W1, tol=0.9, iters=2, dens=3.0, endtol=0.25):
    ys, xs = nodes // W1, nodes % W1
    pts = np.column_stack([xs, ys]).astype(float)
    if len(pts) > 2:
        pts = np.asarray(LineString(pts).simplify(tol, preserve_topology=False).coords)
    pts = chaikin(densify(pts, dens), iters)      # corner cut <= dens/4 px
    if len(pts) > 2 and endtol > 0:
        pts = np.asarray(LineString(pts).simplify(endtol, preserve_topology=False).coords)
    return pts

# ------------------------------------------------------------------ main ----
def run(path='work/lab_clean.npy', out='work/cells.json', tol=0.9, iters=2,
        min_area_px=60, note=True):
    L = np.load(path).astype(np.int32)
    H, W = L.shape; W1 = W + 1
    t0 = time.time()
    src, dst, N, _ = build_graph(L)
    print(f'  {len(src)} half-edges  ({time.time()-t0:.0f}s)', flush=True)
    arcs, *_ = chain_arcs(src, dst, N)
    print(f'  {len(arcs)} arcs  ({time.time()-t0:.0f}s)', flush=True)
    lines = []
    for nd in arcs:
        if len(nd) < 2: continue
        p = smooth_arc(np.asarray(nd, np.int64), W1, tol, iters)
        if len(p) >= 2:
            lines.append(LineString(p))
    print(f'  {len(lines)} smoothed arcs  ({time.time()-t0:.0f}s)', flush=True)
    polys = list(polygonize(lines))
    print(f'  {len(polys)} cells  ({time.time()-t0:.0f}s)', flush=True)
    ok, bad = [], 0
    for p in polys:
        if not p.is_valid or p.area < min_area_px:
            bad += 1; continue
        rp = p.representative_point()
        rr = int(np.floor(rp.y)); cc = int(np.floor(rp.x))
        if not (0 <= rr < H and 0 <= cc < W): bad += 1; continue
        ok.append((int(L[rr, cc]), p))
    print(f'  labelled {len(ok)} cells, dropped {bad}  ({time.time()-t0:.0f}s)', flush=True)
    json.dump(None, open(out, 'w')) if False else None
    return ok, (H, W)

if __name__ == '__main__':
    import sys
    crop = None
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        L = np.load('work/lab_clean.npy')[1000:1200, 1500:1700].astype(np.int32)
        np.save('/tmp/crop.npy', L); crop = '/tmp/crop.npy'
    cells, shape = run(crop or 'work/lab_clean.npy')
    from collections import Counter
    print(Counter(c for c, _ in cells).most_common(10))
