"""Editing of compiled SSL modules (protobuf body), preserving untouched bytes."""
import pip as P

def varint(v):
    if v < 0:
        v += 1 << 64
    return P.varint(v)

def key(f, wt):
    return varint((f << 3) | wt)

def enc_field(f, v):
    if isinstance(v, int):
        return key(f, 0) + varint(v)
    return key(f, 2) + varint(len(v)) + v

def parse(buf):
    """[(field, value)] value: int or bytes (wiretypes 0/2 only, others kept as ('raw', bytes))."""
    out = []
    for f, s, e, v in P.pb_fields(buf):
        wt = P.read_varint(buf, s)[0] & 7
        if wt in (0, 2):
            out.append((f, v))
        else:
            out.append((f, ('raw', buf[s:e])))
    return out

def serialize(fields):
    b = bytearray()
    for f, v in fields:
        if isinstance(v, tuple):
            b += v[1]
        else:
            b += enc_field(f, v)
    return bytes(b)

def msg(**kw):
    """build message from f<N>=value (lists for repeated)."""
    items = sorted(((int(k[1:]), v) for k, v in kw.items()), key=lambda x: x[0])
    out = []
    for f, v in items:
        for x in (v if isinstance(v, list) else [v]):
            out.append((f, x))
    return serialize(out)

def get(fields, f):
    return [v for ff, v in fields if ff == f]

def first(fields, f, d=None):
    r = get(fields, f)
    return r[0] if r else d

def insert_after_group(fields, f, newvals):
    """insert (f, v) entries after the last entry with field f (or in field order)."""
    idx = None
    for i, (ff, v) in enumerate(fields):
        if ff == f:
            idx = i
    if idx is None:
        idx = 0
        for i, (ff, v) in enumerate(fields):
            if ff < f:
                idx = i + 1
        idx -= 1
    for k, v in enumerate(newvals):
        fields.insert(idx + 1 + k, (f, v))


class ModEditor:
    def __init__(self, module):
        """module: pip.Module"""
        self.module = module
        self.fields = parse(module.body)
        self.strings = [s.decode('utf-8') for s in get(self.fields, 6)]
        self.types = list(get(self.fields, 5))
        self.ext = parse(first(self.fields, 4, b''))
        self.funcs = list(get(self.fields, 8))
        self.new_strings = []
        self.new_types = []
        self.dirty_ext = False
        self.func_updates = {}

    # --- strings
    def string(self, s):
        allstr = self.strings + self.new_strings
        if s in allstr:
            return allstr.index(s)
        self.new_strings.append(s)
        return len(allstr)

    # --- types
    def all_types(self):
        return self.types + self.new_types

    def type_raw(self, i):
        return self.all_types()[i]

    def add_type(self, raw):
        at = self.all_types()
        if raw in at:
            return at.index(raw)
        self.new_types.append(raw)
        return len(at)

    # --- externals
    def ext_type_names(self):
        allstr = self.strings + self.new_strings
        return [allstr[first(parse(v), 1)] for f, v in self.ext if f == 1]

    def ext_type(self, name):
        names = self.ext_type_names()
        if name in names:
            return names.index(name)
        si = self.string(name)
        newv = msg(f1=si)
        last1 = max([i for i, (f, v) in enumerate(self.ext) if f == 1], default=-1)
        self.ext.insert(last1 + 1, (1, newv))
        self.dirty_ext = True
        return len(names)

    def ext_members(self):
        out = []
        for f, v in self.ext:
            if f == 4:
                p = parse(v)
                out.append(dict(kind=first(p, 1), name=first(p, 2), owner=first(p, 3), slot=first(p, 4), sig=first(p, 5)))
        return out

    def add_ext_member(self, kind, name, owner_t, slot, sig_t):
        si = self.string(name)
        for e in self.ext_members():
            if e['name'] == si and e['owner'] == owner_t and e['slot'] == slot:
                return
        fl = [(1, kind), (2, si), (3, owner_t), (4, slot), (5, sig_t)]
        last = max([i for i, (f, v) in enumerate(self.ext) if f == 4], default=len(self.ext) - 1)
        self.ext.insert(last + 1, (4, serialize(fl)))
        self.dirty_ext = True

    # --- functions
    def func_index(self, name, nth=0):
        hits = []
        for i, raw in enumerate(self.funcs):
            fl = parse(raw)
            hdr = parse(first(fl, 2))
            if self.strings[first(hdr, 1)] == name:
                hits.append(i)
        return hits[nth] if hits else None

    def func_fields(self, i):
        return parse(self.func_updates.get(i, self.funcs[i]))

    def func_code(self, i):
        fl = self.func_fields(i)
        return P.decode_code(first(fl, 5, b''))

    def func_consts(self, i):
        return [parse(c) for c in get(self.func_fields(i), 4)]

    def add_func_const(self, i, raw):
        """returns const index (existing equal const reused)."""
        fl = self.func_fields(i)
        cs = get(fl, 4)
        if raw in cs:
            return cs.index(raw)
        idx = len(cs)
        insert_after_group(fl, 4, [raw])
        self.func_updates[i] = serialize(fl)
        return idx

    def const_string(self, i, s):
        return self.add_func_const(i, msg(f1=4, f5=self.string(s)))

    def const_type(self, i, tidx):
        return self.add_func_const(i, msg(f1=5, f6=tidx))

    def set_func_code(self, i, instrs):
        fl = self.func_fields(i)
        code = P.encode_code(instrs)
        out = []
        done = False
        for f, v in fl:
            if f == 5:
                out.append((5, code))
                done = True
            else:
                out.append((f, v))
        if not done:
            out.append((5, code))
        self.func_updates[i] = serialize(out)

    # --- build
    def body(self):
        fields = list(self.fields)
        # functions
        fi = 0
        out = []
        for f, v in fields:
            if f == 8:
                out.append((8, self.func_updates.get(fi, v)))
                fi += 1
            elif f == 4 and self.dirty_ext:
                out.append((4, serialize(self.ext)))
            else:
                out.append((f, v))
        fields = out
        if self.new_types:
            insert_after_group(fields, 5, self.new_types)
        if self.new_strings:
            insert_after_group(fields, 6, [s.encode('utf-8') for s in self.new_strings])
        return serialize(fields)

    def commit(self):
        self.module.body = self.body()


# ---------------------------------------------------------------------------
# Copying type descriptors / external member entries between modules

def import_type(dst, src, ti):
    """dst: ModEditor, src: ModEditor; returns type index in dst."""
    raw = src.type_raw(ti)
    fl = parse(raw)
    k = first(fl, 1)
    sstr = src.strings + src.new_strings
    names = src.ext_type_names()
    if k == 3:
        return dst.add_type(msg(f1=3, f2=dst.ext_type(names[first(fl, 2)])))
    if k == 4:
        d = parse(first(fl, 9))
        args = [import_type(dst, src, a) for a in get(d, 2)]
        inner = [(1, dst.ext_type(names[first(d, 1)]))] + [(2, a) for a in args]
        return dst.add_type(serialize([(1, 4), (9, serialize(inner))]))
    if k == 6:
        return dst.add_type(msg(f1=6, f3=dst.string(sstr[first(fl, 3)])))
    if k == 8:
        return dst.add_type(msg(f1=8, f2=import_type(dst, src, first(fl, 2))))
    if k == 9:
        d = parse(first(fl, 4))
        inner = []
        for f, v in d:
            if f in (1, 2):
                inner.append((f, import_type(dst, src, v)))
            else:
                raise ValueError('sig field %d' % f)
        return dst.add_type(serialize([(1, 9), (4, serialize(inner))]))
    if k == 10:
        d = parse(first(fl, 6))
        inner = []
        for f, v in d:
            if f in (1, 3):
                inner.append((f, import_type(dst, src, v)))
            else:
                inner.append((f, v))
        return dst.add_type(serialize([(1, 10), (6, serialize(inner))]))
    if k == 5:
        d = parse(first(fl, 8))
        inner = [(1, import_type(dst, src, first(d, 1))), (2, dst.string(sstr[first(d, 2)])),
                 (3, dst.ext_type(names[first(d, 3)]))]
        return dst.add_type(serialize([(1, 5), (8, serialize(inner))]))
    raise ValueError('cannot import type kind %s' % k)


def find_ext_member_source(owner_name, member_name, slot, bundle_mods):
    """Find a module (ModEditor) that already imports owner.member (by class base name)."""
    import ssl as S
    for n, me in bundle_mods():
        names = me.ext_type_names()
        sstr = me.strings
        for e in me.ext_members():
            if sstr[e['name']] != member_name or e['slot'] != slot:
                continue
            t = parse(me.type_raw(e['owner']))
            k = first(t, 1)
            if k == 4:
                on = names[first(parse(first(t, 9)), 1)]
            elif k == 3:
                on = names[first(t, 2)]
            else:
                continue
            if on == owner_name:
                return me, e
    return None, None


def import_ext_member(dst, src, e):
    owner = import_type(dst, src, e['owner'])
    sig = import_type(dst, src, e['sig'])
    dst.add_ext_member(e['kind'], src.strings[e['name']], owner, e['slot'], sig)
