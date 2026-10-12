import io, re, sys, pickle, ssl as S, dis as D
db = pickle.load(open('../data/classdb_r3.pkl', 'rb'))
def kind(cls, slot):
    c = cls
    while c and c in db:
        if slot in db[c]['members']:
            return db[c]['members'][slot]
        c = (db[c]['base'] or '').split('<')[0]
    return None
seen = {}
for n in S.all_names():
    try:
        m = S.get(n); d = D.Dis(m)
    except Exception:
        continue
    for i, f in enumerate(m.funcs):
        if not f['code']: continue
        buf = io.StringIO()
        try: d.dis(i, out=buf)
        except Exception: continue
        L = buf.getvalue().splitlines()
        for k, ln in enumerate(L):
            if ' op14 ' in ln:
                prev = L[k-1]
                mt = re.search(r': (\w+)\s*$', prev)
                slot = re.search(r'int\s+(\d+)', L[k-2])
                if not mt or not slot: continue
                cls, s = mt.group(1), int(slot.group(1))
                mem = kind(cls, s)
                if mem and mem['kind'] == 1:
                    key = (cls, mem['name'])
                    if key not in seen:
                        seen[key] = n
                        print(n, cls, mem['name'], mem.get('args'))
