import pickle, ssl as S
from vm import VM, Obj, Arr, Dct, VMError

pm = pickle.load(open('../data/patched_release.pkl', 'rb'))
VMOD = 'ui.components.popups.repair.popup_repair_ui_view_new'
m = S.Mod(VMOD, pm[VMOD])
fidx = {f['name']: i for i, f in enumerate(m.funcs)}

def row(h, mx, c=0, w=0):
    return Obj('PopupRepairUiViewTruckData', health=h, maxHealth=mx, repairPartsCost=c, repairWheelsCost=w)

class ListAdapter:
    pass

def make():
    lst = Obj('UiListAdapter', data=Arr(), selected=None)
    I = {
        ('PopupRepairUiViewNew', 'UpdateTargetSwitcher'): lambda s, *a: None,
        ('PopupRepairUiViewNew', 'UpdateSourceSwitcher'): lambda s, *a: None,
        ('PopupRepairUiViewNew', 'SelectRepairPosition'): lambda s, d: s.f.__setitem__('selected_item', d),
        ('UiListAdapter', 'GetSelectedData'): lambda l: l.f['selected'],
        ('UiListAdapter', 'GetData'): lambda l: l.f['data'],
        ('UiListAdapter', 'SetData'): lambda l, data, b: l.f.__setitem__('data', data),
        ('UiTextColors', 'GetColorByStatusMinMax'): lambda s, a, b: 'color',
        ('UiMovieClip', 'GotoAndStop'): lambda s, x: None,
    }
    G = {1046: lambda txt, col: str(txt), 930: lambda fmt, *a: fmt % tuple(x for x in a if x is not None),
         123: lambda typ, name, icon, cost, color: Obj('PopupRepairUiViewLirItemData', type=typ, name=name, iconName=icon, cost=cost)}
    vm = VM(m, I, G)
    vm.lenient = True
    view = Obj('PopupRepairUiViewNew', repairPositionList=lst, selectedIndex=-1, hintText='',
               repairView=Obj('UiPopupLibPopuprepair', additionalInfo=Obj('UiMovieClip'),
                              btnHold=Obj('UiEmbeddedClipText', text='')))
    return vm, view, lst

def data(rows):
    return Obj('PopupRepairUiViewData2', targetName='t', targetHasArrows=True, sourceName='s', sourceHasArrows=True,
               damagesData=Arr(rows), availableRepairParts=150, maxRepairParts=150, availableRepairWheels=2,
               maxRepairWheels=2, showVisualHint=False)

vm, view, lst = make()
svc = data([row(1397, 1500, 103, 0), row(8, 8, 0, 0), row(0, 0), row(0, 0), row(0, -1)])
vm.run(fidx['UpdateData'], view, [svc])
items = lst.f['data']
print('service rows:', [(getattr(i, 'f', {}).get('name'), i.f.get('cost') if hasattr(i, 'f') else None) for i in items])
assert len(items) == 3
assert items[1].f['name'] == 'UI_POPUP_RESUPPLY_PARTS' and items[2].f['name'] == 'UI_HUD_REPAIR_DIALOG_REPAIR_WHEELS'
print('parts row value:', items[1].f['iconName'])
# truck mode -> 6 rows
vm, view, lst = make()
trk = data([row(170, 170), row(6, 6), row(200, 200), row(150, 150), row(50, 50)])
vm.run(fidx['UpdateData'], view, [trk])
assert len(lst.f['data']) == 6
# selection index out of range after switching to service target
vm, view, lst = make()
vm.run(fidx['UpdateData'], view, [trk])
lst.f['selected'] = lst.f['data'][5]
vm.run(fidx['UpdateData'], view, [svc])
print('selectedIndex after switch:', view.f['selectedIndex'])
assert view.f['selectedIndex'] == 0
# hint: no 'fully repaired' for service target
view.f['hintText'] = 'UI_HUD_REPAIR_FULLY_REPAIRED'
view.f['lastData'] = svc
vm.run(fidx['UpdateRepairHint'], view, [])
assert view.f['repairView'].f['btnHold'].f['text'] == '', view.f['repairView'].f['btnHold'].f
view.f['hintText'] = 'UI_HUD_REPAIR_FULLY_REPAIRED'
view.f['lastData'] = trk
vm.run(fidx['UpdateRepairHint'], view, [])
assert view.f['repairView'].f['btnHold'].f['text'] == 'UI_HUD_REPAIR_FULLY_REPAIRED'
print('VIEW OK')
