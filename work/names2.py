import json, re
pal=json.load(open('work/palette.json')); rows=json.load(open('work/legend_rows.json'))
by={}
for r in rows: by.setdefault(tuple(r['rgb']), r)
FIX=[('Fomation','Formation'),('lIlaro','Ilaro'),('SokotoGroup','Sokoto Group'),
 ('Eze - aku','Eze-Aku'),('Awgu - Formation','Awgu Formation'),('Awi - Mfamosing','Awi-Mfamosing'),
 ('Lafia - Wukari','Lafia-Wukari'),('Ogwashi - Asaba','Ogwashi-Asaba'),('Keri-Kerri','Kerri-Kerri'),
 ('Meaderbelt','Meander belt'),('Charr','Charnockitic'),('Mediu','Medium'),('Coars','Coarse'),
 ('Porph','Porphyroblastic'),('Grave','Gravel'),('Bauch','Bauchite'),('Igniml','Ignimbrite'),
 ('lgnimbrite','Ignimbrite'),('calcerous','calcareous'),('phylities','phyllites'),
 ('Felds','Feldspathic sandstone, calcareous sandstone and shelly limestone'),('IronFormation','iron formation')]
WORDS=['intercalations','intercalated','interlayered','including','limestones','sandstones',
 'sandstone','limestone','siltstone','mudstone','claystone','ironstone','shales','sands','shale',
 'conglomerate','quartzite','phyllite','phylite','schist','gneiss','granite','diorite','syenite',
 'gabbro','basalt','rhyolite','dolerite','pegmatite','mylonites','mylonite','migmatite',
 'amphibolite','porphyry','charnockite','hornfelstic','hornfelsic','slate','marble','swamp','swamps',
 'water','clay','clays','sand','gravel','grit','pebbles','coal','group','formation','and','with',
 'mainly','locally','also']
def split_token(t):
    if len(t) < 7: return t
    for w in sorted(set(WORDS), key=len, reverse=True):
        t = re.sub(r'(?<=[a-z])(' + re.escape(w) + r')(?![a-z])', r' \1', t, flags=re.I)
    return t
def fix(s, code=''):
    if not s: return ''
    for a, b in FIX: s = s.replace(a, b)
    segs=[x.strip() for x in s.split('/') if x.strip()]
    if segs: s = max(segs, key=len)
    s = ' '.join(split_token(t) if ' ' not in t else t for t in s.split())
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)
    if code: s = re.sub(r'^' + re.escape(code) + r'\s+', '', s, flags=re.I)
    s = re.sub(r',\s*,', ',', s); s = re.sub(r'\s*,\s*', ', ', s)
    s = re.sub(r'\s+', ' ', s).strip(' ,;:-')
    s = re.sub(r'\s+([.,;:])', r'\1', s)
    return s[:118]
n=0
for p in pal:
    raw = by.get(tuple(p['rgb']))
    if raw and p.get('src') == 'legend' and p['code'] != 'MS':
        p['name'] = fix(raw.get('name') or '', p['code'])
        p['lith'] = fix(raw.get('lith') or '', p['code'])
        p['age']  = fix(raw.get('age') or '')
        n += 1
    if not p.get('name'): p['name'] = p.get('lith','')
json.dump(pal, open('work/palette.json','w'), indent=1)
print('cleaned', n)
