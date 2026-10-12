import sys, io, ssl as S, dis as D
pat = sys.argv[1]; before = int(sys.argv[2]) if len(sys.argv) > 2 else 3
limit = int(sys.argv[3]) if len(sys.argv) > 3 else 40
hits = 0
for n in S.all_names():
    try:
        m = S.get(n); d = D.Dis(m)
    except Exception:
        continue
    for i, f in enumerate(m.funcs):
        if not f['code']:
            continue
        buf = io.StringIO()
        try:
            d.dis(i, out=buf)
        except Exception:
            continue
        lines = buf.getvalue().splitlines()
        for k, ln in enumerate(lines):
            if pat in ln:
                print('##', n, lines[0][:110])
                for x in lines[max(1, k - before):k + 1]:
                    print('   ', x.strip())
                hits += 1
                if hits >= limit:
                    sys.exit()
