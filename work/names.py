import json, re
WORDS = ['intercalations','intercalated','interbedded','including','limestone','sandstone','siltstone',
 'mudstone','claystone','ironstone','shale','shales','siltstone','sandstones','sandstone','conglomerate',
 'marble','quartzite','schist','gneiss','granite','diorite','syenite','gabbro','basalt','rhyolite',
 'dolerite','pegmatite','mylonite','migmatite','amphibolite','porphyry','charnockite','phylite','slate',
 'clay','clays','sand','sands','gravel','grit','pebbles','coal','lignite','swamp','swamps','water',
 'and','with','mainly','locally','also','including','formation','group','member','undifferentiated']
FIX = [('Fomation','Formation'),('Charr,','Charnockitic:'),('Mediu,','Medium,'),('Coars,','Coarse,'),
 ('Porph,','Porphyroblastic:'),('Grave,','Gravel,'),('Bauch,','Bauchite:'),('lIlaro','Ilaro'),
 ('Meaderbelt','Meander belt'),('Keri-Kerri','Kerri-Kerri'),('Eze - aku','Eze-Aku'),
 ('Awgu - Formation','Awgu Formation'),('Awi - Mfamosing','Awi-Mfamosing'),
 ('Lafia - Wukari','Lafia-Wukari'),('Ogwashi - Asaba','Ogwashi-Asaba'),('Igniml','Ignimbrite'),
 ('lgnimbrite','Ignimbrite'),('Sand, ABSandsandPebbles','Sands and pebbles'),
 ('Biotiteandbiotite','Biotite and biotite'),('Banded IronFormation','Banded iron formation'),
 ('Felds','Feldspathic sandstone, calcareous sandstone and shelly limestone'),
 ('Sandstonesand','Sandstone and'),('Clay, ImshClayandShalewith','Clay, clay and shale with'),
 ('Clay, Issh Clay clayey','Clay, clayey'),('Porph, OPgPorphroblastic','Porphyroblastic'),
 ('Grave, Glgss Gravel and sand','Gravel and sand'),
 ('Coars, OSq Coarse','Coarse'),('Mediu, OGm Medium-to','Medium-to'),
 ('Pebbles and grit, GlpgPebbl, Glpg Pebbles and grit','Pebbles and grit'),
 ('Charr, OGCh Charnockitic rocks','Charnockitic rocks'),
 ('Bauch, ODh Bauchite quartz- diorite','Bauchite quartz-diorite'),
 ('Sands, Bssf Sandstone and Ironstone','Sandstone and ironstone'),
 ('Sands, Gss Sandstone','Sandstone'),('Shale, ANsh Shale and Limestone','Shale and limestone'),
 ('Coal,, Mcst Coal','Coal,'),('Lignite,Claystone','Lignite, claystone'),
 ('Slatephyliteandmetasiltstone','Slate, phyllite and metasiltstone'),
 ('MetaVolcanicMetaSedimentaryincludingpebblyschist','Meta-volcanic and meta-sedimentary rocks, including pebbly schist'),
 ('MWSSands, MWS Sands','Sands'),('Mylonitesinterlayered','Mylonites interlayered'),
 ('Quartzite,massive','Quartzite, massive'),('Undifferentiated schists,including','Undifferentiated schists, including'),
 ('Silicified,shearedrocks,large quartzveins','Silicified, sheared rocks, large quartz veins'),
 ('Granite and graniteporphery','Granite and granite porphyry'),
 ('BiotiteGarnetGneissSchist','Biotite-garnet gneiss and schist'),
 ('Bandedgneiss, biotitegneiss','Banded gneiss, biotite gneiss'),
 ('Biotitehornblendegneiss','Biotite-hornblende gneiss'),
 ('Fine-grained flaggy quartzite and Quartz Schist.','Fine-grained flaggy quartzite and quartz schist'),
 ('Amphibole Schist,Amphibolite','Amphibole schist, amphibolite'),
 ('Shale, sandyclay, calcerous sandstones','Shale, sandy clay, calcareous sandstones'),
 ('Sand,Clay and Swamp','Sand, clay and swamp'),
 ('Sands,Clays,siltstones and limestones','Sands, clays, siltstones and limestones'),
 ('False-bedded sandstone','False-bedded sandstone'),
 ('Blackshale,siltstone and sandstone','Black shale, siltstone and sandstone'),
 ('Sandstone,shaleandClay','Sandstone, shale and clay'),
 ('Sandstone,siltstone and shale','Sandstone, siltstone and shale'),
 ('SandstoneandLimestone','Sandstone and limestone'),
 ('Shaleandlimestone','Shale and limestone'),
 ('Shaleandmudstone','Shale and mudstone'),
 ('Sandstone,limestone,Coal','Sandstone, limestone, coal'),
 ('Coal,shaleand sandstone','Coal, shale and sandstone'),
 ('Feldspathicsandstoneandsiltstone','Feldspathic sandstone and siltstone'),
 ('Sandstone,shale and sandyshale','Sandstone, shale and sandy shale'),
 ('Undifferentiatedgranite,migmatiteandgraniteGneiss','Undifferentiated granite, migmatite and granite gneiss'),
 ('Sands and Clay','Sandstone and clay'),('Sand and Clay','Sand and clay')]
def tidy(s):
    if not s: return ''
    for a,b in FIX: s=s.replace(a,b)
    for w in sorted(set(WORDS), key=len, reverse=True):
        s = re.sub(r'(?<=[a-z,])' + re.escape(w), ' ' + w, s, flags=re.I) if False else s
    # camelCase + glued-word splitting
    for w in sorted(set(WORDS), key=len, reverse=True):
        s = re.sub(r'(?<=[a-z])(' + w + r')', r' \1', s)
    s = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', s)
    s = re.sub(r'\s*,\s*', ', ', s)
    s = re.sub(r'\s+', ' ', s).strip(' ,;:-')
    s = re.sub(r'\s+([.,;:])', r'\1', s)
    return s[:120]
pal=json.load(open('work/palette.json'))
for p in pal:
    for k in ('name','lith','age'):
        before=p.get(k,''); after=tidy(before)
        if after and len(after)>4: p[k]=after
        elif after: p[k]=after
    if not p.get('name'): p['name']=p.get('lith','')
json.dump(pal, open('work/palette.json','w'), indent=1)
for i in (0,2,20,26,34,36,42,67,92,67):
    p=pal[i]; print(f'cls{i+1:3d} {p["code"]:9s} | {p["name"][:56]:56s} | {p["lith"][:50]}')
