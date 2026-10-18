#!/usr/bin/env python3
"""Draw 'alignment_reality.png': the same features measured as a DISTANCE, not as a bias.

The point of the figure is to answer one question - if both sheets are plotted in
EPSG:4326, how far apart do the shared features actually sit? - and to separate that
from the systematic offset (median dE/dN), which is a different number.

Separation is measured as the distance from sampled points on one line to the nearest
point of the other line (shapely, exact point-to-line), both directions, on lines
resampled every ~400 m.  Numbers quoted in VALIDATION.md / ACCURACY.md come from the
same routine in validate_coordinates.check_sheet_to_sheet().
"""
import os
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import shapely
import shapefile
from shapely.geometry import LineString

ROOT = os.path.dirname(os.path.abspath(__file__))
GEO = os.path.join(ROOT, 'shapefiles')
MIN = os.path.join(ROOT, 'shapefiles_minerals')
KMY = 110.57                       # km per degree of latitude at 9 N


def lines(path):
    out = []
    for sh in shapefile.Reader(path).shapes():
        p = np.asarray(sh.points, float)
        if len(p) < 2:
            continue
        parts = list(sh.parts) + [len(p)]
        for a, b in zip(parts[:-1], parts[1:]):
            if b - a >= 2:
                out.append(LineString(p[a:b]))
    return out


def dens(lset, step=0.004, cap=40000):
    chunks = []
    for l in lset:
        co = np.asarray(l.coords, float)
        for p, q in zip(co[:-1], co[1:]):
            n = max(2, int(np.hypot(*(q - p)) / step) + 1)
            t = np.linspace(0, 1, n, endpoint=False)[:, None]
            chunks.append(p + (q - p) * t)
    P = np.vstack(chunks) if chunks else np.zeros((0, 2))
    return P[np.linspace(0, len(P) - 1, cap).astype(int)] if len(P) > cap else P


def sep(P, others):
    U = shapely.union_all(others) if len(others) > 1 else others[0]
    return np.asarray(shapely.distance(shapely.points(P), U), float) * KMY


geology_rivers = lines(os.path.join(GEO, 'rivers.shp'))
mineral_rivers = lines(os.path.join(MIN, 'rivers.shp'))
border_2011 = lines(os.path.join(GEO, 'state_boundaries.shp'))
border_2023 = lines(os.path.join(MIN, 'international_boundary.shp'))
# keep only the 2011 state-boundary segments that follow the international line
_UB = shapely.union_all(border_2023)
_COR = _UB.buffer(0.05)
border_2011_border_only = []
for _a in border_2011:
    if _a.distance(_UB) < 0.05:
        border_2011_border_only += [g for g in shapely.get_parts(_a.intersection(_COR))
                                    if isinstance(g, LineString) and g.length > 0]

# --- separation figures ------------------------------------------------------
# the 2011 layer also carries state boundaries, so the unambiguous 2023
# international line is measured against the whole 2011 set
d_border = sep(dens(border_2023), border_2011)
d_river_a = sep(dens(geology_rivers), mineral_rivers)
d_river_b = sep(dens(mineral_rivers), geology_rivers)
d_river = np.concatenate([d_river_a, d_river_b])
med = lambda d: float(np.median(d))
print('border median %.0f m, p90 %.0f m, max %.0f m'
      % (med(d_border) * 1000, np.percentile(d_border, 90) * 1000, d_border.max() * 1000))
print('rivers median %.2f km (2011->2023 %.2f, 2023->2011 %.2f), p90 %.2f km'
      % (med(d_river), med(d_river_a), med(d_river_b), np.percentile(d_river, 90)))

# numbers measured once, documented in ACCURACY.md
RIVERS_PRECAL_KM = 3.94        # before the georeferencing correction
RIVERS_NE_KM = 3.12            # 2023 rivers vs NE 10 m Niger+Benue
BORDER_NE_KM = 1.40            # 2023 border vs NE 50 m
TOWNS_PRINTED_KM = 11.07
TOWNS_CORRECTED_KM = 2.66

# --- figure ------------------------------------------------------------------
fig = plt.figure(figsize=(15, 9.6))
gs = fig.add_gridspec(2, 3, height_ratios=[1.0, 0.95], hspace=0.34, wspace=0.28)
fig.suptitle('Do the two sheets line up when plotted in EPSG:4326? \u2014 measured, layer by layer',
             fontsize=15, y=0.975)

ax = fig.add_subplot(gs[0, 0])
for ln in border_2023:
    ax.plot(*ln.xy, color='#1f4e79', lw=2.6, alpha=0.55, solid_capstyle='round')
for ln in border_2011_border_only:
    ax.plot(*ln.xy, color='#c0392b', lw=0.7)
ax.set_xlim(2.5, 15.0); ax.set_ylim(4.0, 14.0)
ax.set_aspect(1 / np.cos(np.radians(9)))
ax.set_title('National border, both sheets\nmedian separation %.0f m' % (med(d_border) * 1000),
             fontsize=11)
ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
ax.tick_params(labelsize=8); ax.grid(alpha=0.25, lw=0.4)
ax.legend([plt.Line2D([], [], color='#c0392b', lw=1.2),
           plt.Line2D([], [], color='#1f4e79', lw=3.2, alpha=0.55)],
          ['2011', '2023'], fontsize=8, loc='lower left',
          frameon=True, framealpha=0.9, edgecolor='0.8')

ax = fig.add_subplot(gs[0, 1])
win = (6.0, 7.85, 7.55, 8.62)
for lset, c, lw in ((geology_rivers, '#c0392b', 1.0), (mineral_rivers, '#1f4e79', 1.2)):
    for ln in lset:
        if ln.bounds[2] < win[0] or ln.bounds[0] > win[1] or ln.bounds[3] < win[2] or ln.bounds[1] > win[3]:
            continue
        x, y = ln.xy
        ax.plot(x, y, color=c, lw=lw)
ax.set_xlim(win[0], win[1]); ax.set_ylim(win[2], win[3])
ax.set_aspect(1 / np.cos(np.radians(8)))
ax.set_title('Rivers, Niger\u2013Benue confluence\nmedian separation %.1f km' % med(d_river), fontsize=11)
ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
ax.tick_params(labelsize=8); ax.grid(alpha=0.25, lw=0.4)
ax.legend([plt.Line2D([], [], color='#c0392b', lw=1.2),
           plt.Line2D([], [], color='#1f4e79', lw=3.2, alpha=0.55)],
          ['2011', '2023'], fontsize=8, loc='lower left',
          frameon=True, framealpha=0.9, edgecolor='0.8')

ax = fig.add_subplot(gs[0, 2])
for shp_dir, marker, size in ((GEO, 'o', 14), (MIN, 's', 10)):
    for layer, colour, label in (('towns', '#e67e22', 'as printed'),
                                 ('towns_wgs84', '#8e1b1b', 'corrected')):
        path = os.path.join(shp_dir, layer + '.shp')
        if not os.path.exists(path):
            continue
        pts = np.array([sh.points[0] for sh in shapefile.Reader(path).shapes() if sh.points], float)
        ax.scatter(pts[:, 0], pts[:, 1], s=size, marker=marker, c=colour,
                   label=label, linewidths=0, alpha=0.85)
ax.set_xlim(2.5, 8.5); ax.set_ylim(4.2, 7.4)
ax.set_aspect(1 / np.cos(np.radians(6)))
ax.set_title('Town markers: as printed vs corrected\n(every arrow points the same way \u2014 a scale error)',
             fontsize=11)
ax.set_xlabel('longitude'); ax.set_ylabel('latitude')
ax.tick_params(labelsize=8); ax.grid(alpha=0.25, lw=0.4)
h, l = ax.get_legend_handles_labels()
seen = dict(zip(l, h))
ax.legend(seen.values(), seen.keys(), fontsize=8, loc='lower right', frameon=True,
          framealpha=0.9, edgecolor='0.8', markerscale=1.4)

ax = fig.add_subplot(gs[1, :])
bars = [
    ('same border,\nboth sheets', med(d_border), '#1f77b4'),
    ('same rivers,\nboth sheets', med(d_river), '#1f77b4'),
    ('rivers, before\ncalibration', RIVERS_PRECAL_KM, '#999999'),
    ('rivers vs NE 10 m\n(2023)', RIVERS_NE_KM, '#999999'),
    ('border vs NE 50 m\n(2023)', BORDER_NE_KM, '#999999'),
    ('towns as printed\nvs truth', TOWNS_PRINTED_KM, '#e67e22'),
    ('towns corrected\nvs truth', TOWNS_CORRECTED_KM, '#8e1b1b'),
]
y = np.arange(len(bars))[::-1]
for yy, (label, val, colour) in zip(y, bars):
    ax.barh(yy, val, color=colour, height=0.62)
    txt = ('%.0f m' % (val * 1000)) if val < 0.2 else ('%.1f km' % val)
    ax.text(val * 1.08, yy, txt, va='center', fontsize=10)
ax.set_yticks(y); ax.set_yticklabels([b[0] for b in bars], fontsize=9.5)
ax.set_xscale('log'); ax.set_xlim(0.02, 40)
ax.set_xlabel('median separation / error (km, log scale)')
ax.set_title('The same feature measured as a distance (not as an average offset)', fontsize=12)
ax.grid(axis='x', alpha=0.3, lw=0.5)

out = os.path.join(ROOT, 'alignment_reality.png')
fig.savefig(out, dpi=110, bbox_inches='tight')
print('wrote', out)
