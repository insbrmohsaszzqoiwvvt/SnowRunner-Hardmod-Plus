"""Stack-depth verifier for SSL bytecode."""
import ssl as S
JUMPS = {0x16, 0x18, 0x19, 0x1a}
BIN = set(range(0x1f, 0x35)) - {0x1d, 0x1e}   # binary ops (to refine)
FIXED = {0x02: -1, 0x03: 1, 0x04: 1, 0x05: 1, 0x06: 1, 0x07: 1, 0x08: 1, 0x09: 1,
         0x0a: 0, 0x3b: 0, 0x3c: -1, 0x1b: 0, 0x1d: 0, 0x1e: 0, 0x35: 0, 0x37: 0, 0x38: 1,
         0x39: 1, 0x3f: -1, 0x40: -2, 0x41: 0, 0x42: -1, 0x44: -1, 0x45: -2,
         0x10: -1, 0x11: -2, 0x46: -2, 0x47: -2, 0x48: 0, 0x43: 0, 0x36: 0, 0x16: -1, 0x18: 0, 0x19: 0, 0x1a: 0}
CALLS = {0x0d: 2, 0x0e: 3, 0x0f: 2, 0x3a: 2, 0x14: 4}
OPCALL = {0x15: 1}

class VerifyError(Exception):
    pass

def effect(code, pc, depth_stack_ints):
    op, a = code[pc]
    if op == 0x01:
        return a
    if op in CALLS:
        n = depth_stack_ints
        if n is None:
            raise VerifyError('argc unknown at %d' % pc)
        return -(n + CALLS[op])
    if op in OPCALL:
        return -(a + OPCALL[op])
    if op in FIXED:
        return FIXED[op]
    if op in BIN:
        return -1
    raise VerifyError('unknown op %02x at %d' % (op, pc))

def verify(code, nparams=None):
    """returns max depth; raises VerifyError."""
    n = len(code)
    depth = [None] * n
    # track last pushed int literal for argc (by position in abstract stack)
    work = [(0, 0, ())]
    maxd = 0
    while work:
        pc, d, ints = work.pop()
        while True:
            if pc >= n:
                raise VerifyError('fell off end')
            if depth[pc] is not None:
                if depth[pc] != d:
                    raise VerifyError('depth mismatch at %d: %d vs %d' % (pc, depth[pc], d))
                break
            depth[pc] = d
            op, a = code[pc]
            if op in (0x12, 0x13):
                break
            argc = None
            if op in CALLS:
                idx = d - (2 if op == 0x0e else 1)
                lit = dict(ints).get(idx)
                if op == 0x0e:
                    lit = dict(ints).get(d - 2)
                if op == 0x14:
                    lit = dict(ints).get(d - 5)
                argc = lit
            e = effect(code, pc, argc)
            nd = d + e
            if nd < 0:
                raise VerifyError('stack underflow at %d' % pc)
            # maintain int literal map: position -> value
            im = {k: v for k, v in ints if k < min(d, nd) or (k < d and e >= 0 and k < d)}
            im = {k: v for k, v in ints if k < nd and k < d - (0 if e >= 0 else 0)}
            # drop entries above new top
            im = {k: v for k, v in im.items() if k < nd}
            if op == 0x04:
                im[d] = a
            elif op not in (0x18, 0x19, 0x1a, 0x3b) and e >= 0 and op != 0x01:
                im.pop(nd - 1, None)
            if op in (0x0d, 0x0e, 0x0f, 0x3a, 0x02, 0x16) or e < 0:
                im = {k: v for k, v in im.items() if k < nd}
                if op in (0x0d, 0x0e, 0x0f, 0x3a, 0x14):
                    im.pop(nd - 1, None)
            ints2 = tuple(sorted(im.items()))
            maxd = max(maxd, nd)
            if op in JUMPS:
                tgt = a
                if not 0 <= tgt < n:
                    raise VerifyError('bad jump target %d at %d' % (tgt, pc))
                td = nd if op != 0x16 else nd
                work.append((tgt, td, ints2))
                if op == 0x1a:
                    break
            pc += 1
            d = nd
            ints = ints2
    return maxd

if __name__ == '__main__':
    from collections import Counter
    errs = Counter(); ex = {}
    total = 0
    for name in S.all_names():
        m = S.get(name)
        for f in m.funcs:
            if not f['code']:
                continue
            total += 1
            try:
                verify(f['code'])
            except VerifyError as e:
                k = str(e).split(' at ')[0]
                errs[k] += 1
                ex.setdefault(k, []).append((name, f['name'], str(e)))
    print('functions', total, 'errors', sum(errs.values()))
    for k, c in errs.most_common():
        print(c, k, ex[k][:3])
