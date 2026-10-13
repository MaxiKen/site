import numpy as np, json, sys
sys.path.insert(0,'work')
from PIL import Image
from geo import x_of, y_of
from collections import Counter
Image.MAX_IMAGE_PIXELS=None
pal=json.load(open('work/palette.json'))
L=np.load(sys.argv[1] if len(sys.argv)>1 else 'work/lab_clean.npy')
A=np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int64)
def cls(lo,la,win=9):
    x=int(round(x_of(lo)))-189; y=int(round(y_of(la)))-189
    if not (0<=y<L.shape[0] and 0<=x<L.shape[1]): return None,None,None
    b=L[max(0,y-win):y+win+1, max(0,x-win):x+win+1].ravel()
    v,c=Counter(b.tolist()).most_common(1)[0]
    return v, c/b.size, tuple(A[y+189,x+189])
PTS=[('Port Harcourt',7.02,4.82,'Delta mangrove/freshwater swamp'),
     ('Warri',5.75,5.52,'Delta mangrove / Sombreiro-Warri'),
     ('Benin City',5.62,6.34,'Benin Fm sand'),
     ('Lagos',3.38,6.52,'Coastal plain sands'),
     ('Ibadan',3.90,7.38,'Basement gneiss/granite'),
     ('Abeokuta',3.35,7.15,'Abeokuta/Ewekoro Fm OR basement'),
     ('Akure',5.20,7.25,'Basement'),
     ('Ilorin',4.55,8.50,'Basement / Nupe sandstone'),
     ('Enugu',7.50,6.45,'Enugu shale / Nsukka Fm'),
     ('Onitsha',6.78,6.14,'Imo/Ameki OR Delta sands'),
     ('Owerri',7.03,5.48,'Benin / Ameki'),
     ('Calabar',8.32,4.98,'Cretaceous Calabar flank / Delta'),
     ('Uyo',7.93,5.04,'Benin Fm / Delta'),
     ('Lokoja',6.74,7.80,'Lokoja/Bida sandstone'),
     ('Abuja',7.49,9.06,'Basement granite-gneiss'),
     ('Minna',6.55,9.61,'Basement schist belts'),
     ('Kaduna',7.44,10.52,'Basement'),
     ('Zaria',7.72,11.08,'Basement'),
     ('Kano',8.52,12.00,'Basement granite/gneiss'),
     ('Katsina',7.60,12.98,'Basement or Gwandu Fm'),
     ('Sokoto',5.24,13.06,'Gwandu/Sokoto Group'),
     ('Birnin Kebbi',4.20,12.45,'Iullemmeden / Gwandu'),
     ('Jos',8.89,9.90,'Younger Granite / volcanics'),
     ('Bauchi',9.85,10.32,'Basement / Younger Granite'),
     ('Maiduguri',13.15,11.83,'Chad Formation'),
     ('Damaturu',11.96,11.75,'Chad Formation'),
     ('Potiskum',11.09,11.71,'Kerri-Kerri / Chad'),
     ('Gombe',11.17,10.29,'Gombe ss / Kerri-Kerri'),
     ('Yola',12.48,9.23,'Bima ss / Kerri-Kerri'),
     ('Makurdi',8.53,7.73,'Benue trough sediments'),
     ('Lake Chad',14.30,13.30,'WATER'),
     ('Lake Kainji',4.60,10.40,'WATER')]
print(f'{"place":14s} {"expected":38s} -> {"code":6s} {"name/lith":52s} agree%  rgb')
for nm,lo,la,exp in PTS:
    v,f,rgb=cls(lo,la)
    if v is None: print(f'{nm:14s} {exp:38s} -> OFF MAP'); continue
    if v==201: c,n_,l='PAPER','(blank paper / outside mapped area)',''; 
    elif 1<=v<=len(pal): p=pal[v-1]; c,n_,l=p['code'],p['name'] or p['lith'],p['lith']
    else: c,n_,l=str(v),'?',''
    print(f'{nm:14s} {exp:38s} -> {c:6s} {(n_ or l)[:52]:52s} {f*100:5.1f}  {rgb}')
