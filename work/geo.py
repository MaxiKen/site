import json
g=json.load(open('work/georef.json'))
A_LON,B_LON = g['a_lon'], g['b_lon']
A_LAT,B_LAT = g['a_lat'], g['b_lat']
X0,Y0 = 189,189
def lon_of(x): return A_LON*x + B_LON
def lat_of(y): return A_LAT*y + B_LAT
def x_of(lon): return (lon - B_LON)/A_LON
def y_of(lat): return (lat - B_LAT)/A_LAT
