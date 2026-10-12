import ssl as S, collections
from ssl import F, one
stats = collections.Counter(); ex = {}
for n in S.all_names():
    try:
        m = S.get(n)
    except Exception:
        continue
    for f in m.funcs:
        code = f['code']
        if not code or not isinstance(code, list):
            continue
        for k, (op, a) in enumerate(code):
            if op != 0x14 or k < 5:
                continue
            # [bound...][nbound][fnref][nparams][slot][obj...]
            # find pattern backwards: obj could be several instrs; search 04 nb, 06 c, 04 np, 04 slot
            for j in range(k - 1, max(0, k - 8), -1):
                if code[j][0] == 0x04 and code[j-1][0] == 0x04 and code[j-2][0] == 0x06 and code[j-3][0] == 0x04:
                    nb, c, np_ = code[j-3][1], code[j-2][1], code[j-1][1]
                    cc = f['consts'][c]
                    v = one(cc, 7) if cc.get(7) else None
                    stats[(v, nb, np_)] += 1
                    ex.setdefault((v, nb, np_), (n, f['name']))
                    break
for key, cnt in sorted(stats.items(), key=lambda x: -x[1])[:40]:
    print(key, cnt, ex[key])
