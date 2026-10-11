"""
Библиотека для правки скомпилированных скриптов SnowRunner (модули SSL в
initial_*.sslbundle): разбор и сборка модуля, добавление строк, типов и импортов,
мини-компилятор байткода (выражения, условия, циклы) и проверка стека.

Формат (выяснен разбором байткода игры):
  модуль - protobuf: 2 - импортируемые модули, 4 - внешние символы (4.1 типы по
  имени, 4.2 глобальные функции, 4.4 члены чужих классов: вид, имя, тип-владелец,
  номер слота, сигнатура), 5 - таблица типов, 6 - строки, 7 - классы, 8 - функции
  (1 сигнатура, 2 имя и параметры, 3 - нативная, 4 - константы, 5 - код).
  Вызов метода: зарезервировать слот результата (01:1), аргументы в обратном
  порядке, объект, число аргументов (04:n), 0d:слот. Глобальная функция - то же,
  но вместо объекта 08 и номер функции из 4.2. Первая инструкция функции с
  локальными переменными - 01:N (N локальных, адресуются 07:-1..-N).
"""
import struct

# ---------------------------------------------------------------------------
# varint / protobuf

def varint(v):
    if v < 0:
        v += 1 << 64
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        out.append(b | (0x80 if v else 0))
        if not v:
            return bytes(out)


def read_varint(b, p):
    r = s = 0
    while True:
        c = b[p]
        p += 1
        r |= (c & 0x7F) << s
        s += 7
        if not c & 0x80:
            return r, p


def pb_parse(buf):
    """[(поле, значение)]; значение - int или bytes; прочие типы - ('raw', байты)."""
    out = []
    p = 0
    while p < len(buf):
        start = p
        key, p = read_varint(buf, p)
        f, wt = key >> 3, key & 7
        if wt == 0:
            v, p = read_varint(buf, p)
            out.append((f, v))
        elif wt == 2:
            ln, p = read_varint(buf, p)
            out.append((f, buf[p:p + ln]))
            p += ln
        elif wt == 5:
            p += 4
            out.append((f, ('raw', buf[start:p])))
        elif wt == 1:
            p += 8
            out.append((f, ('raw', buf[start:p])))
        else:
            raise ValueError("неизвестный тип поля protobuf")
    return out


def pb_build(fields):
    b = bytearray()
    for f, v in fields:
        if isinstance(v, tuple):
            b += v[1]
        elif isinstance(v, int):
            b += varint(f << 3) + varint(v)
        else:
            b += varint((f << 3) | 2) + varint(len(v)) + v
    return bytes(b)


def pb_get(fields, f):
    return [v for ff, v in fields if ff == f]


def pb_first(fields, f, default=None):
    for ff, v in fields:
        if ff == f:
            return v
    return default


def msg(*pairs):
    return pb_build(list(pairs))


def to_signed(v):
    return v - (1 << 64) if v >= 1 << 63 else v

# ---------------------------------------------------------------------------
# код функции

def I(op, arg=0):
    return ((arg + 0x800000) << 8) | op


def decode_code(code):
    out = []
    p = 0
    while p < len(code):
        if code[p] != 0x08:
            raise ValueError("неожиданный формат кода функции")
        v, p = read_varint(code, p + 1)
        out.append((v & 0xFF, (v >> 8) - 0x800000))
    return out


def encode_code(instrs):
    return b"".join(b"\x08" + varint(I(op, arg)) for op, arg in instrs)


def parse_pattern(text):
    """'07:-1 04:9 30:7 16:*' -> [(op, arg|None)]"""
    out = []
    for item in text.split():
        op, arg = item.split(":")
        out.append((int(op, 16), None if arg == "*" else int(arg)))
    return out


def find_all(code, pattern):
    pat = parse_pattern(pattern) if isinstance(pattern, str) else pattern
    hits = []
    for i in range(len(code) - len(pat) + 1):
        if all(code[i + k][0] == q[0] and (q[1] is None or code[i + k][1] == q[1])
               for k, q in enumerate(pat)):
            hits.append(i)
    return hits


def find_one(code, pattern, what=""):
    hits = find_all(code, pattern)
    if len(hits) != 1:
        raise PatchError("не удалось однозначно найти место в коде (%s): %d совпадений"
                         % (what or pattern, len(hits)))
    return hits[0]


class PatchError(Exception):
    pass

# ---------------------------------------------------------------------------
# бандл

def split_bundle(data):
    if data[:4] != b"S3DB":
        raise ValueError("неизвестный формат бандла")
    n = struct.unpack_from("<I", data, 11)[0]
    p = 20
    names = []
    for _ in range(n):
        ln = struct.unpack_from("<I", data, p)[0]
        p += 4
        names.append(data[p:p + ln].decode())
        p += ln
    if data[p] != 1:
        raise ValueError("неожиданная структура бандла")
    p += 1
    prefix = data[:p]
    sizes = struct.unpack_from("<%dI" % n, data, p)
    p += 4 * n
    blobs = []
    for size in sizes:
        blobs.append(data[p:p + size])
        p += size
    if p != len(data):
        raise ValueError("неожиданная структура бандла")
    return prefix, names, blobs


def join_bundle(prefix, blobs):
    return prefix + struct.pack("<%dI" % len(blobs), *map(len, blobs)) + b"".join(blobs)

# ---------------------------------------------------------------------------
# модуль

class ModEditor:
    """Модуль с возможностью правок; нетронутые поля сохраняются байт в байт."""

    def __init__(self, blob, name=""):
        if blob[:4] != b"SSLB" or struct.unpack_from("<I", blob, 12)[0] != len(blob) - 16:
            raise ValueError("неизвестный формат модуля")
        self.name = name
        self.header = blob[:12]
        self.fields = pb_parse(blob[16:])
        self.strings = [s.decode("utf-8") for s in pb_get(self.fields, 6)]
        self.types = list(pb_get(self.fields, 5))
        self.ext = pb_parse(pb_first(self.fields, 4, b""))
        self.funcs = list(pb_get(self.fields, 8))
        self.classes_raw = list(pb_get(self.fields, 7))
        self.new_strings = []
        self.new_types = []
        self.dirty_ext = False
        self.func_updates = {}
        self.class_updates = set()

    # строки
    def all_strings(self):
        return self.strings + self.new_strings

    def string(self, s):
        allstr = self.all_strings()
        if s in allstr:
            return allstr.index(s)
        self.new_strings.append(s)
        return len(allstr)

    # типы
    def all_types(self):
        return self.types + self.new_types

    def add_type(self, raw):
        at = self.all_types()
        if raw in at:
            return at.index(raw)
        self.new_types.append(raw)
        return len(at)

    def type_name(self, ti, depth=0):
        """человекочитаемое имя типа (для проверок)."""
        t = pb_parse(self.all_types()[ti])
        k = pb_first(t, 1)
        S = self.all_strings()
        if depth > 8:
            return "?"
        if k == 1:
            return self.class_name(pb_first(t, 2, 0))
        if k == 3:
            return self.ext_type_names()[pb_first(t, 2, 0)]
        if k == 4:
            d = pb_parse(pb_first(t, 9))
            base = self.ext_type_names()[pb_first(d, 1, 0)]
            args = pb_get(d, 2)
            return base + ("<%s>" % ",".join(self.type_name(a, depth + 1) for a in args) if args else "")
        if k == 9:
            d = pb_parse(pb_first(t, 4))
            ret = self.type_name(pb_first(d, 1), depth + 1) if pb_get(d, 1) else "void"
            return "fn(%s)->%s" % (",".join(self.type_name(a, depth + 1) for a in pb_get(d, 2)), ret)
        if k == 6:
            return S[pb_first(t, 3)]
        if k == 8:
            return "ref<%s>" % self.type_name(pb_first(t, 2), depth + 1)
        if k == 10:
            d = pb_parse(pb_first(t, 6))
            return "%s<%s>" % (self.type_name(pb_first(d, 1), depth + 1).split("<")[0],
                               self.type_name(pb_first(d, 3), depth + 1))
        if k == 5:
            d = pb_parse(pb_first(t, 8))
            return self.ext_type_names()[pb_first(d, 3)]
        if k == 2:
            d = pb_parse(pb_first(t, 7))
            return S[pb_first(d, 2)]
        return "k%d" % k

    def find_type(self, name):
        for i in range(len(self.all_types())):
            try:
                if self.type_name(i) == name:
                    return i
            except (IndexError, TypeError):
                pass
        return None

    # классы
    def class_name(self, ci):
        return self.strings[pb_first(pb_parse(self.classes_raw[ci]), 1)]

    def class_index(self, name):
        for ci in range(len(self.classes_raw)):
            if self.class_name(ci) == name:
                return ci
        return None

    def class_members(self, ci):
        """[(имя, слот, вид, индекс функции/типа)]"""
        out = []
        for mm in pb_get(pb_parse(self.classes_raw[ci]), 3):
            m = pb_parse(mm)
            out.append((self.all_strings()[pb_first(m, 1)], pb_first(m, 2), pb_first(m, 3), pb_first(m, 4)))
        return out

    def local_class_type(self, name):
        """индекс типа (вид 1) класса этого модуля."""
        ci = self.class_index(name)
        return self.add_type(msg((1, 1), (2, ci)))

    def member_type(self, ci, member):
        """тип члена класса: поле (вид 4/5) - тип поля, метод - сигнатура, событие - тип делегата"""
        for mm in pb_get(pb_parse(self.classes_raw[ci]), 3):
            m = pb_parse(mm)
            if self.all_strings()[pb_first(m, 1)] != member:
                continue
            k = pb_first(m, 3)
            if k in (1, 2):
                return self.func_sig(pb_first(m, 4))
            if k == 4:
                return pb_first(m, 4)
            if k == 5:
                return pb_first(pb_parse(pb_first(m, 8)), 1)
            if k == 3:
                return pb_first(pb_parse(pb_first(m, 6)), 1)
            raise PatchError("вид члена %d не поддерживается (%s)" % (k, member))
        raise PatchError("член %s не найден" % member)

    def add_class_field(self, cls, name, type_idx):
        """добавить поле (вид 5) в конец класса этого модуля (только для классов без
        своих методов, чтобы слоты методов не сдвигались). -> слот"""
        ci = self.class_index(cls)
        rec = pb_parse(self.classes_raw[ci])
        members = [pb_parse(v) for f, v in rec if f == 3]
        for m in members:
            if self.all_strings()[pb_first(m, 1)] == name:
                return pb_first(m, 2)
        if any(pb_first(m, 3) in (1, 2, 3) for m in members):
            raise PatchError("в класс %s нельзя добавить поле: у него есть методы" % cls)
        fields = [m for m in members if pb_first(m, 3) == 5]
        if not fields:
            raise PatchError("в классе %s нет полей-образцов" % cls)
        slot = max(pb_first(m, 2) for m in members) + 1
        attr = pb_first(fields[-1], 7, b"")
        entry = pb_build([(1, self.string(name)), (2, slot), (3, 5), (7, attr),
                          (8, msg((1, type_idx), (2, 0)))])
        last = max(i for i, (f, v) in enumerate(rec) if f == 3)
        rec.insert(last + 1, (3, entry))
        self.classes_raw[ci] = pb_build(rec)
        self.class_updates.add(ci)
        return slot

    # внешние символы
    def ext_type_names(self):
        S = self.all_strings()
        return [S[pb_first(pb_parse(v), 1)] for f, v in self.ext if f == 1]

    def ext_type(self, name):
        names = self.ext_type_names()
        if name in names:
            return names.index(name)
        si = self.string(name)
        last = max([i for i, (f, v) in enumerate(self.ext) if f == 1], default=-1)
        self.ext.insert(last + 1, (1, msg((1, si))))
        self.dirty_ext = True
        return len(names)

    def class_type(self, name):
        """тип 'класс по имени' (вид 4) - для чужих классов."""
        return self.add_type(msg((1, 4), (9, msg((1, self.ext_type(name))))))

    def ext_funcs(self):
        S = self.all_strings()
        out = []
        for f, v in self.ext:
            if f == 2:
                p = pb_parse(v)
                out.append(dict(name=S[pb_first(p, 1)], sig=pb_first(p, 2), gid=pb_first(p, 3), b=pb_first(p, 4)))
        return out

    def add_ext_func(self, name, sig, gid, b):
        if any(f["name"] == name for f in self.ext_funcs()):
            return
        entry = pb_build([(1, self.string(name)), (2, sig), (3, gid), (4, b)])
        S = self.all_strings()
        pos = None
        for i, (f, v) in enumerate(self.ext):
            if f == 2:
                if S[pb_first(pb_parse(v), 1)] > name and pos is None:
                    pos = i
        if pos is None:
            last = max([i for i, (f, v) in enumerate(self.ext) if f in (1, 2)], default=-1)
            pos = last + 1
        self.ext.insert(pos, (2, entry))
        self.dirty_ext = True

    def ext_members(self):
        out = []
        for f, v in self.ext:
            if f == 4:
                p = pb_parse(v)
                out.append(dict(kind=pb_first(p, 1), name=pb_first(p, 2), owner=pb_first(p, 3),
                                slot=pb_first(p, 4), sig=pb_first(p, 5)))
        return out

    def add_ext_member(self, kind, name, owner_t, slot, sig_t):
        si = self.string(name)
        for e in self.ext_members():
            if e["owner"] == owner_t and e["slot"] == slot:
                if e["name"] != si:
                    raise PatchError("конфликт импорта %s (слот %d)" % (name, slot))
                return
        entry = pb_build([(1, kind), (2, si), (3, owner_t), (4, slot), (5, sig_t)])
        pos = None
        for i, (f, v) in enumerate(self.ext):
            if f == 4:
                p = pb_parse(v)
                if (pb_first(p, 3), pb_first(p, 4)) > (owner_t, slot) and pos is None:
                    pos = i
        if pos is None:
            pos = max([i for i, (f, v) in enumerate(self.ext) if f in (1, 2, 3, 4)], default=-1) + 1
        self.ext.insert(pos, (4, entry))
        self.dirty_ext = True

    # функции
    def func_name(self, i):
        fl = pb_parse(self.funcs[i])
        return self.strings[pb_first(pb_parse(pb_first(fl, 2)), 1)]

    def func_index(self, name, cls=None):
        """индекс функции по имени (и классу, если имя неоднозначно)."""
        hits = [i for i in range(len(self.funcs)) if self.func_name(i) == name]
        if cls is not None:
            ci = self.class_index(cls)
            own = {m[3] for m in self.class_members(ci) if m[2] == 2}
            hits = [i for i in hits if i in own]
        if len(hits) != 1:
            raise PatchError("функция %s не найдена однозначно в %s" % (name, self.name))
        return hits[0]

    def func_fields(self, i):
        return pb_parse(self.func_updates.get(i, self.funcs[i]))

    def func_code(self, i):
        return decode_code(pb_first(self.func_fields(i), 5, b""))

    def func_sig(self, i):
        return pb_first(self.func_fields(i), 1)

    def func_nparams(self, i):
        return len(pb_get(pb_parse(pb_first(self.func_fields(i), 2)), 2))

    def add_func_const(self, i, raw):
        fl = self.func_fields(i)
        cs = pb_get(fl, 4)
        if raw in cs:
            return cs.index(raw)
        pos = max([k for k, (f, v) in enumerate(fl) if f == 4], default=None)
        if pos is None:
            pos = max(k for k, (f, v) in enumerate(fl) if f in (1, 2, 3))
        fl.insert(pos + 1, (4, raw))
        self.func_updates[i] = pb_build(fl)
        return len(cs)

    def const_string(self, i, s):
        return self.add_func_const(i, msg((1, 4), (5, self.string(s))))

    def const_type(self, i, tidx):
        return self.add_func_const(i, msg((1, 5), (6, tidx)))

    def const_int(self, i, v):
        """целая константа (так записываются номера слотов событий для 10/11)"""
        return self.add_func_const(i, msg((1, 1), (2, v)))

    def const_float(self, i, v):
        # поле 4 - fixed32 (тип 5), как у констант игры
        return self.add_func_const(i, msg((1, 3), (4, ("raw", b"\x25" + struct.pack("<f", v)))))

    def const_method_ref(self, i):
        """ссылка «метод объекта» для создания делегата (14)"""
        return self.add_func_const(i, msg((1, 6), (7, 0)))

    def set_func_code(self, i, instrs):
        fl = self.func_fields(i)
        code = encode_code(instrs)
        out = [(f, code) if f == 5 else (f, v) for f, v in fl]
        if not pb_get(fl, 5):
            out.append((5, code))
        self.func_updates[i] = pb_build(out)

    # сборка
    def body(self):
        out = []
        fi = ci = 0
        for f, v in self.fields:
            if f == 8:
                out.append((8, self.func_updates.get(fi, v)))
                fi += 1
            elif f == 7:
                out.append((7, self.classes_raw[ci] if ci in self.class_updates else v))
                ci += 1
            elif f == 4 and self.dirty_ext:
                out.append((4, pb_build(self.ext)))
            else:
                out.append((f, v))
        for fno, vals in ((5, self.new_types), (6, [s.encode("utf-8") for s in self.new_strings])):
            if vals:
                last = max(i for i, (f, v) in enumerate(out) if f == fno)
                out[last + 1:last + 1] = [(fno, v) for v in vals]
        return pb_build(out)

    def blob(self):
        body = self.body()
        return self.header + struct.pack("<I", len(body)) + body

# ---------------------------------------------------------------------------
# перенос типов и импортов из другого модуля

def import_type(dst, src, ti):
    t = pb_parse(src.all_types()[ti])
    k = pb_first(t, 1)
    names = src.ext_type_names()
    S = src.all_strings()
    if k == 1:   # класс модуля-источника -> чужой класс по имени
        return dst.class_type(src.class_name(pb_first(t, 2, 0)))
    if k == 3:
        return dst.add_type(msg((1, 3), (2, dst.ext_type(names[pb_first(t, 2, 0)]))))
    if k == 4:
        d = pb_parse(pb_first(t, 9))
        inner = [(1, dst.ext_type(names[pb_first(d, 1, 0)]))] + \
                [(2, import_type(dst, src, a)) for a in pb_get(d, 2)]
        return dst.add_type(msg((1, 4), (9, pb_build(inner))))
    if k == 6:
        return dst.add_type(msg((1, 6), (3, dst.string(S[pb_first(t, 3)]))))
    if k == 8:
        return dst.add_type(msg((1, 8), (2, import_type(dst, src, pb_first(t, 2)))))
    if k == 9:
        d = pb_parse(pb_first(t, 4))
        inner = [(f, import_type(dst, src, v)) for f, v in d]
        return dst.add_type(msg((1, 9), (4, pb_build(inner))))
    if k == 10:
        d = pb_parse(pb_first(t, 6))
        inner = [(f, import_type(dst, src, v) if f in (1, 3) else v) for f, v in d]
        return dst.add_type(msg((1, 10), (6, pb_build(inner))))
    if k == 5:
        d = pb_parse(pb_first(t, 8))
        inner = [(1, import_type(dst, src, pb_first(d, 1))), (2, dst.string(S[pb_first(d, 2)])),
                 (3, dst.ext_type(names[pb_first(d, 3)]))]
        return dst.add_type(msg((1, 5), (8, pb_build(inner))))
    if k == 2:   # делегат: в модуле-приёмнике такой же объявляется по сигнатуре
        d = pb_parse(pb_first(t, 7))
        name = S[pb_first(d, 2)]
        found = dst.find_type(name)
        if found is not None and pb_first(pb_parse(dst.all_types()[found]), 1) == 2:
            return found
        inner = [(1, import_type(dst, src, pb_first(d, 1))), (2, dst.string(name)), (3, dst.string("")),
                 (4, 0), (5, 0)]
        return dst.add_type(msg((1, 2), (7, pb_build(inner))))
    raise PatchError("не удаётся перенести тип вида %s" % k)


def ensure_member(dst, owner, member, decl, decl_cls=None):
    """Добавить в dst импорт члена owner.member (как это сделал бы компилятор).
    decl - ModEditor модуля, где объявлен член (в классе decl_cls, по умолчанию owner).
    Возвращает слот."""
    dc = decl_cls or owner
    ci = decl.class_index(dc)
    if ci is None:
        raise PatchError("класс %s не найден в %s" % (dc, decl.name))
    for name, slot, k, fidx in decl.class_members(ci):
        if name != member:
            continue
        S = dst.all_strings()
        for e in dst.ext_members():
            if e["slot"] == slot and S[e["name"]] == member and \
                    dst.type_name(e["owner"]).split("<")[0] == owner:
                return slot
        t = decl.member_type(ci, member)
        if k == 3:   # событие: в импорте - сигнатура делегата
            td = pb_parse(decl.all_types()[t])
            if pb_first(td, 1) == 2:
                t = pb_first(pb_parse(pb_first(td, 7)), 1)
        elif k not in (1, 2, 4, 5):
            raise PatchError("вид члена %d не поддерживается (%s)" % (k, member))
        sig = import_type(dst, decl, t)
        dst.add_ext_member(k, member, dst.class_type(owner), slot, sig)
        return slot
    raise PatchError("член %s.%s не найден в %s" % (dc, member, decl.name))


def ensure_global(dst, src, name):
    """Добавить в dst импорт глобальной функции name из модуля src. -> номер функции."""
    for f in src.ext_funcs():
        if f["name"] == name:
            dst.add_ext_func(name, import_type(dst, src, f["sig"]), f["gid"], f["b"])
            return f["gid"]
    raise PatchError("глобальная функция %s не найдена в %s" % (name, src.name))


def member_slot(decl, cls, member):
    """слот члена cls.member по объявлению класса в модуле decl."""
    ci = decl.class_index(cls)
    if ci is None:
        raise PatchError("класс %s не найден в %s" % (cls, decl.name))
    for name, slot, k, fidx in decl.class_members(ci):
        if name == member:
            return slot
    raise PatchError("член %s.%s не найден" % (cls, member))

# ---------------------------------------------------------------------------
# проверка стека

_FIXED = {0x02: -1, 0x03: 1, 0x04: 1, 0x05: 1, 0x06: 1, 0x07: 1, 0x08: 1, 0x09: 1,
          0x0A: 0, 0x3B: 0, 0x3C: -1, 0x1B: 0, 0x1D: 0, 0x1E: 0, 0x35: 0, 0x37: 0, 0x38: 1,
          0x39: 1, 0x3F: -1, 0x40: -2, 0x41: 0, 0x42: -1, 0x44: -1, 0x45: -2, 0x46: -2,
          0x47: -2, 0x48: 0, 0x43: 0, 0x36: 0, 0x10: -1, 0x11: -2,
          0x16: -1, 0x18: 0, 0x19: 0, 0x1A: 0}
_CALLS = {0x0D: 2, 0x0E: 3, 0x0F: 2, 0x3A: 2, 0x14: 4}
_ARGC_POS = {0x0D: 1, 0x0E: 2, 0x0F: 1, 0x3A: 1, 0x14: 5}
JUMPS = (0x16, 0x18, 0x19, 0x1A)
_PUSH = (0x01, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08, 0x09, 0x38, 0x39)
_PEEK = (0x18, 0x19, 0x1A, 0x3B)


def verify(code):
    """Проверка согласованности глубины стека на всех путях. Возвращает макс. глубину."""
    n = len(code)
    depth = [None] * n
    work = [(0, 0, ())]
    maxd = 0
    while work:
        pc, d, ints = work.pop()
        while True:
            if pc >= n:
                raise PatchError("выполнение выходит за конец функции")
            if depth[pc] is not None:
                if depth[pc] != d:
                    raise PatchError("разная глубина стека в %d: %d и %d" % (pc, depth[pc], d))
                break
            depth[pc] = d
            op, a = code[pc]
            if op in (0x12, 0x13):
                break
            im = dict(ints)
            if op == 0x01:
                e = a
            elif op in _CALLS:
                argc = im.get(d - _ARGC_POS[op])
                if argc is None:
                    raise PatchError("неизвестное число аргументов в %d" % pc)
                e = -(argc + _CALLS[op])
            elif op == 0x15:
                e = -(a + 1)
            elif op in _FIXED:
                e = _FIXED[op]
            elif 0x1F <= op <= 0x34:
                e = -1
            else:
                raise PatchError("неизвестная инструкция %02x в %d" % (op, pc))
            nd = d + e
            if nd < 0:
                raise PatchError("стек пуст в %d" % pc)
            if op in _PUSH:
                im = {k: v for k, v in im.items() if k < d}
                if op == 0x04:
                    im[d] = a
            elif op not in _PEEK:
                im = {k: v for k, v in im.items() if k < nd - 1}
            ints2 = tuple(sorted(im.items()))
            maxd = max(maxd, nd)
            if op in JUMPS:
                if not 0 <= a < n:
                    raise PatchError("переход за пределы функции в %d" % pc)
                work.append((a, nd, ints2))
                if op == 0x1A:
                    break
            pc += 1
            d = nd
            ints = ints2
    return maxd

# ---------------------------------------------------------------------------
# мини-компилятор
#
# Элементы кода: ('i', op, arg) - инструкция, ('j', op, цель) - переход на метку
# (строка) или на исходную инструкцию ('orig', индекс), ('l', имя) - метка.

import itertools
_labels = itertools.count()


def newlabel(prefix="L"):
    return "%s%d" % (prefix, next(_labels))


def Ins(op, arg=0):
    return ("i", op, arg)


def Jmp(op, target):
    return ("j", op, target)


def Label(name):
    return ("l", name)


class Expr:
    def emit(self):
        raise NotImplementedError


class Local(Expr):
    """07:k - локальная (-k), параметр (k > 0), this (0)"""
    def __init__(self, k):
        self.k = k

    def emit(self):
        return [Ins(0x07, self.k)]


THIS = Local(0)


class Int(Expr):
    def __init__(self, v):
        self.v = v

    def emit(self):
        return [Ins(0x04, self.v)]


class Bool(Expr):
    def __init__(self, v):
        self.v = 1 if v else 0

    def emit(self):
        return [Ins(0x05, self.v)]


class _Null(Expr):
    def emit(self):
        return [Ins(0x03)]


NULL = _Null()


class Const(Expr):
    """06:k - константа функции (строка и т.п.)"""
    def __init__(self, k):
        self.k = k

    def emit(self):
        return [Ins(0x06, self.k)]


class Call(Expr):
    """obj.метод(аргументы) по номеру слота"""
    def __init__(self, obj, slot, *args):
        self.obj, self.slot, self.args = obj, slot, args

    def emit(self):
        out = [Ins(0x01, 1)]
        for a in reversed(self.args):
            out += a.emit()
        return out + self.obj.emit() + [Ins(0x04, len(self.args)), Ins(0x0D, self.slot)]


class GCall(Expr):
    """глобальная функция по номеру (поле 3 записи 4.2)"""
    def __init__(self, gid, *args):
        self.gid, self.args = gid, args

    def emit(self):
        out = [Ins(0x01, 1)]
        for a in reversed(self.args):
            out += a.emit()
        return out + [Ins(0x08), Ins(0x04, len(self.args)), Ins(0x0D, self.gid)]


class Field(Expr):
    def __init__(self, obj, slot):
        self.obj, self.slot = obj, slot

    def emit(self):
        return self.obj.emit() + [Ins(0x0A, self.slot)]


class ArrGet(Expr):
    def __init__(self, arr, idx):
        self.arr, self.idx = arr, idx

    def emit(self):
        return self.idx.emit() + self.arr.emit() + [Ins(0x3F)]


class Count(Expr):
    def __init__(self, arr):
        self.arr = arr

    def emit(self):
        return self.arr.emit() + [Ins(0x41)]


class New(Expr):
    """новый объект; k - константа функции с типом"""
    def __init__(self, k):
        self.k = k

    def emit(self):
        return [Ins(0x01, 1), Ins(0x39, self.k), Ins(0x04, 0), Ins(0x3A, self.k)]


class Bin(Expr):
    def __init__(self, op, a, b, arg=0):
        self.op, self.a, self.b, self.arg = op, a, b, arg

    def emit(self):
        return self.a.emit() + self.b.emit() + [Ins(self.op, self.arg)]


def Add(a, b): return Bin(0x20, a, b)
def Sub(a, b): return Bin(0x24, a, b)
def Eq(a, b): return Bin(0x30, a, b, 7)
def Ne(a, b): return Bin(0x30, a, b, 8)
def Lt(a, b): return Bin(0x31, a, b, 9)
def Gt(a, b): return Bin(0x31, a, b, 10)
def Le(a, b): return Bin(0x31, a, b, 11)
def Ge(a, b): return Bin(0x31, a, b, 12)


class Not(Expr):
    def __init__(self, a):
        self.a = a

    def emit(self):
        return self.a.emit() + [Ins(0x1B)]


class And(Expr):
    def __init__(self, *xs):
        self.xs = xs

    def emit(self):
        end = newlabel("and")
        out = self.xs[0].emit()
        for x in self.xs[1:]:
            out += [Jmp(0x18, end), Ins(0x02)] + x.emit()
        return out + [Label(end)]


class Or(Expr):
    def __init__(self, *xs):
        self.xs = xs

    def emit(self):
        end = newlabel("or")
        out = self.xs[0].emit()
        for x in self.xs[1:]:
            out += [Jmp(0x19, end), Ins(0x02)] + x.emit()
        return out + [Label(end)]


class Cond(Expr):
    """c ? a : b"""
    def __init__(self, c, a, b):
        self.c, self.a, self.b = c, a, b

    def emit(self):
        lelse, lend = newlabel("celse"), newlabel("cend")
        return (self.c.emit() + [Jmp(0x16, lelse)] + self.a.emit() + [Jmp(0x1A, lend), Label(lelse)]
                + self.b.emit() + [Label(lend)])


class Assign(Expr):
    """(L = e) как выражение: значение остаётся на стеке"""
    def __init__(self, k, e):
        self.k, self.e = k, e

    def emit(self):
        return self.e.emit() + [Ins(0x3B, self.k)]


class Cast(Expr):
    """приведение типа: k - константа функции с целевым типом"""
    def __init__(self, e, k):
        self.e, self.k = e, k

    def emit(self):
        return self.e.emit() + [Ins(0x35, self.k)]


def FAdd(a, b): return Bin(0x21, a, b)
def FSub(a, b): return Bin(0x25, a, b)
def FMul(a, b): return Bin(0x28, a, b)
def Concat(a, b): return Bin(0x22, a, b)
def FLt(a, b): return Bin(0x32, a, b, 9)
def FGt(a, b): return Bin(0x32, a, b, 10)
def FLe(a, b): return Bin(0x32, a, b, 11)
def FGe(a, b): return Bin(0x32, a, b, 12)


class Delegate(Expr):
    """делегат obj.метод(слот): nparams - число параметров метода, tconst - константа
    с типом делегата, fnconst - константа-ссылка на метод, bound - привязанные аргументы"""
    def __init__(self, obj, slot, nparams, tconst, fnconst, *bound):
        self.obj, self.slot, self.nparams, self.tconst, self.fnconst, self.bound = \
            obj, slot, nparams, tconst, fnconst, bound

    def emit(self):
        out = []
        for b in self.bound:
            out += b.emit()
        return out + [Ins(0x04, len(self.bound)), Ins(0x06, self.fnconst), Ins(0x04, self.nparams),
                      Ins(0x04, self.slot)] + self.obj.emit() + [Ins(0x14, self.tconst)]


class RawExpr(Expr):
    def __init__(self, items):
        self.items = list(items)

    def emit(self):
        return list(self.items)

# операторы

_loops = []


def emit_block(stmts):
    out = []
    for s in stmts:
        out += s.emit()
    return out


class Stmt:
    def emit(self):
        raise NotImplementedError


class SetLocal(Stmt):
    def __init__(self, k, e):
        self.k, self.e = k, e

    def emit(self):
        return self.e.emit() + [Ins(0x3B, self.k), Ins(0x02)]


class SetField(Stmt):
    def __init__(self, obj, slot, val):
        self.obj, self.slot, self.val = obj, slot, val

    def emit(self):
        return self.val.emit() + self.obj.emit() + [Ins(0x3C, self.slot), Ins(0x02)]


class Do(Stmt):
    """вычислить выражение (вызов) и снять результат со стека"""
    def __init__(self, e):
        self.e = e

    def emit(self):
        return self.e.emit() + [Ins(0x02)]


class Subscribe(Stmt):
    """obj.событие += делегат; k - константа функции с номером слота события"""
    def __init__(self, obj, k, delegate):
        self.obj, self.k, self.delegate = obj, k, delegate

    def emit(self):
        return self.obj.emit() + self.delegate.emit() + [Ins(0x10, self.k), Ins(0x02)]


class Unsubscribe(Stmt):
    """отписать все делегаты объекта subscriber от события obj (как в коде игры)"""
    def __init__(self, subscriber, obj, k):
        self.subscriber, self.obj, self.k = subscriber, obj, k

    def emit(self):
        return self.subscriber.emit() + self.obj.emit() + [Ins(0x11, self.k), Ins(0x03), Ins(0x02)]


class ArrAdd(Stmt):
    def __init__(self, arr, val):
        self.arr, self.val = arr, val

    def emit(self):
        return self.val.emit() + self.arr.emit() + [Ins(0x42), Ins(0x02)]


class ArrSet(Stmt):
    def __init__(self, arr, idx, val):
        self.arr, self.idx, self.val = arr, idx, val

    def emit(self):
        return self.val.emit() + self.idx.emit() + self.arr.emit() + [Ins(0x40), Ins(0x02)]


class If(Stmt):
    def __init__(self, cond, then, els=()):
        self.cond, self.then, self.els = cond, list(then), list(els)

    def emit(self):
        lelse, lend = newlabel("else"), newlabel("endif")
        out = self.cond.emit() + [Jmp(0x16, lelse)] + emit_block(self.then)
        if self.els:
            return out + [Jmp(0x1A, lend), Label(lelse)] + emit_block(self.els) + [Label(lend)]
        return out + [Label(lelse)]


class While(Stmt):
    def __init__(self, cond, body, step=()):
        self.cond, self.body, self.step = cond, list(body), list(step)

    def emit(self):
        top, cont, end = newlabel("wtop"), newlabel("wcont"), newlabel("wend")
        _loops.append((cont, end))
        try:
            body = emit_block(self.body)
        finally:
            _loops.pop()
        return ([Label(top)] + self.cond.emit() + [Jmp(0x16, end)] + body + [Label(cont)]
                + emit_block(self.step) + [Jmp(0x1A, top), Label(end)])


class Break(Stmt):
    def emit(self):
        return [Jmp(0x1A, _loops[-1][1])]


class Continue(Stmt):
    def emit(self):
        return [Jmp(0x1A, _loops[-1][0])]


class Block(Stmt):
    def __init__(self, stmts):
        self.stmts = list(stmts)

    def emit(self):
        return emit_block(self.stmts)


def ForEach(arr, i, n, el, body):
    """for (i = 0, n = arr.Count; i < n; i++) { el = arr[i]; body } - как в коде игры"""
    return Block([SetLocal(n, Count(arr)), SetLocal(i, Int(0)),
                  While(Lt(Local(i), Local(n)), [SetLocal(el, ArrGet(arr, Local(i)))] + list(body),
                        step=[SetLocal(i, Add(Local(i), Int(1)))])])


class Goto(Stmt):
    def __init__(self, target):
        self.target = target

    def emit(self):
        return [Jmp(0x1A, self.target)]


class Return(Stmt):
    """return e; n - число параметров + 1"""
    def __init__(self, e, n):
        self.e, self.n = e, n

    def emit(self):
        return self.e.emit() + [Ins(0x12, self.n)]


class ReturnVoid(Stmt):
    def __init__(self, n):
        self.n = n

    def emit(self):
        return [Ins(0x13, self.n)]


def compile_block(stmts):
    return emit_block(stmts)


def link(items):
    pos = {}
    n = 0
    for it in items:
        if it[0] == "l":
            if it[1] in pos:
                raise PatchError("повтор метки " + it[1])
            pos[it[1]] = n
        else:
            n += 1
    out = []
    for it in items:
        if it[0] == "i":
            out.append((it[1], it[2]))
        elif it[0] == "j":
            out.append((it[1], pos[it[2]]))
    return out


class Locals:
    """выделение новых локальных переменных функции"""
    def __init__(self, code):
        self.base = code[0][1] if code and code[0][0] == 0x01 and any(
            op in (0x07, 0x3B) and a < 0 for op, a in code) else 0
        self.has_reserve = self.base > 0
        self.count = 0

    def new(self):
        self.count += 1
        return -(self.base + self.count)


class FunctionPatch:
    """Правка существующего кода: вставки и замены, переходы пересчитываются."""

    def __init__(self, code):
        self.code = list(code)
        self.before = {}
        self.replaced = {}
        self.locals = Locals(self.code)

    def new_local(self):
        return self.locals.new()

    def insert(self, idx, items, redirect=True):
        """вставить перед исходной инструкцией idx; redirect - переходы на idx попадают
        во вставленный код (иначе - мимо него)."""
        self.before.setdefault(idx, []).append((list(items), redirect))

    def replace(self, start, end, items):
        for s, (e, _) in self.replaced.items():
            if not (end <= s or start >= e):
                raise PatchError("пересекающиеся замены")
        self.replaced[start] = (end, list(items))

    def build(self):
        code = list(self.code)
        inner = set()
        for s, (e, _) in self.replaced.items():
            inner.update(range(s + 1, e))
        items = []
        skip_until = -1
        for i in range(len(code) + 1):
            ins = self.before.get(i, [])
            for its, red in ins:
                if not red:
                    items += its
            items.append(Label("o%d" % i))
            for its, red in ins:
                if red:
                    items += its
            if i == len(code):
                break
            if i in self.replaced:
                end, its = self.replaced[i]
                items += its
                skip_until = end
            if i < skip_until:
                continue
            op, a = code[i]
            if op in JUMPS:
                if a in inner:
                    raise PatchError("переход внутрь заменённого участка")
                items.append(Jmp(op, "o%d" % a))
            else:
                items.append(Ins(op, a))
        fixed = []
        for it in items:
            if it[0] == "j" and isinstance(it[2], tuple):
                if it[2][1] in inner:
                    raise PatchError("переход внутрь заменённого участка")
                fixed.append(Jmp(it[1], "o%d" % it[2][1]))
            else:
                fixed.append(it)
        out = link(fixed)
        # новые локальные переменные
        if self.locals.count:
            total = self.locals.base + self.locals.count
            if self.locals.has_reserve:
                out[0] = (0x01, total)
            else:
                out = [(0x01, total)] + [(op, a + 1 if op in JUMPS else a) for op, a in out]
        verify(out)
        return out
