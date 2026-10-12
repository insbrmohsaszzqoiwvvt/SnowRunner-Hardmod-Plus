import pip as P
from collections import defaultdict

def F(buf):
    """dict field -> list of values"""
    d = defaultdict(list)
    for f, s, e, v in P.pb_fields(buf):
        d[f].append(v)
    return d

def one(d, k, default=None):
    v = d.get(k)
    return v[0] if v else default

class Mod:
    def __init__(self, name, blob):
        self.name = name
        self.m = P.Module(blob)
        b = F(self.m.body)
        self.raw = b
        self.strings = [s.decode('utf-8', 'replace') for s in b[6]]
        S = self.strings
        self.imports = [S[i] for i in b[2]]
        ext = F(one(b, 4, b''))
        self.ext_types = [S[one(F(x), 1)] for x in ext[1]]
        self.ext_funcs = []
        for x in ext[2]:
            d = F(x)
            self.ext_funcs.append(dict(name=S[one(d, 1)], sig=one(d, 2), a=one(d, 3), b=one(d, 4)))
        self.ext_members = []
        for x in ext[4]:
            d = F(x)
            self.ext_members.append(dict(kind=one(d, 1), name=S[one(d, 2)], owner=one(d, 3), slot=one(d, 4), sig=one(d, 5)))
        self.ext_other = {k: v for k, v in ext.items() if k not in (1, 2, 4)}
        self.types = [F(x) for x in b[5]]
        self.classes = []
        for x in b[7]:
            d = F(x)
            c = dict(name=S[one(d, 1)], base=one(d, 2), members=[], raw=d)
            for mm in d[3]:
                md = F(mm)
                tdesc = one(md, 8)
                c['members'].append(dict(name=S[one(md, 1)], slot=one(md, 2), kind=one(md, 3),
                                         func=one(md, 4), ftype=(F(tdesc) if tdesc is not None else None), raw=md))
            self.classes.append(c)
        self.funcs = []
        for x in b[8]:
            d = F(x)
            hdr = F(one(d, 2))
            params = [S[one(F(p), 1)] for p in hdr[2]]
            consts = [F(c) for c in d[4]]
            code = P.decode_code(one(d, 5, b''))
            self.funcs.append(dict(sig=one(d, 1), name=S[one(hdr, 1)], params=params, consts=consts,
                                   code=code, f3=one(d, 3), raw=d))
        self.globals_raw = {k: v for k, v in b.items() if k not in (1, 2, 3, 4, 5, 6, 7, 8)}

    def tname(self, ti, depth=0):
        if ti is None:
            return '?'
        if ti >= len(self.types) or depth > 6:
            return 't%d' % ti
        t = self.types[ti]
        k = one(t, 1)
        S = self.strings
        if k == 1:
            return self.classes[one(t, 2, 0)]['name'] if one(t, 2, 0) < len(self.classes) else 'lc%d' % one(t, 2, 0)
        if k == 3:
            return self.ext_types[one(t, 2, 0)]
        if k == 4:
            d = F(one(t, 9))
            base = self.ext_types[one(d, 1, 0)]
            if d[2]:
                return '%s<%s>' % (base, ','.join(self.tname(a, depth + 1) for a in d[2]))
            return base
        if k == 9:
            d = F(one(t, 4))
            ret = self.tname(one(d, 1), depth + 1) if d.get(1) else 'void'
            return 'fn(%s)->%s' % (','.join(self.tname(a, depth + 1) for a in d[2]), ret)
        if k == 6:
            return S[one(t, 3)]
        if k == 8:
            return 'ref<%s>' % self.tname(one(t, 2), depth + 1)
        if k == 10:
            d = F(one(t, 6))
            return '%s<%s>' % (self.tname(one(d, 1), depth + 1).split('<')[0], self.tname(one(d, 3), depth + 1))
        if k == 5:
            d = F(one(t, 8))
            return self.ext_types[one(d, 3)] if one(d, 3) is not None and one(d, 3) < len(self.ext_types) else 'dlg?'
        if k == 2:
            d = F(one(t, 7))
            return S[one(d, 2)]
        return 'k%d:%s' % (k, {kk: vv for kk, vv in t.items() if kk != 1})

import os
def load_bundle(path=os.environ.get('SSL_BUNDLE', '../data/release.sslbundle')):
    d = open(path, 'rb').read()
    prefix, names, blobs = P.split_bundle(d)
    return names, blobs

_cache = {}
def get(name):
    global _names, _blobs, _idx
    if not _cache:
        _names, _blobs = load_bundle()
        _idx = {n: i for i, n in enumerate(_names)}
        _cache['x'] = 1
    return Mod(name, _blobs[_idx[name]])

def all_names():
    get('game.truck') if not _cache else None
    return _names
