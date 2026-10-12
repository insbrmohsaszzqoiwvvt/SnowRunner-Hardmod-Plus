import sys, pickle, ssl as S, dis as D
pm = pickle.load(open('../data/patched_release.pkl','rb'))
mod = sys.argv[1]; names = sys.argv[2:]
m = S.Mod(mod, pm[mod])
d = D.Dis(m)
for i, f in enumerate(m.funcs):
    if f['name'] in names and f['code']:
        d.dis(i)
