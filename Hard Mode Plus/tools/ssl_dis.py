"""
Дизассемблер скриптов SnowRunner (модули SSL) с именами методов и полей.

  python ssl_dis.py <initial.pak | *.sslbundle> --list [подстрока]   # список модулей
  python ssl_dis.py <initial.pak | *.sslbundle> <модуль> [функция ...]

Имена членов восстанавливаются по типам (локальные, параметры, поля, результаты
вызовов). Первый запуск строит базу классов (~20 с) и кэширует её рядом с файлом.
Формат вывода: номер инструкции, опкод, операнд, пояснение.
"""
import os
import pickle
import re
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import sslpatch as L  # noqa: E402

OPN = {0x01: "reserve", 0x02: "pop", 0x03: "null", 0x04: "int", 0x05: "bool", 0x06: "const",
       0x07: "local", 0x08: "globals", 0x0A: "getf", 0x0D: "call", 0x0E: "callbase", 0x0F: "fire",
       0x10: "subscribe", 0x11: "unsubscribe", 0x12: "ret", 0x13: "retv", 0x14: "delegate",
       0x15: "invoke", 0x16: "jf", 0x18: "jf_keep", 0x19: "jt_keep", 0x1A: "jmp", 0x1B: "not",
       0x1D: "neg", 0x20: "add", 0x21: "fadd", 0x22: "concat", 0x24: "sub", 0x25: "fsub",
       0x27: "mul", 0x28: "fmul", 0x2A: "div", 0x2B: "fdiv", 0x30: "eq/ne", 0x31: "cmp",
       0x32: "fcmp", 0x35: "cast", 0x36: "is", 0x37: "as", 0x38: "default", 0x39: "new",
       0x3A: "ctor", 0x3B: "setl", 0x3C: "setf", 0x3F: "aget", 0x40: "aset", 0x41: "count",
       0x42: "aadd", 0x44: "dget", 0x45: "dset", 0x46: "dadd", 0x47: "dgetadd", 0x48: "dcount"}
CMP = {7: "==", 8: "!=", 9: "<", 10: ">", 11: "<=", 12: ">="}


def load_bundle(path):
    if path.lower().endswith(".pak"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.replace("\\", "/").endswith("initial_release.sslbundle"))
            data = z.read(name)
    else:
        data = open(path, "rb").read()
    _, names, blobs = L.split_bundle(data)
    return dict(zip(names, blobs))


def build_db(mods, cache):
    if os.path.exists(cache):
        return pickle.load(open(cache, "rb"))
    db = {}
    for n, blob in mods.items():
        e = L.ModEditor(blob, n)
        for ci in range(len(e.classes_raw)):
            fl = L.pb_parse(e.classes_raw[ci])
            base = L.pb_first(fl, 2)
            mem = {}
            for name, slot, k, idx in e.class_members(ci):
                info = dict(name=name, kind=k)
                try:
                    if k in (1, 2) and idx is not None:
                        info["type"] = "fn"
                        sig = L.pb_parse(L.pb_first(L.pb_parse(e.all_types()[e.func_sig(idx)]), 4))
                        info["ret"] = e.type_name(L.pb_first(sig, 1)) if L.pb_get(sig, 1) else "void"
                        info["func"] = idx
                    elif k == 4:
                        info["type"] = e.type_name(idx)
                    elif k == 5:
                        for mm in L.pb_get(fl, 3):
                            m = L.pb_parse(mm)
                            if L.pb_first(m, 2) == slot:
                                info["type"] = e.type_name(L.pb_first(L.pb_parse(L.pb_first(m, 8)), 1))
                except (IndexError, TypeError):
                    pass
                mem[slot] = info
            db[e.class_name(ci)] = dict(module=n, base=e.type_name(base) if base is not None else None, members=mem)
        for x in e.ext_members():
            owner = e.type_name(x["owner"]).split("<")[0]
            if owner in db and db[owner]["module"] != "<builtin>":
                continue
            ent = db.setdefault(owner, dict(module="<builtin>", base=None, members={}))
            t = e.type_name(x["sig"])
            info = dict(name=e.all_strings()[x["name"]], kind=x["kind"])
            if t.startswith("fn("):
                info["ret"] = t.rsplit("->", 1)[1]
            else:
                info["type"] = t
            ent["members"].setdefault(x["slot"], info)
    pickle.dump(db, open(cache, "wb"))
    return db


class Dis:
    def __init__(self, db, e):
        self.db, self.e = db, e

    def lookup(self, cls, slot):
        c = (cls or "").split("<")[0]
        for _ in range(30):
            ent = self.db.get(c)
            if not ent:
                break
            if slot in ent["members"]:
                return c, ent["members"][slot]
            c = (ent["base"] or "").split("<")[0]
        obj = self.db.get("object", {}).get("members", {})
        return ("object", obj[slot]) if slot in obj else (None, None)

    @staticmethod
    def subst(owner, t):
        if owner and "<" in owner and t and "T" in t:
            arg = owner[owner.index("<") + 1:-1]
            t = re.sub(r"\bT\b", arg, t)
        if t and t.startswith("ref<"):
            t = t[4:-1]
        return t

    def func_class(self, fi):
        for ci in range(len(self.e.classes_raw)):
            for name, slot, k, idx in self.e.class_members(ci):
                if k == 2 and idx == fi:
                    return self.e.class_name(ci)
        return ""

    def const(self, fi, k):
        cs = [L.pb_parse(c) for c in L.pb_get(self.e.func_fields(fi), 4)]
        c = cs[k]
        kind = L.pb_first(c, 1)
        if kind == 4:
            return repr(self.e.all_strings()[L.pb_first(c, 5)]), "string"
        if kind == 5:
            t = self.e.type_name(L.pb_first(c, 6))
            return "type " + t, t
        if kind == 3:
            import struct
            return "%g" % struct.unpack("<f", L.pb_first(c, 4)[1][-4:])[0], "float"
        return "const%d" % kind, None

    def dis(self, fi, out=sys.stdout):
        e = self.e
        cls = self.func_class(fi)
        code = e.func_code(fi)
        sig = L.pb_parse(L.pb_first(L.pb_parse(e.all_types()[e.func_sig(fi)]), 4))
        argt = [e.type_name(a) for a in L.pb_get(sig, 2)]
        params = [e.all_strings()[L.pb_first(L.pb_parse(p), 1)]
                  for p in L.pb_get(L.pb_parse(L.pb_first(e.func_fields(fi), 2)), 2)]
        ret = e.type_name(L.pb_first(sig, 1)) if L.pb_get(sig, 1) else "void"
        print("\n=== %s.%s(%s) -> %s   [функция %d]" % (cls, e.func_name(fi),
              ", ".join("%s %s" % x for x in zip(argt, params)), ret, fi), file=out)
        gfuncs = {f["gid"]: f for f in e.ext_funcs()}
        locs, stack = {}, []
        for pc, (op, a) in enumerate(code):
            note = ""
            try:
                if op == 0x01:
                    stack += [(None, None)] * a
                elif op == 0x02:
                    stack.pop()
                elif op in (0x03, 0x05):
                    stack.append((None, None))
                elif op == 0x04:
                    stack.append(("int", a))
                elif op == 0x06:
                    note, t = self.const(fi, a)
                    stack.append((t, None))
                elif op == 0x07:
                    if a == 0:
                        t, note = cls, "this"
                    elif a > 0:
                        t, note = (argt[a - 1] if a <= len(argt) else None), (params[a - 1] if a <= len(params) else "arg%d" % a)
                    else:
                        t, note = locs.get(a), "L%d" % -a
                    stack.append((t, None))
                    note += " : %s" % t
                elif op == 0x08:
                    stack.append(("GLOBALS", None))
                elif op == 0x0A:
                    t, _ = stack.pop()
                    c, m = self.lookup(t, a)
                    ft = self.subst(t, m.get("type")) if m else None
                    note = "%s.%s : %s" % (c, m["name"], ft) if m else "%s.?%d" % (t, a)
                    stack.append((ft, None))
                elif op == 0x3C:
                    t, _ = stack.pop()
                    c, m = self.lookup(t, a)
                    note = "%s.%s =" % (c, m["name"]) if m else "?%d =" % a
                elif op == 0x3B:
                    locs[a] = stack[-1][0]
                    note = "L%d =" % -a
                elif op in (0x0D, 0x0E):
                    bcls = stack.pop()[0] if op == 0x0E else None
                    n = stack.pop()[1] or 0
                    rt, _ = stack.pop()
                    for _ in range(n):
                        stack.pop()
                    if rt == "GLOBALS":
                        g = gfuncs.get(a)
                        r = e.type_name(g["sig"]).rsplit("->", 1)[1] if g else None
                        note = "%s(%d) -> %s" % (g["name"] if g else "global%d" % a, n, r)
                    else:
                        c, m = self.lookup(bcls or rt, a)
                        r = self.subst(rt, m.get("ret")) if m else None
                        note = "%s.%s(%d) -> %s" % (c, m["name"], n, r) if m else "%s.?%d(%d)" % (rt, a, n)
                    stack[-1] = (r, None)
                elif op in (0x30, 0x31, 0x32):
                    stack.pop()
                    stack[-1] = ("bool", None)
                    note = CMP.get(a, "")
                elif op == 0x39:
                    note, t = self.const(fi, a)
                    stack.append((t[5:] if t and t.startswith("type ") else t, None))
                elif op == 0x3A:
                    n = stack.pop()[1] or 0
                    o = stack.pop()
                    for _ in range(n):
                        stack.pop()
                    stack[-1] = o
                elif op == 0x3F:
                    arr, _ = stack.pop()
                    stack.pop()
                    el = arr[arr.index("<") + 1:-1] if arr and "<" in arr else None
                    stack.append((el, None))
                elif op == 0x41:
                    stack[-1] = ("int", None)
                elif op in (0x16, 0x42, 0x44, 0x10):
                    stack.pop()
                elif op in (0x40, 0x45, 0x46, 0x47, 0x11):
                    stack.pop()
                    stack.pop()
                elif op == 0x0F:
                    n = stack.pop()[1] or 0
                    stack.pop()
                    for _ in range(n):
                        stack.pop()
                elif op == 0x14:
                    stack.pop(), stack.pop(), stack.pop(), stack.pop()
                    nb = stack.pop()[1] or 0
                    for _ in range(nb):
                        stack.pop()
                    stack.append(("delegate", None))
                elif op == 0x15:
                    for _ in range(a + 1):
                        stack.pop()
                    stack.append((None, None))
                elif 0x1F <= op <= 0x2E:
                    stack.pop()
                elif op == 0x38:
                    stack.append((None, None))
            except IndexError:
                note += " [?]"
                stack = []
            print("%5d  %02x %-11s %6d   %s" % (pc, op, OPN.get(op, "op%02x" % op), a, note), file=out)


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    mods = load_bundle(sys.argv[1])
    if sys.argv[2] == "--list":
        for n in sorted(mods):
            if len(sys.argv) < 4 or sys.argv[3] in n:
                print(n)
        return
    db = build_db(mods, os.path.join(os.path.dirname(os.path.abspath(__file__)), "classdb.pkl"))
    e = L.ModEditor(mods[sys.argv[2]], sys.argv[2])
    d = Dis(db, e)
    for fi in range(len(e.funcs)):
        if (len(sys.argv) == 3 or e.func_name(fi) in sys.argv[3:]) and e.func_code(fi):
            d.dis(fi)


if __name__ == "__main__":
    main()
