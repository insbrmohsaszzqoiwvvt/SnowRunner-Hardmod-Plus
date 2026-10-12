"""Тест патча отдельных колёс: контроллер окна ремонта (на пропатченном модуле)."""
import os
assert os.environ.get('SSL_BUNDLE'), 'SSL_BUNDLE'
import ssl as S
from vm import VM, Obj, Arr, Dct, VMError, Delegate
import test_repair as TR

RMOD = 'ui.components.popups.repair.popup_repair_ui_controller_new'
m = S.get(RMOD)
fidx = {f['name']: i for i, f in enumerate(m.funcs)}

def vec(x, y, z): return Obj('Vector3d', x=float(x), y=float(y), z=float(z))

POS = [(-2, 0, -1), (2, 0, 1), (0, 0, 1), (2, 0, -1), (-2, 0, 1), (0.1, 0, -1)]
EXPECT = [1, 3, 2, 5, 4, 0]

def wheel_truck():
    t = TR.truck('T')
    t.f['wheelDamages'] = Arr([TR.dmg(10 * i, 100) for i in range(6)])
    t.f['pos'] = POS
    t.f['truckDamageHandler'] = Obj('TruckDamageHandler', truck=t, markersOffsets=Dct())
    return t

class W(TR.World):
    def __init__(self, cur, near, mp=False):
        TR.m = m  # пропатченный модуль
        super().__init__(cur, near, mp)
        self.vm = VM(m, self.vm.impls, self.vm.g)
        self.markers = Obj('IngameMarkersController', markers=Dct())
        self.terminated = []
        self.dc = Obj('DamageController')
        I = self.vm.impls
        I.update({
            ('Truck', 'GetPosWheels'): lambda t: Arr([vec(*p) for p in t.f['pos']]),
            ('Truck', 'GetChassisWorldTransformValue'): lambda t: Obj('Transform3d'),
            # преобразования - сдвиг по x (машина стоит в точке px)
            ('Truck', 'GetTransformValue'): lambda t: Obj('Transform3d', tx=float(t.f.get('px', 0.0))),
            ('Transform3d', 'TransformPoint'): lambda tr, v: vec(v.f['x'] + tr.f.get('tx', 0.0), v.f['y'], v.f['z']),
            # TruckDamageHandler.GetMarkerPos - как в игре: смещение из словаря + положение машины
            ('TruckDamageHandler', 'GetMarkerPos'): lambda h, mid: (lambda o: vec(
                o.f['x'] + float(h.f['truck'].f.get('px', 0.0)), o.f['y'], o.f['z']))(h.f['markersOffsets'][mid]),
            ('UiTextColors', 'GetColorByStatusMinMax'): lambda c, cur, mx: (lambda n: c.f.setdefault(n, Obj('Color', name=n[:-5])))(
                'redColor' if cur / mx <= 0.25 else ('yellowColor' if cur / mx <= 0.75 else 'whiteColor')),
            ('Color', 'IsEqual'): lambda a, b: a is b,
            ('UiColorTransform', 'SetupMultiplyer'): lambda ct, col: ct.f.__setitem__('fill', col),
            ('GameSession', 'GetIngameMarkersCtrl'): lambda s: self.markers,
            ('GameSession', 'GetDamageController'): lambda s: self.dc,
            ('IngameMarkersController', 'ReleaseSingleMarkerUiObject'): TR.rec('Release'),
            ('IngameMarkersController', 'AddUiObjToLayer'): self.add_marker,
            ('IngameMarkersController', 'RemoveObj'): self.remove_obj,
            ('DamageController', 'RepairPart'): TR.rec('DC.RepairPart'),
            ('UiDisplayObjectBase', 'SetParent'): lambda o, par: TR.calls.append(('SetParent', o, par)),
            ('UiMovieClip', 'GotoAndStop'): TR.rec('GotoAndStop'),
            ('NavigationPanelController', 'ForceUpdate'): TR.rec('ForceUpdate'),
        })
        G = self.vm.g
        G[461] = lambda tr: Obj('Transform3d', tx=-tr.f.get('tx', 0.0))
        G[1046] = lambda txt, col: '<%s>%s' % (col.f['name'], txt)
        G[790] = lambda key: {'UI_TRUCK_PART_WHEEL': 'КОЛЕСО'}.get(key, key)
        self.vm.lenient = True

def _add_marker(self, mc, obj, pos, mid, layer, arrow, getpos, anim):
    TR.calls.append(('AddMarker', obj, pos, mid, layer, arrow, getpos, anim))
    mc.f['markers'][mid] = Obj('MarkerUpdateData', markerData=Obj('MarkerCreationData', obj=obj, markerId=mid))

def _remove_obj(self, mc, obj):
    TR.calls.append(('RemoveObj', obj))
    for k, v in list(mc.f['markers'].items()):
        if v.f['markerData'].f['obj'] is obj:
            del mc.f['markers'][k]
            self.terminated.append(obj)

W.add_marker = _add_marker
W.remove_obj = _remove_obj

def setup(src_wheels=3):
    t = wheel_truck()
    serv = TR.addon('srv', 100, 200, src_wheels, 8)
    t.f['addons'] = [serv]
    w = W(t, [])
    p = w.popup
    p.f['sourceAddons'] = Arr([Obj('RepairAddon', parentTruck=t, addon=serv)])
    p.f['sourceAddon'] = p.f['sourceAddons'][0]
    p.f['targetTrucks'] = Arr([t])
    p.f['targetTruck'] = t
    p.f['repairNavPanel'] = Obj('PopupRepairNavigationPanel', isRepairEnabled=False)
    return w, t, serv

def test_create_data():
    w, t, serv = setup()
    data = w.run('CreateData')
    order = list(data.f['hmpWheelOrder'])
    assert order == EXPECT, order
    dd = data.f['damagesData']
    assert len(dd) == 5 + 6, len(dd)
    for k, wi in enumerate(EXPECT):
        e = dd[5 + k].f
        assert (e['health'], e['maxHealth'], e['repairPartsCost'], e['repairWheelsCost']) == \
            (100 - 10 * wi, 100, 0, 1 if wi else 0), (k, e)
    # без лишних строк у вида повреждений 0..4 как в игре
    assert dd[1].f['maxHealth'] == 6
    # сетевая игра: порядок не заполняется
    w2, t2, _ = setup()
    w2.vm.impls[('GameSession', 'IsMultiplayer')] = lambda s: True
    d2 = w2.run('CreateData')
    assert not d2.f.get('hmpWheelOrder'), d2.f.get('hmpWheelOrder')   # (VM создаёт пустые массивы сама)
    assert len(d2.f['damagesData']) == 5
    print('create data ok', order)

def test_enabled_and_repair():
    w, t, serv = setup()
    assert w.run('IsRepairEnabled', 100 + 3) is True       # колесо 3 повреждено (30)
    assert w.run('IsRepairEnabled', 100 + 0) is False      # колесо 0 целое
    assert w.run('IsRepairEnabled', 100 + 9) is False      # нет такого
    serv.f['wh'] = 0
    assert w.run('IsRepairEnabled', 103) is False          # нет запасных
    serv.f['wh'] = 2
    TR.calls.clear()
    w.run('RepairPart', 103)
    assert TR.calls == [('DC.RepairPart', 1003, w.popup.f['sourceAddon'], t)], TR.calls
    TR.calls.clear()
    w.run('RepairPart', 100)
    assert TR.calls == [('PlayCantRepairSound',)], TR.calls
    # обычные строки - как раньше
    assert w.run('IsRepairEnabled', 1) is False             # нет разрушенных колёс
    print('enabled/repair ok')

def test_marker():
    w, t, serv = setup()
    view_data = Obj('PopupRepairUiViewData2', hmpWheelOrder=Arr(EXPECT))
    w.view.f['lastData'] = view_data
    w.view.f['colors'] = Obj('UiTextColors', **{n: Obj('Color', name=n[:-5], a=255.0, r=float(10 * k), g=float(10 * k + 1), b=float(10 * k + 2))
                                                for k, n in enumerate(('redColor', 'yellowColor', 'whiteColor'))})
    t.f['px'] = 10.0
    t.f['pos'] = [(x + 10.0, y, z) for x, y, z in POS]
    TR.calls.clear()
    w.run('UpdateNavPanel', 100 + 2)
    names = [c[0] for c in TR.calls]
    assert names[0] != 'RemoveObj' and 'AddMarker' in names, names   # прежнего маркера не было
    add = [c for c in TR.calls if c[0] == 'AddMarker'][0]
    mk, pos, mid, layer, arrow, getpos, anim = add[1:]
    assert mid == 'hmp_wheel_marker' and layer == 0 and arrow is None and anim is False
    assert (pos.f['x'], pos.f['z']) == (10.0, 1.0), pos.f
    # маркер следует за машиной: getPos - TruckDamageHandler.GetMarkerPos с id маркера
    dh = t.f['truckDamageHandler']
    assert isinstance(getpos, Delegate) and getpos.obj is dh and getpos.bound == ['hmp_wheel_marker'], getpos
    off = dh.f['markersOffsets']['hmp_wheel_marker']
    assert (off.f['x'], off.f['z']) == (0.0, 1.0), off.f      # смещение от машины
    t.f['px'] = 25.0                                           # машина уехала
    p2 = w.vm.invoke(getpos)
    assert (p2.f['x'], p2.f['z']) == (25.0, 1.0), p2.f
    part = mk.f['truckDmgModulePart'].f['tf'].f['text']
    tf = mk.f['tfCont'].f['dmgValue'].f['tf']
    assert part == 'КОЛЕСО 3', part        # колесо 2 - третье по порядку
    assert tf.f['text'] == '<white>80/100' and tf.f['isHtml'] is True, tf.f   # 80% - белый
    assert ('GotoAndStop', 'normal') in TR.calls, TR.calls
    img = [c[1] for c in TR.calls if c[0] == 'SetParent'][0]
    assert 'colorTransform' not in img.f, img.f          # целое колесо - значок как в оверлее
    # 50% - жёлтый, без красной подсветки; 20% - красный с подсветкой (кадр damaged)
    TR.calls.clear()
    w.run('UpdateNavPanel', 100 + 5)
    mk5 = [c for c in TR.calls if c[0] == 'AddMarker'][0][1]
    assert mk5.f['tfCont'].f['dmgValue'].f['tf'].f['text'] == '<yellow>50/100'
    img5 = [c[1] for c in TR.calls if c[0] == 'SetParent'][0]
    ct = img5.f['colorTransform']
    mul, sh = ct.f['multiplier'].f, ct.f['shift'].f
    assert (mul['a'], mul['r'], mul['g'], mul['b']) == (255.0, 10.0, 11.0, 12.0), mul   # жёлтый (r,g,b), альфа как есть
    assert (sh['a'], sh['r'], sh['g'], sh['b']) == (0.0, 0.0, 0.0, 0.0), sh
    assert ('GotoAndStop', 'normal') in TR.calls and ('GotoAndStop', 'damaged') not in TR.calls, TR.calls
    t.f['wheelDamages'][4].f['damage'] = 80
    TR.calls.clear()
    w.run('UpdateNavPanel', 100 + 4)
    mk4 = [c for c in TR.calls if c[0] == 'AddMarker'][0][1]
    assert mk4.f['tfCont'].f['dmgValue'].f['tf'].f['text'] == '<red>20/100'
    assert ('GotoAndStop', 'damaged') in TR.calls, TR.calls
    img4 = [c[1] for c in TR.calls if c[0] == 'SetParent'][0]
    assert 'colorTransform' not in img4.f, img4.f          # красный - только кадр damaged, как в оверлее
    TR.calls.clear()
    w.run('UpdateNavPanel', 100 + 2)
    first = mk
    # повторный выбор колеса: старый значок уничтожается, на экране один маркер
    w.run('UpdateNavPanel', 100 + 3)
    w.run('UpdateNavPanel', 100 + 3)
    assert len(w.markers.f['markers']) == 1 and w.terminated[0] is first and len(w.terminated) == 5, w.terminated
    TR.calls.clear()
    w.run('UpdateNavPanel', 1)
    assert [c[0] for c in TR.calls if c[0] in ('RemoveObj', 'AddMarker', 'Release')] == ['RemoveObj'], TR.calls
    assert not w.markers.f['markers']
    print('marker ok')

if __name__ == '__main__':
    test_create_data()
    test_enabled_and_repair()
    test_marker()

def test_hide():
    w, t, serv = setup()
    w.vm.impls[('*', '*')] = lambda o, n, *a: TR.calls.append(('*' + n,))
    w.view.f['lastData'] = Obj('PopupRepairUiViewData2', hmpWheelOrder=Arr(EXPECT))
    w.run('UpdateNavPanel', 101)
    mk = w.markers.f['markers']['hmp_wheel_marker'].f['markerData'].f['obj']
    TR.calls.clear()
    try:
        w.run('Hide', False, None)
    except (VMError, AttributeError):
        pass
    assert TR.calls and TR.calls[0] == ('RemoveObj', mk), TR.calls[:3]
    assert not w.markers.f['markers']
    print('hide ok')

test_hide()
