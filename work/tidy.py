import json, re
pal=json.load(open('work/palette.json'))
def clean(s):
    if not s: return ''
    s=s.replace('�',' ').strip()
    parts=[p.strip() for p in s.split('/')]
    parts=[p for p in parts if p]
    if len(parts)>=2 and parts[1].lower().startswith(parts[0].lower()[:4]):
        parts=[parts[1]]+parts[2:]
    out=', '.join(dict.fromkeys(parts))
    out=re.sub(r'\s+',' ',out).strip(' ,')
    out=re.sub(r'\s+([.,;])', r'\1', out)
    return out[:110]
for p in pal:
    for k in ('name','lith','age'):
        p[k]=clean(p.get(k,''))
    if not p.get('name'): p['name']=p.get('lith','')
json.dump(pal, open('work/palette.json','w'), indent=1)
for i in (92,2,77,3,88):
    p=pal[i]; print(f'cls{i+1:3d} {p["code"]:8s} | {p["name"][:58]:58s} | {p["lith"][:58]}')
