import sys, numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
Image.MAX_IMAGE_PIXELS=None
ocr = RapidOCR()
def run(path, box, tile=1400, overlap=100, out=None):
    im = Image.open(path).convert('RGB')
    x0,y0,x1,y1 = box
    res=[]
    for ty in range(y0, y1, tile-overlap):
        for tx in range(x0, x1, tile-overlap):
            bx0,bx1 = tx, min(tx+tile,x1); by0,by1 = ty, min(ty+tile,y1)
            if bx1-bx0<10 or by1-by0<10: continue
            crop = np.asarray(im.crop((bx0,by0,bx1,by1)))
            r,_ = ocr(crop)
            if r:
                for item in r:
                    pts = np.asarray(item[0]) + np.array([bx0,by0])
                    cx = pts[:,0].mean(); cy = pts[:,1].mean()
                    res.append((cx,cy,item[1],item[2],pts.min(axis=0),pts.max(axis=0)))
    return res
if __name__=='__main__':
    path=sys.argv[1]; box=tuple(int(v) for v in sys.argv[2:6])
    res = run(path, box)
    for cx,cy,t,s,mn,mx in sorted(res, key=lambda r:(round(r[1]/12), r[0])):
        print(f'{int(cx):5d} {int(cy):5d} {s:.2f} {t}')
