"""
Патчи сервиса (ремонт и груз) для SnowRunner, поверх библиотеки sslpatch.

  repair_from_nearby - окно ремонта берёт запчасти не только из аддонов и прицепа
      текущей машины, но и из любых машин/прицепов рядом (в т.ч. отцепленных
      сервисных прицепов и аддонов чужих машин). Кнопка «Ремонт» в меню
      взаимодействия появляется, если рядом есть такой источник.
  repair_parts_transfer - перекладка запчастей и колёс между сервисными
      аддонами и прицепами через то же окно ремонта (как переливание топлива):
      каждый сервисный аддон машины и каждый сервисный прицеп рядом - отдельная
      цель в списке целей. У такой цели вместо узлов машины строки «Все»,
      «Запчасти», «Колёса» с остатком/вместимостью; «Ремонт» перекладывает в неё
      запчасти и/или колёса из выбранного источника.
  winch_unpack_cargo - если лебёдка текущей машины зацеплена за прицеп или машину
      с грузом, в меню взаимодействия «Распаковать груз» / «Упаковать груз»
      действуют на груз того, за кого зацеплена лебёдка.
  repair_single_wheel - у строки «Колёса» окна ремонта появляются стрелки (мышь и
      стрелки клавиатуры): «Колёса» (как в игре) -> «Колесо 1» -> «Колесо 2» ...
      (слева направо, спереди назад). У отдельного колеса показан его урон,
      выбранное колесо отмечено на машине маркером, как в оверлее урона (маркер
      едет вместе с машиной, цвет - как у строки в окне), «Ремонт» меняет это
      колесо на запасное (одно колесо из источника). Первая цифра «Колёса»
      окрашена по худшему колесу.
  cargo_loading_price - цена автоматической погрузки (там, где она платная: Сложный
      режим, NG+ с платной погрузкой) зависит от груза: заданная цена за каждый
      слот груза, у брёвен вместо числа слотов - свой множитель для коротких,
      средних (и сожжённых) и длинных. Множитель цены погрузки NG+ по-прежнему
      применяется.

В сетевой игре (кооператив) патчи окна ремонта ничего не меняют.

Цели-аддоны хранятся в обычном списке целей окна (targetTrucks): машина или
прицеп повторяется в списке по разу на каждый свой сервисный аддон. Какой аддон
выбран, определяется по номеру повтора: у машины первое вхождение - ремонт самой
машины, следующие - её сервисные аддоны по порядку; у прицепа все вхождения -
аддоны. Так не нужно менять устройство классов игры.
"""
from sslpatch import (PatchError, ModEditor, Local, THIS, Int, Bool, NULL, Const, Call, GCall, Field,
                      ArrGet, Count, New, Eq, Ne, Lt, Gt, Le, Ge, Add, Sub, Not, And, Or, Cond, Assign,
                      SetLocal, SetField, Do, ArrAdd, ArrSet, If, While, Break, Continue, Block, ForEach,
                      Goto, Return, ReturnVoid, FunctionPatch, Ins, Jmp, Label, newlabel, find_one,
                      find_all, ensure_member, ensure_global, member_slot, compile_block, import_type,
                      Cast, FAdd, FSub, FMul, FLt, FGt, FGe, Concat, Delegate, Subscribe, Unsubscribe, DictGet,
                      DictSet, Mul, Div, RawExpr)

REPAIR = "ui.components.popups.repair.popup_repair_ui_controller_new"
REPAIR_VIEW = "ui.components.popups.repair.popup_repair_ui_view_new"
HUD = "ui.hud.hud_controllers.hud_interaction_panel_controller"
TRUCK = "game.truck"
ADDON = "game.truck_addon"
SESSION = "game.game_modes.game_session"
TRUCKS_MANAGER = "game.truck_manager.trucks_manager"
DAMAGE = "game.damage_controller"
HUD_LIB = "ui.autogen_libs.ui_hud_lib"
GFX = "ui.ui_gfx"
GFX_LIST = "ui.ui_gfx_list"
LIST_ADAPTER = "ui.hud.hud_viewes.ui_list_adapter"
INPUT_SCREEN = "ui.ui_system.input_screen.ssl_ui_input_screen"
INPUT_EVENT = "ui.ui_system.input_screen.ssl_ui_input_event"
MARKERS = "ui.ui_system.markers.ingame_markers_controller"
TRANSFORM = "math.transform"
VEC3 = "math.vector_3d"
VEC2 = "math.vector_2d"
FUTURE = "ssl.lib.future"
NET_HEALTH = "network.net_health_controller"
DAMAGE_HUD = "ui.hud.hud_viewes.hud_truck_state_indication_ui_view"
POPUP_LIB = "ui.autogen_libs.ui_popup_lib"
DAMAGE_HANDLER = "game.truck_damage_handler"
TEXT_COLORS = "ui.ui_system.ui_text_colors"
COLOR = "math.color"
CARGO_LOADING = "ui.components.popups.cargo.popup_cargo_loading_ui_controller"

WHEEL_KEY = "repair_single_wheel"
LOADING_KEY = "cargo_loading_price"
KEYS = ("repair_from_nearby", "repair_parts_transfer", "winch_unpack_cargo", WHEEL_KEY, LOADING_KEY)

# строка-метка в изменённых модулях: по ней видно, что initial.pak уже пропатчен
MARKER = "hard_mode_plus_service_patch"

# строки списка для цели-аддона (ключи локализации игры) и значки
PARTS_LABEL = "UI_POPUP_RESUPPLY_PARTS"
PARTS_ICON = "repairPartsImg20"
WHEELS_LABEL = "UI_POPUP_RESUPPLY_WHEELS"
WHEELS_ICON = "wheelRepairMenuIcon"
FULLY_REPAIRED = "UI_HUD_REPAIR_FULLY_REPAIRED"

# метка «это цель-аддон» в данных окна: у 5-й строки повреждений maxHealth = -1
SERVICE_SENTINEL = -1

# отдельные колёса
WHEEL_LABEL = "UI_TRUCK_PART_WHEEL"         # «КОЛЕСО» (из оверлея урона)
WHEEL_TYPE_BASE = 100       # тип строки «одно колесо»: 100 + номер колеса в машине
WHEEL_DD_BASE = 5           # строки повреждений колёс (по порядку показа) идут с 5-й
DC_WHEEL_BASE = 1000        # DamageController.RepairPart(1000 + номер колеса)
WHEEL_FLIP_MOUSE = 1000     # SwitchTarget(±1000) вида - стрелка мышью
WHEEL_FLIP_KEY = 2000       # SwitchTarget(±2000) - стрелка клавиатуры (только на строке колёс)
WHEEL_MARKER_ID = "hmp_wheel_marker"
SAME_AXLE = 0.3             # колёса ближе 0.3 м по длине машины - на одной оси
ARROW_SCALE = 60.0          # стрелки колёс меньше стрелок переключателя цели (масштаб в
                            # процентах, как scaleX в игре: 100 - обычный размер)
# стрелки колёс сдвинуты от колонок стрелок «Цели» внутрь, к краям строки, на эту долю
# расстояния между стрелками «Цели»; по высоте - от центра текста строки на эту долю
# высоты стрелки (её height больше видимого рисунка; оба числа подобраны по скриншотам)
ARROW_INSET = 0.0625
ARROW_SHIFT_Y = -0.227
# новые поля данных окна (PopupRepairUiViewData2)
F_ORDER, F_PREV, F_NEXT = "hmpWheelOrder", "hmpPrevArrow", "hmpNextArrow"

# погрузка: цена за слот груза по умолчанию (как цена погрузки в Сложном режиме игры) и
# множители брёвен по умолчанию; значение настройки - (цена, {вид брёвен: множитель в %})
LOADING_DEFAULT = 150
LOGS_DEFAULT = {"short": 1, "medium": 2, "long": 3}
LOGS_TYPES = {"CargoLogsShort": "short", "CargoLogsMedium": "medium",
              "CargoLogsMedium_Burnt": "medium", "CargoLogsLong": "long"}
LOADING_VALUE = (LOADING_DEFAULT, {k: v * 100 for k, v in LOGS_DEFAULT.items()})

# модули, которые читаются (изменяются REPAIR, REPAIR_VIEW, HUD, DAMAGE и CARGO_LOADING)
ALL_MODULES = {REPAIR, REPAIR_VIEW, HUD, TRUCK, ADDON, SESSION, TRUCKS_MANAGER, DAMAGE, HUD_LIB, GFX,
               GFX_LIST, LIST_ADAPTER, INPUT_SCREEN, INPUT_EVENT, MARKERS, TRANSFORM, VEC3, VEC2, FUTURE, NET_HEALTH,
               DAMAGE_HUD, POPUP_LIB, DAMAGE_HANDLER, TEXT_COLORS, COLOR, CARGO_LOADING}


class Sym:
    """слоты членов по объявлениям классов (проверяются при каждом запуске)"""

    def __init__(self, ed):
        self.ed = ed

    def __call__(self, mod, cls, member):
        return member_slot(self.ed[mod], cls, member)


def ext_slot(ed, member, owner=None):
    """слот члена, уже импортированного модулем (по имени, однозначно)"""
    S = ed.all_strings()
    slots = {e["slot"] for e in ed.ext_members() if S[e["name"]] == member
             and (owner is None or ed.type_name(e["owner"]).split("<")[0] == owner)}
    if len(slots) != 1:
        raise PatchError("импорт %s в %s не найден однозначно" % (member, ed.name))
    return slots.pop()


def ext_gid(ed, name):
    for f in ed.ext_funcs():
        if f["name"] == name:
            return f["gid"]
    raise PatchError("глобальная функция %s не импортирована в %s" % (name, ed.name))

# ---------------------------------------------------------------------------
# окно ремонта


class RepairCtx:
    """символы и общие выражения для модуля окна ремонта"""

    def __init__(self, ed):
        self.ed = ed
        m = ed[REPAIR]
        self.m = m
        s = Sym(ed)
        P = "PopupRepairUiControllerNew"
        self.f = {n: member_slot(m, P, n) for n in (
            "repairTruckRange", "sourceAddons", "targetTrucks", "sourceIndex", "targetIndex", "sourceAddon",
            "targetTruck", "nearTrucks", "destroyedWheelsAmount", "RepairAll", "GetView")}
        self.f["gameSession"] = ext_slot(m, "gameSession")
        self.f["UpdateViewData"] = ext_slot(m, "UpdateViewData")
        self.ra = {n: member_slot(m, "RepairAddon", n) for n in ("parentTruck", "addon", "Init")}
        self.t = {n: s(TRUCK, "Truck", n) for n in (
            "id", "IsTrailer", "AsTruckAddon", "GetType", "GetCurrentTruckAddons", "GetTrailer")}
        self.a = {n: s(ADDON, "TruckAddon", n) for n in (
            "name", "SetRepairs", "GetRepairs", "SetWheelRepairs", "GetWheelRepairs",
            "GetRepairsCapacity", "GetWheelRepairsCapacity")}
        self.gs = {n: s(SESSION, "GameSession", n) for n in ("GetTrucksManager", "IsMultiplayer", "GetClientProxy")}
        self.near = s(TRUCKS_MANAGER, "TrucksManager", "GetNearTrucksForCurrentTruck")
        self.view = {n: ext_slot(m, n) for n in ("PlayRepairAllSound", "PlayCantRepairSound")}
        self.data = {n: ext_slot(m, n) for n in ("targetName", "damagesData")}
        self.g = {n: ext_gid(m, n) for n in ("GetCurrentGameSession", "GetGameEngine",
                                             "PopupRepairUiViewTruckDataCreate", "GetAppMode")}
        self.cur_truck_slot = ext_slot(m, "GetCurrentTruck", "Game")
        self.arr_clone = ext_slot(m, "Clone", "array")
        self.arr_clear = ext_slot(m, "Clear", "array")
        self.arr_push_front = ext_slot(m, "PushFront", "array")
        self.addons_mgr = ext_slot(m, "GetTruckAddonsManager")
        self.ui_desc = ext_slot(m, "GetTruckUiDesc")
        self.ui_name = ext_slot(m, "uiName")
        self.objstor = (ext_slot(m, "GetObjectiveStatusStorage"),
                        ext_slot(m, "IsTruckBlockedForRepairAndRefuelByObjective"))
        # импорты, которых в модуле не было (то, что добавил бы компилятор)
        for cls, mod, names in (
                ("TruckAddon", ADDON, ("SetRepairs", "SetWheelRepairs", "GetRepairs", "GetWheelRepairs",
                                       "GetRepairsCapacity", "GetWheelRepairsCapacity", "name")),
                ("Truck", TRUCK, ("IsTrailer", "AsTruckAddon", "GetType", "GetCurrentTruckAddons", "id",
                                  "GetTrailer")),
                ("GameSession", SESSION, ("IsMultiplayer", "GetTrucksManager", "GetClientProxy")),
                ("TrucksManager", TRUCKS_MANAGER, ("GetNearTrucksForCurrentTruck",))):
            for n in names:
                ensure_member(m, cls, n, ed[mod])

    # выражения
    def session(self):
        return Field(THIS, self.f["gameSession"])

    def single_player(self):
        return Not(Call(self.session(), self.gs["IsMultiplayer"]))

    def cur_truck(self):
        return Call(GCall(self.g["GetGameEngine"]), self.cur_truck_slot)

    def addons(self, truck):
        # GetCurrentTruckAddons(includeTrailer=false, includeThisTruck=true, includeCargoes=true)
        return Call(truck, self.t["GetCurrentTruckAddons"], Bool(False), Bool(True), Bool(True))

    def has_capacity(self, a):
        return Or(Gt(Call(a, self.a["GetRepairsCapacity"]), Int(0)),
                  Gt(Call(a, self.a["GetWheelRepairsCapacity"]), Int(0)))

    def has_stock(self, a):
        return Or(Gt(Call(a, self.a["GetRepairs"]), Int(0)), Gt(Call(a, self.a["GetWheelRepairs"]), Int(0)))

    def src_addon_expr(self):
        """this.sourceAddon?.addon (null, если источника нет)"""
        sa = Field(THIS, self.f["sourceAddon"])
        return Cond(Eq(sa, NULL), NULL, Field(Field(THIS, self.f["sourceAddon"]), self.ra["addon"]))

    def truck_ui_name(self, truck):
        """имя для поиска описания: у прицепа - имя его аддона (как у источников)"""
        return Cond(Call(truck, self.t["IsTrailer"]),
                    Field(Call(truck, self.t["AsTruckAddon"]), self.a["name"]),
                    Call(truck, self.t["GetType"]))

    def ui_name_of(self, name_expr):
        """GetAppMode().GetTruckAddonsManager().GetTruckUiDesc(name, false).uiName"""
        return Field(Call(Call(GCall(self.g["GetAppMode"]), self.addons_mgr), self.ui_desc, name_expr, Bool(False)),
                     self.ui_name)

    def need(self, a, src, cap, get):
        """сколько можно переложить: min(вместимость - остаток в a, остаток в src)"""
        A = self.a
        free = Sub(Call(a, A[cap]), Call(a, A[get]))
        return Cond(Lt(free, Call(src, A[get])), Sub(Call(a, A[cap]), Call(a, A[get])), Call(src, A[get]))


def service_addons_loop(c, fp, truck, body):
    """for a in сервисные аддоны truck (с вместимостью запчастей или колёс): body(a)"""
    arr, j, m, a = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
    return Block([SetLocal(arr, c.addons(truck)),
                  ForEach(Local(arr), j, m, a, [
                      If(Or(Eq(Local(a), NULL), Not(c.has_capacity(Local(a)))), [Continue()]),
                  ] + body(Local(a)))])


def resolve_target(c, fp, idx):
    """операторы, вычисляющие в локальной out сервисный аддон записи targetTrucks[idx]
    (null - ремонт машины). -> (операторы, out)"""
    out, t, occ, j, cnt = (fp.new_local() for _ in range(5))
    tg = Field(THIS, c.f["targetTrucks"])
    stmts = [
        SetLocal(out, NULL),
        If(And(c.single_player(), Ge(idx, Int(0)), Lt(idx, Count(tg))), [
            SetLocal(t, ArrGet(Field(THIS, c.f["targetTrucks"]), idx)),
            If(Ne(Local(t), NULL), [
                SetLocal(occ, Int(0)),
                SetLocal(j, Int(0)),
                While(Lt(Local(j), idx), [
                    If(Eq(ArrGet(Field(THIS, c.f["targetTrucks"]), Local(j)), Local(t)),
                       [SetLocal(occ, Add(Local(occ), Int(1)))]),
                ], step=[SetLocal(j, Add(Local(j), Int(1)))]),
                If(Not(Call(Local(t), c.t["IsTrailer"])), [SetLocal(occ, Sub(Local(occ), Int(1)))]),
                If(Ge(Local(occ), Int(0)), [
                    SetLocal(cnt, Int(0)),
                    service_addons_loop(c, fp, Local(t), lambda a: [
                        If(Eq(Local(cnt), Local(occ)), [SetLocal(out, a), Break()]),
                        SetLocal(cnt, Add(Local(cnt), Int(1))),
                    ]),
                ]),
            ]),
        ]),
    ]
    return stmts, out


def patch_update_near_trucks(c, fp, enabled):
    """UpdateNearTrucks: источники рядом; сервисные аддоны и прицепы как отдельные цели"""
    code = fp.code
    nt = Field(THIS, c.f["nearTrucks"])
    tt = c.f["targetTrucks"]
    if "repair_from_nearby" in enabled:
        # перед: targetTrucks = GetNearbyTrucksAndTrailers()
        at = find_one(code, "01:1 07:0 04:0 0d:* 07:0 3c:%d" % tt, "UpdateNearTrucks/targets")
        cur = fp.new_local()
        i, n, t = fp.new_local(), fp.new_local(), fp.new_local()
        arr, j, m, a = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        found, k, kn, s = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        ra = fp.new_local()
        newra = c.m.const_type(c.fi, c.m.local_class_type("RepairAddon"))
        srcs = Field(THIS, c.f["sourceAddons"])
        body = [
            SetLocal(cur, c.cur_truck()),
            If(And(c.single_player(), Ne(nt, NULL)), [
                ForEach(nt, i, n, t, [
                    If(Or(Eq(Local(t), NULL), Eq(Local(t), Local(cur))), [Continue()]),
                    SetLocal(arr, c.addons(Local(t))),
                    ForEach(Local(arr), j, m, a, [
                        If(Eq(Local(a), NULL), [Continue()]),
                        If(Not(c.has_stock(Local(a))), [Continue()]),
                        SetLocal(found, Bool(False)),
                        ForEach(srcs, k, kn, s, [
                            If(Eq(Field(Local(s), c.ra["addon"]), Local(a)), [SetLocal(found, Bool(True)), Break()]),
                        ]),
                        If(Local(found), [Continue()]),
                        SetLocal(ra, New(newra)),
                        Do(Call(Local(ra), c.ra["Init"], Local(t), Local(a))),
                        ArrAdd(srcs, Local(ra)),
                    ]),
                ]),
            ]),
        ]
        fp.insert(at, compile_block(body))
    if "repair_parts_transfer" in enabled:
        # перед проверкой «целей или источников нет - закрыть окно»
        at = find_one(code, "07:0 0a:%d 41:0 04:0 30:7 19:*" % tt, "UpdateNearTrucks/empty-check")
        tgts = Field(THIS, tt)
        snap, i, n, t = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        ok, k, kn, x = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        stor, cand, cur, tr = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        gos, isblk = c.objstor
        body = [
            If(And(c.single_player(), Ne(nt, NULL)), [
                # 1) после каждой машины - её сервисные аддоны
                SetLocal(snap, Call(tgts, c.arr_clone)),
                Do(Call(Field(THIS, tt), c.arr_clear)),
                ForEach(Local(snap), i, n, t, [
                    ArrAdd(Field(THIS, tt), Local(t)),
                    If(Ne(Local(t), NULL), [
                        service_addons_loop(c, fp, Local(t), lambda a: [ArrAdd(Field(THIS, tt), Local(t))]),
                    ]),
                ]),
                # 2) сервисные прицепы: свой прицеп и всё рядом
                SetLocal(stor, Call(Call(GCall(c.g["GetCurrentGameSession"]), c.gs["GetClientProxy"]), gos)),
                SetLocal(cand, Call(nt, c.arr_clone)),
                SetLocal(cur, c.cur_truck()),
                If(Ne(Local(cur), NULL), [
                    SetLocal(tr, Call(Local(cur), c.t["GetTrailer"])),
                    If(Ne(Local(tr), NULL), [Do(Call(Local(cand), c.arr_push_front, Local(tr)))]),
                ]),
                ForEach(Local(cand), i, n, t, [
                    If(Or(Eq(Local(t), NULL), Not(Call(Local(t), c.t["IsTrailer"]))), [Continue()]),
                    SetLocal(ok, Bool(True)),
                    ForEach(Field(THIS, tt), k, kn, x, [
                        If(Eq(Local(x), Local(t)), [SetLocal(ok, Bool(False)), Break()]),
                    ]),
                    If(Not(Local(ok)), [Continue()]),
                    If(Ne(Local(stor), NULL), [
                        If(Call(Local(stor), isblk, Field(Local(t), c.t["id"])), [Continue()]),
                    ]),
                    service_addons_loop(c, fp, Local(t), lambda a: [ArrAdd(Field(THIS, tt), Local(t))]),
                ]),
            ]),
        ]
        fp.insert(at, compile_block(body))
        patch_self_skip(c, fp)


def patch_self_skip(c, fp):
    """«цель совпадает с источником - пропустить»: для цели-аддона сравнивать сам аддон.
    targets[targetIndex].AsTruckAddon()  ->  (аддон цели ?? targets[targetIndex].AsTruckAddon())"""
    pat = "01:1 07:0 0a:%d 07:0 0a:%d 3f:0 04:0 0d:%d" % (c.f["targetIndex"], c.f["targetTrucks"],
                                                          c.t["AsTruckAddon"])
    hits = find_all(fp.code, pat)
    if not hits:
        raise PatchError("не найдена проверка «цель = источник» (%s)" % c.fname)
    for at in hits:
        pre, out = resolve_target(c, fp, Field(THIS, c.f["targetIndex"]))
        expr = Cond(Ne(Local(out), NULL), Local(out),
                    Call(ArrGet(Field(THIS, c.f["targetTrucks"]), Field(THIS, c.f["targetIndex"])),
                         c.t["AsTruckAddon"]))
        fp.replace(at, at + 8, compile_block(pre) + expr.emit())


def patch_is_can_be_shown(c, fp):
    """IsCanBeShown: окно можно открыть и при источнике запчастей рядом"""
    at = find_one(fp.code, "1a:* 05:0 12:1", "IsCanBeShown/return-false") + 1
    near, i, n, t = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
    arr, j, m, a = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
    body = [
        If(c.single_player(), [
            SetLocal(near, Call(Call(GCall(c.g["GetCurrentGameSession"]), c.gs["GetTrucksManager"]),
                                c.near, Field(THIS, c.f["repairTruckRange"]))),
            If(Ne(Local(near), NULL), [
                ForEach(Local(near), i, n, t, [
                    If(Eq(Local(t), NULL), [Continue()]),
                    SetLocal(arr, c.addons(Local(t))),
                    ForEach(Local(arr), j, m, a, [
                        If(And(Ne(Local(a), NULL), c.has_stock(Local(a))), [Return(Bool(True), 1)]),
                    ]),
                ]),
            ]),
        ]),
    ]
    fp.insert(at, compile_block(body))


def transfer_stmts(c, fp, cont, src, parts, wheels):
    """переложить из src в cont (parts/wheels - выражения bool: что перекладывать)"""
    give, moved = fp.new_local(), fp.new_local()
    A = c.a
    stmts = [SetLocal(moved, Int(0))]
    for flag, cap, get, set_ in ((parts, "GetRepairsCapacity", "GetRepairs", "SetRepairs"),
                                 (wheels, "GetWheelRepairsCapacity", "GetWheelRepairs", "SetWheelRepairs")):
        stmts.append(If(flag, [
            SetLocal(give, c.need(cont, src, cap, get)),
            If(Gt(Local(give), Int(0)), [
                Do(Call(cont, A[set_], Add(Call(cont, A[get]), Local(give)))),
                Do(Call(src, A[set_], Sub(Call(src, A[get]), Local(give)))),
                SetLocal(moved, Add(Local(moved), Local(give))),
            ]),
        ]))
    view = lambda: Call(THIS, c.f["GetView"])
    stmts += [
        If(Gt(Local(moved), Int(0)), [Do(Call(view(), c.view["PlayRepairAllSound"]))],
           [Do(Call(view(), c.view["PlayCantRepairSound"]))]),
        Do(Call(THIS, c.f["UpdateViewData"])),
    ]
    return stmts


def patch_repair_all(c, fp):
    """RepairAll: цель-аддон - переложить запчасти и колёса"""
    src = fp.new_local()
    pre, cont = resolve_target(c, fp, Field(THIS, c.f["targetIndex"]))
    body = pre + [
        SetLocal(src, c.src_addon_expr()),
        If(Ne(Local(cont), NULL), [
            If(And(Ne(Local(src), NULL), Ne(Local(src), Local(cont))),
               transfer_stmts(c, fp, Local(cont), Local(src), Bool(True), Bool(True))),
            ReturnVoid(1)]),
    ]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def patch_repair_part(c, fp):
    """RepairPart(part): цель-аддон - строка 0 запчасти, строка 1 колёса"""
    src = fp.new_local()
    pre, cont = resolve_target(c, fp, Field(THIS, c.f["targetIndex"]))
    part = Local(1)
    body = pre + [
        SetLocal(src, c.src_addon_expr()),
        If(Ne(Local(cont), NULL), [
            If(And(Ne(Local(src), NULL), Ne(Local(src), Local(cont))),
               transfer_stmts(c, fp, Local(cont), Local(src), Ne(part, Int(1)), Ne(part, Int(0)))),
            ReturnVoid(2)]),
    ]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def patch_is_repair_enabled(c, fp):
    """IsRepairEnabled(part): для цели-аддона - есть ли что переложить по строке"""
    at = find_one(fp.code, "07:1 04:7 30:7 16:* 05:0 12:2", "IsRepairEnabled/none")
    at = fp.code[at + 3][1]          # начало ветки part != NONE
    src = fp.new_local()
    pre, cont = resolve_target(c, fp, Field(THIS, c.f["targetIndex"]))
    A = c.a
    cn, s = Local(cont), Local(src)
    can_p = And(Gt(Call(cn, A["GetRepairsCapacity"]), Call(cn, A["GetRepairs"])), Gt(Call(s, A["GetRepairs"]), Int(0)))
    can_w = And(Gt(Call(cn, A["GetWheelRepairsCapacity"]), Call(cn, A["GetWheelRepairs"])),
                Gt(Call(s, A["GetWheelRepairs"]), Int(0)))
    part = Local(1)
    body = pre + [
        SetLocal(src, c.src_addon_expr()),
        If(Ne(cn, NULL), [
            If(Or(Eq(s, NULL), Eq(s, cn)), [Return(Bool(False), 2)]),
            If(Eq(part, Int(0)), [Return(can_p, 2)]),
            If(Eq(part, Int(1)), [Return(can_w, 2)]),
            Return(Or(can_p, can_w), 2),
        ]),
    ]
    fp.insert(at, compile_block(body))


def patch_create_data(c, fp):
    """CreateData: для цели-аддона - имя аддона и строки «запчасти»/«колёса»"""
    code = fp.code
    # 1) описание цели: у прицепа ищем по имени аддона (на случай записи без аддона)
    at = find_one(code, "01:1 05:0 01:1 07:-3 04:0 0d:%d 07:-1 04:2 0d:*" % c.t["GetType"], "CreateData/target-desc")
    fp.replace(at + 2, at + 6, c.truck_ui_name(Local(-3)).emit())
    # 2) цель-аддон: строки 0 - запчасти, 1 - колёса, 4 - метка; без чтения повреждений
    rows = find_one(code, "01:1 07:-3 01:1 39:* 04:0 3a:* 04:1 0d:* 3b:-7", "CreateData/damages")
    hint = find_one(code, "01:1 07:0 0a:* 04:0 0d:* 07:-5 3c:*", "CreateData/hint")
    pre, cont = resolve_target(c, fp, Field(THIS, c.f["targetIndex"]))
    A = c.a
    cn, src = Local(cont), Local(-2)
    dd = lambda: Field(Local(-5), c.data["damagesData"])
    create = lambda *v: GCall(c.g["PopupRepairUiViewTruckDataCreate"], *[x if not isinstance(x, int) else Int(x) for x in v])
    cost_p, cost_w = fp.new_local(), fp.new_local()
    body = pre + [If(Or(Ne(cn, NULL), Call(Local(-3), c.t["IsTrailer"])), [
        Do(Call(dd(), 13, Int(5))),
        If(Ne(cn, NULL), [
            SetLocal(cost_p, Int(0)), SetLocal(cost_w, Int(0)),
            If(Ne(src, cn), [SetLocal(cost_p, c.need(cn, src, "GetRepairsCapacity", "GetRepairs")),
                             SetLocal(cost_w, c.need(cn, src, "GetWheelRepairsCapacity", "GetWheelRepairs"))]),
            ArrSet(dd(), Int(0), create(Call(cn, A["GetRepairs"]), Call(cn, A["GetRepairsCapacity"]), Local(cost_p), 0)),
            ArrSet(dd(), Int(1), create(Call(cn, A["GetWheelRepairs"]), Call(cn, A["GetWheelRepairsCapacity"]),
                                        0, Local(cost_w))),
            SetField(Local(-5), c.data["targetName"], c.ui_name_of(Field(cn, A["name"]))),
        ], [
            ArrSet(dd(), Int(0), create(0, 0, 0, 0)),
            ArrSet(dd(), Int(1), create(0, 0, 0, 0)),
        ]),
        ArrSet(dd(), Int(2), create(0, 0, 0, 0)),
        ArrSet(dd(), Int(3), create(0, 0, 0, 0)),
        ArrSet(dd(), Int(4), create(0, SERVICE_SENTINEL, 0, 0)),
        SetField(THIS, c.f["destroyedWheelsAmount"], Int(0)),
        Goto(("orig", hint)),
    ])]
    fp.insert(rows, compile_block(body))


def patch_truck_marker(c, fp):
    """GetRepairTruckMarker: для прицепа - без чтения повреждений"""
    code = fp.code
    at = find_one(code, "01:1 05:0 01:1 07:1 04:0 0d:%d 07:-1 04:2 0d:*" % c.t["GetType"], "Marker/desc")
    fp.replace(at + 2, at + 6, c.truck_ui_name(Local(1)).emit())
    dmg = find_one(code, "01:1 07:1 04:0 0d:* 3b:-3 02:0 07:-3 01:1 07:1 04:0 0d:* 24:0 3b:-4",
                   "Marker/damage")
    newarr = find_one(code, "01:1 39:* 04:0 3a:* 3b:-5", "Marker/array")
    final = find_one(code, "01:1 07:3 07:-5 07:2 07:-2 0a:* 08:0 04:4 0d:*", "Marker/create")
    k = code[newarr + 1][1]
    body = [If(Call(Local(1), c.t["IsTrailer"]), [SetLocal(-5, New(k)), Goto(("orig", final))])]
    fp.insert(dmg, compile_block(body))


def patch_create_markers(c, fp):
    """CreateMarkers: машина, повторённая в списке целей (её аддоны), получает один маркер;
    он выделен, если выбрана любая её запись"""
    code = fp.code
    pat = "3f:0 3b:* 02:0 07:* 03:0 30:7 16:* 1a:* 01:1 07:* 07:0 0a:%d 30:7" % c.f["targetIndex"]
    at = find_one(code, pat, "CreateMarkers/targets")
    el, cont, idx, arr = code[at + 1][1], code[at + 7][1], code[at + 9][1], code[at - 1][1]
    j, dup = fp.new_local(), fp.new_local()
    body = [SetLocal(dup, Bool(False)), SetLocal(j, Int(0)),
            While(Lt(Local(j), Local(idx)), [
                If(Eq(ArrGet(Local(arr), Local(j)), Local(el)), [SetLocal(dup, Bool(True)), Break()]),
            ], step=[SetLocal(j, Add(Local(j), Int(1)))]),
            If(Local(dup), [Goto(("orig", cont))])]
    fp.insert(at + 8, compile_block(body))
    tg = lambda: Field(THIS, c.f["targetTrucks"])
    ti = lambda: Field(THIS, c.f["targetIndex"])
    sel = And(Ge(ti(), Int(0)), Lt(ti(), Count(tg())), Eq(ArrGet(tg(), ti()), Local(el)))
    fp.replace(at + 9, at + 13, sel.emit())


# ---------------------------------------------------------------------------
# отдельные колёса: контроллер окна ремонта


class WheelCtx:
    """символы для патча отдельных колёс в модуле окна ремонта"""

    def __init__(self, c, ed):
        m = c.m
        self.c = c
        imp = lambda cls, n, mod, dc=None: ensure_member(m, cls, n, ed[mod], dc)
        self.t = {n: imp("Truck", n, TRUCK) for n in ("wheelDamages", "GetPosWheels", "GetChassisWorldTransformValue",
                                                      "GetTransformValue", "truckDamageHandler")}
        self.dmg = {n: imp("DamageData", n, ADDON) for n in ("damage", "damageCapacity")}
        self.point = imp("Transform3d", "TransformPoint", TRANSFORM)
        self.vx, self.vz = imp("Vector3d", "x", VEC3), imp("Vector3d", "z", VEC3)
        self.markers_ctrl = imp("GameSession", "GetIngameMarkersCtrl", SESSION)
        self.damage_ctrl = imp("GameSession", "GetDamageController", SESSION)
        self.dc_repair = imp("DamageController", "RepairPart", DAMAGE)
        self.release = imp("IngameMarkersController", "ReleaseSingleMarkerUiObject", MARKERS)
        self.remove_obj = imp("IngameMarkersController", "RemoveObj", MARKERS)
        self.markers = imp("IngameMarkersController", "markers", MARKERS)
        self.marker_data = imp("MarkerUpdateData", "markerData", MARKERS)
        self.marker_obj = imp("MarkerCreationData", "obj", MARKERS)
        self.add_obj = imp("IngameMarkersController", "AddUiObjToLayer", MARKERS)
        self.mk = {n: imp("UiHudLibTruckdmgmarker", n, HUD_LIB) for n in ("truckDmgModulePart", "partImg", "tfCont")}
        self.part_tf = imp("UiHudLibTruckdmgmodulepartname", "tf", HUD_LIB)
        self.dmg_value = imp("UiHudLibTruckdmgtext", "dmgValue", HUD_LIB)
        self.value_tf = imp("UiHudLibTruckdmgvalue", "tf", HUD_LIB)
        self.label_text = imp("UiLabel", "text", GFX)
        self.set_parent = imp("UiDisplayObjectBase", "SetParent", GFX)
        self.goto_stop = imp("UiMovieClip", "GotoAndStop", GFX)
        self.view_last = imp("PopupRepairUiViewNew", "lastData", REPAIR_VIEW)
        # маркер следует за машиной так же, как всплывающие цифры урона: смещение от
        # машины лежит в TruckDamageHandler.markersOffsets, позицию каждый кадр даёт его
        # GetMarkerPos (делегат getPos маркера)
        self.dh_offsets = imp("TruckDamageHandler", "markersOffsets", DAMAGE_HANDLER)
        self.dh_get_pos = imp("TruckDamageHandler", "GetMarkerPos", DAMAGE_HANDLER)
        mk_mod = ed[MARKERS]
        cb = mk_mod.find_type("CbReturnVector3d")
        self.get_pos_t = None if cb is None else import_type(m, mk_mod, cb)
        # цвет - как у строк окна ремонта (UiTextColors: белый / жёлтый / красный)
        self.view_colors = imp("PopupRepairUiViewNew", "colors", REPAIR_VIEW)
        self.by_status = imp("UiTextColors", "GetColorByStatusMinMax", TEXT_COLORS)
        self.red = imp("UiTextColors", "redColor", TEXT_COLORS)
        self.yellow = imp("UiTextColors", "yellowColor", TEXT_COLORS)
        self.color_eq = imp("Color", "IsEqual", COLOR)
        # жёлтое колесо: рисунок умножается на цвет, прозрачность не меняется
        # (SetupMultiplyer игры ещё и делает значок непрозрачным - кружок чернеет)
        self.ct_mult = imp("UiColorTransform", "multiplier", GFX)
        self.ct_shift = imp("UiColorTransform", "shift", GFX)
        self.rgba = {n: imp("Color", n, COLOR) for n in ("a", "r", "g", "b")}
        self.color_t = m.class_type("Color")
        self.color_tf = imp("UiDisplayObjectBase", "colorTransform", GFX)
        self.is_html = imp("UiLabel", "isHtml", GFX)
        self.g_html = ensure_global(m, ed[REPAIR_VIEW], "HtmlColorText")
        self.ct_t = m.class_type("UiColorTransform")
        self.order = imp("PopupRepairUiViewData2", F_ORDER, REPAIR_VIEW)
        self.arr_index_of = 14                                  # array.IndexOf (встроенный класс)
        self.arr_contains = 15                                  # array.Contains
        self.g_invert = ensure_global(m, ed[DAMAGE_HUD], "Transform3dInvert")
        self.g_loc = ensure_global(m, ed[SESSION], "GetLocalizationString")
        net = ed[NET_HEALTH]
        self.int_array_t = import_type(m, net, net.member_type(net.class_index("DamageParams"), "wheelDamageValue"))
        self.marker_t = m.class_type("UiHudLibTruckdmgmarker")
        self.wheel_img_t = m.class_type("UiHudLibImgwheels")
        self.string_t, self.float_t = m.find_type("string"), m.find_type("float")
        if None in (self.string_t, self.float_t, self.get_pos_t):
            raise PatchError("типы string/float/CbReturnVector3d не найдены в %s" % m.name)

    def wheel_ok(self, src, truck, w):
        """есть чем заменить колесо w машины truck и оно повреждено"""
        T, D, A = self.t, self.dmg, self.c.a
        return And(Ne(src, NULL), Ne(truck, NULL), Ge(w, Int(0)), Lt(w, Count(Field(truck, T["wheelDamages"]))),
                   Gt(Call(src, A["GetWheelRepairs"]), Int(0)),
                   Gt(Field(ArrGet(Field(truck, T["wheelDamages"]), w), D["damage"]), Int(0)))


def patch_wheel_create_data(w, fp):
    """CreateData (цель - машина): порядок колёс (слева направо, спереди назад) и строки
    повреждений колёс в этом порядке (damagesData[5...])"""
    c, m, code = w.c, w.c.m, fp.code
    hint = find_one(code, "01:1 07:0 0a:* 04:0 0d:* 07:-5 3c:*", "CreateData/hint")
    fi = c.fi
    T, D = w.t, w.dmg
    truck, data = Local(-3), Local(-5)
    ordl, wd, pw, n, inv, i, k, best, a, b, d = (fp.new_local() for _ in range(11))
    order = lambda: Field(data, w.order)
    eps = Const(m.const_float(fi, SAME_AXLE))
    x = lambda v: Field(Local(v), w.vx)
    z = lambda v: Field(Local(v), w.vz)
    create = lambda *v: GCall(c.g["PopupRepairUiViewTruckDataCreate"], *v)
    body = [If(c.single_player(), [
        SetLocal(ordl, New(m.const_type(fi, w.int_array_t))),
        SetField(data, w.order, Local(ordl)),
        SetLocal(wd, Field(truck, T["wheelDamages"])),
        SetLocal(pw, Call(truck, T["GetPosWheels"])),
        SetLocal(n, Count(Local(wd))),
        If(And(Ne(Local(pw), NULL), Eq(Count(Local(pw)), Local(n))), [
            # координаты колёс относительно рамы: x - вперёд, z - влево
            SetLocal(inv, GCall(w.g_invert, Call(truck, T["GetChassisWorldTransformValue"]))),
            SetLocal(i, Int(0)),
            While(Lt(Local(i), Local(n)), [
                ArrSet(Local(pw), Local(i), Call(Local(inv), w.point, ArrGet(Local(pw), Local(i)))),
            ], step=[SetLocal(i, Add(Local(i), Int(1)))]),
            SetLocal(k, Int(0)),
            While(Lt(Local(k), Local(n)), [
                SetLocal(best, Int(-1)),
                SetLocal(i, Int(0)),
                While(Lt(Local(i), Local(n)), [
                    If(Call(Local(ordl), w.arr_contains, Local(i)), [Continue()]),
                    If(Lt(Local(best), Int(0)), [SetLocal(best, Local(i)), Continue()]),
                    SetLocal(a, ArrGet(Local(pw), Local(i))),
                    SetLocal(b, ArrGet(Local(pw), Local(best))),
                    If(Or(FGt(x(a), FAdd(x(b), eps)), And(FGe(x(a), FSub(x(b), eps)), FGt(z(a), z(b)))),
                       [SetLocal(best, Local(i))]),
                ], step=[SetLocal(i, Add(Local(i), Int(1)))]),
                ArrAdd(Local(ordl), Local(best)),
            ], step=[SetLocal(k, Add(Local(k), Int(1)))]),
        ], [
            SetLocal(i, Int(0)),
            While(Lt(Local(i), Local(n)), [ArrAdd(Local(ordl), Local(i))],
                  step=[SetLocal(i, Add(Local(i), Int(1)))]),
        ]),
        SetLocal(k, Int(0)),
        While(Lt(Local(k), Local(n)), [
            SetLocal(d, ArrGet(Local(wd), ArrGet(Local(ordl), Local(k)))),
            ArrAdd(Field(data, c.data["damagesData"]),
                   create(Sub(Field(Local(d), D["damageCapacity"]), Field(Local(d), D["damage"])),
                          Field(Local(d), D["damageCapacity"]), Int(0),
                          Cond(Gt(Field(Local(d), D["damage"]), Int(0)), Int(1), Int(0)))),
        ], step=[SetLocal(k, Add(Local(k), Int(1)))]),
    ])]
    # перед подсказкой; ветка цели-аддона прыгает на подсказку мимо этого кода
    fp.insert(hint, compile_block(body), redirect=False)


def wheel_part_prologue(w, fp, part):
    """-> (операторы, src, truck, wheel): для строки «одно колесо» (part >= 100)"""
    c = w.c
    src, truck, wheel = fp.new_local(), fp.new_local(), fp.new_local()
    return [SetLocal(src, c.src_addon_expr()), SetLocal(truck, Field(THIS, c.f["targetTruck"])),
            SetLocal(wheel, Sub(part, Int(WHEEL_TYPE_BASE)))], Local(src), Local(truck), Local(wheel)


def patch_wheel_is_repair_enabled(w, fp):
    """IsRepairEnabled(part): одно колесо - есть запасное в источнике и колесо повреждено"""
    at = find_one(fp.code, "07:1 04:7 30:7 16:* 05:0 12:2", "IsRepairEnabled/none")
    at = fp.code[at + 3][1]
    part = Local(1)
    pre, src, truck, wheel = wheel_part_prologue(w, fp, part)
    body = [If(Ge(part, Int(WHEEL_TYPE_BASE)), pre + [
        Return(And(w.c.single_player(), w.wheel_ok(src, truck, wheel)), 2)])]
    fp.insert(at, compile_block(body))


def patch_wheel_repair_part(w, fp):
    """RepairPart(part): одно колесо - DamageController.RepairPart(1000 + колесо, ...)"""
    c = w.c
    part = Local(1)
    pre, src, truck, wheel = wheel_part_prologue(w, fp, part)
    dc = Call(GCall(c.g["GetCurrentGameSession"]), w.damage_ctrl)
    body = [If(Ge(part, Int(WHEEL_TYPE_BASE)), pre + [
        If(And(c.single_player(), w.wheel_ok(src, truck, wheel)),
           [Do(Call(dc, w.dc_repair, Add(Int(DC_WHEEL_BASE), wheel), Field(THIS, c.f["sourceAddon"]), truck))],
           [Do(Call(Call(THIS, c.f["GetView"]), c.view["PlayCantRepairSound"]))]),
        ReturnVoid(2)])]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def wheel_marker_remove(w, fp, fi, mc):
    """убрать маркер колеса совсем: RemoveObj уничтожает значок (одно снятие с учёта
    оставило бы его висеть на экране)"""
    m = w.c.m
    md, obj = fp.new_local(), fp.new_local()
    mid = Const(m.const_string(fi, WHEEL_MARKER_ID))
    return [
        SetLocal(md, DictGet(Field(mc, w.markers), mid, NULL)),
        If(Ne(Local(md), NULL), [
            SetLocal(obj, NULL),
            If(Ne(Field(Local(md), w.marker_data), NULL), [
                SetLocal(obj, Field(Field(Local(md), w.marker_data), w.marker_obj))]),
            If(Ne(Local(obj), NULL), [Do(Call(mc, w.remove_obj, Local(obj)))],
               [Do(Call(mc, w.release, Const(m.const_string(fi, WHEEL_MARKER_ID))))]),
        ]),
    ]


def patch_wheel_nav_panel(w, fp):
    """UpdateNavPanel(part): маркер выбранного колеса на машине (как в оверлее урона)"""
    c, m, fi = w.c, w.c.m, w.c.fi
    T, D = w.t, w.dmg
    part = Local(1)
    mc, truck, wheel, wd, pw, d, mk, img, num, last = (fp.new_local() for _ in range(10))
    hp, col, colors, ct, cm, cs, dh, offs, get_pos = (fp.new_local() for _ in range(9))
    S = lambda v: Cast(v, m.const_type(fi, w.string_t))
    F = lambda v: Cast(v, m.const_type(fi, w.float_t))
    k = lambda s_: Const(m.const_string(fi, s_))
    view = lambda: Call(THIS, c.f["GetView"])
    view_order = lambda: Field(Field(view(), w.view_last), w.order)
    value_tf = lambda: Field(Field(Field(Local(mk), w.mk["tfCont"]), w.dmg_value), w.value_tf)
    marker_id = k(WHEEL_MARKER_ID)
    body = [
        SetLocal(mc, Call(GCall(c.g["GetCurrentGameSession"]), w.markers_ctrl)),
        If(Ne(Local(mc), NULL), wheel_marker_remove(w, fp, fi, Local(mc)) + [
            SetLocal(truck, Field(THIS, c.f["targetTruck"])),
            If(And(Ge(part, Int(WHEEL_TYPE_BASE)), c.single_player(), Ne(Local(truck), NULL)), [
                SetLocal(wheel, Sub(part, Int(WHEEL_TYPE_BASE))),
                SetLocal(wd, Field(Local(truck), T["wheelDamages"])),
                SetLocal(pw, Call(Local(truck), T["GetPosWheels"])),
                If(And(Ne(Local(pw), NULL), Lt(Local(wheel), Count(Local(wd))), Lt(Local(wheel), Count(Local(pw)))), [
                    SetLocal(d, ArrGet(Local(wd), Local(wheel))),
                    SetLocal(hp, Sub(Field(Local(d), D["damageCapacity"]), Field(Local(d), D["damage"]))),
                    # номер колеса в списке (как в строке окна)
                    SetLocal(num, Add(Local(wheel), Int(1))),
                    SetLocal(last, Field(view(), w.view_last)),
                    If(And(Ne(Local(last), NULL), Ne(Field(Local(last), w.order), NULL)), [
                        SetLocal(num, Add(Call(view_order(), w.arr_index_of, Local(wheel)), Int(1)))]),
                    SetLocal(mk, New(m.const_type(fi, w.marker_t))),
                    SetLocal(img, New(m.const_type(fi, w.wheel_img_t))),
                    Do(Call(Local(img), w.set_parent, Field(Local(mk), w.mk["partImg"]))),
                    SetField(Field(Field(Local(mk), w.mk["truckDmgModulePart"]), w.part_tf), w.label_text,
                             Concat(Concat(GCall(w.g_loc, k(WHEEL_LABEL)), k(" ")), S(Local(num)))),
                    # цвет - как у строки колеса в окне: белый, жёлтый (<= 75%), красный (<= 25%).
                    # Красное колесо - кадр damaged маркера, как в оверлее урона (рисунок колеса
                    # игра красит сама); жёлтое - рисунок колеса умножается на жёлтый
                    SetLocal(colors, Field(view(), w.view_colors)),
                    SetLocal(col, NULL),
                    If(Ne(Local(colors), NULL), [
                        SetLocal(col, Call(Local(colors), w.by_status, F(Local(hp)),
                                           F(Field(Local(d), D["damageCapacity"]))))]),
                    If(Ne(Local(col), NULL), [
                        SetField(value_tf(), w.is_html, Bool(True)),
                        SetField(value_tf(), w.label_text,
                                 Concat(Concat(GCall(w.g_html, S(Local(hp)), Local(col)), k("/")),
                                        S(Field(Local(d), D["damageCapacity"])))),
                        If(Call(Local(col), w.color_eq, Field(Local(colors), w.yellow)), [
                            SetLocal(ct, New(m.const_type(fi, w.ct_t))),
                            SetLocal(cm, New(m.const_type(fi, w.color_t))),
                            SetField(Local(cm), w.rgba["a"], Const(m.const_float(fi, 255.0))),
                        ] + [SetField(Local(cm), w.rgba[ch], Field(Local(col), w.rgba[ch])) for ch in "rgb"] + [
                            SetLocal(cs, New(m.const_type(fi, w.color_t))),
                        ] + [SetField(Local(cs), w.rgba[ch], Const(m.const_float(fi, 0.0))) for ch in "argb"] + [
                            SetField(Local(ct), w.ct_mult, Local(cm)),
                            SetField(Local(ct), w.ct_shift, Local(cs)),
                            SetField(Local(img), w.color_tf, Local(ct)),
                        ]),
                    ], [
                        SetField(value_tf(), w.label_text,
                                 Concat(Concat(S(Local(hp)), k("/")), S(Field(Local(d), D["damageCapacity"])))),
                    ]),
                    Do(Call(Local(mk), w.goto_stop,
                            Cond(And(Ne(Local(col), NULL), Call(Local(col), w.color_eq, Field(Local(colors), w.red))),
                                 k("damaged"), k("normal")))),
                    # привязка к машине: смещение колеса от машины -> markersOffsets,
                    # позицию каждый кадр считает TruckDamageHandler.GetMarkerPos
                    SetLocal(get_pos, NULL),
                    SetLocal(dh, Field(Local(truck), T["truckDamageHandler"])),
                    If(Ne(Local(dh), NULL), [
                        SetLocal(offs, Field(Local(dh), w.dh_offsets)),
                        If(Ne(Local(offs), NULL), [
                            DictSet(Local(offs), marker_id,
                                    Call(GCall(w.g_invert, Call(Local(truck), T["GetTransformValue"])), w.point,
                                         ArrGet(Local(pw), Local(wheel)))),
                            SetLocal(get_pos, Delegate(Local(dh), w.dh_get_pos, 1, m.const_type(fi, w.get_pos_t),
                                                       m.const_method_ref(fi), marker_id)),
                        ]),
                    ]),
                    Do(Call(Local(mc), w.add_obj, Local(mk), ArrGet(Local(pw), Local(wheel)), marker_id,
                            Int(0), NULL, Local(get_pos), Bool(False))),
                ]),
            ]),
        ]),
    ]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def patch_wheel_hide(w, fp):
    """Hide: убрать маркер колеса"""
    c = w.c
    mc = fp.new_local()
    body = [SetLocal(mc, Call(GCall(c.g["GetCurrentGameSession"]), w.markers_ctrl)),
            If(Ne(Local(mc), NULL), wheel_marker_remove(w, fp, c.fi, Local(mc)))]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def apply_repair(ed, enabled):
    c = RepairCtx(ed)
    m = c.m
    P = "PopupRepairUiControllerNew"
    jobs = [("UpdateNearTrucks", lambda fp: patch_update_near_trucks(c, fp, enabled))]
    if "repair_from_nearby" in enabled:
        jobs.append(("IsCanBeShown", lambda fp: patch_is_can_be_shown(c, fp)))
    if "repair_parts_transfer" in enabled:
        jobs += [("SwitchSource", lambda fp: patch_self_skip(c, fp)),
                 ("SwitchTarget", lambda fp: patch_self_skip(c, fp)),
                 ("RepairAll", lambda fp: patch_repair_all(c, fp)),
                 ("RepairPart", lambda fp: patch_repair_part(c, fp)),
                 ("IsRepairEnabled", lambda fp: patch_is_repair_enabled(c, fp)),
                 ("CreateData", lambda fp: patch_create_data(c, fp)),
                 ("GetRepairTruckMarker", lambda fp: patch_truck_marker(c, fp)),
                 ("CreateMarkers", lambda fp: patch_create_markers(c, fp))]
    if WHEEL_KEY in enabled:
        w = WheelCtx(c, ed)
        jobs += [("CreateData", lambda fp: patch_wheel_create_data(w, fp)),
                 ("IsRepairEnabled", lambda fp: patch_wheel_is_repair_enabled(w, fp)),
                 ("RepairPart", lambda fp: patch_wheel_repair_part(w, fp)),
                 ("UpdateNavPanel", lambda fp: patch_wheel_nav_panel(w, fp)),
                 ("Hide", lambda fp: patch_wheel_hide(w, fp))]
    for name, job in jobs:
        c.fi = m.func_index(name, P)
        c.fname = name
        fp = FunctionPatch(m.func_code(c.fi))
        job(fp)
        m.set_func_code(c.fi, fp.build())

# ---------------------------------------------------------------------------
# вид окна ремонта: строки для цели-аддона


def apply_repair_view(ed, enabled):
    vc = ViewCtx(ed)
    v, V = vc.v, vc.V
    service = "repair_parts_transfer" in enabled
    wv = WheelView(vc, ed) if WHEEL_KEY in enabled else None

    # UpdateData (одним проходом: места ищутся в исходном коде)
    fi = v.func_index("UpdateData", V)
    fp = FunctionPatch(v.func_code(fi))
    code = fp.code
    rows = find_one(code, "01:1 07:-1 0a:%d 06:* 06:* 04:1 07:0 04:4 0d:%d" % (vc.dd, vc.create_row), "View/rows")
    setdata = find_one(code, "01:1 05:1 07:-4 07:0 0a:%d 04:2 0d:*" % vc.list, "View/set-data")
    restore = find_one(code, "07:0 0a:%d 04:-1 30:8 16:*" % vc.sel, "View/restore-selection")
    data_at = find_one(code, "07:1 37:0 3b:-1 02:0", "View/data") + 4
    if service:
        # цель-аддон: вместо 5 узлов машины - «Запчасти» и «Колёса»
        k = lambda s_: Const(v.const_string(fi, s_))
        row = lambda typ, label, icon: ArrAdd(Local(-4), Call(THIS, vc.create_row, Int(typ), k(label), k(icon),
                                                              Field(Local(-1), vc.dd)))
        fp.insert(rows, compile_block([If(vc.is_service(Local(-1)), [
            row(0, PARTS_LABEL, PARTS_ICON), row(1, WHEELS_LABEL, WHEELS_ICON), Goto(("orig", setdata))])]))
        # выбранная строка могла пропасть (строк стало меньше)
        fp.insert(restore, compile_block([
            If(Ge(Field(THIS, vc.sel), Count(Local(-4))), [SetField(THIS, vc.sel, Int(0))])]))
    if wv:
        wheel_view_update_data(vc, wv, fp, fi, data_at, rows, setdata)
    v.set_func_code(fi, fp.build())

    # UpdateRepairHint
    fi = v.func_index("UpdateRepairHint", V)
    fp = FunctionPatch(v.func_code(fi))
    if service:
        # у цели-аддона нет надписи «Нет урона»
        at = 1 if fp.locals.has_reserve else 0
        fp.insert(at, compile_block([
            If(And(vc.is_service(Field(THIS, vc.last)),
                   Eq(Field(THIS, vc.hint_text), Const(v.const_string(fi, FULLY_REPAIRED)))),
               [SetField(THIS, vc.hint_text, Const(v.const_string(fi, "")))])]), redirect=False)
    if wv:
        wheel_view_hint(vc, wv, fp, fi)
    v.set_func_code(fi, fp.build())

    if wv:
        apply_wheel_view(ed, vc, wv)

# ---------------------------------------------------------------------------
# отдельные колёса: замена колеса (DamageController) и вид окна


def apply_damage_controller(ed):
    """DamageController.RepairPart(1000 + колесо, ...): заменить одно колесо на запасное"""
    d = ed[DAMAGE]
    DC = "DamageController"
    fi = d.func_index("RepairPart", DC)
    fp = FunctionPatch(d.func_code(fi))
    target_repair = member_slot(d, DC, "targetRepair")
    total = member_slot(d, DC, "rapairTotalValue")
    total_repair = member_slot(ed[NET_HEALTH], "DamageParams", "totalRepair")
    total_wheel = member_slot(ed[NET_HEALTH], "DamageParams", "totalWheelRepair")
    wheel_values = member_slot(ed[NET_HEALTH], "DamageParams", "wheelDamageValue")
    wheels = member_slot(ed[TRUCK], "Truck", "wheelDamages")
    damage = member_slot(ed[ADDON], "DamageData", "damage")
    for cls, n, mod in (("DamageParams", "totalWheelRepair", NET_HEALTH), ("DamageParams", "wheelDamageValue", NET_HEALTH),
                        ("Truck", "wheelDamages", TRUCK), ("DamageData", "damage", ADDON)):
        ensure_member(d, cls, n, ed[mod])
    code = fp.code
    at = find_one(code, "07:1 04:1 30:7 16:*", "DamageController/wheels")
    tail = find_one(code, "07:0 0a:%d 07:-1 0a:%d 20:0 07:0 3c:%d" % (total, total_repair, total), "DamageController/tail")
    wheel, wd = fp.new_local(), fp.new_local()
    params, avail, truck = Local(-1), Local(-3), Local(3)
    body = [If(Ge(Local(1), Int(DC_WHEEL_BASE)), [
        SetLocal(wheel, Sub(Local(1), Int(DC_WHEEL_BASE))),
        SetField(THIS, target_repair, Int(1)),                  # дальше - как ремонт колёс
        SetLocal(wd, Field(truck, wheels)),
        If(And(Lt(Local(wheel), Count(Local(wd))), Gt(avail, Int(0)),
               Gt(Field(ArrGet(Local(wd), Local(wheel)), damage), Int(0))), [
            SetField(params, total_wheel, Add(Field(params, total_wheel), Int(1))),
            ArrSet(Field(params, wheel_values), Local(wheel), Int(0)),
            SetField(THIS, total, Add(Field(THIS, total), Field(ArrGet(Local(wd), Local(wheel)), damage))),
        ]),
        Goto(("orig", tail)),
    ])]
    fp.insert(at, compile_block(body))
    d.set_func_code(fi, fp.build())


class ViewCtx:
    """символы вида окна ремонта"""

    def __init__(self, ed):
        v = ed[REPAIR_VIEW]
        self.v = v
        V = "PopupRepairUiViewNew"
        self.V = V
        sl = lambda n, cls=V: member_slot(v, cls, n)
        self.sel, self.last, self.hint_text = sl("selectedIndex"), sl("lastData"), sl("hintText")
        self.create_row = sl("PopupRepairUiViewLirItemDataCreateByDamageData")
        self.list = sl("repairPositionList")
        self.repair_view = sl("repairView")
        self.update_data, self.update_hint, self.switch_target = sl("UpdateData"), sl("UpdateRepairHint"), sl("SwitchTarget")
        self.click_sound = sl("switchClickSound")
        self.dd = sl("damagesData", "PopupRepairUiViewData2")
        self.max_health = sl("maxHealth", "PopupRepairUiViewTruckData")
        self.item_type = sl("type", "PopupRepairUiViewLirItemData")
        self.is_all = sl("isAll", "PopupRepairUiViewLirItemData")

    def is_service(self, data):
        dd = lambda: Field(data, self.dd)
        return And(Ne(data, NULL), Gt(Count(dd()), Int(4)),
                   Eq(Field(ArrGet(Field(data, self.dd), Int(4)), self.max_health), Int(SERVICE_SENTINEL)))


class WheelView:
    """символы вида для отдельных колёс"""

    def __init__(self, vc, ed):
        v = vc.v
        self.vc = vc
        imp = lambda cls, n, mod, dc=None: ensure_member(v, cls, n, ed[mod], dc)
        D2 = "PopupRepairUiViewData2"
        net = ed[NET_HEALTH]
        int_array = import_type(v, net, net.member_type(net.class_index("DamageParams"), "wheelDamageValue"))
        arrow_t = v.class_type("UiPopupLibHudpopuparrow")
        self.order = v.add_class_field(D2, F_ORDER, int_array)
        self.prev = v.add_class_field(D2, F_PREV, arrow_t)
        self.next = v.add_class_field(D2, F_NEXT, arrow_t)
        self.arrow_t = arrow_t
        self.get_data = ext_slot(v, "GetData", "UiListAdapter")
        self.get_selected = ext_slot(v, "GetSelectedData", "UiListAdapter")
        self.select_index = imp("UiListAdapter", "SelectIndex", LIST_ADAPTER)
        self.input_screen = imp("UiListAdapter", "uiInputScreen", LIST_ADAPTER)
        self.set_data = ext_slot(v, "SetData", "UiListAdapter")
        self.try_get = imp("SslUiInputScreen", "TryGet", INPUT_SCREEN)
        self.on_press = imp("SslUiInputEvent", "OnPress", INPUT_EVENT)
        self.on_click = imp("UiPopupLibHudpopuparrow", "OnClick", GFX, "UiMovieClip")
        self.set_parent = ext_slot(v, "SetParent")
        self.ui = {n: imp("UiDisplayObjectBase", n, GFX) for n in (
            "x", "y", "width", "height", "scaleX", "scaleY", "rotation", "visible", "LocalToOtherCoords")}
        self.vec_x, self.vec_y = imp("Vector2d", "x", VEC2), imp("Vector2d", "y", VEC2)
        self.items = imp("UiCoreList", "items", GFX_LIST)
        self.row_header = imp("UiPopupLibPopuprepairlir", "headerTf", POPUP_LIB)
        self.item_data = imp("UiListItem", "data", GFX_LIST)
        self.add_callback = imp("Future", "AddCallback", FUTURE)
        self.g_loc = ensure_global(v, ed[SESSION], "GetLocalizationString")
        self.g_vec_zero = ensure_global(v, ed[GFX], "Vector2dZero")
        self.details = ext_slot(v, "repairTargetDetails")
        self.switcher = ext_slot(v, "repairTargetSwitcher")
        self.prev_btn = ext_slot(v, "prevBtn", "UiPopupLibHudpopuprepairtargetswitcher")
        self.next_btn = ext_slot(v, "nextBtn", "UiPopupLibHudpopuprepairtargetswitcher")
        self.ui_sounds = ext_slot(v, "uiSounds")
        self.play_sound = ext_slot(v, "PlaySound", "UiSounds")
        # цвет строки «Колёса» - по худшему колесу
        self.health = member_slot(v, "PopupRepairUiViewTruckData", "health")
        self.value_text = member_slot(v, "PopupRepairUiViewLirItemData", "valueText")
        self.item_color = member_slot(v, "PopupRepairUiViewLirItemData", "color")
        self.colors = member_slot(v, vc.V, "colors")
        self.by_status = imp("UiTextColors", "GetColorByStatusMinMax", TEXT_COLORS)
        self.g_html = ext_gid(v, "HtmlColorText")
        self.float_t = v.find_type("float")
        self.cb_void_t = v.find_type("__class__void_")
        self.cb_variant_t = v.find_type("__class__void__variant")
        self.string_t = v.find_type("string")
        if None in (self.cb_void_t, self.cb_variant_t, self.string_t, self.float_t):
            raise PatchError("не найдены типы делегатов в %s" % v.name)
        self.arr_index_of = 14


def wheel_row_lookup(wv, fp, items, data):
    """операторы: найти в списке строку колёс (тип 1 или >= 100) -> (операторы, индекс, позиция)
    позиция: -1 - «все колёса», иначе номер колеса в порядке показа"""
    vc = wv.vc
    idx, pos, i, n, it, t = (fp.new_local() for _ in range(6))
    stmts = [SetLocal(idx, Int(-1)), SetLocal(pos, Int(-1)),
             If(Ne(items, NULL), [ForEach(items, i, n, it, [
                 If(Eq(Local(it), NULL), [Continue()]),
                 If(Field(Local(it), vc.is_all), [Continue()]),
                 SetLocal(t, Field(Local(it), vc.item_type)),
                 If(Or(Eq(Local(t), Int(1)), Ge(Local(t), Int(WHEEL_TYPE_BASE))), [
                     SetLocal(idx, Local(i)),
                     If(And(Ge(Local(t), Int(WHEEL_TYPE_BASE)), Ne(Field(data, wv.order), NULL)), [
                         SetLocal(pos, Call(Field(data, wv.order), wv.arr_index_of,
                                            Sub(Local(t), Int(WHEEL_TYPE_BASE))))]),
                     Break()]),
             ])])]
    return stmts, idx, pos


def wheel_name(wv, fi, pos):
    """«КОЛЕСО n» (n с единицы)"""
    v = wv.vc.v
    k = lambda s_: Const(v.const_string(fi, s_))
    return Concat(Concat(GCall(wv.g_loc, k(WHEEL_LABEL)), k(" ")),
                  Cast(Add(pos, Int(1)), v.const_type(fi, wv.string_t)))


def wheels_row_color(vc, wv, fp, fi, item, dd):
    """строка «Колёса»: первая цифра и значок - цветом худшего колеса (белый / жёлтый /
    красный, как у строк окна), а не по числу лопнувших колёс"""
    v = vc.v
    j, best, e, b, col = (fp.new_local() for _ in range(5))
    H, M = wv.health, vc.max_health
    F = lambda x: Cast(x, v.const_type(fi, wv.float_t))
    S = lambda x: Cast(x, v.const_type(fi, wv.string_t))
    fld = lambda x, f: F(Field(Local(x), f))
    total = lambda: ArrGet(dd(), Int(1))
    return [If(Gt(Count(dd()), Int(WHEEL_DD_BASE)), [
        SetLocal(best, Int(WHEEL_DD_BASE)),
        SetLocal(j, Int(WHEEL_DD_BASE + 1)),
        While(Lt(Local(j), Count(dd())), [
            SetLocal(e, ArrGet(dd(), Local(j))),
            SetLocal(b, ArrGet(dd(), Local(best))),
            # e.health / e.max < b.health / b.max (без деления)
            If(FLt(FMul(fld(e, H), fld(b, M)), FMul(fld(b, H), fld(e, M))), [SetLocal(best, Local(j))]),
        ], step=[SetLocal(j, Add(Local(j), Int(1)))]),
        SetLocal(b, ArrGet(dd(), Local(best))),
        SetLocal(col, Call(Field(THIS, wv.colors), wv.by_status, fld(b, H), fld(b, M))),
        SetField(item, wv.value_text,
                 Concat(Concat(GCall(wv.g_html, S(Field(total(), H)), Local(col)), Const(v.const_string(fi, "/"))),
                        S(Field(total(), M)))),
        SetField(item, wv.item_color, Local(col)),
    ])]


def wheel_view_update_data(vc, wv, fp, fi, at, row, setdata):
    """UpdateData: стрелки (переносятся из прошлых данных), строка колёс, расстановка стрелок.
    at - после «data = (PopupRepairUiViewData2)arg», row - создание строки колёс, setdata - SetData"""
    v = vc.v
    code = fp.code
    lst = lambda: Field(THIS, vc.list)
    rv = lambda: Field(THIS, vc.repair_view)
    data = Local(-1)
    old = lambda: Field(THIS, vc.last)
    arrow = fp.new_local()
    fnref = v.const_method_ref(fi)
    make_arrows = []
    # стрелка в библиотеке смотрит влево: правую отражаем по горизонтали
    for fld, sx, direction in ((wv.prev, ARROW_SCALE, -WHEEL_FLIP_MOUSE), (wv.next, -ARROW_SCALE, WHEEL_FLIP_MOUSE)):
        make_arrows += [
            SetLocal(arrow, New(v.const_type(fi, wv.arrow_t))),
            Do(Call(Local(arrow), wv.set_parent, rv())),
            SetField(Local(arrow), wv.ui["scaleX"], Const(v.const_float(fi, sx))),
            SetField(Local(arrow), wv.ui["scaleY"], Const(v.const_float(fi, ARROW_SCALE))),
            SetField(Local(arrow), wv.ui["visible"], Bool(False)),
            Subscribe(Local(arrow), v.const_int(fi, wv.on_click),
                      Delegate(THIS, vc.switch_target, 1, v.const_type(fi, wv.cb_void_t), fnref, Int(direction))),
            SetField(data, fld, Local(arrow)),
        ]
    fp.insert(at, compile_block([If(Ne(data, NULL), [
        If(Ne(old(), NULL), [SetField(data, wv.prev, Field(old(), wv.prev)),
                             SetField(data, wv.next, Field(old(), wv.next))]),
        If(Eq(Field(data, wv.prev), NULL), make_arrows),
    ])]))
    # строка колёс: «КОЛЕСА» или выбранное колесо (выбор берётся из прежних строк списка)
    icon_k, label_k = code[row + 3][1], code[row + 4][1]
    pre, _, pos = wheel_row_lookup(wv, fp, Call(lst(), wv.get_data), data)
    item = fp.new_local()
    dd = lambda: Field(data, vc.dd)
    order = lambda: Field(data, wv.order)
    body = pre + [
        SetLocal(item, NULL),
        If(And(Ge(Local(pos), Int(0)), Lt(Add(Local(pos), Int(WHEEL_DD_BASE)), Count(dd()))), [
            SetLocal(item, Call(THIS, vc.create_row, Add(Local(pos), Int(WHEEL_DD_BASE)), wheel_name(wv, fi, Local(pos)),
                                Const(icon_k), dd())),
            SetField(Local(item), vc.item_type, Add(ArrGet(order(), Local(pos)), Int(WHEEL_TYPE_BASE))),
        ]),
        If(Eq(Local(item), NULL), [SetLocal(item, Call(THIS, vc.create_row, Int(1), Const(label_k), Const(icon_k), dd())),
                                   ] + wheels_row_color(vc, wv, fp, fi, Local(item), dd)),
    ]
    fp.insert(row, compile_block(body))
    fp.replace(row, row + 9, [Ins(0x07, item)])
    # после заполнения списка - расставить стрелки (UpdateRepairHint)
    if code[setdata + 7] != (0x02, 0):
        raise PatchError("неожиданный код после SetData")
    fut = fp.new_local()
    body = [If(Ne(Local(fut), NULL), [
        Do(Call(Local(fut), wv.add_callback,
                Delegate(THIS, vc.update_hint, 0, v.const_type(fi, wv.cb_variant_t), fnref)))])]
    fp.replace(setdata + 7, setdata + 8, [Ins(0x3B, fut), Ins(0x02)] + compile_block(body))


def wheel_view_hint(vc, wv, fp, fi):
    """UpdateRepairHint: показать/спрятать и расставить стрелки у строки колёс"""
    v = vc.v
    lst = lambda: Field(THIS, vc.list)
    rv = lambda: Field(THIS, vc.repair_view)
    d, row_item, i, n, it, pos2, ry = (fp.new_local() for _ in range(7))
    show, a, hdr, ppos, npos, dx = (fp.new_local() for _ in range(6))
    sw = lambda: Field(rv(), wv.switcher)
    pre, widx, _ = wheel_row_lookup(wv, fp, Call(lst(), wv.get_data), Local(d))
    wdata = fp.new_local()
    U = wv.ui
    half = Const(v.const_float(fi, 0.5))
    inset = Const(v.const_float(fi, ARROW_INSET))
    drop = Const(v.const_float(fi, ARROW_SHIFT_Y))
    fx = lambda o, f: Field(o, U[f])
    body = [
        SetLocal(d, Field(THIS, vc.last)),
        If(And(Ne(Local(d), NULL), Ne(Field(Local(d), wv.prev), NULL), Ne(Field(Local(d), wv.next), NULL)), [
            SetLocal(show, Bool(False)),
            SetLocal(row_item, NULL),
            If(And(Not(vc.is_service(Local(d))), Ne(Field(Local(d), wv.order), NULL),
                   Gt(Count(Field(Local(d), wv.order)), Int(0))), pre + [
                If(Ge(Local(widx), Int(0)), [
                    SetLocal(wdata, ArrGet(Call(lst(), wv.get_data), Local(widx))),
                    ForEach(Field(Field(rv(), wv.details), wv.items), i, n, it, [
                        If(And(Ne(Local(it), NULL), Eq(Field(Local(it), wv.item_data), Local(wdata))),
                           [SetLocal(row_item, Local(it)), Break()]),
                    ]),
                ]),
            ]),
            If(Ne(Local(row_item), NULL), [
                # по вертикали - по центру текста строки; по горизонтали - от колонок
                # стрелок переключателя цели внутрь, вплотную к краям строки
                SetLocal(hdr, Field(Local(row_item), wv.row_header)),
                SetLocal(pos2, NULL),
                If(Ne(Local(hdr), NULL), [
                    SetLocal(pos2, Call(Local(hdr), U["LocalToOtherCoords"], rv(), GCall(wv.g_vec_zero)))]),
                SetLocal(ppos, Call(Field(sw(), wv.prev_btn), U["LocalToOtherCoords"], rv(), GCall(wv.g_vec_zero))),
                SetLocal(npos, Call(Field(sw(), wv.next_btn), U["LocalToOtherCoords"], rv(), GCall(wv.g_vec_zero))),
                If(And(Ne(Local(pos2), NULL), Ne(Local(ppos), NULL), Ne(Local(npos), NULL)), [
                    SetLocal(show, Bool(True)),
                    SetLocal(ry, FAdd(Field(Local(pos2), wv.vec_y), FMul(fx(Local(hdr), "height"), half))),
                    SetLocal(dx, FMul(FSub(Field(Local(npos), wv.vec_x), Field(Local(ppos), wv.vec_x)), inset)),
                    SetLocal(a, Field(Local(d), wv.prev)),
                    SetField(Local(a), U["x"], FAdd(Field(Local(ppos), wv.vec_x), Local(dx))),
                    SetField(Local(a), U["y"], FAdd(Local(ry), FMul(fx(Local(a), "height"), drop))),
                    SetLocal(a, Field(Local(d), wv.next)),
                    SetField(Local(a), U["x"], FSub(Field(Local(npos), wv.vec_x), Local(dx))),
                    SetField(Local(a), U["y"], FAdd(Local(ry), FMul(fx(Local(a), "height"), drop))),
                ]),
            ]),
            SetField(Field(Local(d), wv.prev), U["visible"], Local(show)),
            SetField(Field(Local(d), wv.next), U["visible"], Local(show)),
        ]),
    ]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def apply_wheel_view(ed, vc, wv):
    v, V = vc.v, vc.V
    lst = lambda: Field(THIS, vc.list)

    # SwitchTarget(direction): ±1000/±2000 - перелистнуть колесо; обычное переключение
    # цели сбрасывает выбор колеса
    fi = v.func_index("SwitchTarget", V)
    fp = FunctionPatch(v.func_code(fi))
    direction = Local(1)
    d, items, p, n, i, it = (fp.new_local() for _ in range(6))
    pre, widx, pos = wheel_row_lookup(wv, fp, Local(items), Local(d))
    order = lambda: Field(Local(d), wv.order)
    flip = [
        SetLocal(d, Field(THIS, vc.last)),
        If(And(Ne(Local(d), NULL), Not(vc.is_service(Local(d))), Ne(order(), NULL)), [
            SetLocal(n, Count(order())),
            SetLocal(items, Call(lst(), wv.get_data)),
            If(Gt(Local(n), Int(0)), pre + [
                If(Ge(Local(widx), Int(0)), [
                    # клавиатура - только когда выбрана строка колёс
                    If(And(Or(Ge(direction, Int(WHEEL_FLIP_KEY)), Le(direction, Int(-WHEEL_FLIP_KEY))),
                           Ne(Call(lst(), wv.get_selected), ArrGet(Local(items), Local(widx)))), [ReturnVoid(2)]),
                    SetLocal(p, Cond(Gt(direction, Int(0)), Add(Local(pos), Int(1)), Sub(Local(pos), Int(1)))),
                    If(Ge(Local(p), Local(n)), [SetLocal(p, Int(-1))]),
                    If(Lt(Local(p), Int(-1)), [SetLocal(p, Sub(Local(n), Int(1)))]),
                    SetField(ArrGet(Local(items), Local(widx)), vc.item_type,
                             Cond(Lt(Local(p), Int(0)), Int(1), Add(ArrGet(order(), Local(p)), Int(WHEEL_TYPE_BASE)))),
                    Do(Call(lst(), wv.select_index, Local(widx))),
                    Do(Call(THIS, vc.update_data, Local(d))),
                    Do(Call(Field(THIS, wv.ui_sounds), wv.play_sound, Field(THIS, vc.click_sound))),
                ]),
            ]),
        ]),
        ReturnVoid(2),
    ]
    reset = [SetLocal(items, Call(lst(), wv.get_data)),
             If(Ne(Local(items), NULL), [ForEach(Local(items), i, n, it, [
                 If(And(Ne(Local(it), NULL), Ge(Field(Local(it), vc.item_type), Int(WHEEL_TYPE_BASE))),
                    [SetField(Local(it), vc.item_type, Int(1))]),
             ])])]
    body = [If(Or(Ge(direction, Int(WHEEL_FLIP_MOUSE)), Le(direction, Int(-WHEEL_FLIP_MOUSE))), flip, reset)]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)
    v.set_func_code(fi, fp.build())

    # Hide: при закрытии окна выбор колеса сбрасывается
    fi = v.func_index("Hide", V)
    fp = FunctionPatch(v.func_code(fi))
    items, i, n, it = (fp.new_local() for _ in range(4))
    body = [SetLocal(items, Call(lst(), wv.get_data)),
            If(Ne(Local(items), NULL), [ForEach(Local(items), i, n, it, [
                If(And(Ne(Local(it), NULL), Ge(Field(Local(it), vc.item_type), Int(WHEEL_TYPE_BASE))),
                   [SetField(Local(it), vc.item_type, Int(1))]),
            ])])]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)
    v.set_func_code(fi, fp.build())

    # SelectRepairPosition: строка «одно колесо» -> её строка повреждений (5 + позиция)
    fi = v.func_index("SelectRepairPosition", V)
    fp = FunctionPatch(v.func_code(fi))
    at = find_one(fp.code, "07:-1 0a:%d 07:0 0a:%d 0a:%d 3f:0" % (vc.item_type, vc.last, vc.dd), "View/select-dd")
    idx, p = fp.new_local(), fp.new_local()
    ld = lambda: Field(THIS, vc.last)
    pre = [SetLocal(idx, Field(Local(-1), vc.item_type)),
           If(Ge(Local(idx), Int(WHEEL_TYPE_BASE)), [
               SetLocal(p, Int(-1)),
               If(Ne(Field(ld(), wv.order), NULL), [
                   SetLocal(p, Call(Field(ld(), wv.order), wv.arr_index_of, Sub(Local(idx), Int(WHEEL_TYPE_BASE))))]),
               SetLocal(idx, Add(Local(p), Int(WHEEL_DD_BASE))),
               If(Or(Lt(Local(p), Int(0)), Ge(Local(idx), Count(Field(ld(), vc.dd)))), [SetLocal(idx, Int(1))]),
           ])]
    fp.insert(at, compile_block(pre))
    fp.replace(at, at + 6, ArrGet(Field(ld(), vc.dd), Local(idx)).emit())
    v.set_func_code(fi, fp.build())

    # GetFullRepairCostStr: «Все» считается только по 5 узлам, без строк отдельных колёс
    fi = v.func_index("GetFullRepairCostStr", V)
    fp = FunctionPatch(v.func_code(fi))
    at = find_one(fp.code, "07:-3 41:0 3b:-4 02:0", "View/full-cost") + 4
    fp.insert(at, compile_block([If(Gt(Local(-4), Int(WHEEL_DD_BASE)), [SetLocal(-4, Int(WHEEL_DD_BASE))])]))
    v.set_func_code(fi, fp.build())

    # UpdateFullRepairHint: подсказка «Все» тоже только по 5 узлам - строки отдельных
    # колёс (частично побитых) не должны требовать очков ремонта колёс
    fi = v.func_index("UpdateFullRepairHint", V)
    fp = FunctionPatch(v.func_code(fi))
    at = find_one(fp.code, "07:-3 41:0 3b:-4 02:0", "View/full-hint") + 4
    fp.insert(at, compile_block([If(Gt(Local(-4), Int(WHEEL_DD_BASE)), [SetLocal(-4, Int(WHEEL_DD_BASE))])]))
    v.set_func_code(fi, fp.build())

    # SubscribeContent / UnsubscribeContent: стрелки клавиатуры (ввод списка)
    for fname, subscribe in (("SubscribeContent", True), ("UnsubscribeContent", False)):
        fi = v.func_index(fname, V)
        fp = FunctionPatch(v.func_code(fi))
        scr, ev = fp.new_local(), fp.new_local()
        fnref = v.const_method_ref(fi)
        body = [SetLocal(scr, Field(lst(), wv.input_screen))]
        inner = []
        for key, direction in (("Left", -WHEEL_FLIP_KEY), ("Right", WHEEL_FLIP_KEY)):
            if subscribe:
                act = Subscribe(Local(ev), v.const_int(fi, wv.on_press),
                                Delegate(THIS, vc.switch_target, 1, v.const_type(fi, wv.cb_void_t), fnref, Int(direction)))
            else:
                act = Unsubscribe(THIS, Local(ev), v.const_int(fi, wv.on_press))
            inner += [SetLocal(ev, Call(Local(scr), wv.try_get, Const(v.const_string(fi, key)))),
                      If(Ne(Local(ev), NULL), [act])]
        body.append(If(Ne(Local(scr), NULL), inner))
        if subscribe:
            at = len(fp.code) - 1                   # перед последним retv
            if fp.code[at][0] != 0x13:
                raise PatchError("неожиданный конец %s" % fname)
            fp.insert(at, compile_block(body), redirect=False)
        else:
            at = 1 if fp.locals.has_reserve else 0
            fp.insert(at, compile_block(body), redirect=False)
        v.set_func_code(fi, fp.build())


# ---------------------------------------------------------------------------
# меню взаимодействия (HUD)


def apply_hud(ed, enabled):
    h = ed[HUD]
    H = "HudInteractionPanelController"
    s = Sym(ed)
    T = {n: s(TRUCK, "Truck", n) for n in ("GetWinchTruck", "GetCargoes")}
    is_empty = 9                                    # dict.IsEmpty (встроенный класс)
    if "repair_from_nearby" in enabled:
        fi = h.func_index("CreateTruckData", H)
        fp = FunctionPatch(h.func_code(fi))
        # if (L) кнопка «Ремонт» (действие 12)  ->  if (!L) L = repairPopup.IsCanBeShown()
        at = find_one(fp.code, "07:* 16:* 01:1 06:* 06:* 04:12 06:* 07:0 04:4 0d:*", "HUD/repair-button")
        flag = fp.code[at][1]
        popup = Field(THIS, member_slot(h, H, "repairPopup"))
        slot = ensure_member(h, "PopupRepairUiControllerNew", "IsCanBeShown", ed[REPAIR])
        body = [If(And(Not(Local(flag)), Ne(popup, NULL)), [SetLocal(flag, Call(popup, slot))])]
        fp.insert(at, compile_block(body))
        h.set_func_code(fi, fp.build())
    if "winch_unpack_cargo" in enabled:
        for n in ("GetWinchTruck", "GetCargoes"):
            ensure_member(h, "Truck", n, ed[TRUCK])
        cur = member_slot(h, H, "currentTruck")
        utils = member_slot(h, H, "truckCargoUtils")
        unpack = ext_slot(h, "UnpackCargo")
        pack = ext_slot(h, "PackCargo", "TruckCargoUtils")
        check_pack = ext_slot(h, "CheckAnyCargoToPack", "TruckCargoUtils")
        has_unpacked = ext_slot(h, "HasUnpackedCargoInTruckOrTrailer")

        def winch(truck, w):
            # (w = truck.GetWinchTruck(true, false)) != null
            return Ne(Assign(w, Call(truck, T["GetWinchTruck"], Bool(True), Bool(False))), NULL)

        def winched_with_cargo(truck, w):
            return And(winch(truck, w), Not(Call(Call(Local(w), T["GetCargoes"], Bool(True)), is_empty)))

        def winched_with_unpacked(truck, w):
            return And(winch(truck, w), Call(Field(THIS, utils), has_unpacked, Local(w)))

        def pack_target(fp):
            """-> (операторы, локальная): кого упаковывать - зацепленного или свою машину"""
            w, p = fp.new_local(), fp.new_local()
            return [SetLocal(p, Field(THIS, cur)),
                    If(winched_with_unpacked(Field(THIS, cur), w), [SetLocal(p, Local(w))])], p

        # CreateCargoData: кнопки распаковки/упаковки и для груза зацепленной машины
        fi = h.func_index("CreateCargoData", H)
        fp = FunctionPatch(h.func_code(fi))
        at = find_one(fp.code, "01:1 01:1 05:1 07:1 04:1 0d:%d 04:0 0d:%d 1b:0 16:*" % (T["GetCargoes"], is_empty),
                      "HUD/unpack-button")
        w = fp.new_local()
        lab = newlabel("or")
        fp.insert(at + 9, [Jmp(0x19, lab), Ins(0x02)] + winched_with_cargo(Local(1), w).emit() + [Label(lab)])
        at = find_one(fp.code, "01:1 07:1 07:0 0a:%d 04:1 0d:%d 16:*" % (utils, has_unpacked), "HUD/pack-button")
        w2 = fp.new_local()
        lab = newlabel("or")
        fp.insert(at + 6, [Jmp(0x19, lab), Ins(0x02)] + winched_with_unpacked(Local(1), w2).emit() + [Label(lab)])
        h.set_func_code(fi, fp.build())

        # HandleActionRequest: действие 9 (распаковать), действие 8 (упаковать)
        fi = h.func_index("HandleActionRequest", H)
        fp = FunctionPatch(h.func_code(fi))
        pat = "04:9 30:7 16:* 01:1 07:0 0a:%d 07:0 0a:%d 04:1 0d:%d 02:0" % (cur, utils, unpack)
        at = find_one(fp.code, pat, "HUD/unpack-action") + 3
        w = fp.new_local()
        body = [If(winched_with_cargo(Field(THIS, cur), w),
                   [Do(Call(Field(THIS, utils), unpack, Local(w)))],
                   [Do(Call(Field(THIS, utils), unpack, Field(THIS, cur)))])]
        fp.replace(at, at + 8, compile_block(body))
        pat = "04:8 30:7 16:* 01:1 07:0 0a:%d 07:0 0a:%d 04:1 0d:%d" % (cur, utils, check_pack)
        at = find_one(fp.code, pat, "HUD/pack-action") + 3
        pre, p = pack_target(fp)
        fp.insert(at, compile_block(pre))
        fp.replace(at + 1, at + 3, [Ins(0x07, p)])
        at = find_one(fp.code, "01:1 07:0 0a:%d 07:0 0a:%d 04:1 0d:%d 02:0" % (cur, utils, pack), "HUD/pack-call")
        fp.replace(at + 1, at + 3, [Ins(0x07, p)])
        h.set_func_code(fi, fp.build())

        # AcceptPackWarning: упаковка после предупреждения - тому же, кому и в действии 8
        fi = h.func_index("AcceptPackWarning", H)
        fp = FunctionPatch(h.func_code(fi))
        at = find_one(fp.code, "01:1 07:0 0a:%d 07:0 0a:%d 04:1 0d:%d 02:0" % (cur, utils, pack), "HUD/accept-pack")
        pre, p = pack_target(fp)
        fp.insert(at, compile_block(pre))
        fp.replace(at + 1, at + 3, [Ins(0x07, p)])
        h.set_func_code(fi, fp.build())

# ---------------------------------------------------------------------------
# окно погрузки


def apply_cargo_loading(ed, value):
    price, logs_pct = value
    m = ed[CARGO_LOADING]
    C = "PopupCargoLoadingUiController"
    base = member_slot(m, C, "autoLoadPrice")
    info = member_slot(m, C, "currentCargoInfo")
    get_view = member_slot(m, C, "GetView")
    get_price = ext_slot(m, "GetAutoloadPrice")
    cargo = ext_slot(m, "cargo", "PopupCargoInfo")
    ctype = ext_slot(m, "type", "Cargo")
    slots = ext_slot(m, "slotLength", "Cargo")
    set_price = ext_slot(m, "SetPriceForAutoLoading")
    get_money = ext_slot(m, "GetMoney")
    add_money = ext_slot(m, "AddMoney")

    # InitContent: autoLoadPrice = GetAutoloadPrice() * GetLoadingPriceFactor()  ->
    # (GetAutoloadPrice() > 0 ? цена из настроек : 0) * GetLoadingPriceFactor() - цена слота
    fi = m.func_index("InitContent", C)
    fp = FunctionPatch(m.func_code(fi))
    at = find_one(fp.code, "01:1 01:1 01:1 08:0 04:0 0d:* 04:0 0d:* 04:0 0d:%d 07:* 27:0 07:0 3c:%d"
                  % (get_price, base), "cargo/base-price")
    vanilla = RawExpr(Ins(op, a) for op, a in fp.code[at:at + 10])
    fp.replace(at, at + 10, Cond(Gt(vanilla, Int(0)), Int(price), Int(0)).emit())
    m.set_func_code(fi, fp.build())

    def cargo_price(fi):
        """autoLoadPrice * множитель% / 100 для currentCargoInfo.cargo: у брёвен - множитель
        их вида, у остальных грузов - число слотов (не меньше 1)"""
        c = Field(Field(THIS, info), cargo)
        n = Field(c, slots)
        pct = Mul(Cond(Gt(n, Int(0)), n, Int(1)), Int(100))
        for t, kind in sorted(LOGS_TYPES.items(), reverse=True):
            pct = Cond(Eq(Field(c, ctype), Const(m.const_string(fi, t))), Int(logs_pct[kind]), pct)
        return Div(Mul(Field(THIS, base), pct), Int(100)).emit()

    # TryShowCargoPreview: цена на кнопке погрузки и проверка «не хватает денег»
    fi = m.func_index("TryShowCargoPreview", C)
    fp = FunctionPatch(m.func_code(fi))
    at = find_one(fp.code, "07:0 0a:%d 01:1 07:0 04:0 0d:%d 04:1 0d:%d" % (base, get_view, set_price),
                  "cargo/show-price")
    fp.replace(at, at + 2, cargo_price(fi))
    at = find_one(fp.code, "0d:%d 07:0 0a:%d 31:9" % (get_money, base), "cargo/enough-money")
    fp.replace(at + 1, at + 3, cargo_price(fi))
    m.set_func_code(fi, fp.build())

    # Action: списание денег за погрузку
    fi = m.func_index("Action", C)
    fp = FunctionPatch(m.func_code(fi))
    at = find_one(fp.code, "07:0 0a:%d 1d:0 07:0 0a:* 04:1 0d:%d" % (base, add_money), "cargo/pay")
    fp.replace(at, at + 2, cargo_price(fi))
    m.set_func_code(fi, fp.build())

# ---------------------------------------------------------------------------


def apply(ed, enabled):
    """ed: {имя модуля: ModEditor}; enabled: {ключ: значение}. -> изменённые модули"""
    changed = set()
    repair_keys = {"repair_from_nearby", "repair_parts_transfer", WHEEL_KEY} & set(enabled)
    # сначала вид: в нём добавляются поля данных окна, которые читает контроллер
    if {"repair_parts_transfer", WHEEL_KEY} & set(enabled):
        apply_repair_view(ed, enabled)
        changed.add(REPAIR_VIEW)
    if repair_keys:
        apply_repair(ed, enabled)
        changed.add(REPAIR)
    if WHEEL_KEY in enabled:
        apply_damage_controller(ed)
        changed.add(DAMAGE)
    if "repair_from_nearby" in enabled or "winch_unpack_cargo" in enabled:
        apply_hud(ed, enabled)
        changed.add(HUD)
    if LOADING_KEY in enabled:
        apply_cargo_loading(ed, enabled[LOADING_KEY])
        changed.add(CARGO_LOADING)
    for n in changed:
        ed[n].string(MARKER)
    return changed


def is_patched(ed):
    return any(MARKER in ed[n].strings for n in (REPAIR, REPAIR_VIEW, HUD, DAMAGE, CARGO_LOADING) if n in ed)


def check(ed):
    """проверка, что все места правок находятся (на копиях модулей)"""
    apply({k: ModEditor(v.blob(), v.name) for k, v in ed.items()},
          {k: LOADING_VALUE if k == LOADING_KEY else True for k in KEYS})
