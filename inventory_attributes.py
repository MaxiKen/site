#!/usr/bin/env python3
"""Attribute inventory of every shapefile layer of both extractions.

For each layer: geometry type, feature count, and for every field the number of
features that carry a non-empty value (fill rate).  Also reports the size
fields (area / length) and their totals, so that "every layer has a complete
attribute table" can be checked in one go.

Usage:  python inventory_attributes.py [dir ...]   (default: shapefiles shapefiles_minerals)
        python inventory_attributes.py --markdown            # markdown tables on stdout
        python inventory_attributes.py --update-attributes-md  # refresh section 4 of ATTRIBUTES.md
"""
import os
import sys

import shapefile

GEOM = {1: 'Point', 3: 'Polyline', 5: 'Polygon', 8: 'MultiPoint', 11: 'PointZ', 13: 'PolylineZ', 15: 'PolygonZ'}


def inventory(path):
    r = shapefile.Reader(path)
    fields = [(f[0], f[1], f[2], f[3]) for f in r.fields[1:]]
    recs = r.records()
    n = len(recs)
    filled = []
    for i, (name, ftype, size, dec) in enumerate(fields):
        cnt = 0
        for rec in recs:
            v = rec[i]
            if v is None:
                continue
            if isinstance(v, str):
                if v.strip():
                    cnt += 1
            else:
                cnt += 1
        filled.append(cnt)
    sizes = {}
    for i, (name, ftype, size, dec) in enumerate(fields):
        if name in ('area_km2', 'len_km', 'length_km', 'perim_km'):
            vals = [rec[i] for rec in recs if isinstance(rec[i], (int, float))]
            sizes[name] = (len(vals), sum(vals))
    return {'layer': os.path.basename(path)[:-4], 'geom': GEOM.get(r.shapeType, str(r.shapeType)), 'n': n,
            'fields': fields, 'filled': filled, 'sizes': sizes}


def main(argv):
    md = '--markdown' in argv or '--update-attributes-md' in argv
    dirs = [a for a in argv if not a.startswith('--')] or ['shapefiles', 'shapefiles_minerals']
    out = []
    for d in dirs:
        shps = sorted(f for f in os.listdir(d) if f.endswith('.shp'))
        if md:
            out.append(f'\n## {d}/ ({len(shps)} layers)\n')
        else:
            out.append(f'\n=== {d}/ ({len(shps)} layers) ===')
        for fn in shps:
            inv = inventory(os.path.join(d, fn))
            n = inv['n']
            size_txt = '; '.join(f'{k}: {c}/{n} filled, total {t:,.0f}' for k, (c, t) in inv['sizes'].items()) or '-'
            if md:
                out.append(f'\n### {inv["layer"]}  ({inv["geom"]}, {n} features)\n')
                out.append(f'Size fields: {size_txt}\n')
                out.append('| field | type | filled | % |')
                out.append('|---|---|---:|---:|')
                for (name, ftype, size, dec), c in zip(inv['fields'], inv['filled']):
                    t = f'{ftype}{size}' + (f'.{dec}' if dec else '')
                    out.append(f'| `{name}` | {t} | {c} | {100 * c / n if n else 0:.0f} |')
            else:
                out.append(f'\n{inv["layer"]}  [{inv["geom"]}, {n} features]  sizes: {size_txt}')
                cells = []
                for (name, ftype, size, dec), c in zip(inv['fields'], inv['filled']):
                    cells.append(f'{name}={c}' + ('' if c == n else f'({100 * c / n if n else 0:.0f}%)'))
                out.append('   ' + ', '.join(cells))
    text = '\n'.join(out)
    if '--update-attributes-md' in argv:
        # refresh section 4 of ATTRIBUTES.md (everything after its heading) with the measured fill rates
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ATTRIBUTES.md')
        doc = open(path, encoding='utf-8').read()
        head, sep, _ = doc.partition('## 4. Fill rate of every field')
        intro_end = doc.find('\n## shapefiles', doc.find('## 4. Fill rate'))
        intro = doc[len(head) + len(sep):intro_end] if intro_end > 0 else ''
        open(path, 'w', encoding='utf-8').write(head + sep + intro + text + '\n')
        print('ATTRIBUTES.md section 4 updated')
    else:
        print(text)


if __name__ == '__main__':
    main(sys.argv[1:])
