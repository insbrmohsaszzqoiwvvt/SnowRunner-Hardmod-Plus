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

В сетевой игре (кооператив) первые два патча ничего не меняют.

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
                      find_all, ensure_member, ensure_global, member_slot, compile_block)

REPAIR = "ui.components.popups.repair.popup_repair_ui_controller_new"
REPAIR_VIEW = "ui.components.popups.repair.popup_repair_ui_view_new"
HUD = "ui.hud.hud_controllers.hud_interaction_panel_controller"
TRUCK = "game.truck"
ADDON = "game.truck_addon"
SESSION = "game.game_modes.game_session"
TRUCKS_MANAGER = "game.truck_manager.trucks_manager"
TRANSLATE_SRC = "ui.components.minimap.minimap_ui_data_creator_contract"

KEYS = ("repair_from_nearby", "repair_parts_transfer", "winch_unpack_cargo")

# строка-метка в изменённых модулях: по ней видно, что initial.pak уже пропатчен
MARKER = "hard_mode_plus_service_patch"

# строки списка для цели-аддона (ключи локализации игры) и значки
PARTS_LABEL = "UI_POPUP_RESUPPLY_PARTS"
PARTS_ICON = "repairPartsImg20"
WHEELS_LABEL = "UI_HUD_REPAIR_DIALOG_REPAIR_WHEELS"
WHEELS_ICON = "wheelRepairMenuIcon"
FULLY_REPAIRED = "UI_HUD_REPAIR_FULLY_REPAIRED"

# метка «это цель-аддон» в данных окна: у 5-й строки повреждений maxHealth = -1
SERVICE_SENTINEL = -1

# модули, которые читаются (изменяются REPAIR, REPAIR_VIEW и HUD)
ALL_MODULES = {REPAIR, REPAIR_VIEW, HUD, TRUCK, ADDON, SESSION, TRUCKS_MANAGER, TRANSLATE_SRC}


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
    for name, job in jobs:
        c.fi = m.func_index(name, P)
        c.fname = name
        fp = FunctionPatch(m.func_code(c.fi))
        job(fp)
        m.set_func_code(c.fi, fp.build())

# ---------------------------------------------------------------------------
# вид окна ремонта: строки для цели-аддона


def apply_repair_view(ed):
    v = ed[REPAIR_VIEW]
    V = "PopupRepairUiViewNew"
    sel = member_slot(v, V, "selectedIndex")
    last = member_slot(v, V, "lastData")
    hint_text = member_slot(v, V, "hintText")
    create_row = member_slot(v, V, "PopupRepairUiViewLirItemDataCreateByDamageData")
    dd_slot = member_slot(v, "PopupRepairUiViewData2", "damagesData")
    max_health = member_slot(v, "PopupRepairUiViewTruckData", "maxHealth")

    def is_service(data):
        dd = lambda: Field(data, dd_slot)
        return And(Ne(data, NULL), Gt(Count(dd()), Int(4)),
                   Eq(Field(ArrGet(Field(data, dd_slot), Int(4)), max_health), Int(SERVICE_SENTINEL)))

    # UpdateData: вместо 5 узлов машины - «Запчасти» и «Колёса»
    fi = v.func_index("UpdateData", V)
    fp = FunctionPatch(v.func_code(fi))
    code = fp.code
    rows = find_one(code, "01:1 07:-1 0a:%d 06:* 06:* 04:1 07:0 04:4 0d:%d" % (dd_slot, create_row), "View/rows")
    setdata = find_one(code, "01:1 05:1 07:-4 07:0 0a:* 04:2 0d:*", "View/set-data")
    restore = find_one(code, "07:0 0a:%d 04:-1 30:8 16:*" % sel, "View/restore-selection")
    k = lambda s: Const(v.const_string(fi, s))
    row = lambda typ, label, icon: ArrAdd(Local(-4), Call(THIS, create_row, Int(typ), k(label), k(icon),
                                                          Field(Local(-1), dd_slot)))
    fp.insert(rows, compile_block([If(is_service(Local(-1)), [
        row(0, PARTS_LABEL, PARTS_ICON), row(1, WHEELS_LABEL, WHEELS_ICON), Goto(("orig", setdata))])]))
    # выбранная строка могла пропасть (строк стало меньше)
    fp.insert(restore, compile_block([
        If(Ge(Field(THIS, sel), Count(Local(-4))), [SetField(THIS, sel, Int(0))])]))
    v.set_func_code(fi, fp.build())

    # UpdateRepairHint: у цели-аддона нет надписи «Нет урона»
    fi = v.func_index("UpdateRepairHint", V)
    fp = FunctionPatch(v.func_code(fi))
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block([
        If(And(is_service(Field(THIS, last)), Eq(Field(THIS, hint_text), Const(v.const_string(fi, FULLY_REPAIRED)))),
           [SetField(THIS, hint_text, Const(v.const_string(fi, "")))])]), redirect=False)
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


def apply(ed, enabled):
    """ed: {имя модуля: ModEditor}; enabled: {ключ: значение}. -> изменённые модули"""
    changed = set()
    if "repair_from_nearby" in enabled or "repair_parts_transfer" in enabled:
        apply_repair(ed, enabled)
        changed.add(REPAIR)
    if "repair_parts_transfer" in enabled:
        apply_repair_view(ed)
        changed.add(REPAIR_VIEW)
    if "repair_from_nearby" in enabled or "winch_unpack_cargo" in enabled:
        apply_hud(ed, enabled)
        changed.add(HUD)
    for n in changed:
        ed[n].string(MARKER)
    return changed


def is_patched(ed):
    return any(MARKER in ed[n].strings for n in (REPAIR, REPAIR_VIEW, HUD) if n in ed)


def check(ed):
    """проверка, что все места правок находятся (на копиях модулей)"""
    apply({k: ModEditor(v.blob(), v.name) for k, v in ed.items()}, {k: True for k in KEYS})
