import sys, io, ssl as S, dis as D
pat = sys.argv[1]
for n in S.all_names():
    try:
        m = S.get(n)
        d = D.Dis(m)
        for i, f in enumerate(m.funcs):
            if not f['code']:
                continue
            buf = io.StringIO()
            try:
                d.dis(i, out=buf)
            except Exception:
                continue
            txt = buf.getvalue()
            if pat in txt:
                head = txt.splitlines()[0]
                for ln in txt.splitlines():
                    if pat in ln:
                        print(n, '|', head, '|', ln.strip())
    except Exception as e:
        pass
