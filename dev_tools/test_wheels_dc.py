"""DamageController.RepairPart(1000 + колесо): меняется только это колесо, тратится 1 колесо."""
import os
assert os.environ.get('SSL_BUNDLE')
import ssl as S
from vm import VM, Obj, Arr, Dct, VMError

m = S.get('game.damage_controller')
fidx = {f['name']: i for i, f in enumerate(m.funcs)}
calls = []

def dmg(d, cap=100): return Obj('DamageData', damage=d, damageCapacity=cap)

def run(target, wheels_dmg, src_wheels=3, src_parts=50, mode_type=0):
    t = Obj('Truck', type='T', wheelDamages=Arr([dmg(d) for d in wheels_dmg]), engineDamage=dmg(30),
            fuelTankDamage=dmg(0), gearboxDamage=dmg(0), suspensionDamage=dmg(0))
    addon = Obj('TruckAddon', name='srv', rep=src_parts, wh=src_wheels)
    ra = Obj('RepairAddon', parentTruck=Obj('Truck', type='P'), addon=addon)
    gs = Obj('GameSession')
    dc = Obj('DamageController', gameSession=gs, rapairTotalValue=0, targetRepair=None, repairedTruck=None,
             truckIdsForCheck=Arr())
    I = {
        ('TruckAddon', 'GetRepairs'): lambda a: a.f['rep'],
        ('TruckAddon', 'SetRepairs'): lambda a, v: a.f.__setitem__('rep', v),
        ('TruckAddon', 'GetWheelRepairs'): lambda a: a.f['wh'],
        ('TruckAddon', 'SetWheelRepairs'): lambda a, v: a.f.__setitem__('wh', v),
        ('GameSession', 'GetGameMode'): lambda s: Obj('GameModeBase'),
        ('GameModeBase', 'GetType'): lambda g: mode_type,
        ('GameSession', 'GetGameDifficultyManager'): lambda s: Obj('GameDifficultyManager'),
        ('GameDifficultyManager', 'GetRepairPointsRequiredFactor'): lambda s, n: 1.0,
        ('Truck', 'GetWheelDamageData'): lambda tr: tr.f['wheelDamages'],
        ('Truck', 'HandleRepair'): lambda tr, d, n: calls.append(('HandleRepair',)),
        ('Truck', 'CreateDesc'): lambda tr: Obj('TruckDesc'),
        ('DamageController', 'CheckObjectiveRepairedTruck'): lambda s, a, b: None,
        ('DamageController', 'CompleteRepair'): lambda s: calls.append(('Complete', s.f['targetRepair'], s.f['rapairTotalValue'])),
        ('DamageParams', 'HasResupplyInfo'): lambda p: False,
        ('DamageParams', 'HasDamageInfo'): lambda p: True,
    }
    G = {413: lambda v, lo, hi: max(lo, min(hi, v)), 101: lambda: gs}
    vm = VM(m, I, G)
    vm.lenient = True
    calls.clear()
    vm.run(fidx['RepairPart'], dc, [target, ra, t])
    return [d.f['damage'] for d in t.f['wheelDamages']], addon.f['wh'], addon.f['rep'], list(calls), t

w, wh, rep, c, t = run(1002, [10, 20, 30, 0])
assert w == [10, 20, 0, 0], w
assert wh == 2 and rep == 50, (wh, rep)
assert ('Complete', 1, 30) in c, c
print('single wheel ok', w, wh, c)
w, wh, rep, c, t = run(1003, [10, 20, 30, 0])          # колесо целое - ничего
assert w == [10, 20, 30, 0] and wh == 3, (w, wh)
w, wh, rep, c, t = run(1001, [10, 20, 30, 0], src_wheels=0)   # нет запасных
assert w == [10, 20, 30, 0] and wh == 0, (w, wh)
w, wh, rep, c, t = run(1009, [10, 20])                 # нет колеса
assert w == [10, 20] and wh == 3
# обычный ремонт колёс (разрушенные) - как в игре
w, wh, rep, c, t = run(1, [100, 20, 100])
assert w == [0, 20, 0] and wh == 1, (w, wh)
print('vanilla wheels ok', w, wh)
