"""Тест вида окна ремонта: строка колеса, стрелки, перелистывание (пропатченный модуль)."""
import os
assert os.environ.get('SSL_BUNDLE')
import ssl as S
from vm import VM, Obj, Arr, Dct, VMError, Delegate

VMOD = 'ui.components.popups.repair.popup_repair_ui_view_new'
m = S.get(VMOD)
fidx = {f['name']: i for i, f in enumerate(m.funcs)}
log = []

def color_of(cur, mx):
    p = cur / mx if mx else 0.0
    return 'red' if p <= 0.25 else ('yellow' if p <= 0.75 else 'white')

def row(h, mx, c=0, w=0):
    return Obj('PopupRepairUiViewTruckData', health=h, maxHealth=mx, repairPartsCost=c, repairWheelsCost=w)

ORDER = [1, 3, 2, 5, 4, 0]
DMG = [0, 10, 20, 30, 40, 50]           # урон колеса i

def truck_data(order=ORDER):
    dd = [row(170, 170), row(6, 6), row(200, 200), row(150, 150), row(50, 50)]
    for wi in (order or []):
        dd.append(row(100 - DMG[wi], 100, 0, 1 if DMG[wi] else 0))
    return Obj('PopupRepairUiViewData2', targetName='t', targetHasArrows=True, sourceName='s', sourceHasArrows=True,
               damagesData=Arr(dd), availableRepairParts=150, maxRepairParts=150, availableRepairWheels=2,
               maxRepairWheels=2, showVisualHint=False, hmpWheelOrder=Arr(order) if order is not None else None,
               hmpPrevArrow=None, hmpNextArrow=None)

def service_data():
    return Obj('PopupRepairUiViewData2', targetName='t', targetHasArrows=True, sourceName='s', sourceHasArrows=True,
               damagesData=Arr([row(1397, 1500, 103, 0), row(8, 8, 0, 0), row(0, 0), row(0, 0), row(0, -1)]),
               availableRepairParts=150, maxRepairParts=150, availableRepairWheels=2, maxRepairWheels=2,
               showVisualHint=False, hmpWheelOrder=None, hmpPrevArrow=None, hmpNextArrow=None)

class Env:
    def __init__(self):
        self.events = {'Left': Obj('SslUiInputEvent'), 'Right': Obj('SslUiInputEvent')}
        scr = Obj('SslUiInputScreen')
        self.lst = Obj('UiListAdapter', data=Arr(), selected=None, uiInputScreen=scr)
        self.callbacks = []
        self.rows = []      # отрисованные строки списка
        details = Obj('UiPopupLibPopuprepairtargetdetailslist', items=Arr())
        self.details = details
        sw = Obj('UiPopupLibHudpopuprepairtargetswitcher',
                 prevBtn=Obj('UiPopupLibHudpopuparrow', x0=10.0, y0=40.0),
                 nextBtn=Obj('UiPopupLibHudpopuparrow', x0=420.0, y0=40.0))
        env = self
        def set_data(l, data, focus):
            l.f['data'] = data
            sel = l.f.get('sel_idx')
            l.f['selected'] = data[sel] if sel is not None and sel < len(data) else None
            # строки списка: высота 30, ширина 300, сверху вниз от y=100
            details.f['items'] = Arr([Obj('PopupRepairUiViewLirItem', data=d, width=300.0, height=30.0, y0=100.0 + 30 * k,
                                          headerTf=Obj('UiPopupLibHudpopupreswitchertfsmallleft', x0=60.0,
                                                       y0=108.0 + 30 * k, height=14.0))
                                      for k, d in enumerate(data)])
            fut = Obj('Future')
            return fut
        def select_index(l, i):
            l.f['sel_idx'] = i
            l.f['selected'] = l.f['data'][i]
        I = {
            ('PopupRepairUiViewNew', 'UpdateTargetSwitcher'): lambda s, *a: None,
            ('PopupRepairUiViewNew', 'UpdateSourceSwitcher'): lambda s, *a: None,
            ('UiListAdapter', 'GetSelectedData'): lambda l: l.f['selected'],
            ('UiListAdapter', 'GetData'): lambda l: l.f['data'],
            ('UiListAdapter', 'SetData'): set_data,
            ('UiListAdapter', 'SelectIndex'): select_index,
            ('SslUiInputScreen', 'TryGet'): lambda s, n: env.events.get(n),
            ('Future', 'AddCallback'): lambda f, d: env.callbacks.append(d),
            ('UiTextColors', 'GetColorByStatusMinMax'): lambda s, a, b: color_of(a, b),
            ('UiMovieClip', 'GotoAndStop'): lambda s, x: None,
            ('UiDisplayObjectBase', 'SetParent'): lambda o, p: log.append(('SetParent', o.cls, p.cls)),
            ('UiDisplayObjectBase', 'LocalToOtherCoords'): lambda o, other, v: Obj('Vector2d', x=o.f.get('x0', 20.0) + v.f['x'], y=o.f['y0'] + v.f['y']),
            ('UiSounds', 'PlaySound'): lambda s, snd: log.append(('sound', snd)),
            ('ComponentUiViewBase', 'SubscribeContent'): lambda s: None,
            ('ComponentUiViewBase', 'UnsubscribeContent'): lambda s: None,
            ('RepairRefuelBaseView', 'SubscribeCbForSwitcher'): lambda s, *a: None,
            ('RepairRefuelBaseView', 'UnsubscribeCbForSwitcher'): lambda s, *a: None,
        }
        G = {1046: lambda txt, col: '<%s>%s' % (col, txt), 930: lambda fmt, *a: fmt % tuple(x for x in a if x is not None),
             123: lambda typ, name, icon, cost, color: Obj('PopupRepairUiViewLirItemData', type=typ, name=name,
                                                         iconName=icon, valueText=cost, isAll=False),
             479: lambda: Obj('Vector2d', x=0.0, y=0.0),
             790: lambda key: {'UI_TRUCK_PART_WHEEL': 'КОЛЕСО'}.get(key, key)}
        self.vm = VM(m, I, G)
        self.vm.lenient = True
        self.view = Obj('PopupRepairUiViewNew', repairPositionList=self.lst, selectedIndex=-1, hintText='',
                        switchClickSound='click', uiSounds=Obj('UiSounds'), lastData=None,
                        repairView=Obj('UiPopupLibPopuprepair', additionalInfo=Obj('UiMovieClip'),
                                       btnHold=Obj('UiEmbeddedClipText', text=''),
                                       repairTargetSwitcher=sw, repairTargetDetails=details))

    def run(self, name, *a):
        return self.vm.run(fidx[name], self.view, list(a))

    def names(self):
        return [(d.f.get('name'), d.f.get('type'), d.f.get('valueText')) for d in self.lst.f['data']]

def test_rows_and_arrows():
    e = Env()
    d = truck_data()
    e.run('UpdateData', d)
    rows = e.names()
    assert len(rows) == 6 and rows[1][0] == 'UI_HUD_REPAIR_DIALOG_REPAIR_WHEELS' and rows[1][1] == 1, rows
    pa, na = d.f['hmpPrevArrow'], d.f['hmpNextArrow']
    assert pa.cls == 'UiPopupLibHudpopuparrow' and na.cls == 'UiPopupLibHudpopuparrow'
    assert abs(pa.f['scaleX'] - 60) < 1e-6 and abs(na.f['scaleX'] + 60) < 1e-6 and abs(na.f['scaleY'] - 60) < 1e-6
    assert pa.f['visible'] is False
    clicks = [x for x in pa.f['__ev'][81]] + [x for x in na.f['__ev'][81]]
    assert [c.bound for c in clicks] == [[-1000], [1000]] and all(c.obj is e.view for c in clicks), clicks
    assert len(e.callbacks) == 1 and e.callbacks[0].nparams == 0
    pa.f['width'] = na.f['width'] = 20.0
    pa.f['height'] = na.f['height'] = 15.0
    # колбэк после заполнения списка расставляет стрелки (UpdateRepairHint)
    e.vm.invoke(e.callbacks[0], 'result')
    assert pa.f['visible'] is True and na.f['visible'] is True
    # строка 1: x=20, y=130, высота 30, ширина 300; у стрелки width - из lenient (Obj) -> задаём
    print('arrows at', pa.f.get('x'), pa.f.get('y'), na.f.get('x'), na.f.get('y'))
    # повторный UpdateData - стрелки те же
    d2 = truck_data()
    e.run('UpdateData', d2)
    assert d2.f['hmpPrevArrow'] is pa and d2.f['hmpNextArrow'] is na
    print('rows/arrows ok')
    return e

def test_flip():
    e = Env()
    d = truck_data()
    e.run('UpdateData', d)
    for a in (d.f['hmpPrevArrow'], d.f['hmpNextArrow']):
        a.f['width'] = 20.0
        a.f['height'] = 15.0
    seq = []
    for _ in range(8):
        e.vm.invoke(d.f['hmpNextArrow'].f['__ev'][81][0])
        r = e.names()[1]
        seq.append((r[0], r[1], r[2]))
    print('flip right:', [s[0] for s in seq])
    assert [s[0] for s in seq[:6]] == ['КОЛЕСО %d' % k for k in range(1, 7)], seq
    assert seq[6][0] == 'UI_HUD_REPAIR_DIALOG_REPAIR_WHEELS' and seq[7][0] == 'КОЛЕСО 1', seq
    assert [s[1] for s in seq[:6]] == [100 + w for w in ORDER], seq
    assert seq[0][2] == '<white>90/100', seq[0]       # колесо 1 = номер 1 (урон 10)
    assert e.lst.f['selected'] is e.lst.f['data'][1]  # выбрана строка колёс
    # влево из «колесо 1» -> «все»
    e.vm.invoke(d.f['hmpPrevArrow'].f['__ev'][81][0])
    assert e.names()[1][0] == 'UI_HUD_REPAIR_DIALOG_REPAIR_WHEELS'
    e.vm.invoke(d.f['hmpPrevArrow'].f['__ev'][81][0])
    assert e.names()[1][0] == 'КОЛЕСО 6', e.names()[1]
    # стрелки - от колонок стрелок переключателя цели (x 10 и 420) внутрь на 0.0625 * 410,
    # центр - по центру текста строки 1 (y=138, высота 14 -> 145) + 0.1 высоты стрелки (15)
    e.run('UpdateRepairHint')
    pa, na = d.f['hmpPrevArrow'], d.f['hmpNextArrow']
    assert all(abs(u - v) < 1e-4 for u, v in zip((pa.f['x'], pa.f['y'], na.f['x'], na.f['y']),
                                                  (35.625, 145 - 0.227 * 15, 394.375, 145 - 0.227 * 15))), \
        (pa.f['x'], pa.f['y'], na.f['x'], na.f['y'])
    # «КОЛЕСО 6» - целое колесо: «нет урона»
    assert e.view.f['hintText'] == 'UI_HUD_REPAIR_FULLY_REPAIRED'
    # -> «КОЛЕСА» -> «КОЛЕСО 1» (урон 10): подсказка с ценой в колёсах
    e.vm.invoke(d.f['hmpNextArrow'].f['__ev'][81][0])
    e.vm.invoke(d.f['hmpNextArrow'].f['__ev'][81][0])
    assert e.names()[1][0] == 'КОЛЕСО 1'
    hint = e.view.f['hintText']
    print('hint for wheel:', hint)
    assert 'UI_HUD_REPAIR_DIALOG_HINT' in hint, hint
    print('flip ok')

def test_keyboard_and_reset():
    e = Env()
    d = truck_data()
    e.run('SubscribeContent') if False else None
    # подписка клавиатуры
    try:
        e.run('SubscribeContent')
    except (VMError, AttributeError, KeyError) as ex:
        print('SubscribeContent (base part not mocked):', ex)
    L, R = e.events['Left'], e.events['Right']
    assert [x.bound for x in L.f.get('__ev', {}).get(4, [])] == [[-2000]], L.f
    assert [x.bound for x in R.f.get('__ev', {}).get(4, [])] == [[2000]], R.f
    e.run('UpdateData', d)
    d.f['hmpPrevArrow'].f['width'] = d.f['hmpNextArrow'].f['width'] = 20.0
    d.f['hmpPrevArrow'].f['height'] = d.f['hmpNextArrow'].f['height'] = 15.0
    # клавиатура: строка колёс не выбрана -> ничего
    e.lst.f['selected'] = e.lst.f['data'][3]
    e.vm.invoke(R.f['__ev'][4][0])
    assert e.names()[1][0] == 'UI_HUD_REPAIR_DIALOG_REPAIR_WHEELS'
    e.lst.f['selected'] = e.lst.f['data'][1]
    e.lst.f['sel_idx'] = 1
    e.vm.invoke(R.f['__ev'][4][0])
    assert e.names()[1][0] == 'КОЛЕСО 1', e.names()
    e.vm.invoke(R.f['__ev'][4][0])
    assert e.names()[1][0] == 'КОЛЕСО 2'
    # переключение цели сбрасывает выбор колеса
    try:
        e.run('SwitchTarget', 1)
    except (VMError, AttributeError) as ex:
        pass
    assert e.lst.f['data'][1].f['type'] == 1
    # отписка
    try:
        e.run('UnsubscribeContent')
    except (VMError, AttributeError, KeyError):
        pass
    assert not L.f['__ev'][4] and not R.f['__ev'][4]
    print('keyboard/reset ok')

def test_service_and_mp():
    e = Env()
    s = service_data()
    e.run('UpdateData', s)
    s.f['hmpPrevArrow'].f['width'] = s.f['hmpNextArrow'].f['width'] = 20.0
    s.f['hmpPrevArrow'].f['height'] = s.f['hmpNextArrow'].f['height'] = 15.0
    assert [n[0] for n in e.names()] == ['UI_HUD_REPAIR_DIALOG_REPAIR_ALL', 'UI_POPUP_RESUPPLY_PARTS', 'UI_POPUP_RESUPPLY_WHEELS'], e.names()
    e.vm.invoke(e.callbacks[-1])
    assert s.f['hmpPrevArrow'].f['visible'] is False
    # стрелка у сервисной цели ничего не делает
    e.vm.invoke(s.f['hmpNextArrow'].f['__ev'][81][0])
    assert [n[0] for n in e.names()][2] == 'UI_POPUP_RESUPPLY_WHEELS'
    # сеть (нет порядка колёс) - строка как в игре, стрелок нет
    e2 = Env()
    d = truck_data(order=None)
    d.f['hmpWheelOrder'] = None
    e2.run('UpdateData', d)
    d.f['hmpPrevArrow'].f['width'] = d.f['hmpNextArrow'].f['width'] = 20.0
    d.f['hmpPrevArrow'].f['height'] = d.f['hmpNextArrow'].f['height'] = 15.0
    e2.vm.invoke(e2.callbacks[-1])
    assert d.f['hmpPrevArrow'].f['visible'] is False
    print('service/mp ok')

def test_select_and_cost():
    e = Env()
    d = truck_data()
    e.run('UpdateData', d)
    d.f['hmpPrevArrow'].f['width'] = d.f['hmpNextArrow'].f['width'] = 20.0
    d.f['hmpPrevArrow'].f['height'] = d.f['hmpNextArrow'].f['height'] = 15.0
    # «Все» считает только 5 узлов
    full = e.vm.run(fidx['GetFullRepairCostStr'], e.view, [d])
    assert full == '', full          # у узлов машины нет урона; колёса не считаются
    d.f['damagesData'][3].f['repairPartsCost'] = 20
    full = e.vm.run(fidx['GetFullRepairCostStr'], e.view, [d])
    print('full cost:', repr(full))
    assert full == '|repairPartsImg20|20', full
    print('cost ok')

def test_wheels_color_and_full_hint():
    e = Env()
    d = truck_data()
    e.run('UpdateData', d)
    r = e.lst.f['data'][1]
    # худшее колесо - урон 50 из 100 (50%%) -> жёлтый, числа строки - как в игре (6/6)
    assert (r.f['valueText'], r.f['color']) == ('<yellow>6/6', 'yellow'), (r.f['valueText'], r.f.get('color'))
    d = truck_data()
    d.f['damagesData'][5 + 2].f['health'] = 20        # колесо с 20/100 -> красный
    e.run('UpdateData', d)
    r = e.lst.f['data'][1]
    assert (r.f['valueText'], r.f['color']) == ('<red>6/6', 'red'), r.f['valueText']
    d = truck_data()
    for k in range(5, 11):
        d.f['damagesData'][k].f['health'] = 99        # 99/100 -> белый
    e.run('UpdateData', d)
    assert e.lst.f['data'][1].f['valueText'] == '<white>6/6', e.lst.f['data'][1].f['valueText']
    # «Все»: частично побитые колёса (строки 5..) не требуют очков колёс
    d = truck_data()
    e.run('UpdateData', d)
    e.run('UpdateFullRepairHint')
    assert e.view.f['hintText'] == 'UI_HUD_REPAIR_FULLY_REPAIRED', e.view.f['hintText']
    d.f['damagesData'][1].f['repairWheelsCost'] = 2   # два лопнувших колеса - как в игре
    e.run('UpdateFullRepairHint')
    assert e.view.f['hintText'].endswith('|repairWheelsImg20|2'), e.view.f['hintText']
    # сеть (нет строк колёс) - цвет как в игре
    e2 = Env()
    d = truck_data(order=None)
    d.f['hmpWheelOrder'] = None
    e2.run('UpdateData', d)
    assert e2.lst.f['data'][1].f['valueText'] == '<white>6/6', e2.lst.f['data'][1].f['valueText']
    print('wheels color / full hint ok')

test_rows_and_arrows()
test_wheels_color_and_full_hint()
test_flip()
test_keyboard_and_reset()
test_service_and_mp()
test_select_and_cost()
print('WHEELS VIEW OK')

def test_hide_reset():
    e = Env()
    d = truck_data()
    e.run('UpdateData', d)
    d.f['hmpPrevArrow'].f['width'] = d.f['hmpNextArrow'].f['width'] = 20.0
    d.f['hmpPrevArrow'].f['height'] = d.f['hmpNextArrow'].f['height'] = 15.0
    e.vm.invoke(d.f['hmpNextArrow'].f['__ev'][81][0])
    assert e.lst.f['data'][1].f['type'] == 101
    e.vm.impls[('UiListAdapter', 'Deactivate')] = lambda l: None
    e.vm.impls[('RepairRefuelBaseView', 'Hide')] = lambda s, a, b: None
    e.run('Hide', False, None)
    assert e.lst.f['data'][1].f['type'] == 1
    print('hide reset ok')

test_hide_reset()
