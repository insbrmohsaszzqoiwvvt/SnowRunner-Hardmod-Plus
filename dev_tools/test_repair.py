import pickle, ssl as S
from vm import VM, Obj, Arr, Dct, VMError

pm = pickle.load(open('../data/patched_release.pkl', 'rb'))
RMOD = 'ui.components.popups.repair.popup_repair_ui_controller_new'
m = S.Mod(RMOD, pm[RMOD])
fidx = {f['name']: i for i, f in enumerate(m.funcs)}

def dmg(d=0, cap=100):
    return Obj('DamageData', damage=d, damageCapacity=cap)

def addon(name, rep, cap, wh, wcap):
    return Obj('TruckAddon', name=name, rep=rep, cap=cap, wh=wh, wcap=wcap)

def truck(tid, trailer=False, addons=(), self_addon=None, damaged=0, cargo=None, winch=None):
    t = Obj('Truck', id=tid, type=tid, trailer=trailer, addons=list(addons), self_addon=self_addon,
            totalDamageCapacity=0 if trailer else 1000,
            engineDamage=dmg(damaged), fuelTankDamage=dmg(), gearboxDamage=dmg(), suspensionDamage=dmg(),
            wheelDamages=Arr([dmg(), dmg()]), cargo=cargo or {}, winch=winch, phantomMode=0)
    return t

def get_addons(t, incTrailer, incSelf, incCargo):
    r = list(t.f['addons'])
    if incSelf and t.f['self_addon'] is not None:
        r.append(t.f['self_addon'])
    if incTrailer and t.f.get('trailer_obj'):
        tr = t.f['trailer_obj']
        r.append(tr.f['self_addon'])
    return Arr(r)

impl = {
    ('Truck', 'IsTrailer'): lambda t: t.f['trailer'],
    ('Truck', 'AsTruckAddon'): lambda t: t.f['self_addon'],
    ('Truck', 'GetType'): lambda t: t.f['type'],
    ('Truck', 'GetCurrentTruckAddons'): get_addons,
    ('Truck', 'GetTrailer'): lambda t: t.f.get('trailer_obj'),
    ('Truck', 'GetDamageCapacityWithoutWheels'): lambda t: 400,
    ('Truck', 'GetTotalDamageForObjective'): lambda t: 50,
    ('Truck', 'GetWheelDamageData'): lambda t: t.f['wheelDamages'],
    ('TruckAddon', 'GetRepairs'): lambda a: a.f['rep'],
    ('TruckAddon', 'SetRepairs'): lambda a, v: a.f.__setitem__('rep', v),
    ('TruckAddon', 'GetWheelRepairs'): lambda a: a.f['wh'],
    ('TruckAddon', 'SetWheelRepairs'): lambda a, v: a.f.__setitem__('wh', v),
    ('TruckAddon', 'GetRepairsCapacity'): lambda a: a.f['cap'],
    ('TruckAddon', 'GetWheelRepairsCapacity'): lambda a: a.f['wcap'],
}

calls = []
def rec(name, ret=None):
    def f(*a):
        calls.append((name,) + a[1:])
        return ret
    return f

class World:
    def __init__(self, cur, near, mp=False, blocked=()):
        self.cur, self.near = cur, near
        self.gs = Obj('GameSession')
        self.tm = Obj('TrucksManager')
        self.game = Obj('Game')
        self.cp = Obj('ClientProxyBase')
        self.os = Obj('ObjectiveStatusStorage')
        self.view = Obj('PopupRepairUiViewNew')
        self.dm = Obj('GameDifficultyManager')
        I = dict(impl)
        I.update({
            ('GameSession', 'IsMultiplayer'): lambda s: mp,
            ('GameSession', 'GetTrucksManager'): lambda s: self.tm,
            ('GameSession', 'GetClientProxy'): lambda s: self.cp,
            ('GameSession', 'IsHardMode'): lambda s: True,
            ('GameSession', 'GetGameDifficultyManager'): lambda s: self.dm,
            ('GameDifficultyManager', 'GetRepairPointsRequiredFactor'): lambda s, n: 1.0,
            ('TrucksManager', 'GetNearTrucksForCurrentTruck'): lambda s, r: Arr(near),
            ('Game', 'GetCurrentTruck'): lambda s: cur,
            ('TrucksManager', 'GetCurrentTruck'): lambda s: cur,
            ('ClientProxyBase', 'GetObjectiveStatusStorage'): lambda s: self.os,
            ('ObjectiveStatusStorage', 'IsTruckBlockedForRepairAndRefuelByObjective'): lambda s, i: i in blocked,
            ('PopupRepairUiViewNew', 'PlayRepairAllSound'): rec('PlayRepairAllSound'),
            ('PopupRepairUiViewNew', 'PlayCantRepairSound'): rec('PlayCantRepairSound'),
            ('PopupRepairUiControllerNew', 'GetView'): lambda s: self.view,
            ('PopupRepairUiControllerNew', 'UpdateViewData'): rec('UpdateViewData'),
            ('PopupRepairUiControllerNew', 'UnsubscribesTrucks'): rec('Unsub'),
            ('PopupRepairUiControllerNew', 'SubscribesTrucks'): self.subscribes,
            ('PopupRepairUiControllerNew', 'Hide'): rec('Hide'),
            ('Truck', 'GetTrailer'): lambda t: t.f.get('trailer_obj'),
            ('TruckAddonsManager', 'GetTruckUiDesc'): lambda s, name, b: Obj('TruckUiDesc', uiName='UI_' + name),
            ('ApplicationMode', 'GetTruckAddonsManager'): lambda s: Obj('TruckAddonsManager'),
            ('TruckDamagesData', 'GetDataFromTruck'): self.dd,
            ('DamageData', 'IsDestroyed'): lambda d: d.f['damage'] >= d.f['damageCapacity'],
        })
        G = {101: lambda: self.gs, 18: lambda: self.game,
             413: lambda v, lo, hi: max(lo, min(hi, v)),
             124: lambda h, mx, c, w: Obj('PopupRepairUiViewTruckData', health=h, maxHealth=mx, repairPartsCost=c, repairWheelsCost=w),
             930: lambda fmt, *a: fmt % tuple(x for x in a if x is not None),
             1028: lambda s: 'T(%s)' % s,
             100: lambda: Obj('ApplicationMode'),
             119: lambda name, icon, res, sel: Obj('MarkerOnTrucksGarnishAddonData', name=name, res=res, sel=sel),
             122: lambda icon, a, b: ('res', icon, a, b)}
        self.vm = VM(m, I, G)
        self.popup = Obj('PopupRepairUiControllerNew', gameSession=self.gs, repairTruckRange=100,
                         sourceAddons=Arr(), targetTrucks=Arr(), forbiddenTrucks=Arr(), sourceIndex=0,
                         targetIndex=0, sourceAddon=None, targetTruck=None, nearTrucks=Arr(near),
                         destroyedWheelsAmount=0, isRepairControllerShowed=True,
                         navPanels=Dct(default=Obj('PopupRepairNavigationPanel')),
                         repairIconName=Arr(['i%d' % k for k in range(16)]))

    def dd(self, d, t):
        d.f.update(engineDamageData=t.f['engineDamage'], suspensionDamageData=t.f['suspensionDamage'],
                   gearboxDamageData=t.f['gearboxDamage'], fuelTankDamageData=t.f['fuelTankDamage'],
                   wheelDamageDatas=t.f['wheelDamages'])
        return d

    def subscribes(self, p):
        if p.f['sourceAddons']:
            p.f['sourceAddon'] = p.f['sourceAddons'][p.f['sourceIndex']]
        if p.f['targetTrucks']:
            p.f['targetTruck'] = p.f['targetTrucks'][p.f['targetIndex']]

    def run(self, name, *args):
        return self.vm.run(fidx[name], self.popup, list(args))


def scene():
    T_add = addon('srv_trailer', 30, 60, 2, 4)
    T = truck('T', trailer=True, self_addon=T_add)
    XA = addon('srv_addon', 10, 20, 1, 2)
    X = truck('X', addons=[XA], self_addon=addon('X_body', 0, 0, 0, 0))
    XT_add = addon('cargo_trailer', 0, 0, 0, 0)
    XT = truck('XT', trailer=True, self_addon=XT_add)
    X.f['trailer_obj'] = XT
    CA = addon('cur_srv', 0, 20, 0, 2)
    C = truck('C', addons=[CA], self_addon=addon('C_body', 0, 0, 0, 0))
    return dict(T_add=T_add, T=T, XA=XA, X=X, XT=XT, CA=CA, C=C)


def ids(w):
    return [t.f['id'] for t in w.popup.f['targetTrucks']]

def resolve_all(w):
    """target container per index via CreateData side effects is heavy; use RepairAll-free check:
    run CreateData for each index and read targetName"""
    out = []
    for i in range(len(w.popup.f['targetTrucks'])):
        w.popup.f['targetIndex'] = i
        w.subscribes(w.popup)
        d = w.run('CreateData')
        svc = d.f['damagesData'][4].f['maxHealth'] == -1
        out.append((d.f['targetName'], svc))
    return out

def test_update_near():
    s = scene()
    w = World(s['C'], [s['C'], s['T'], s['X'], s['XT'], None])
    r = w.run('UpdateNearTrucks')
    src = [ra.f['addon'].f['name'] for ra in w.popup.f['sourceAddons']]
    print('UpdateNearTrucks ->', r, 'sources', src, 'targets', ids(w))
    assert src == ['cur_srv', 'srv_trailer', 'srv_addon'], src
    assert ids(w) == ['C', 'C', 'X', 'X', 'T'], ids(w)
    res = resolve_all(w)
    print('entries:', res)
    assert res == [('UI_C', False), ('UI_cur_srv', True), ('UI_X', False), ('UI_srv_addon', True), ('UI_srv_trailer', True)], res
    # multiplayer: only vanilla
    w = World(s['C'], [s['C'], s['T'], s['X'], s['XT']], mp=True)
    w.run('UpdateNearTrucks')
    assert [ra.f['addon'].f['name'] for ra in w.popup.f['sourceAddons']] == ['cur_srv']
    assert ids(w) == ['C', 'X']
    # blocked trailer not a target; scout without addons; own trailer not in nearTrucks
    s2 = scene()
    C2 = truck('C2')
    CT = truck('CT', trailer=True, self_addon=addon('own_trailer', 5, 50, 0, 4))
    C2.f['trailer_obj'] = CT
    w = World(C2, [C2, s2['T'], s2['X']], blocked={'T'})
    r = w.run('UpdateNearTrucks')
    print('scout ->', r, [ra.f['addon'].f['name'] for ra in w.popup.f['sourceAddons']], ids(w))
    assert ids(w) == ['C2', 'X', 'X', 'CT'], ids(w)


def test_can_be_shown():
    s = scene()
    C2 = truck('C2')
    w = World(C2, [C2, s['T']])
    assert w.run('IsCanBeShown') is True
    w = World(C2, [C2])
    assert w.run('IsCanBeShown') is False
    s['T_add'].f['rep'] = 0; s['T_add'].f['wh'] = 0
    w = World(C2, [C2, s['T']])
    assert w.run('IsCanBeShown') is False
    w = World(C2, [C2, s['X']], mp=True)
    assert w.run('IsCanBeShown') is False
    w = World(s['C'], [])
    assert w.run('IsCanBeShown') is True
    print('IsCanBeShown ok')


def setup(target_idx, source_key):
    s = scene()
    w = World(s['C'], [s['C'], s['T'], s['X'], s['XT']])
    w.run('UpdateNearTrucks')
    p = w.popup
    p.f['sourceIndex'] = [ra.f['addon'] for ra in p.f['sourceAddons']].index(s[source_key])
    p.f['targetIndex'] = target_idx
    w.subscribes(p)
    return s, w, p


def test_transfer():
    # targets: [C, C(cur_srv), X, X(srv_addon), T]
    s, w, p = setup(1, 'T_add')
    assert w.run('IsRepairEnabled', 6) is True
    assert w.run('IsRepairEnabled', 0) is True and w.run('IsRepairEnabled', 1) is True
    calls.clear()
    w.run('RepairPart', 0)                      # only parts
    assert (s['CA'].f['rep'], s['CA'].f['wh'], s['T_add'].f['rep'], s['T_add'].f['wh']) == (20, 0, 10, 2), s['CA'].f
    assert w.run('IsRepairEnabled', 0) is False and w.run('IsRepairEnabled', 1) is True
    w.run('RepairPart', 1)                      # only wheels
    assert (s['CA'].f['wh'], s['T_add'].f['wh']) == (2, 0)
    assert w.run('IsRepairEnabled', 6) is False
    calls.clear(); w.run('RepairAll')
    assert ('PlayCantRepairSound',) in calls
    # into trailer from X's addon (RepairAll)
    s, w, p = setup(4, 'XA')
    calls.clear(); w.run('RepairAll')
    assert (s['XA'].f['rep'], s['XA'].f['wh'], s['T_add'].f['rep'], s['T_add'].f['wh']) == (0, 0, 40, 3)
    assert ('PlayRepairAllSound',) in calls
    # source == target addon -> disabled, nothing happens
    s, w, p = setup(3, 'XA')
    assert w.run('IsRepairEnabled', 6) is False
    w.run('RepairAll')
    assert s['XA'].f['rep'] == 10
    # repair entry of an undamaged truck -> vanilla (RepairTruck), no transfer
    s, w, p = setup(0, 'T_add')
    dc = Obj('DamageController')
    w.vm.impls[('GameSession', 'GetDamageController')] = lambda g: dc
    w.vm.impls[('DamageController', 'RepairTruck')] = rec('RepairTruck')
    calls.clear(); w.run('RepairAll')
    assert calls and calls[0][0] == 'RepairTruck', calls
    assert s['CA'].f['rep'] == 0
    print('transfer ok')


def test_create_data():
    s, w, p = setup(4, 'XA')
    d = w.run('CreateData')
    rows = [(r.f['health'], r.f['maxHealth'], r.f['repairPartsCost'], r.f['repairWheelsCost']) for r in d.f['damagesData']]
    print('CreateData trailer:', d.f['targetName'], rows)
    assert d.f['targetName'] == 'UI_srv_trailer'
    assert rows[0] == (30, 60, 10, 0) and rows[1] == (2, 4, 0, 1) and rows[4][1] == -1
    s, w, p = setup(1, 'T_add')
    d = w.run('CreateData')
    rows = [(r.f['health'], r.f['maxHealth'], r.f['repairPartsCost'], r.f['repairWheelsCost']) for r in d.f['damagesData']]
    print('CreateData addon:', d.f['targetName'], rows)
    assert rows[0] == (0, 20, 20, 0) and rows[1] == (0, 2, 0, 2)
    s, w, p = setup(0, 'T_add')
    d = w.run('CreateData')
    print('CreateData truck:', d.f['targetName'], [r.f['maxHealth'] for r in d.f['damagesData']])
    assert d.f['targetName'] == 'UI_C' and d.f['damagesData'][4].f['maxHealth'] != -1
    print('CreateData ok')


def test_switch():
    s, w, p = setup(0, 'CA')
    w.run('SwitchTarget', 1)              # 1 is C(cur_srv) == source -> skipped to 2
    print('SwitchTarget ->', p.f['targetIndex'])
    assert p.f['targetIndex'] == 2
    s, w, p = setup(1, 'T_add')
    w.run('SwitchSource', -1)             # sources: cur_srv(0), srv_trailer(1) ... -> 0 = cur_srv == target C(cur_srv) -> skip
    print('SwitchSource ->', p.f['sourceIndex'])
    assert p.f['sourceIndex'] != 0
    print('switch ok')


def test_create_markers():
    s, w, p = setup(3, 'T_add')            # selected: X(srv_addon)
    decorated = []
    w.vm.impls[('MarkerOnTrucksGarnish', 'Decorate')] = lambda g, arr: decorated.extend(arr)
    w.vm.impls[('MarkerOnTrucksGarnishData', 'x')] = None
    p.f['truckGarnish'] = Obj('MarkerOnTrucksGarnish')
    p.f['markerDataArray'] = Arr()
    w.run('CreateMarkers')
    trucks = [d.f['truck'].f['id'] for d in decorated]
    print('markers for:', trucks, [[(a.f['name'], a.f.get('sel')) for a in d.f['addons']] for d in decorated])
    assert sorted(trucks) == sorted(set(trucks)), trucks
    xd = [d for d in decorated if d.f['truck'].f['id'] == 'X'][0]
    assert xd.f['addons'][0].f['sel'] is True
    print('markers ok')


def test_marker():
    s, w, p = setup(4, 'XA')
    mk = w.run('GetRepairTruckMarker', s['T'], 'icon', True)
    assert mk.f['name'] == 'UI_srv_trailer' and list(mk.f['res']) == []
    mk = w.run('GetRepairTruckMarker', s['C'], 'icon', False)
    print('marker ok')


for t in (test_update_near, test_can_be_shown, test_transfer, test_create_data, test_switch, test_create_markers, test_marker):
    t()
print('ALL OK')
