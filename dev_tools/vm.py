"""Mini SSL VM for testing patched functions with mock objects."""
import ssl as S, db as DB, dis as D
from ssl import F, one
CDB = DB.load()

class VMError(Exception): pass

GLOBALS = object()

class Obj:
    def __init__(self, cls, **fields):
        self.cls = cls
        self.f = dict(fields)   # by member name
        self.calls = []
    def __repr__(self):
        return '<%s %s>' % (self.cls, self.f.get('id') or self.f.get('name') or id(self) % 1000)

class Arr(list):
    cls = 'array'

class Delegate:
    def __init__(self, obj, slot, nparams, bound):
        self.obj, self.slot, self.nparams, self.bound = obj, slot, nparams, bound
    def __repr__(self):
        return '<dlg %r.%d %r>' % (self.obj, self.slot, self.bound)

def same(a, b):
    if isinstance(a, (Obj, Arr, Dct, Delegate)) or isinstance(b, (Obj, Arr, Dct, Delegate)):
        return a is b
    return a == b

class Dct(dict):
    cls = 'dict'

def member(cls, slot):
    c, mem = D.lookup(cls, slot)
    if not mem:
        raise VMError('no member %s.%d' % (cls, slot))
    return c, mem

class VM:
    def __init__(self, mod, impls, globals_):
        self.m = mod            # ssl.Mod
        self.impls = impls      # {(cls, name): fn(self_obj, *args)}
        self.g = globals_       # {gid: fn}
        self.trace = []

    def method_impl(self, obj, slot, base=None):
        cls = base or obj.cls
        c, mem = member(cls, slot)
        name = mem['name']
        # mock by any class in the chain
        cc = cls
        seen = 0
        while cc and seen < 20:
            if (cc, name) in self.impls:
                return name, self.impls[(cc, name)]
            e = CDB.get(cc)
            cc = D.base_name(e['base']) if e else None
            seen += 1
        if ('*', name) in self.impls:
            return name, self.impls[('*', name)]
        # script method of tested module class
        if c and CDB.get(c, {}).get('module') == self.m.name and mem.get('func') is not None:
            fi = mem['func']
            return name, (lambda o, *a, fi=fi: self.run(fi, o, list(a)))
        if ('*', '*') in self.impls:
            return name, (lambda o, *a, n=name: self.impls[('*', '*')](o, n, *a))
        raise VMError('unimplemented %s.%s (slot %d)' % (cls, name, slot))

    def invoke(self, dlg, *args):
        a = (list(dlg.bound) + list(args))[:dlg.nparams]
        name, impl = self.method_impl(dlg.obj, dlg.slot)
        return impl(dlg.obj, *a)

    def getf(self, obj, slot):
        if obj is None:
            raise VMError('null deref getf %d' % slot)
        if isinstance(obj, (Arr, Dct)):
            raise VMError('getf on container')
        c, mem = member(obj.cls, slot)
        if mem['name'] not in obj.f and getattr(self, 'lenient', False):
            ty = (mem.get('type') or 'object').split('<')[0]
            prim = {'int': 0, 'float': 0.0, 'bool': False, 'string': '', 'TruckRepairParts': 0}
            obj.f[mem['name']] = prim[ty] if ty in prim else (Arr() if ty == 'array' else (Dct() if ty == 'dict' else Obj(ty)))
        if mem['name'] not in obj.f:
            raise VMError('field %s.%s not set' % (obj.cls, mem['name']))
        return obj.f[mem['name']]

    def setf(self, obj, slot, v):
        c, mem = member(obj.cls, slot)
        obj.f[mem['name']] = v

    def const(self, f, k):
        c = f['consts'][k]
        kind = one(c, 1)
        if kind == 4:
            return self.m.strings[one(c, 5)]
        if kind == 5:
            return ('type', self.m.tname(one(c, 6)))
        if kind == 3:
            import struct
            return struct.unpack('<f', one(c, 4))[0]
        if kind == 1:
            return one(c, 2)
        if kind == 6:
            return ('fnref', one(c, 7))
        return ('const', kind)

    def call_container(self, obj, slot, args):
        if isinstance(obj, Arr):
            name = CDB['array']['members'][slot]['name']
            if name == 'Clear': obj.clear(); return None
            if name == 'Count': return len(obj)
            if name == 'IsEmpty': return len(obj) == 0
            if name == 'Add': obj.append(args[0]); return None
            if name == 'PushFront': obj.insert(0, args[0]); return None
            if name == 'RemoveAt':
                del obj[args[0]:args[0] + args[1]]; return None
            if name == 'Resize':
                n = args[0]
                if len(obj) < n: obj.extend([None] * (n - len(obj)))
                else: del obj[n:]
                return None
            if name == 'Clone': return Arr(obj)
            if name == 'Contains': return any(same(x, args[0]) for x in obj)
            if name == 'Get': return obj[args[0]]
            if name == 'IndexOf': return next((i for i, x in enumerate(obj) if same(x, args[0])), -1)
            raise VMError('array.' + name)
        if isinstance(obj, Dct):
            name = CDB['dict']['members'][slot]['name']
            if name == 'IsEmpty': return len(obj) == 0
            if name == 'Count': return len(obj)
            raise VMError('dict.' + name)
        raise VMError('container?')

    def run(self, fi, this, args, start=None, init_locals=None):
        f = self.m.funcs[fi]
        code = f['code']
        stack = []
        frame = [this] + list(args)
        locs = {}
        pc = 0
        if start is not None:
            n = code[0][1]
            stack = [None] * n
            locbase = 0
            for k, v in (init_locals or {}).items():
                stack[-k - 1] = v
            pc = start
        steps = 0
        while True:
            steps += 1
            if steps > 200000:
                raise VMError('too many steps')
            op, a = code[pc]
            if getattr(self, 'debug', None) == f['name']:
                print('  dbg', pc, '%02x' % op, a, stack[-3:])
            pc += 1
            if op == 0x01:
                stack += [None] * a
                if pc == 1 and any(o in (7, 0x3b) and x < 0 for o, x in code):
                    # locals reservation
                    base = len(stack) - a
                    locbase = base
            elif op == 0x02: stack.pop()
            elif op == 0x03: stack.append(None)
            elif op in (0x04, 0x05): stack.append(a if op == 4 else bool(a))
            elif op == 0x06: stack.append(self.const(f, a))
            elif op == 0x07:
                if a >= 0: stack.append(frame[a])
                else: stack.append(stack[locbase + (-a) - 1])
            elif op == 0x3b:
                stack[locbase + (-a) - 1] = stack[-1]
            elif op == 0x08: stack.append(GLOBALS)
            elif op == 0x0a:
                o = stack.pop(); stack.append(self.getf(o, a))
            elif op == 0x3c:
                o = stack.pop(); self.setf(o, a, stack[-1])
            elif op in (0x0d, 0x0e):
                if op == 0x0e:
                    bc = stack.pop()
                argc = stack.pop(); recv = stack.pop()
                cargs = [stack.pop() for _ in range(argc)]
                if recv is GLOBALS:
                    if a not in self.g: raise VMError('global %d' % a)
                    r = self.g[a](*cargs)
                elif recv is None:
                    raise VMError('null call slot %d at pc %d in %s' % (a, pc - 1, f['name']))
                elif isinstance(recv, (Arr, Dct)):
                    r = self.call_container(recv, a, cargs)
                else:
                    name, impl = self.method_impl(recv, a, bc[1] if op == 0x0e else None)
                    self.trace.append((recv, name, cargs))
                    r = impl(recv, *cargs)
                stack[-1] = r
            elif op == 0x0f:
                argc = stack.pop(); recv = stack.pop()
                for _ in range(argc): stack.pop()
                stack[-1] = None
            elif op == 0x12:
                return stack[-1]
            elif op == 0x13:
                return None
            elif op == 0x16:
                v = stack.pop()
                if not v: pc = a
            elif op == 0x18:
                if not stack[-1]: pc = a
            elif op == 0x19:
                if stack[-1]: pc = a
            elif op == 0x1a: pc = a
            elif op == 0x1b: stack[-1] = not stack[-1]
            elif op == 0x1d: stack[-1] = -stack[-1]
            elif op in (0x20, 0x21, 0x24, 0x25, 0x27, 0x28, 0x22):
                b = stack.pop(); x = stack.pop()
                stack.append(x + b if op in (0x20, 0x21, 0x22) else (x - b if op in (0x24, 0x25) else x * b))
            elif op == 0x2a:
                b = stack.pop(); x = stack.pop()
                stack.append(int(x / b))
            elif op == 0x30:
                b = stack.pop(); x = stack.pop()
                eq = same(x, b)
                stack.append(eq if a == 7 else not eq)
            elif op in (0x31, 0x32):
                b = stack.pop(); x = stack.pop()
                stack.append({9: x < b, 10: x > b, 11: x <= b, 12: x >= b}[a])
            elif op == 0x39:
                t = self.const(f, a)[1]
                if t.startswith('array'): o = Arr()
                elif t.startswith('dict'): o = Dct()
                else:
                    o = Obj(t)
                    for s_, mm in CDB.get(t, {}).get('members', {}).items():
                        ty = mm.get('type') or ''
                        if mm['kind'] == 5 and ty.startswith('array'): o.f[mm['name']] = Arr()
                stack.append(o)
            elif op == 0x3a:
                argc = stack.pop(); o = stack.pop()
                for _ in range(argc): stack.pop()
                stack[-1] = o
            elif op == 0x3f:
                arr = stack.pop(); i = stack.pop()
                if not (0 <= i < len(arr)): raise VMError('index %r out of range %d at pc %d in %s' % (i, len(arr), pc - 1, f['name']))
                stack.append(arr[i])
            elif op == 0x40:
                arr = stack.pop(); i = stack.pop(); arr[i] = stack[-1]
            elif op == 0x41:
                arr = stack.pop(); stack.append(len(arr))
            elif op == 0x42:
                arr = stack.pop(); arr.append(stack[-1])
            elif op == 0x44:
                d = stack.pop(); k = stack.pop(); stack.append(d.get(k))
            elif op == 0x45:
                d = stack.pop(); k = stack.pop(); d[k] = stack[-1]
            elif op == 0x47:
                d = stack.pop(); k = stack.pop(); dflt = stack.pop(); stack.append(d.get(k, dflt))
            elif op == 0x37:
                pass
            elif op == 0x35:
                t = self.const(f, a)
                tn = t[1] if isinstance(t, tuple) else None
                v = stack[-1]
                if tn == 'int': stack[-1] = int(v)
                elif tn == 'float': stack[-1] = float(v)
                elif tn == 'string': stack[-1] = str(v)
                elif tn == 'bool': stack[-1] = bool(v)
            elif op == 0x14:
                obj = stack.pop(); slot = stack.pop(); nparams = stack.pop(); stack.pop(); nb = stack.pop()
                bound = [stack.pop() for _ in range(nb)][::-1]
                stack.append(Delegate(obj, slot, nparams, bound))
            elif op == 0x10:
                dlg = stack.pop(); obj = stack.pop()
                ev = self.const(f, a)
                obj.f.setdefault('__ev', {}).setdefault(ev, []).append(dlg)
                self.trace.append((obj, '+event%d' % ev, [dlg]))
                stack.append(None)
            elif op == 0x11:
                obj = stack.pop(); sub = stack.pop()
                ev = self.const(f, a)
                lst = obj.f.setdefault('__ev', {}).setdefault(ev, [])
                lst[:] = [d for d in lst if d.obj is not sub]
                self.trace.append((obj, '-event%d' % ev, [sub]))
            else:
                raise VMError('op %02x at %d' % (op, pc - 1))
