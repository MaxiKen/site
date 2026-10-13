import numpy as np, sys
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
a = np.asarray(Image.open('pic NGSA geological-map-of-nigeria-.jpg').convert('RGB')).astype(np.int16)
def art(x0,y0,x1,y1,sx=1,sy=1,mode='lum'):
    sub = a[y0:y1, x0:x1][::sy, ::sx]
    mx=sub.max(axis=2); mn=sub.min(axis=2); sat=mx-mn
    out=[]
    for r in range(sub.shape[0]):
        line=''
        for c in range(sub.shape[1]):
            m=mx[r,c]; n=mn[r,c]; s=sat[r,c]
            if m<110: ch='#'          # black linework
            elif n>235 and s<12: ch=' '  # white
            elif s<20: ch='.'        # gray
            else:
                # colour letter by hue
                px=sub[r,c]; R,G,B=px
                if R>=G and R>=B: ch='R' if B<G else ('M' if B>G+30 else 'r')
                elif G>=R and G>=B: ch='G' if R<B+40 else 'Y'
                else: ch='B' if G>R+30 else ('C' if G>R else 'b')
                if m>235 and s<40: ch=ch.lower()
            line+=ch
        out.append(line)
    return out
if __name__=='__main__':
    x0,y0,x1,y1=[int(v) for v in sys.argv[1:5]]
    sx=int(sys.argv[5]) if len(sys.argv)>5 else 1
    sy=int(sys.argv[6]) if len(sys.argv)>6 else 1
    for i,l in enumerate(art(x0,y0,x1,y1,sx,sy)): print(f'{y0+i*sy:5d} |{l}')
