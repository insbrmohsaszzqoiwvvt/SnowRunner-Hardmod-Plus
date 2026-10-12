import pickle, ssl as S, sys
sys.path.insert(0, '../out')
import sslpatch as L
from vm import VM, Obj, Arr, Dct, VMError
import test_repair as TR

pm = pickle.load(open('../data/patched_release.pkl', 'rb'))
HMOD = 'ui.hud.hud_controllers.hud_interaction_panel_controller'
m = S.Mod(HMOD, pm[HMOD])
fidx = {f['name']: i for i, f in enumerate(m.funcs)}
calls = []
def rec(name, ret=None):
    def f(*a):
        calls.append((name,) + a[1:])
        return ret
    return f

def make(cur):
    I = dict(TR.impl)
    I.update({
        ('TruckInputController', 'IsMoving'): lambda s: False,
        ('Transform3d', 'GetUp'): lambda s: 'up',
        ('Truck', 'GetTransformValue'): lambda t: Obj('Transform3d'),
        ('Truck', 'GetCargoes'): lambda t, inc: Dct(t.f['cargo']),
        ('Truck', 'GetWinchTruck'): lambda t, a, b: t.f['winch'],
        ('Truck', 'CheckConstrainedTrucksAbove'): lambda t: False,
        ('Truck', 'CheckUnconstrainedTrucksAbove'): lambda t: False,
        ('Truck', 'HasIKCraneAddon'): lambda t: False,
        ('TruckCargoUtils', 'HasUnpackedCargoInTruckOrTrailer'): lambda s, t: bool(t.f.get('unpacked')),
        ('TruckCargoUtils', 'UnpackCargo'): rec('UnpackCargo'),
        ('TruckCargoUtils', 'PackCargo'): rec('PackCargo'),
        ('TruckCargoUtils', 'CheckAnyCargoToPack'): lambda s, t: (calls.append(('Check', t)), Obj('PackCargoFailureInfoCommon', reason=1, isLogs=False))[1],
        ('PackCargoFailureInfoCommon', 'CanPack'): lambda s: True,
        ('CargoRemover', 'IsActive'): lambda s: False,
        ('PopupsQueue', 'Hide'): lambda s, p: None,
        ('PopupUiController', 'GetId'): lambda s: 1,
        ('HudInteractionPanelController', 'SetData'): lambda s, t: None,
        ('HudInteractionPanelController', 'CreateButtonData'): lambda s, action, aid, a1, a2: Obj('Btn', action=action, aid=aid),
    })
    G = {500: lambda: 'unitY', 486: lambda a, b: 0.0}
    vm = VM(m, I, G)
    vm.lenient = True
    hud = Obj('HudInteractionPanelController', truckInputController=Obj('TruckInputController'),
              truckCargoUtils=Obj('TruckCargoUtils'), currentTruck=cur, cargoRemover=Obj('CargoRemover'),
              packWarningPopup=Obj('PopupPackCargoWarningController'), popupsQueue=Obj('PopupsQueue'), currentTruckAddons=Arr())
    return vm, hud

def buttons(d):
    return [b.f['action'].split('PANEL_')[-1] for b in d.f['buttonsData']]

def action(vm, hud, aid):
    code = m.funcs[fidx['HandleActionRequest']]['code']
    pc = L.find_one(code, '07:-1 04:%d 30:7 16:*' % aid)
    calls.clear()
    vm.run(fidx['HandleActionRequest'], hud, [None], start=pc, init_locals={-1: aid})
    return list(calls)

C = TR.truck('C', cargo={})
T = TR.truck('T', trailer=True, cargo={'logs': 2})
C.f['winch'] = T
vm, hud = make(C)
print('packed cargo on winched trailer ->', buttons(vm.run(fidx['CreateCargoData'], hud, [C])))
assert 'UNPACK_CARGO' in buttons(vm.run(fidx['CreateCargoData'], hud, [C]))
print('unpack action:', action(vm, hud, 9)); assert action(vm, hud, 9)[0][1] is T
T.f['cargo'] = {}; T.f['unpacked'] = True
b = buttons(vm.run(fidx['CreateCargoData'], hud, [C]))
print('unpacked cargo on winched trailer ->', b)
assert 'PACK_CARGO' in b and 'UNPACK_CARGO' not in b
cl = action(vm, hud, 8)
print('pack action:', cl)
assert cl[0] == ('Check', T) and cl[1][0] == 'PackCargo' and cl[1][1] is T
calls.clear(); vm.run(fidx['AcceptPackWarning'], hud, [])
print('accept warning:', calls); assert calls[0][1] is T
# no winch -> own truck
C.f['winch'] = None; C.f['unpacked'] = True
b = buttons(vm.run(fidx['CreateCargoData'], hud, [C]))
assert 'PACK_CARGO' in b
cl = action(vm, hud, 8); assert cl[0] == ('Check', C) and cl[1][1] is C
calls.clear(); vm.run(fidx['AcceptPackWarning'], hud, []); assert calls[0][1] is C
C.f['unpacked'] = False
assert 'PACK_CARGO' not in buttons(vm.run(fidx['CreateCargoData'], hud, [C]))
# winched to truck with nothing -> own cargo unpack
C.f['winch'] = T; T.f['unpacked'] = False; C.f['cargo'] = {'x': 1}
assert action(vm, hud, 9)[0][1] is C
print('HUD OK')
