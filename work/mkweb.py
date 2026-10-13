import json, os, shutil, geopandas as gpd, numpy as np
G=json.load(open('work/georef.json')); A_LON,B_LON,A_LAT,B_LAT=G['a_lon'],G['b_lon'],G['a_lat'],G['b_lat']
os.makedirs('web', exist_ok=True); os.makedirs('web/images', exist_ok=True)
for f in ('leaflet.js','leaflet.css'):
    shutil.copy(f'node_modules/leaflet/dist/{f}', f'web/{f}')
for f in os.listdir('node_modules/leaflet/dist/images'):
    shutil.copy(f'node_modules/leaflet/dist/images/{f}', f'web/images/{f}')
src='pic NGSA geological-map-of-nigeria-.jpg'
shutil.copy(src, 'web/original.jpg')
IW, IH = 6600, 3675
bounds = dict(south=A_LAT*IH+B_LAT, west=B_LON, north=B_LAT, east=A_LON*IW+B_LON)
bounds = {k: round(float(v), 6) for k, v in bounds.items()}
print('image bounds', bounds)

def prep(name, tol):
    g = gpd.read_file(f'output/{name}.geojson')
    g['geometry'] = g.geometry.simplify(tol, preserve_topology=True)
    cols=['CLASS_ID','CODE','NAME','LITH','AGE','RGB','HEX','AREA_KM2','NPART','NOTE','geometry']
    g[cols].to_file(f'web/{name}.geojson', driver='GeoJSON')
    print(f'{name}: {len(g)} feats, {os.path.getsize(f"web/{name}.geojson")/1e6:.2f} MB')
prep('nigeria_geology', 0.0009)
prep('nigeria_hydro', 0.0009)
json.dump(dict(bounds=bounds, width=IW, height=IH), open('web/meta.json','w'))
