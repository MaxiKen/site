import numpy as np, json, sys
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
Image.MAX_IMAGE_PIXELS=None
im = Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')
ocr = RapidOCR()
X0,X1,Y0,Y1 = 189,4274,189,3524
TILE, OV, SC = 800, 70, 2
out=[]
for ty in range(Y0, Y1, TILE-OV):
    for tx in range(X0, X1, TILE-OV):
        bx1, by1 = min(tx+TILE, X1), min(ty+TILE, Y1)
        if bx1-tx<40 or by1-ty<40: continue
        c = im.crop((tx,ty,bx1,by1)).resize(((bx1-tx)*SC,(by1-ty)*SC), Image.LANCZOS)
        r,_ = ocr(np.asarray(c))
        if r:
            for item in r:
                pts=np.asarray(item[0])/SC + np.array([tx,ty])
                out.append(dict(cx=float(pts[:,0].mean()), cy=float(pts[:,1].mean()),
                                w=float(pts[:,0].max()-pts[:,0].min()), h=float(pts[:,1].max()-pts[:,1].min()),
                                t=item[1], s=float(item[2])))
        print(f'  tile {tx},{ty} -> {len(out)}', flush=True)
json.dump(out, open('work/map_labels.json','w'))
print('total', len(out))
