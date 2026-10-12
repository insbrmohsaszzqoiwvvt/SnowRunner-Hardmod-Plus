"""Global class database across all modules."""
import ssl as S, pickle, os
from ssl import F, one

import os
DBFILE = os.environ.get('SSL_DB', '../data/classdb.pkl')

def typename_base(t):
    return t.split('<')[0] if t else t

def build():
    db = {}       # class name -> dict(module, base, members{slot: (name, kind, rettype/fieldtype, sig)})
    mfuncs = {}   # module -> [func names]
    for n in S.all_names():
        m = S.get(n)
        for c in m.classes:
            mem = {}
            for mm in c['members']:
                k = mm['kind']
                info = dict(name=mm['name'], kind=k)
                if k in (1, 2) and mm['func'] is not None:
                    f = m.funcs[mm['func']]
                    sig = m.types[f['sig']]
                    d = F(one(sig, 4))
                    info['ret'] = m.tname(one(d, 1)) if d.get(1) else 'void'
                    info['args'] = [m.tname(a) for a in d[2]]
                    info['params'] = f['params']
                    info['func'] = mm['func']
                elif k == 4:
                    info['type'] = m.tname(mm['func'])
                elif k == 5 and mm['ftype'] is not None:
                    info['type'] = m.tname(one(mm['ftype'], 1))
                elif k == 6:
                    info['type'] = c['name']
                elif k == 3:
                    info['type'] = 'event'
                mem[mm['slot']] = info
            base = m.tname(c['base']) if c['base'] is not None else None
            key = c['name']
            if key in db:
                key = '%s@%s' % (c['name'], n)
            db[key] = dict(module=n, base=base, members=mem)
    # builtin classes (array, dict, string...) known only from import tables
    for n in S.all_names():
        m = S.get(n)
        for e in m.ext_members:
            owner = m.tname(e['owner']).split('<')[0]
            if owner in db and '@' not in owner and db[owner]['module'] != '<builtin>':
                continue
            ent = db.setdefault(owner, dict(module='<builtin>', base=None, members={}))
            if e['slot'] in ent['members']:
                continue
            info = dict(name=e['name'], kind=e['kind'])
            t = m.tname(e['sig'])
            if t.startswith('fn('):
                sd = F(one(m.types[e['sig']], 4))
                info['ret'] = m.tname(one(sd, 1)) if sd.get(1) else 'void'
                info['args'] = [m.tname(a) for a in sd[2]]
            else:
                info['type'] = t
            ent['members'][e['slot']] = info
    pickle.dump(db, open(DBFILE, 'wb'))
    return db

def load():
    if os.path.exists(DBFILE):
        return pickle.load(open(DBFILE, 'rb'))
    return build()

if __name__ == '__main__':
    db = build()
    print(len(db))
    dup = [k for k in db if '@' in k]
    print('dups', len(dup), dup[:30])
