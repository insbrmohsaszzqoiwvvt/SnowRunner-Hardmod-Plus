"""Цена погрузки: база из настроек (если в игре погрузка платная) * множитель NG+,
за слот груза; брёвна - база * множитель вида (короткие/средние и горелые/длинные)."""
import os, sys
assert os.environ.get('SSL_BUNDLE')
import ssl as S
from vm import VM, Obj, Arr, Dct, VMError
sys.path.insert(0, '/home/user/SnowRunner-Hardmod-Plus/Hard Mode Plus')
import sslpatch as SP, service_patches as SV

NAME = 'ui.components.popups.cargo.popup_cargo_loading_ui_controller'
DATA = '/tmp/claude-0/-home-user-SnowRunner-Hardmod-Plus/4f10eee7-7669-5080-b6af-5b4cdb4ff33e/scratchpad/data/'


def module(price):
    """модуль окна погрузки, пропатченный с заданной ценой (None - оригинал)"""
    pre, names, blobs = SP.split_bundle(open(DATA + 'release.sslbundle', 'rb').read())
    idx = {n: i for i, n in enumerate(names)}
    ed = {n: SP.ModEditor(blobs[idx[n]], n) for n in SV.ALL_MODULES}
    if price is not None:
        SV.apply(ed, {SV.LOADING_KEY: price})
    return S.Mod(NAME, ed[NAME].blob())


LOGS = {'CargoLogsMedium', 'CargoLogsLong', 'CargoLogsShort', 'CargoLogsMedium_Burnt'}


def mocks(st):
    def any_(o, name, *a):
        return {'CanPlaceCargo': True, 'ShowCargoPreview': True, 'IsInfinite': True,
                'IsCargoExcluded': False, 'IsAnyTruckInZone': False}.get(name)
    return {
        ('*', '*'): any_,
        ('GameSession', 'GetGameDifficultyManager'): lambda s: Obj('GameDifficultyManager'),
        ('GameSession', 'GetPlayerProfileController'): lambda s: st['ppc'],
        ('ApplicationMode', 'GetTruckAddonsManager'): lambda s: Obj('TruckAddonsManager'),
        ('TruckAddonsManager', 'GetAllSuitableCargo'): lambda s, t: Arr(),
        ('GameSession', 'GetTrucksManager'): lambda s: Obj('TrucksManager'),
        ('TrucksManager', 'GetTruckInputsController'): lambda s: Obj('TruckInputController'),
        ('TruckInputController', 'GetFoldableAddonController'): lambda s: Obj('FoldableAddonController'),
        ('Truck', 'GetCenterPosCached'): lambda s: Obj('Vector3d'),
        ('PopupCargoLoadingUiController', 'PlayCargoPreviewSound'): lambda s, p: None,
        ('GameSession', 'GetZoneDescStorage'): lambda s: Obj('ZoneDescStorageContainerBase'),
        ('ZoneDescStorageContainerBase', 'TryGetZoneDesc'): lambda s, z: None,
        ('GameSession', 'GetHudManager'): lambda s: Obj('HudStateManagerMr'),
        ('HudStateManagerMr', 'GetDefaultHud'): lambda s: Obj('UiHudLibDefaulthud'),
        ('ApplicationMode', 'GetDeviceListener'): lambda s: Obj('InputFocusDeviceListener'),
        ('GameDifficultyManager', 'GetAutoloadPrice'): lambda s: st['autoload'],
        ('GameDifficultyManager', 'GetLoadingPriceFactor'): lambda s: st['factor'],
        ('TruckCargoUtils', 'GetCargoAutoloadCount'): lambda s, t: 3 if t in LOGS else 1,
        ('PlayerProfileController', 'AddMoney'): lambda s, v: st['money'].append(v),
        ('PlayerProfileController', 'GetMoney'): lambda s: st['balance'],
        ('PopupCargoLoadingUiController', 'GetView'): lambda s: st['view'],
        ('PopupCargoLoadingUiController', 'GetCurrentCargoTruckContainer'): lambda s: Obj('Truck'),
        ('PopupCargoLoadingUiController', 'AutoLoadCargo'): lambda s, n: st['loaded'].append(n),
        ('PopupCargoLoadingUiController', 'SendPopupAction'): lambda s, a: None,
        ('PopupCargoLoadingUiView', 'SetPriceForAutoLoading'): lambda s, p: st['shown'].append(p),
        ('PopupCargoLoadingUiView', 'SetWarningText'): lambda s, t: st['warn'].append(t),
        ('TruckAddonsManager', 'GetCargoByTypeAndSubtype'): lambda s, t, sub, f: st['cargo'],
    }


def run(m, fname, autoload=150, factor=1, ctype='CargoBricks', slots=1, balance=10 ** 6, base=None):
    st = dict(autoload=autoload, factor=factor, money=[], shown=[], warn=[], loaded=[], balance=balance,
              ppc=Obj('PlayerProfileController'), view=Obj('PopupCargoLoadingUiView'))
    st['cargo'] = Obj('Cargo', type=ctype, slotLength=slots, name='c')
    gs = Obj('GameSession')
    G = {101: lambda: gs, 18: lambda: Obj('Game'), 100: lambda: Obj('ApplicationMode'),
         163: lambda *a: None, 78: lambda t: False, 80: lambda a: Obj('TruckAddonDesc')}
    vm = VM(m, mocks(st), G)
    vm.lenient = True
    info = Obj('PopupCargoInfo', cargo=st['cargo'], count=5)
    c = Obj('PopupCargoLoadingUiController', playerProfileController=st['ppc'], currentCargoInfo=info,
            currentCargoLoadingPlace=0, utils=Obj('TruckCargoUtils'), mngr=Obj('TruckAddonsManager'),
            autoLoadPrice=base, gameSession=gs, currentTruck=Obj('Truck'), platformId='p',
            gameEngine=Obj('Game'), zoneGlobalId='z')
    fi = next(i for i, f in enumerate(m.funcs) if f['name'] == fname)
    if fname == 'InitContent':
        vm.run(fi, c, [Obj('PopupCargoInitialData')])
    elif fname == 'TryShowCargoPreview':
        vm.run(fi, c, [info])
    else:
        vm.run(fi, c, [])
    return c, st


D = {'short': 100, 'medium': 200, 'long': 300}
van, p150, p200 = module(None), module((150, D)), module((200, D))
pfrac = module((200, {'short': 150, 'medium': 0, 'long': 1000}))

# база
assert run(van, 'InitContent')[0].f['autoLoadPrice'] == 150
assert run(p150, 'InitContent')[0].f['autoLoadPrice'] == 150
assert run(p200, 'InitContent')[0].f['autoLoadPrice'] == 200
assert run(p200, 'InitContent', factor=2)[0].f['autoLoadPrice'] == 400      # NG+ x2
assert run(p200, 'InitContent', factor=0)[0].f['autoLoadPrice'] == 0        # NG+ бесплатно
assert run(p200, 'InitContent', autoload=0)[0].f['autoLoadPrice'] == 0      # обычный режим
assert run(module((0, D)), 'InitContent')[0].f['autoLoadPrice'] == 0
print('base ok')

# оплата
for slots, want in ((1, 200), (2, 400), (4, 800), (5, 1000), (6, 1200), (0, 200)):
    c, st = run(p200, 'Action', slots=slots, base=200)
    assert st['money'] == [-want], (slots, st['money'])
    assert st['loaded'] == [1]
for t, want in (('CargoLogsShort', 200), ('CargoLogsMedium', 400), ('CargoLogsMedium_Burnt', 400),
                ('CargoLogsLong', 600)):
    c, st = run(p200, 'Action', ctype=t, slots=1, base=200)
    assert st['money'] == [-want] and st['loaded'] == [3], (t, st)
    c, st = run(p200, 'Action', ctype=t, slots=4, base=400)               # слоты не важны, NG+ x2
    assert st['money'] == [-2 * want], (t, st)
for t, want in (('CargoLogsShort', 300), ('CargoLogsMedium', 0), ('CargoLogsLong', 2000)):
    c, st = run(pfrac, 'Action', ctype=t, base=200)
    assert st['money'] == [-want], (t, st)
c, st = run(pfrac, 'Action', ctype='CargoLogsShort', base=150)            # 150 * 1.5 = 225
assert st['money'] == [-225], st
c, st = run(pfrac, 'Action', slots=2, base=200)
assert st['money'] == [-400], st
c, st = run(p200, 'Action', slots=4, base=0)                              # бесплатно - не платим
assert st['money'] == [] and st['loaded'] == [1], st
c, st = run(van, 'Action', slots=4, base=150)
assert st['money'] == [-150], st
print('pay ok')

# цена на кнопке и проверка денег
c, st = run(p200, 'TryShowCargoPreview', slots=4, base=200, balance=10 ** 6)
assert st['shown'] == [800] and st['warn'][-1] == '', st
c, st = run(p200, 'TryShowCargoPreview', slots=4, base=200, balance=700)
assert st['shown'] == [800] and st['warn'][-1] == 'UI_NO_ENOUGH_MONEY', st
c, st = run(p200, 'TryShowCargoPreview', slots=1, base=200, balance=700)
assert st['shown'] == [200] and st['warn'][-1] == '', st
c, st = run(p200, 'TryShowCargoPreview', ctype='CargoLogsLong', base=200, balance=599)
assert st['shown'] == [600] and st['warn'][-1] == 'UI_NO_ENOUGH_MONEY', st
c, st = run(p200, 'TryShowCargoPreview', ctype='CargoLogsMedium_Burnt', base=200, balance=400)
assert st['shown'] == [400] and st['warn'][-1] == '', st
c, st = run(p200, 'TryShowCargoPreview', slots=4, base=0)
assert st['shown'] == [], st
c, st = run(van, 'TryShowCargoPreview', slots=4, base=150, balance=200)
assert st['shown'] == [150] and st['warn'][-1] == '', st
print('preview ok')
