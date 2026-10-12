"""Фары привязаны к игроку: TruckInputController.SetActiveTruck / UpdateTruckStickersMaterial.
Игра гасит фары обоих грузовиков не сразу при пересадке, а позже (reset)."""
import os, sys
assert os.environ.get('SSL_BUNDLE') and os.environ.get('SSL_DB')
import ssl as S
from vm import VM, Obj, Arr, Dct, VMError
sys.path.insert(0, '/home/user/SnowRunner-Hardmod-Plus/Hard Mode Plus')
import sslpatch as SP, service_patches as SV

NAME = 'game.truck_manager.truck_input_controller'
DATA = '/tmp/claude-0/-home-user-SnowRunner-Hardmod-Plus/4f10eee7-7669-5080-b6af-5b4cdb4ff33e/scratchpad/data/'


def module(delay):
    """модуль контроллера, пропатченный с задержкой delay (None - оригинал)"""
    pre, names, blobs = SP.split_bundle(open(DATA + 'release.sslbundle', 'rb').read())
    idx = {n: i for i, n in enumerate(names)}
    ed = {n: SP.ModEditor(blobs[idx[n]], n) for n in SV.ALL_MODULES}
    if delay is not None:
        SV.apply(ed, {SV.LIGHTS_KEY: delay})
    return S.Mod(NAME, ed[NAME].blob())


class World:
    def __init__(self, m):
        self.m = m
        self.trucks = []
        self.log = []          # (грузовик, вкл/выкл) - только изменения состояния (щелчки)
        self.queue = []        # (время, номер, делегат)
        self.now = 0
        self.seq = 0
        self.stickers = []
        self.sched = Obj('AsyncScheduler')
        self.tm = Obj('TrucksManager')
        self.gs = Obj('GameSession')
        I = {
            ('*', '*'): lambda o, name, *a: None,
            ('Truck', 'GetTruckInput'): lambda t: t.f['input'],
            ('Truck', 'EnableHeadLight'): self.enable,
            ('Truck', 'IsTrailer'): lambda t: True,
            ('Truck', 'IsDiffLockEnabled'): lambda t: False,
            ('Truck', 'UpdateTruckStickersMaterial'): lambda t: self.stickers.append(t),
            ('AsyncScheduler', 'Delay'): self.delay,
            ('GameSession', 'GetTrucksManager'): lambda s: self.tm,
            ('TrucksManager', 'GetAllTrucks'): lambda s: Arr(self.trucks),
            ('TruckInputController', 'SetCanBeWinched'): lambda s, v: None,
        }
        self.vm = VM(m, I, {})
        self.vm.lenient = True
        self.c = Obj('TruckInputController', currTruck=None, currHeadLightsOn=False, scheduler=self.sched,
                     gameSession=self.gs, winchController=Obj('WinchController'),
                     foldableAddonController=None, isMoving=False, userSettings=Obj('UserSettings'))
        self.fi = {f['name']: i for i, f in enumerate(m.funcs) if f['code']}

    def delay(self, s, ms, dlg):
        self.seq += 1
        self.queue.append((self.now + ms, self.seq, dlg))

    def enable(self, t, on):
        t.f['input'].f['isHeadLight'] = on

    def step(self, fn):
        """один кадр: в лог - итоговые изменения фар (щелчок игра делает раз за кадр)"""
        before = {id(t): on(t) for t in self.trucks}
        fn()
        for t in self.trucks:
            if on(t) != before[id(t)]:
                self.log.append((t.f['name'], on(t)))

    def truck(self, name, lights=False):
        t = Obj('Truck', name=name, input=Obj('TruckInput', isHeadLight=lights), chassisLinearVelocity=0.0,
                isAdvancedMode=False, engineStartDelay=1.0, diffLockAlways=False,
                truckState=Obj('TruckState', hmpLightsTasks=0, hmpLightsKeep=False))
        self.trucks.append(t)
        return t

    def enter(self, t):
        self.log.clear()
        self.step(lambda: self.vm.run(self.fi['SetActiveTruck'], self.c, [t]))

    def toggle(self):
        self.step(lambda: self.vm.run(self.fi['ChangeHeadlights'], self.c, []))

    def run_until(self, t_ms, reset=(), reset_at=None):
        """прогнать задачи до момента t_ms; reset - грузовики, которым игра гасит фары в reset_at"""
        self.log.clear()
        while True:
            due = sorted(q for q in self.queue if q[0] <= t_ms)
            if reset_at is not None and (not due or due[0][0] > reset_at):
                self.now = reset_at
                for r in reset:
                    r.f['input'].f['isHeadLight'] = False   # игра гасит фары (без нашего лога)
                reset_at = None
                continue
            if not due:
                break
            q = due[0]
            self.queue.remove(q)
            self.now = q[0]
            self.step(lambda: self.vm.invoke(q[2]))
        self.now = t_ms

    def pending(self, t):
        return sum(1 for q in self.queue if q[2].bound[0] is t)


def on(t):
    return t.f['input'].f['isHeadLight']


p60, p0, van = module(60), module(0), module(None)

# --- в игре: фары нового грузовика как были
w = World(van)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
assert on(a) and w.c.f['currHeadLightsOn']
w.enter(b)
assert not on(b) and not w.c.f['currHeadLightsOn'] and w.queue == []
assert w.stickers == [a, b]
print('vanilla ok')

# --- наклейки: прямой вызов вместо UpdateTruckStickersMaterial контроллера
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.enter(b)
assert w.stickers == [a, b], w.stickers
w.enter(None)
assert w.stickers == [a, b]
print('stickers ok')

# --- первый грузовик (загрузка карты): как есть, задач нет
w = World(p60)
a = w.truck('A')
w.enter(a)
assert not on(a) and w.log == [] and w.queue == []
w = World(p60)
a = w.truck('A', lights=True)
w.enter(a)
assert on(a) and w.c.f['currHeadLightsOn'] and w.log == [] and w.queue == []
print('first truck ok')

# --- фары включены, игра гасит фары обоих грузовиков через 50 мс после пересадки
for reset_at in (50, 400, 1800, 5000):
    w = World(p60)
    a, b = w.truck('A'), w.truck('B')
    w.enter(a); w.toggle()
    w.enter(b)
    assert on(b) and on(a) and w.c.f['currHeadLightsOn']
    assert w.pending(b) == 6 and w.pending(a) == 7, (w.pending(a), w.pending(b))
    w.run_until(7000, reset=(a, b), reset_at=reset_at)
    assert on(b) and on(a), (reset_at, w.log)
    assert w.log == [('A', True), ('B', True)] or w.log == [('B', True), ('A', True)], (reset_at, w.log)
    w.run_until(59000)
    assert on(a) and on(b) and w.log == []
    w.run_until(61000)
    assert not on(a) and on(b) and w.log == [('A', False)], w.log
    assert a.f['truckState'].f['hmpLightsTasks'] == 0 and not a.f['truckState'].f['hmpLightsKeep']
    assert b.f['truckState'].f['hmpLightsTasks'] == 0
print('switch on + late reset ok')

# --- игра не гасит фары: щелчков от задач нет
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b)
assert w.log == [('B', True)], w.log
w.run_until(7000)
assert w.log == [] and on(a) and on(b)
w.run_until(61000)
assert w.log == [('A', False)]
print('no reset ok')

# --- игрок выключил фары: в новом грузовике выключены, задач нет
w = World(p60)
a, b = w.truck('A'), w.truck('B', lights=True)
w.enter(a)
w.enter(b)
assert not on(b) and not w.c.f['currHeadLightsOn'] and w.log == [('B', False)] and w.queue == [], w.log
w.toggle(); assert on(b)
w.toggle(); assert not on(b)
print('switch off ok')

# --- игрок выключил фары в новом грузовике до повторных попыток: попытки их не включают
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b)
w.run_until(300, reset=(a, b), reset_at=50)
assert on(b)
w.toggle()
assert not on(b) and not w.c.f['currHeadLightsOn']
w.run_until(10000)
assert not on(b), w.log
print('player off during retries ok')

# --- вернулся в покинутый до срока: старые задачи не гасят его фары
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b)
w.run_until(10000)
w.enter(a)                                   # A: фары включены, B держит фары
assert on(a) and on(b)
w.run_until(65000, reset=(a, b), reset_at=10050)
assert on(a) and on(b), w.log                # старая последняя задача A (60 с) - A текущий
w.run_until(71000)
assert on(a) and not on(b) and w.log == [('B', False)], w.log
print('return ok')

# --- покинул, вернулся, снова покинул: гаснет через 60 с после последнего ухода
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b); w.run_until(10000)
w.enter(a); w.run_until(20000)
w.enter(b)
w.run_until(79000)
assert on(a), w.log                          # задача ухода в 0 с (60 с) не погасила
w.run_until(81000)
assert not on(a) and on(b), w.log
print('leave twice ok')

# --- покинул с выключенными фарами после возврата: старые задачи не включают
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b); w.run_until(1000)
w.enter(a); w.toggle()                      # выключил фары в A
assert not on(a)
w.enter(b)
assert not on(b)
w.run_until(70000)
assert not on(a) and not on(b), w.log
print('left dark ok')

# --- грузовик удалён до срока: не трогаем
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b)
w.trucks.remove(a)
w.run_until(70000, reset=(a,), reset_at=50)
assert not on(a) and ('A', True) not in w.log and ('A', False) not in w.log, w.log
w = World(p60)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.trucks.remove(a)
a.f['input'].f['isHeadLight'] = False
w.enter(b)
assert on(b) and not on(a) and ('A', True) not in w.log, w.log
w.run_until(70000)
assert ('A', True) not in w.log
print('removed truck ok')

# --- выход из грузовика (гараж, смена карты): фары игрока сохраняются
w = World(p60)
a, c = w.truck('A'), w.truck('C')
w.enter(a); w.toggle()
w.enter(None)
assert w.c.f['currHeadLightsOn'] and w.queue == [] and w.log == []
w.enter(c)
assert on(c) and w.log == [('C', True)] and w.pending(c) == 6, w.log
w.run_until(7000, reset=(c,), reset_at=100)
assert on(c)
w = World(p60)
a, c = w.truck('A'), w.truck('C', lights=True)
w.enter(a)
w.enter(None)
w.enter(c)
assert on(c) and w.log == [] and w.c.f['currHeadLightsOn']
print('leave ok')

# --- задержка 0: покинутый гаснет сразу, новый включается и после сброса
w = World(p0)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b)
assert on(b) and not on(a) and w.pending(a) == 0 and w.pending(b) == 6, w.log
w.run_until(7000, reset=(b,), reset_at=50)
assert on(b) and not on(a)
print('delay 0 ok')

# --- короткая задержка (2 с): последняя задача покинутого - после попыток
p2 = module(2)
w = World(p2)
a, b = w.truck('A'), w.truck('B')
w.enter(a); w.toggle()
w.enter(b)
w.run_until(6400, reset=(a, b), reset_at=50)
assert on(a)
w.run_until(6600)
assert not on(a) and on(b)
print('short delay ok')
