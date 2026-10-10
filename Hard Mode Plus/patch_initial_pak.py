"""
Патч initial.pak (скрипты игры) SnowRunner. Патчи настраиваются в settings.ini:

  contest_attempts - число попыток испытаний: 0 - без ограничения, N - не больше N
                     (GetMaxContestsAttempts() возвращает заданное число).
  contest_reward_factor - множитель денежной награды за испытания (золото/серебро/
                     бронза). Применяется и к выплате, и к суммам в интерфейсе.
  contest_xp_factor - множитель опыта за испытания, так же.
  trailer_selling  - продажа прицепов в Сложном режиме. GetTrailerSellingFactor()
                     возвращает множитель продажи ГРУЗОВИКОВ (в Сложном режиме 50%);
                     запрет продажи в игре срабатывает только при множителе -1.
  skip_bootup      - пропуск стартовой заставки (логотипы, предупреждение, юр. текст).
                     Включает встроенный отладочный режим игры «Skip Bootup».
  garage_body_repair - при въезде в гараж корпус (вмятины, царапины, повреждения
                     кузова) чинится бесплатно. Двигатель, коробка, подвеска, бак
                     и колёса по-прежнему чинятся за деньги или запчасти.
  repair_from_nearby - окно ремонта берёт запчасти из любых машин и прицепов рядом
                     (отцепленный сервисный прицеп, аддон чужой машины), как заправка.
  repair_parts_transfer - перекладка запчастей и колёс между сервисными аддонами и
                     прицепами через окно ремонта (см. service_patches.py).
  winch_unpack_cargo - «Распаковать груз» для прицепа/машины, за которую зацеплена
                     лебёдка текущей машины.

Правки делаются в скомпилированном байткоде ([ssl_cache]/initial_*.sslbundle
внутри initial.pak). Патченый файл всегда собирается из оригинала, поэтому
патчи можно включать, выключать и менять их значения в любом сочетании.
Последние три патча собираются из кода в service_patches.py с помощью
библиотеки sslpatch.py (оба файла должны лежать рядом с этим скриптом).

Папка игры задаётся в settings.ini рядом со скриптом. Сейвы не трогаются.
Оригинальный initial.pak сохраняется в папку backup рядом со скриптом.
После обновления игры патч нужно применить заново (бэкап при этом обновится
на новый оригинальный файл).

Использование (игра должна быть закрыта):
  python patch_initial_pak.py             # применить
  python patch_initial_pak.py --restore   # вернуть оригинал из бэкапа
"""
import argparse
import configparser
import filecmp
import math
import os
import shutil
import struct
import subprocess
import sys
import zipfile

import service_patches as SERVICE
from sslpatch import ModEditor, PatchError

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(SCRIPT_DIR, "settings.ini")
BACKUP = os.path.join(SCRIPT_DIR, "backup", "initial.pak")
PAK_REL = os.path.join("preload", "paks", "client", "initial.pak")
RELEASE = "[ssl_cache]/initial_release.sslbundle"
BUNDLES = [RELEASE,
           "[ssl_cache]/initial_profile.sslbundle",
           "[ssl_cache]/initial_debug.sslbundle"]


# ---------------------------------------------------------------------------
# Байткод
#
# Инструкция - varint: младший байт - опкод, старшие 24 бита - операнд со
# смещением 0x800000. Код функции - повторяющееся поле 1 (тег 0x08).
# Опкоды: 01 зарезервировать N слотов, 02 снять со стека, 03 null, 04 целое,
# 05 bool, 06 константа, 07 локальная (0 = this, -N - локальные), 08 глобальный
# объект, 0a прочитать поле, 0d вызвать метод, 12/13 вернуть, 16 перейти, если
# ложь, 18/19 перейти, если ложь/истина (значение остаётся), 1a перейти,
# 20 +, 24 -, 27 *, 2a / (целые), 28 * (дробные), 30/31 сравнить, 35 привести тип,
# 3b записать в локальную.

JUMPS = (0x16, 0x18, 0x19, 0x1A)


def I(op, arg=0):
    return ((arg + 0x800000) << 8) | op


def varint(v):
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


def enc(words):
    return b"".join(b"\x08" + varint(v) for v in words)


def ins(text):
    """Инструкции из текста вида '01:8 07:-4 0d:356' (опкод в hex : операнд, * - любой)."""
    out = []
    for item in text.split():
        op, arg = item.split(":")
        out.append((int(op, 16), None if arg == "*" else int(arg)))
    return out


def match(words, pat):
    """Совпадение шаблона; операнд None (в тексте '*') - любой."""
    return all(w[0] == q[0] and (q[1] is None or w[1] == q[1]) for w, q in zip(words, pat))


def asm(text):
    return enc(I(op, arg) for op, arg in ins(text))


def func(words):
    """Целиком тело короткой функции: поле 5 (тег 0x2a) + длина + код."""
    code = enc(words)
    return b"\x2a" + bytes([len(code)]) + code


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
    return enc(I(op, arg) for op, arg in instrs)


# ---------------------------------------------------------------------------
# Структура бандла и модулей
#
# sslbundle: "S3DB", число модулей (u32 по смещению 11), имена с 20-го байта
# (u32 длина + имя), байт 0x01, u32 размеры всех модулей, затем модули подряд.
# Модуль: 16 байт заголовка (SSLB, версия, хэш исходника, u32 длина тела) и
# тело-protobuf: поле 6 - строки, поле 8 - функции (поле 2.1 - индекс имени,
# поле 5 - код).

def split_bundle(data):
    """-> (префикс до таблицы размеров, [имена], [модули])"""
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


def pb_fields(buf):
    """Поля protobuf: [(номер, начало, конец, значение)]; значение - bytes или int."""
    out = []
    p = 0
    while p < len(buf):
        start = p
        key, p = read_varint(buf, p)
        field, wt = key >> 3, key & 7
        if wt == 0:
            val, p = read_varint(buf, p)
        elif wt == 2:
            ln, p = read_varint(buf, p)
            val = buf[p:p + ln]
            p += ln
        elif wt == 5:
            val = buf[p:p + 4]
            p += 4
        elif wt == 1:
            val = buf[p:p + 8]
            p += 8
        else:
            raise ValueError("неизвестный тип поля protobuf")
        out.append((field, start, p, val))
    return out


class Module:
    def __init__(self, blob):
        if blob[:4] != b"SSLB" or struct.unpack_from("<I", blob, 12)[0] != len(blob) - 16:
            raise ValueError("неизвестный формат модуля")
        self.header = blob[:12]
        self.body = blob[16:]

    def blob(self):
        return self.header + struct.pack("<I", len(self.body)) + self.body

    def functions(self, name):
        """[(начало, конец записи функции в теле, поля функции)] с данным именем."""
        fields = pb_fields(self.body)
        strings = [v for f, s, e, v in fields if f == 6]
        res = []
        for f, s, e, v in fields:
            if f != 8:
                continue
            ff = pb_fields(v)
            hdr = [x[3] for x in ff if x[0] == 2]
            if not hdr:
                continue
            idx = [x[3] for x in pb_fields(hdr[0]) if x[0] == 1]
            if idx and strings[idx[0]] == name.encode():
                res.append((s, e, ff))
        return res

    def replace_code(self, start, end, ffields, instrs):
        """Заменить код функции, сохранив исходные байты остальных её полей."""
        code = encode_code(instrs)
        old = self.body[start:end]
        key, p = read_varint(old, 0)
        ln, p = read_varint(old, p)
        fbody = old[p:]
        new_f = bytearray()
        for f, s, e, v in ffields:
            new_f += (b"\x2a" + varint(len(code)) + code) if f == 5 else fbody[s:e]
        rec = b"\x42" + varint(len(new_f)) + bytes(new_f)
        self.body = self.body[:start] + rec + self.body[end:]


# ---------------------------------------------------------------------------
# Патчи

class BytesPatch:
    """Замена последовательности байт внутри модуля (размер может меняться)."""

    def __init__(self, module, old, new):
        self.module, self.old, self.new = module, old, new

    def is_original(self, mods):
        return mods[self.module].body.count(self.old) == 1

    def apply(self, mods, value):
        m = mods[self.module]
        new = self.new(value) if callable(self.new) else self.new
        m.body = m.body.replace(self.old, new, 1)


class InsertPatch:
    """Вставка инструкций в функцию: перед местом - before, после - after.
    code(value, pos) -> инструкции; переходы внутри - по новым индексам."""

    def __init__(self, module, function, before, after, code):
        self.module, self.function = module, function
        self.before, self.after, self.code = ins(before), ins(after), code

    def _find(self, mods):
        m = mods[self.module]
        pat = self.before + self.after
        hits = []
        for start, end, ff in m.functions(self.function):
            code = [x[3] for x in ff if x[0] == 5]
            if not code:
                continue
            words = decode_code(code[0])
            for i in range(len(words) - len(pat) + 1):
                if match(words[i:i + len(pat)], pat):
                    hits.append((start, end, ff, words, i + len(self.before)))
        return hits

    def is_original(self, mods):
        return len(self._find(mods)) == 1

    def apply(self, mods, value):
        (start, end, ff, words, pos), = self._find(mods)
        new = self.code(value, pos)
        out = []
        for op, arg in words:
            if op in JUMPS:
                if arg == pos:
                    raise ValueError("переход внутрь места вставки (%s)" % self.function)
                if arg > pos:
                    arg += len(new)
            out.append((op, arg))
        out[pos:pos] = new
        mods[self.module].replace_code(start, end, ff, out)


def contest_attempts_code(value):
    # return -1 (без ограничения) или заданное число
    return func([I(0x07), I(0x02), I(0x04, -1 if value == 0 else value), I(0x12, 1)])


def scale(value, pos):
    """деньги * N / D (целые)."""
    n, d = value
    return ins("04:%d 27:0 04:%d 2a:0" % (n, d))


def scale_if(cond):
    """Масштабировать, только если cond (инструкции, дающие bool) истинно."""
    def code(value, pos):
        c = ins(cond)
        s = scale(value, pos)
        return c + [(0x16, pos + len(c) + 1 + len(s))] + s
    return code


# Денежная награда испытаний - поле money (6) у ContestResultRewards (золото,
# серебро, бронза). Везде одна схема: деньги -> 35 (во float) -> * множитель
# сложности -> 35 (обратно); деньги домножаются на N/D перед приведением.
CONTEST_REWARD_SITES = [
    # выплата: ObjectiveRewardsManager.GetRewardsByTime
    InsertPatch("game.missions.rewards.objective_rewards_manager", "GetRewardsByTime",
                "07:-4 0a:6", "35:* 07:-7 28:0", scale),
    # окно испытания перед стартом
    InsertPatch("ui.components.popups.objectives.popup_contest_ui_view", "FillRewards",
                "07:-6 0a:6", "35:* 07:-1 28:0", scale),
    # окно награды после завершения
    InsertPatch("ui.components.popups.objectives.popup_reward_ui_controller", "FillRewards",
                "07:-7 0a:6", "35:* 07:-8 28:0", scale),
    # боковая панель карты
    InsertPatch("ui.components.minimap.minimap_ui_sidepanel_view", "ShowContractReward",
                "07:-6 0a:6", "35:* 07:-1 28:0", scale),
    # профиль: вкладка испытаний
    InsertPatch("game.game_states.game_state_player_profile.player_profile_ui_view",
                "HandleOnContestIndexChange", "07:-10 0a:5", "35:* 07:-5 28:0", scale),
    # профиль: строки списка и описание - только если тип задания CONTEST (3)
    InsertPatch("game.game_states.game_state_player_profile.player_profile_ui_view",
                "OnSetData", "07:-1 0a:10 0a:6", "35:* 07:-2 28:0",
                scale_if("07:-1 0a:11 04:3 30:7")),
    InsertPatch("game.game_states.game_state_player_profile.player_profile_ui_view",
                "SetTaskDesc", "07:1 0a:6", "35:* 07:-2 28:0",
                scale_if("07:2 04:3 30:7")),
]

# Опыт за испытания - поле xp (5) у ContestResultRewards; в данных интерфейса
# профиля опыт лежит в соседнем с деньгами поле.
CONTEST_XP_SITES = [
    # начисление: GiveExperience(xp) в GetRewardsByTime
    InsertPatch("game.missions.rewards.objective_rewards_manager", "GetRewardsByTime",
                "07:-4 0a:5", "07:0 04:1 0d:41", scale),
    InsertPatch("ui.components.popups.objectives.popup_contest_ui_view", "FillRewards",
                "07:-6 0a:5", "35:* 07:-7 0a:145", scale),
    InsertPatch("ui.components.popups.objectives.popup_reward_ui_controller", "FillRewards",
                "07:-7 0a:5", "07:1 3c:8 02:0 07:-7 0a:6", scale),
    InsertPatch("ui.components.minimap.minimap_ui_sidepanel_view", "ShowContractReward",
                "07:-6 0a:5", "35:* 07:-5 0a:145", scale),
    InsertPatch("game.game_states.game_state_player_profile.player_profile_ui_view",
                "HandleOnContestIndexChange", "07:-10 0a:6", "35:* 07:-13 0a:145", scale),
    InsertPatch("game.game_states.game_state_player_profile.player_profile_ui_view",
                "OnSetData", "07:-1 0a:10 0a:7", "35:* 07:0 0a:160",
                scale_if("07:-1 0a:11 04:3 30:7")),
    InsertPatch("game.game_states.game_state_player_profile.player_profile_ui_view",
                "SetTaskDesc", "07:1 0a:7", "07:-8 07:0 04:3",
                scale_if("07:2 04:3 30:7")),
]

PATCHES = [
    # (ключ в settings.ini, [части патча])
    ("contest_attempts", [BytesPatch(
        "game.game_difficulty_manager",
        func([I(0x07), I(0x0A, 6), I(0x0A, 7), I(0x12, 1)]),     # return settings.maxContestAttempts
        contest_attempts_code)]),
    ("contest_reward_factor", CONTEST_REWARD_SITES),
    ("contest_xp_factor", CONTEST_XP_SITES),
    ("trailer_selling", [BytesPatch(
        "game.game_difficulty_manager",
        func([I(0x07), I(0x0A, 6), I(0x0A, 36), I(0x12, 1)]),    # return settings.trailerSellingFactor
        func([I(0x07), I(0x0A, 6), I(0x0A, 27), I(0x12, 1)]))]), # return settings.truckSellingFactor
    ("skip_bootup", [BytesPatch(
        "game.mr_level_load_manager",
        # MrLevelLoadManager.Init: if (GetMrDbgVars().skipBootup.Get()) ... - условный
        # переход заменяется на снятие значения со стека, т.е. всегда ветка пропуска
        enc([I(0x08), I(0x04), I(0x0D, 4), I(0x0A, 29), I(0x04), I(0x0D, 6), I(0x16, 23)]),
        enc([I(0x08), I(0x04), I(0x0D, 4), I(0x0A, 29), I(0x04), I(0x0D, 6), I(0x02)]))]),
    ("garage_body_repair", [BytesPatch(
        "game.game_states.game_state_slot_menu",
        # Начало GameStateSlotMenu.TryRestoreCurrentTruckFuelAndRepair (инструкции 0-67).
        # Было: трижды GetGameDifficultyManager(), затем truck = GetCurrentSlotTruck(),
        # if (truck == null) return.
        asm("01:8 01:1 01:1 07:0 0a:36 04:0 0d:205 04:0 0d:49 3b:-1 "
            "02:0 01:1 01:1 07:0 0a:36 04:0 0d:205 04:0 0d:40 04:0 "
            "30:7 3b:-2 02:0 01:1 01:1 07:0 0a:36 04:0 0d:205 04:0 "
            "0d:54 03:0 30:8 18:47 02:0 01:1 04:25 01:1 01:1 07:0 "
            "0a:36 04:0 0d:205 04:0 0d:54 04:1 0d:15 3b:-3 02:0 01:1 "
            "07:0 04:0 0d:42 3b:-4 02:0 05:0 3b:-5 02:0 05:0 3b:-6 "
            "02:0 05:0 3b:-7 02:0 07:-4 03:0 30:8 16:190"),
        # Стало: менеджер сложности сохраняется в новую локальную -9 (01:9), на
        # освободившемся месте после проверки truck != null вызывается
        # truck.DecalsClearScratches() - то, чем полный ремонт чинит корпус.
        # Остальная функция (платный/бесплатный ремонт частей, топливо) не меняется,
        # индексы инструкций после 67 сохраняются, хвост заполнен переходами на 68.
        asm("01:9 01:1 01:1 07:0 0a:36 04:0 0d:205 3b:-9 04:0 0d:49 "
            "3b:-1 02:0 01:1 07:-9 04:0 0d:40 04:0 30:7 3b:-2 02:0 "
            "01:1 07:-9 04:0 0d:54 03:0 30:8 18:36 02:0 01:1 04:25 "
            "01:1 07:-9 04:0 0d:54 04:1 0d:15 3b:-3 02:0 01:1 07:0 "
            "04:0 0d:42 3b:-4 02:0 05:0 3b:-5 02:0 05:0 3b:-6 02:0 "
            "05:0 3b:-7 02:0 07:-4 03:0 30:8 16:190 01:1 07:-4 04:0 "
            "0d:356 02:0 1a:68 1a:68 1a:68 1a:68 1a:68 1a:68"))]),
]


def load_modules(data, needed):
    prefix, names, blobs = split_bundle(data)
    index = {n: i for i, n in enumerate(names)}
    mods = {n: Module(blobs[index[n]]) for n in needed}
    return prefix, names, blobs, index, mods


def needed_modules():
    return {part.module for _, parts in PATCHES for part in parts}


def service_editors(names, blobs):
    index = {n: i for i, n in enumerate(names)}
    return {n: ModEditor(blobs[index[n]], n) for n in SERVICE.ALL_MODULES}


def bundle_is_original(data):
    _, names, blobs, _, mods = load_modules(data, needed_modules())
    if SERVICE.is_patched(service_editors(names, blobs)):
        return False
    return all(part.is_original(mods) for _, parts in PATCHES for part in parts)


def apply_patches(data, enabled):
    prefix, names, blobs, index, mods = load_modules(data, needed_modules())
    for key, parts in PATCHES:
        for part in parts:
            if not part.is_original(mods):
                raise ValueError("Не удалось однозначно найти код (%s). "
                                 "Возможно, игра обновилась." % key)
    ed = service_editors(names, blobs)
    try:
        SERVICE.check(ed)
    except PatchError as e:
        raise ValueError("Не удалось применить патчи сервиса (%s). Возможно, игра обновилась." % e)
    for key, parts in PATCHES:
        if key in enabled:
            for part in parts:
                part.apply(mods, enabled[key])
    blobs = list(blobs)
    for name, m in mods.items():
        blobs[index[name]] = m.blob()
    changed = SERVICE.apply(ed, {k: v for k, v in enabled.items() if k in SERVICE.KEYS})
    for name in changed:
        blobs[index[name]] = ed[name].blob()
    return join_bundle(prefix, blobs)


def is_original(z):
    return bundle_is_original(z.read(RELEASE))


# ---------------------------------------------------------------------------
# Настройки

def parse_value(cfg, key):
    """-> (включён?, значение, подпись) или выход с ошибкой."""
    raw = cfg.get("patches", key, fallback="yes").split(";")[0].strip().lower()
    def bad(msg):
        sys.exit("settings.ini: %s = %s - %s" % (key, raw, msg))
    if key == "contest_attempts":
        if raw in ("no", "false", "off"):
            return False, None, "испытания: число попыток как в игре"
        if raw in ("yes", "true", "on"):
            raw = "0"
        if not raw.isdigit() or int(raw) > 1000:
            bad("должно быть число от 0 до 1000 (0 - без ограничения) или no")
        n = int(raw)
        return True, n, ("испытания: без ограничения попыток" if n == 0
                         else "испытания: не больше %d попыт%s" % (n, "ки" if n < 5 else "ок"))
    if key in ("contest_reward_factor", "contest_xp_factor"):
        what = "награда" if key == "contest_reward_factor" else "опыт"
        try:
            x = float(raw.replace(",", "."))
        except ValueError:
            bad("должно быть число, например 0.5 (1 - как в игре)")
        if not 0 <= x <= 10:
            bad("должно быть от 0 до 10")
        n = round(x * 100)
        if n == 100:
            return False, None, "%s за испытания: как в игре (x1)" % what
        g = math.gcd(n, 100) or 100
        return True, (n // g, 100 // g), "%s за испытания: x%s" % (what, "%g" % (n / 100))
    labels = {"trailer_selling": "продажа прицепов",
              "skip_bootup": "пропуск стартовой заставки",
              "garage_body_repair": "бесплатный ремонт корпуса в гараже",
              "repair_from_nearby": "ремонт от сервисных машин и прицепов рядом",
              "repair_parts_transfer": "перекладка запчастей между сервисными аддонами и прицепами",
              "winch_unpack_cargo": "распаковка груза через лебёдку"}
    if raw in ("yes", "true", "on", "1"):
        return True, True, labels[key]
    if raw in ("no", "false", "off", "0"):
        return False, None, labels[key]
    bad("должно быть yes или no")


def load_settings():
    if not os.path.exists(SETTINGS):
        sys.exit("Не найден файл настроек: " + SETTINGS)
    cfg = configparser.ConfigParser(inline_comment_prefixes=(";",))
    cfg.read(SETTINGS, encoding="utf-8-sig")
    game_dir = cfg.get("paths", "game_dir", fallback="").strip().strip('"')
    if not game_dir:
        sys.exit("В settings.ini не указана папка игры (game_dir).")
    pak = os.path.join(game_dir, PAK_REL)
    if not os.path.isfile(pak):
        sys.exit("Не найден %s\nПроверьте game_dir в settings.ini." % pak)
    enabled = {}
    for key in [k for k, _ in PATCHES] + list(SERVICE.KEYS):
        on, value, label = parse_value(cfg, key)
        print("  [%s] %s" % ("x" if on else " ", label))
        if on:
            enabled[key] = value
    return pak, enabled


# ---------------------------------------------------------------------------
# Файлы

GAME_LOCKED = ("\nОШИБКА: initial.pak занят - скорее всего, запущена игра.\n"
               "Закройте SnowRunner и запустите скрипт ещё раз. Файл игры НЕ изменён.")


def save_backup(pak):
    """Сохраняет оригинальный (непропатченный) initial.pak в папку скрипта."""
    if os.path.exists(BACKUP) and filecmp.cmp(pak, BACKUP, shallow=False):
        return
    os.makedirs(os.path.dirname(BACKUP), exist_ok=True)
    if os.path.exists(BACKUP):
        print("\nОригинальный initial.pak изменился (обновление игры?), бэкап обновлён.")
    shutil.copy2(pak, BACKUP)
    print("\nБэкап оригинала: " + BACKUP)


def apply(pak, enabled):
    with zipfile.ZipFile(pak) as z:
        current_original = is_original(z)
    if current_original:
        save_backup(pak)
    elif not os.path.exists(BACKUP):
        sys.exit("initial.pak уже пропатчен, а бэкапа оригинала нет: " + BACKUP)
    with zipfile.ZipFile(BACKUP) as src:
        if not is_original(src):
            sys.exit("Бэкап не является оригинальным файлом: " + BACKUP)
        infos = src.infolist()
        contents = {name: apply_patches(src.read(name), enabled) for name in BUNDLES}
        with zipfile.ZipFile(pak) as cur:
            if all(cur.read(n) == contents[n] for n in BUNDLES):
                print("\ninitial.pak уже в нужном состоянии, ничего не изменено.")
                return
        if not enabled:
            try:
                shutil.copy2(BACKUP, pak)
            except PermissionError:
                sys.exit(GAME_LOCKED)
            print("\nВсе патчи выключены: восстановлен оригинальный initial.pak.")
            return
        tmp = pak + ".tmp"
        with zipfile.ZipFile(tmp, "w") as out:
            for info in infos:
                data = contents.get(info.filename)
                if data is None:
                    data = src.read(info)
                zi = zipfile.ZipInfo(info.filename, info.date_time)
                zi.compress_type = info.compress_type
                zi.external_attr = info.external_attr
                zi.create_system = info.create_system
                out.writestr(zi, data)
    # проверка нового архива
    with zipfile.ZipFile(tmp) as z:
        bad = z.testzip()
        if not bad:
            bad = next((n for n in BUNDLES if z.read(n) != contents[n]), None)
    if bad:
        os.remove(tmp)
        sys.exit("Ошибка проверки нового архива на файле " + bad)
    try:
        os.replace(tmp, pak)
    except PermissionError:
        os.remove(tmp)
        sys.exit(GAME_LOCKED)
    print("\nГотово: initial.pak пропатчен.")


def restore(pak):
    if not os.path.exists(BACKUP):
        sys.exit("Бэкап не найден: " + BACKUP)
    if filecmp.cmp(pak, BACKUP, shallow=False):
        print("initial.pak уже совпадает с оригиналом, ничего не изменено.")
        return
    try:
        shutil.copy2(BACKUP, pak)
    except PermissionError:
        sys.exit(GAME_LOCKED)
    print("Оригинальный initial.pak восстановлен из " + BACKUP)


def game_running():
    try:
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq SnowRunner.exe", "/NH"],
                             capture_output=True, text=True, errors="replace").stdout
    except OSError:
        return False
    return "snowrunner.exe" in out.lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true",
                    help="вернуть оригинальный initial.pak из бэкапа")
    args = ap.parse_args()
    if game_running():
        sys.exit("ОШИБКА: игра SnowRunner запущена. Закройте её и запустите скрипт ещё раз.\n"
                 "Файл игры НЕ изменён.")
    if args.restore:
        pak, _ = load_settings()
        print("\nФайл игры: " + pak + "\n")
        restore(pak)
    else:
        print("Патчи:")
        pak, enabled = load_settings()
        print("\nФайл игры: " + pak)
        apply(pak, enabled)


if __name__ == "__main__":
    main()
