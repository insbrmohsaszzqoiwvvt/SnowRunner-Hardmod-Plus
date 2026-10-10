"""
Патчи сервиса (ремонт и груз) для SnowRunner, поверх библиотеки sslpatch.

  repair_from_nearby - окно ремонта берёт запчасти не только из аддонов и прицепа
      текущей машины, но и из любых машин/прицепов рядом (в т.ч. отцепленных
      сервисных прицепов и аддонов чужих машин). Кнопка «Ремонт» в меню
      взаимодействия появляется, если рядом есть такой источник.
  repair_parts_transfer - перекладка запчастей и колёс между сервисными
      аддонами и прицепами через то же окно ремонта (как переливание топлива):
      в списке целей появляются сервисные прицепы рядом и прицеп текущей
      машины; если у цели нечего
      чинить (или это прицеп), «Ремонт» перекладывает запчасти и колёса из
      выбранного источника в её сервисные аддоны/прицеп. У такой цели в названии
      показано [запчасти/вместимость | колёса/вместимость].
  winch_unpack_cargo - если лебёдка текущей машины зацеплена за прицеп или машину
      с упакованным грузом, в меню взаимодействия есть «Распаковать груз», и он
      распаковывает груз именно того, за кого зацеплена лебёдка.

В сетевой игре (кооператив) первые два патча ничего не меняют.
"""
from sslpatch import (PatchError, ModEditor, Local, THIS, Int, Bool, NULL, Const, Call, GCall, Field,
                      ArrGet, Count, New, Eq, Ne, Lt, Gt, Le, Add, Sub, Not, And, Or, Cond, Assign,
                      SetLocal, SetField, Do, ArrAdd, ArrSet, If, Break, Continue, Block, ForEach,
                      Goto, Return, ReturnVoid, FunctionPatch, Ins, Jmp, Label, newlabel, find_one,
                      ensure_member, ensure_global, member_slot, compile_block)

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

# формат названия цели при перекладке: имя, запчасти, вместимость, колёса, вместимость
TARGET_FORMAT = "%s  [%d/%d | %d/%d]"


# модули, которые читаются (изменяются только REPAIR и HUD)
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
            "repairTruckRange", "sourceAddons", "targetTrucks", "sourceAddon", "targetTruck",
            "nearTrucks", "destroyedWheelsAmount", "RepairAll")}
        self.f["gameSession"] = ext_slot(m, "gameSession")
        self.f["UpdateViewData"] = ext_slot(m, "UpdateViewData")
        self.f["GetView"] = member_slot(m, P, "GetView")
        self.ra = {n: member_slot(m, "RepairAddon", n) for n in ("parentTruck", "addon", "Init")}
        self.t = {n: s(TRUCK, "Truck", n) for n in (
            "id", "IsTrailer", "AsTruckAddon", "GetType", "GetCurrentTruckAddons", "GetTrailer",
            "engineDamage", "fuelTankDamage", "gearboxDamage", "suspensionDamage")}
        self.a = {n: s(ADDON, "TruckAddon", n) for n in (
            "name", "SetRepairs", "GetRepairs", "SetWheelRepairs", "GetWheelRepairs",
            "GetRepairsCapacity", "GetWheelRepairsCapacity")}
        self.dmg = s(ADDON, "DamageData", "damage")
        self.gs = {n: s(SESSION, "GameSession", n) for n in ("GetTrucksManager", "IsMultiplayer", "GetClientProxy")}
        self.near = s(TRUCKS_MANAGER, "TrucksManager", "GetNearTrucksForCurrentTruck")
        self.view = {n: ext_slot(m, n) for n in ("PlayRepairAllSound", "PlayCantRepairSound")}
        self.data = {n: ext_slot(m, n) for n in ("targetName", "damagesData")}
        self.g = {n: ext_gid(m, n) for n in ("GetCurrentGameSession", "GetGameEngine",
                                             "PopupRepairUiViewTruckDataCreate")}
        self.cur_truck_slot = ext_slot(m, "GetCurrentTruck", "Game")
        self.arr_clone = ext_slot(m, "Clone", "array")
        self.objstor = (ext_slot(m, "GetObjectiveStatusStorage"),
                        ext_slot(m, "IsTruckBlockedForRepairAndRefuelByObjective"))
        # импорты, которых в модуле не было (то, что добавил бы компилятор)
        for cls, mod, names in (
                ("TruckAddon", ADDON, ("SetRepairs", "SetWheelRepairs", "GetRepairs", "GetWheelRepairs",
                                       "GetRepairsCapacity", "GetWheelRepairsCapacity", "name")),
                ("Truck", TRUCK, ("IsTrailer", "AsTruckAddon", "GetType", "GetCurrentTruckAddons", "id", "GetTrailer",
                                  "engineDamage", "fuelTankDamage", "gearboxDamage", "suspensionDamage")),
                ("GameSession", SESSION, ("IsMultiplayer", "GetTrucksManager", "GetClientProxy")),
                ("TrucksManager", TRUCKS_MANAGER, ("GetNearTrucksForCurrentTruck",))):
            for n in names:
                ensure_member(m, cls, n, ed[mod])
        self.g["StringFormat"] = ensure_global(m, ed[REPAIR_VIEW], "StringFormat")
        self.g["UiTranslateString"] = ensure_global(m, ed[TRANSLATE_SRC], "UiTranslateString")

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

    def damage(self, truck, field):
        return Field(Field(truck, self.t[field]), self.dmg)

    def nothing_to_repair(self, truck):
        return And(*[Le(self.damage(truck, f), Int(0)) for f in
                     ("engineDamage", "fuelTankDamage", "gearboxDamage", "suspensionDamage")]
                   + [Le(Field(THIS, self.f["destroyedWheelsAmount"]), Int(0))])

    def transfer_mode(self, truck, src):
        """цель - прицеп или ей нечего чинить (без сетевой игры)"""
        return And(self.single_player(), Ne(src, NULL), Ne(truck, NULL),
                   Or(Call(truck, self.t["IsTrailer"]), self.nothing_to_repair(truck)))

    def src_addon_expr(self):
        """this.sourceAddon?.addon (null, если источника нет)"""
        sa = Field(THIS, self.f["sourceAddon"])
        return Cond(Eq(sa, NULL), NULL, Field(Field(THIS, self.f["sourceAddon"]), self.ra["addon"]))

    def truck_ui_name(self, truck):
        """имя для поиска описания: у прицепа - имя его аддона (как у источников)"""
        return Cond(Call(truck, self.t["IsTrailer"]),
                    Field(Call(truck, self.t["AsTruckAddon"]), self.a["name"]),
                    Call(truck, self.t["GetType"]))


def patch_update_near_trucks(c, fp, enabled):
    """UpdateNearTrucks: источники рядом и сервисные прицепы как цели"""
    code = fp.code
    nt = Field(THIS, c.f["nearTrucks"])
    if "repair_from_nearby" in enabled:
        # перед: targetTrucks = GetNearbyTrucksAndTrailers()
        at = find_one(code, "01:1 07:0 04:0 0d:* 07:0 3c:%d" % c.f["targetTrucks"], "UpdateNearTrucks/targets")
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
        tt = c.f["targetTrucks"]
        at = find_one(code, "07:0 0a:%d 41:0 04:0 30:7 19:*" % tt, "UpdateNearTrucks/empty-check")
        i, n, t = fp.new_local(), fp.new_local(), fp.new_local()
        arr, j, m, a = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        ok, k, kn, x = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        stor, cand, cur, tr = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
        tgts = Field(THIS, tt)
        gos, isblk = c.objstor
        body = [
            If(And(c.single_player(), Ne(nt, NULL)), [
                SetLocal(stor, Call(Call(GCall(c.g["GetCurrentGameSession"]), c.gs["GetClientProxy"]), gos)),
                # кандидаты: всё рядом + прицеп текущей машины (на случай, если его нет в списке)
                SetLocal(cand, Call(nt, c.arr_clone)),
                SetLocal(cur, c.cur_truck()),
                If(Ne(Local(cur), NULL), [
                    SetLocal(tr, Call(Local(cur), c.t["GetTrailer"])),
                    If(Ne(Local(tr), NULL), [ArrAdd(Local(cand), Local(tr))]),
                ]),
                ForEach(Local(cand), i, n, t, [
                    If(Or(Eq(Local(t), NULL), Not(Call(Local(t), c.t["IsTrailer"]))), [Continue()]),
                    SetLocal(ok, Bool(False)),
                    SetLocal(arr, c.addons(Local(t))),
                    ForEach(Local(arr), j, m, a, [
                        If(And(Ne(Local(a), NULL), c.has_capacity(Local(a))), [SetLocal(ok, Bool(True)), Break()]),
                    ]),
                    If(Not(Local(ok)), [Continue()]),
                    ForEach(tgts, k, kn, x, [
                        If(Eq(Local(x), Local(t)), [SetLocal(ok, Bool(False)), Break()]),
                    ]),
                    If(Not(Local(ok)), [Continue()]),
                    If(Ne(Local(stor), NULL), [
                        If(Call(Local(stor), isblk, Field(Local(t), c.t["id"])), [Continue()]),
                    ]),
                    ArrAdd(tgts, Local(t)),
                ]),
            ]),
        ]
        fp.insert(at, compile_block(body))


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


def transfer_body(c, fp, tgt, src):
    """переложить запчасти и колёса из src в сервисные аддоны цели tgt"""
    arr, j, m, a = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
    moved, give = fp.new_local(), fp.new_local()
    A = c.a
    stmts = [SetLocal(moved, Int(0)), SetLocal(arr, c.addons(tgt))]
    inner = [If(Or(Eq(Local(a), NULL), Eq(Local(a), src)), [Continue()])]
    for cap, get, set_ in (("GetRepairsCapacity", "GetRepairs", "SetRepairs"),
                           ("GetWheelRepairsCapacity", "GetWheelRepairs", "SetWheelRepairs")):
        inner += [
            SetLocal(give, Sub(Call(Local(a), A[cap]), Call(Local(a), A[get]))),
            If(Gt(Local(give), Call(src, A[get])), [SetLocal(give, Call(src, A[get]))]),
            If(Gt(Local(give), Int(0)), [
                Do(Call(Local(a), A[set_], Add(Call(Local(a), A[get]), Local(give)))),
                Do(Call(src, A[set_], Sub(Call(src, A[get]), Local(give)))),
                SetLocal(moved, Add(Local(moved), Local(give))),
            ]),
        ]
    stmts.append(ForEach(Local(arr), j, m, a, inner))
    view = Call(THIS, c.f["GetView"])
    stmts += [
        If(Gt(Local(moved), Int(0)), [Do(Call(view, c.view["PlayRepairAllSound"]))],
           [Do(Call(Call(THIS, c.f["GetView"]), c.view["PlayCantRepairSound"]))]),
        Do(Call(THIS, c.f["UpdateViewData"])),
    ]
    return stmts


def can_transfer(c, fp, tgt, src):
    """есть ли куда и что перекладывать -> выражение в локальной"""
    arr, j, m, a, res = (fp.new_local() for _ in range(5))
    A = c.a
    stmts = [
        SetLocal(res, Bool(False)),
        SetLocal(arr, c.addons(tgt)),
        ForEach(Local(arr), j, m, a, [
            If(Or(Eq(Local(a), NULL), Eq(Local(a), src)), [Continue()]),
            If(Or(And(Gt(Call(Local(a), A["GetRepairsCapacity"]), Call(Local(a), A["GetRepairs"])),
                      Gt(Call(src, A["GetRepairs"]), Int(0))),
                  And(Gt(Call(Local(a), A["GetWheelRepairsCapacity"]), Call(Local(a), A["GetWheelRepairs"])),
                      Gt(Call(src, A["GetWheelRepairs"]), Int(0)))),
               [SetLocal(res, Bool(True)), Break()]),
        ]),
    ]
    return stmts, res


def patch_repair_all(c, fp):
    """RepairAll: в режиме перекладки - переложить вместо ремонта"""
    src = fp.new_local()
    tgt = Field(THIS, c.f["targetTruck"])
    body = [SetLocal(src, c.src_addon_expr()),
            If(c.transfer_mode(tgt, Local(src)), transfer_body(c, fp, tgt, Local(src)) + [ReturnVoid(1)])]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def patch_repair_part(c, fp):
    """RepairPart(part): в режиме перекладки - то же, что RepairAll"""
    src = fp.new_local()
    tgt = Field(THIS, c.f["targetTruck"])
    body = [SetLocal(src, c.src_addon_expr()),
            If(c.transfer_mode(tgt, Local(src)), [Do(Call(THIS, c.f["RepairAll"])), ReturnVoid(2)])]
    at = 1 if fp.locals.has_reserve else 0
    fp.insert(at, compile_block(body), redirect=False)


def patch_is_repair_enabled(c, fp):
    """IsRepairEnabled(part): в режиме перекладки кнопка доступна, если есть что перекладывать"""
    at = find_one(fp.code, "07:1 04:7 30:7 16:* 05:0 12:2", "IsRepairEnabled/none")
    at = fp.code[at + 3][1]          # начало ветки part != NONE
    src = fp.new_local()
    tgt = Field(THIS, c.f["targetTruck"])
    pre, res = can_transfer(c, fp, tgt, Local(src))
    body = [SetLocal(src, c.src_addon_expr()),
            If(c.transfer_mode(tgt, Local(src)), pre + [Return(Local(res), 2)])]
    fp.insert(at, compile_block(body))


def patch_create_data(c, fp):
    """CreateData: имя прицепа-цели, строки повреждений прицепа, остатки у цели"""
    code = fp.code
    # 1) описание цели: у прицепа ищем по имени аддона
    at = find_one(code, "01:1 05:0 01:1 07:-3 04:0 0d:%d 07:-1 04:2 0d:*" % c.t["GetType"], "CreateData/target-desc")
    fp.replace(at + 2, at + 6, c.truck_ui_name(Local(-3)).emit())
    # 2) у прицепа нет повреждений: 5 пустых строк, без чтения данных прицепа
    rows = find_one(code, "01:1 07:-3 01:1 39:* 04:0 3a:* 04:1 0d:* 3b:-7", "CreateData/damages")
    hint = find_one(code, "01:1 07:0 0a:* 04:0 0d:* 07:-5 3c:*", "CreateData/hint")
    dd = Field(Local(-5), c.data["damagesData"])
    empty = lambda: GCall(c.g["PopupRepairUiViewTruckDataCreate"], Int(1), Int(1), Int(0), Int(0))
    body = [If(Call(Local(-3), c.t["IsTrailer"]),
               [Do(Call(dd, 13, Int(5)))]
               + [ArrSet(Field(Local(-5), c.data["damagesData"]), Int(k), empty()) for k in range(5)]
               + [SetField(THIS, c.f["destroyedWheelsAmount"], Int(0)), Goto(("orig", hint))])]
    fp.insert(rows, compile_block(body))
    # 3) в режиме перекладки - остатки в сервисных аддонах цели в названии
    arr, j, m, a = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
    p, pc, w, wc = fp.new_local(), fp.new_local(), fp.new_local(), fp.new_local()
    A = c.a
    fmt = c.m.const_string(c.fi, TARGET_FORMAT)
    tn = c.data["targetName"]
    body = [If(c.transfer_mode(Local(-3), Local(-2)), [
        SetLocal(p, Int(0)), SetLocal(pc, Int(0)), SetLocal(w, Int(0)), SetLocal(wc, Int(0)),
        SetLocal(arr, c.addons(Local(-3))),
        ForEach(Local(arr), j, m, a, [
            If(Or(Eq(Local(a), NULL), Eq(Local(a), Local(-2))), [Continue()]),
            SetLocal(p, Add(Local(p), Call(Local(a), A["GetRepairs"]))),
            SetLocal(pc, Add(Local(pc), Call(Local(a), A["GetRepairsCapacity"]))),
            SetLocal(w, Add(Local(w), Call(Local(a), A["GetWheelRepairs"]))),
            SetLocal(wc, Add(Local(wc), Call(Local(a), A["GetWheelRepairsCapacity"]))),
        ]),
        If(Or(Gt(Local(pc), Int(0)), Gt(Local(wc), Int(0))), [
            SetField(Local(-5), tn, GCall(c.g["StringFormat"], Const(fmt),
                                          GCall(c.g["UiTranslateString"], Field(Local(-5), tn)),
                                          Local(p), Local(pc), Local(w), Local(wc),
                                          NULL, NULL, NULL, NULL, NULL)),
        ]),
    ])]
    fp.insert(hint, compile_block(body))


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


def apply_repair(ed, enabled):
    c = RepairCtx(ed)
    m = c.m
    P = "PopupRepairUiControllerNew"
    jobs = [("UpdateNearTrucks", lambda fp: patch_update_near_trucks(c, fp, enabled))]
    if "repair_from_nearby" in enabled:
        jobs.append(("IsCanBeShown", lambda fp: patch_is_can_be_shown(c, fp)))
    if "repair_parts_transfer" in enabled:
        jobs += [("RepairAll", lambda fp: patch_repair_all(c, fp)),
                 ("RepairPart", lambda fp: patch_repair_part(c, fp)),
                 ("IsRepairEnabled", lambda fp: patch_is_repair_enabled(c, fp)),
                 ("CreateData", lambda fp: patch_create_data(c, fp)),
                 ("GetRepairTruckMarker", lambda fp: patch_truck_marker(c, fp))]
    for name, job in jobs:
        c.fi = m.func_index(name, P)
        fp = FunctionPatch(m.func_code(c.fi))
        job(fp)
        m.set_func_code(c.fi, fp.build())

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

        def winched_with_cargo(fp, truck, w):
            # (w = truck.GetWinchTruck(true, false)) != null && !w.GetCargoes(true).IsEmpty()
            return And(Ne(Assign(w, Call(truck, T["GetWinchTruck"], Bool(True), Bool(False))), NULL),
                       Not(Call(Call(Local(w), T["GetCargoes"], Bool(True)), is_empty)))

        # CreateCargoData: кнопка «Распаковать груз» и для груза на зацепленной машине
        fi = h.func_index("CreateCargoData", H)
        fp = FunctionPatch(h.func_code(fi))
        at = find_one(fp.code, "01:1 01:1 05:1 07:1 04:1 0d:%d 04:0 0d:%d 1b:0 16:*" % (T["GetCargoes"], is_empty),
                      "HUD/unpack-button")
        w = fp.new_local()
        lab = newlabel("or")
        fp.insert(at + 9, [Jmp(0x19, lab), Ins(0x02)] + winched_with_cargo(fp, Local(1), w).emit() + [Label(lab)])
        h.set_func_code(fi, fp.build())
        # HandleActionRequest, действие 9 (распаковать): груз зацепленной машины, если он есть
        fi = h.func_index("HandleActionRequest", H)
        fp = FunctionPatch(h.func_code(fi))
        cur = member_slot(h, H, "currentTruck")
        utils = member_slot(h, H, "truckCargoUtils")
        unpack = ext_slot(h, "UnpackCargo")
        pat = "04:9 30:7 16:* 01:1 07:0 0a:%d 07:0 0a:%d 04:1 0d:%d 02:0" % (cur, utils, unpack)
        at = find_one(fp.code, pat, "HUD/unpack-action") + 3
        w = fp.new_local()
        body = [If(winched_with_cargo(fp, Field(THIS, cur), w),
                   [Do(Call(Field(THIS, utils), unpack, Local(w)))],
                   [Do(Call(Field(THIS, utils), unpack, Field(THIS, cur)))])]
        fp.replace(at, at + 8, compile_block(body))
        h.set_func_code(fi, fp.build())

# ---------------------------------------------------------------------------


def apply(ed, enabled):
    """ed: {имя модуля: ModEditor}; enabled: {ключ: значение}. -> изменённые модули"""
    changed = set()
    if "repair_from_nearby" in enabled or "repair_parts_transfer" in enabled:
        apply_repair(ed, enabled)
        changed.add(REPAIR)
    if "repair_from_nearby" in enabled or "winch_unpack_cargo" in enabled:
        apply_hud(ed, enabled)
        changed.add(HUD)
    for n in changed:
        ed[n].string(MARKER)
    return changed


def is_patched(ed):
    return any(MARKER in ed[n].strings for n in (REPAIR, HUD) if n in ed)


def check(ed):
    """проверка, что все места правок находятся (на копиях модулей)"""
    apply({k: ModEditor(v.blob(), v.name) for k, v in ed.items()}, {k: True for k in KEYS})
