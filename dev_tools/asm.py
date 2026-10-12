"""Mini compiler for SSL bytecode: expressions/statements -> instructions with labels,
and patching of existing function code (with jump remapping)."""
import itertools

JUMPS = (0x16, 0x18, 0x19, 0x1A)
_lab = itertools.count()

def newlabel(prefix='L'):
    return '%s%d' % (prefix, next(_lab))

# items: ('i', op, arg) | ('j', op, target) | ('l', name)
# target: label name (str) or ('orig', idx)

def I(op, arg=0):
    return ('i', op, arg)

def J(op, target):
    return ('j', op, target)

def Lbl(name):
    return ('l', name)

# ---------------------------------------------------------------- expressions
class E:
    def emit(self):
        raise NotImplementedError

class Raw(E):
    def __init__(self, *items):
        self.items = list(items)
    def emit(self):
        return list(self.items)

class Local(E):
    def __init__(self, k): self.k = k
    def emit(self): return [I(0x07, self.k)]

THIS = Local(0)

def Param(k):
    return Local(k)

class Int(E):
    def __init__(self, v): self.v = v
    def emit(self): return [I(0x04, self.v)]

class Bool(E):
    def __init__(self, v): self.v = 1 if v else 0
    def emit(self): return [I(0x05, self.v)]

class NullE(E):
    def emit(self): return [I(0x03)]
NULL = NullE()

class Const(E):
    def __init__(self, k): self.k = k
    def emit(self): return [I(0x06, self.k)]

class Call(E):
    """recv.method(args) by vtable slot"""
    def __init__(self, recv, slot, *args):
        self.recv, self.slot, self.args = recv, slot, args
    def emit(self):
        out = [I(0x01, 1)]
        for a in reversed(self.args):
            out += a.emit()
        out += self.recv.emit()
        out += [I(0x04, len(self.args)), I(0x0D, self.slot)]
        return out

class GCall(E):
    """global function by global id"""
    def __init__(self, gid, *args):
        self.gid, self.args = gid, args
    def emit(self):
        out = [I(0x01, 1)]
        for a in reversed(self.args):
            out += a.emit()
        out += [I(0x08), I(0x04, len(self.args)), I(0x0D, self.gid)]
        return out

class Field(E):
    def __init__(self, obj, slot): self.obj, self.slot = obj, slot
    def emit(self): return self.obj.emit() + [I(0x0A, self.slot)]

class ArrGet(E):
    def __init__(self, arr, idx): self.arr, self.idx = arr, idx
    def emit(self): return self.idx.emit() + self.arr.emit() + [I(0x3F)]

class Count(E):
    def __init__(self, arr): self.arr = arr
    def emit(self): return self.arr.emit() + [I(0x41)]

class New(E):
    """new object of type const k (function const of kind 5)"""
    def __init__(self, k): self.k = k
    def emit(self): return [I(0x01, 1), I(0x39, self.k), I(0x04, 0), I(0x3A, self.k)]

class Bin(E):
    def __init__(self, op, a, b, arg=0): self.op, self.a, self.b, self.arg = op, a, b, arg
    def emit(self): return self.a.emit() + self.b.emit() + [I(self.op, self.arg)]

def Add(a, b): return Bin(0x20, a, b)
def Sub(a, b): return Bin(0x24, a, b)
def Eq(a, b): return Bin(0x30, a, b, 7)
def Ne(a, b): return Bin(0x30, a, b, 8)
def Lt(a, b): return Bin(0x31, a, b, 9)
def Gt(a, b): return Bin(0x31, a, b, 10)
def Le(a, b): return Bin(0x31, a, b, 11)
def Ge(a, b): return Bin(0x31, a, b, 12)

class Not(E):
    def __init__(self, a): self.a = a
    def emit(self): return self.a.emit() + [I(0x1B)]

class And(E):
    def __init__(self, *xs): self.xs = xs
    def emit(self):
        end = newlabel('and')
        out = self.xs[0].emit()
        for x in self.xs[1:]:
            out += [J(0x18, end), I(0x02)] + x.emit()
        return out + [Lbl(end)]

class Or(E):
    def __init__(self, *xs): self.xs = xs
    def emit(self):
        end = newlabel('or')
        out = self.xs[0].emit()
        for x in self.xs[1:]:
            out += [J(0x19, end), I(0x02)] + x.emit()
        return out + [Lbl(end)]

# ---------------------------------------------------------------- statements
_loops = []

def emit_block(stmts):
    out = []
    for s in stmts:
        out += s.emit()
    return out

class S:
    def emit(self):
        raise NotImplementedError

class RawS(S):
    def __init__(self, *items): self.items = list(items)
    def emit(self): return list(self.items)

class SetLocal(S):
    def __init__(self, k, e): self.k, self.e = k, e
    def emit(self): return self.e.emit() + [I(0x3B, self.k), I(0x02)]

class SetField(S):
    def __init__(self, obj, slot, val): self.obj, self.slot, self.val = obj, slot, val
    def emit(self): return self.val.emit() + self.obj.emit() + [I(0x3C, self.slot), I(0x02)]

class Do(S):
    """evaluate expression (call) and drop the result"""
    def __init__(self, e): self.e = e
    def emit(self): return self.e.emit() + [I(0x02)]

class ArrAdd(S):
    def __init__(self, arr, val): self.arr, self.val = arr, val
    def emit(self): return self.val.emit() + self.arr.emit() + [I(0x42), I(0x02)]

class If(S):
    def __init__(self, cond, then, els=()):
        self.cond, self.then, self.els = cond, list(then), list(els)
    def emit(self):
        lelse, lend = newlabel('else'), newlabel('endif')
        out = self.cond.emit() + [J(0x16, lelse)] + emit_block(self.then)
        if self.els:
            out += [J(0x1A, lend), Lbl(lelse)] + emit_block(self.els) + [Lbl(lend)]
        else:
            out += [Lbl(lelse)]
        return out

class While(S):
    def __init__(self, cond, body, step=()):
        self.cond, self.body, self.step = cond, list(body), list(step)
    def emit(self):
        top, cont, end = newlabel('wtop'), newlabel('wcont'), newlabel('wend')
        _loops.append((cont, end))
        try:
            body = emit_block(self.body)
        finally:
            _loops.pop()
        return ([Lbl(top)] + self.cond.emit() + [J(0x16, end)] + body + [Lbl(cont)]
                + emit_block(self.step) + [J(0x1A, top), Lbl(end)])

class Break(S):
    def emit(self): return [J(0x1A, _loops[-1][1])]

class Continue(S):
    def emit(self): return [J(0x1A, _loops[-1][0])]

def ForArray(arr, i, n, el, body):
    """for (i = 0, n = arr.Count; i < n; i++) { el = arr[i]; body }  (arr must be side-effect free)"""
    return Block([SetLocal(n, Count(arr)), SetLocal(i, Int(0)),
                  While(Lt(Local(i), Local(n)), [SetLocal(el, ArrGet(arr, Local(i)))] + list(body),
                        step=[SetLocal(i, Add(Local(i), Int(1)))])])

class Block(S):
    def __init__(self, stmts): self.stmts = list(stmts)
    def emit(self): return emit_block(self.stmts)

class Goto(S):
    def __init__(self, target): self.target = target
    def emit(self): return [J(0x1A, self.target)]

class Return(S):
    def __init__(self, e, n): self.e, self.n = e, n
    def emit(self): return self.e.emit() + [I(0x12, self.n)]

class ReturnVoid(S):
    def __init__(self, n): self.n = n
    def emit(self): return [I(0x13, self.n)]

def compile_stmts(stmts):
    return emit_block(stmts)

# ---------------------------------------------------------------- linking

def link(items, base=0):
    """items -> [(op, arg)], resolving labels; ('orig', i) targets are not allowed here."""
    pos = {}
    n = 0
    for it in items:
        if it[0] == 'l':
            if it[1] in pos:
                raise ValueError('duplicate label ' + it[1])
            pos[it[1]] = base + n
        else:
            n += 1
    out = []
    for it in items:
        if it[0] == 'i':
            out.append((it[1], it[2]))
        elif it[0] == 'j':
            out.append((it[1], pos[it[2]]))
    return out


class FunctionPatch:
    """Edit existing code: insert/replace with new items. Original jumps are remapped."""

    def __init__(self, code):
        self.code = list(code)
        self.before = {}     # orig idx -> list of (items, redirect)
        self.replaced = {}   # orig start -> (end, items)

    def insert(self, idx, items, redirect=True):
        """insert items before original instruction idx. redirect: original jumps to idx land
        on the inserted code (True) or skip it (False)."""
        self.before.setdefault(idx, []).append((list(items), redirect))

    def replace(self, start, end, items):
        """replace original instructions [start, end) by items; jumps to start land on items."""
        for s, (e, _) in self.replaced.items():
            if not (end <= s or start >= e):
                raise ValueError('overlapping replace')
        self.replaced[start] = (end, list(items))

    def build(self):
        items = []
        orig_label = {}
        skip_until = -1
        inner = set()
        for s, (e, _) in self.replaced.items():
            inner.update(range(s + 1, e))
        for i, ins_ in enumerate(self.code + [(None, None)]):
            op, a = ins_
            lab_redirect = 'o%d' % i
            ins = self.before.get(i, [])
            # label for jumps: placed before redirecting inserts, after non-redirecting ones
            redir = [x for x in ins if x[1]]
            nored = [x for x in ins if not x[1]]
            for its, _ in nored:
                items += its
            items.append(Lbl(lab_redirect))
            for its, _ in redir:
                items += its
            if i == len(self.code):
                break
            if i in self.replaced:
                end, its = self.replaced[i]
                items += its
                skip_until = end
            if i < skip_until:
                continue
            if op in JUMPS:
                if a in inner:
                    raise ValueError('jump into replaced range: %d -> %d' % (i, a))
                items.append(J(op, 'o%d' % a))
            else:
                items.append(I(op, a))
        # resolve ('orig', k) targets inside new items
        fixed = []
        for it in items:
            if it[0] == 'j' and isinstance(it[2], tuple):
                if it[2][1] in inner:
                    raise ValueError('jump into replaced range')
                fixed.append(J(it[1], 'o%d' % it[2][1]))
            else:
                fixed.append(it)
        return link(fixed)
