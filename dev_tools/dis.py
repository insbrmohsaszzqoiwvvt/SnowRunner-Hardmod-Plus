import sys, ssl as S, db as DB
from ssl import F, one

CDB = DB.load()
OPN = {0x01: 'reserve', 0x02: 'pop', 0x03: 'null', 0x04: 'int', 0x05: 'bool', 0x06: 'const', 0x07: 'local',
       0x08: 'globals', 0x0a: 'getf', 0x0d: 'call', 0x0e: 'callbase', 0x12: 'ret', 0x13: 'retv', 0x16: 'jf',
       0x18: 'jfk', 0x19: 'jtk', 0x1a: 'jmp', 0x3b: 'setl', 0x3c: 'setf', 0x35: 'cast', 0x30: 'cmp', 0x31: 'cmp2'}

def base_name(t):
    if not t: return t
    return t.split('<')[0]

def lookup(cls, slot):
    seen = 0
    c = base_name(cls)
    while c and c in CDB and seen < 30:
        e = CDB[c]
        if slot in e['members']:
            return c, e['members'][slot]
        c = base_name(e['base'])
        seen += 1
    if slot in CDB['object']['members']:
        return 'object', CDB['object']['members'][slot]
    return None, None

def tmpl(t, rt):
    """substitute T in rt using template args of t (array<X>)"""
    if t and '<' in t and rt and 'T' in rt:
        arg = t[t.index('<') + 1:-1]
        import re
        return re.sub(r'\bT\b', arg, rt)
    return rt

def strip_ref(t):
    if t and t.startswith('ref<'):
        return t[4:-1]
    return t

class Dis:
    def __init__(self, mod):
        self.m = S.get(mod) if isinstance(mod, str) else mod

    def const_desc(self, f, k):
        m = self.m
        if k >= len(f['consts']):
            return 'const?%d' % k, None
        c = f['consts'][k]
        kind = one(c, 1)
        if kind == 1:
            v = one(c, 2)
            return 'C_str?%d' % v, 'string'
        if kind == 4:
            v = one(c, 5)
            return 'C_str:%r' % m.strings[v], 'string'
        if kind == 5:
            v = one(c, 6)
            return 'C_dlg:%s' % m.tname(v), m.tname(v)
        if kind == 6:
            v = one(c, 7)
            return 'C_fn:%s' % (m.funcs[v]['name'] if v < len(m.funcs) else v), 'fnref'
        return 'C?%s' % dict(c), None

    def func_class(self, fi):
        for c in self.m.classes:
            for mm in c['members']:
                if mm['kind'] == 2 and mm['func'] == fi:
                    return c['name']
        return None

    def dis(self, fi, out=sys.stdout):
        m = self.m
        f = m.funcs[fi]
        cls = self.func_class(fi)
        sig = F(one(m.types[f['sig']], 4))
        argt = [m.tname(a) for a in sig[2]]
        ret = m.tname(one(sig, 1)) if sig.get(1) else 'void'
        print('\n=== %s.%s(%s) -> %s   [func %d]' % (cls, f['name'], ', '.join('%s %s' % (t, n) for t, n in zip(argt, f['params'])), ret, fi), file=out)
        locs = {}
        stack = []
        for pc, (op, a) in enumerate(f['code']):
            note = ''
            name = OPN.get(op, 'op%02x' % op)
            try:
                if op == 0x01:
                    stack += [(None, None)] * a
                elif op == 0x02:
                    stack.pop()
                elif op == 0x03:
                    stack.append(('null', None))
                elif op == 0x04:
                    stack.append(('int', a))
                elif op == 0x05:
                    stack.append(('bool', a))
                elif op == 0x06:
                    d, t = self.const_desc(f, a)
                    note = d
                    stack.append((t, d))
                elif op == 0x07:
                    if a == 0:
                        t = cls; note = 'this'
                    elif a > 0:
                        t = argt[a - 1] if a - 1 < len(argt) else None
                        note = f['params'][a - 1] if a - 1 < len(f['params']) else 'arg%d' % a
                    else:
                        t = locs.get(a); note = 'L%d' % -a
                    stack.append((t, note))
                    note += ' : %s' % t
                elif op == 0x08:
                    stack.append(('GLOBALS', None))
                elif op == 0x0a:
                    t, _ = stack.pop()
                    c, mem = lookup(t, a)
                    if mem:
                        ft = tmpl(t, mem.get('type'))
                        note = '%s.%s : %s' % (c, mem['name'], ft)
                    else:
                        ft = None; note = '%s.?%d' % (t, a)
                    stack.append((ft, None))
                elif op == 0x3c:
                    t, _ = stack.pop()
                    c, mem = lookup(t, a)
                    note = '%s.%s =' % (c, mem['name']) if mem else '%s.?%d =' % (t, a)
                elif op == 0x3b:
                    locs[a] = stack[-1][0]
                    note = 'L%d = (%s)' % (-a, stack[-1][0])
                elif op in (0x0d, 0x0e):
                    if op == 0x0e:
                        bc = stack.pop()
                        bcls = bc[0]
                    argc = stack.pop()
                    n = argc[1] if argc[0] == 'int' else 0
                    rt, _ = stack.pop()
                    for _ in range(n):
                        stack.pop()
                    if rt == 'GLOBALS':
                        efs = [e for e in m.ext_funcs if e['a'] == a]
                        if efs:
                            ef = efs[0]
                            sd = F(one(m.types[ef['sig']], 4))
                            r = m.tname(one(sd, 1)) if sd.get(1) else 'void'
                            note = 'G:%s(%d) -> %s' % (ef['name'], n, r)
                        else:
                            r = None; note = 'G?%d' % a
                    else:
                        c, mem = lookup(bcls if op == 0x0e else rt, a)
                        if mem:
                            r = tmpl(rt, mem.get('ret'))
                            note = '%s.%s(%d) -> %s' % (c, mem['name'], n, r)
                        else:
                            r = None; note = '%s.?%d(%d)' % (rt, a, n)
                    r = strip_ref(r)
                    if stack:
                        stack[-1] = (r, None)
                elif op == 0x3f:
                    arr, _ = stack.pop(); stack.pop()
                    el = arr[arr.index('<')+1:-1] if arr and '<' in arr else None
                    note = 'array[idx] : %s' % el
                    stack.append((el, None))
                elif op == 0x39:
                    d, t = self.const_desc(f, a) if a < len(f['consts']) else ('?', None)
                    note = 'new? %s' % d
                    stack.append((t, None))
                elif op == 0x3a:
                    stack.pop(); note = 'ctor'
                elif op == 0x41:
                    stack.pop(); stack.append(('int', None)); note = 'count'
                elif op == 0x42:
                    stack.pop(); note = 'array.Add(v)'
                elif op == 0x35:
                    t, _ = stack.pop()
                    note = 'cast %s' % a
                    stack.append((t, None))
            except IndexError:
                note += ' [stack underflow]'
                stack = []
            print('%4d  %02x %-8s %6d   %s' % (pc, op, name, a, note), file=out)

def main():
    mod = sys.argv[1]
    d = Dis(mod)
    names = sys.argv[2:]
    for i, f in enumerate(d.m.funcs):
        if not names or f['name'] in names:
            if f['code']:
                d.dis(i)

if __name__ == '__main__':
    main()
