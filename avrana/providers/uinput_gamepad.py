"""InputProvider over Linux uinput (python-evdev), extracted from arcade/stream.py unchanged.

Each seat gets one virtual gamepad: semantic buttons map to EV_KEY codes and a d-pad maps to the
ABS_X/ABS_Y axes at full deflection. Every snapshot rewrites both axes and ends with SYN, exactly
as the arcade has done since the prototype (RetroArch reads the pads through its udev driver).

Isolation is 'global': uinput devices are visible to every process on the Pi, so a second
runtime that scans udev joypads (for example another RetroArch) can pick them up. PS1 avoids this
by injecting XTest keys into a private display instead (branch experiment/ps1-title-profiles).

python-evdev is imported only when a controller is opened, so this module imports anywhere.
"""
import time

from avrana.providers.base import ProviderInfo

INFO = ProviderInfo(
    id='uinput-gamepad', kind='input', offers=('input.virtual_gamepad',),
    implementation='Linux uinput via python-evdev (BSD-3-Clause), one device per seat',
    isolation='global')

# Semantic button -> evdev key name. The arcade's four buttons, as mapped in arcade/retroarch.cfg.
ARCADE_CODES = {'fire': 'BTN_SOUTH', 'magic': 'BTN_EAST', 'coin': 'BTN_SELECT', 'start': 'BTN_START'}
AXIS_MIN, AXIS_MAX = -32768, 32767


class UInputGamepad:
    def __init__(self, evdev, slot, layout, codes, *, vendor, product, name):
        E = evdev.ecodes
        self._E = E
        self.layout = layout
        self._keys = {button: getattr(E, codes[button]) for button in layout.buttons}
        capabilities = {E.EV_KEY: list(self._keys.values())}
        if layout.directions == 'dpad':
            capabilities[E.EV_ABS] = [
                (E.ABS_X, evdev.AbsInfo(0, AXIS_MIN, AXIS_MAX, 0, 0, 0)),
                (E.ABS_Y, evdev.AbsInfo(0, AXIS_MIN, AXIS_MAX, 0, 0, 0))]
        self.device = evdev.UInput(capabilities, name=name, vendor=vendor, product=product)
        self.slot = slot
        self.state = frozenset()
        self.updated = time.monotonic()

    def set_state(self, pressed):
        new = self.layout.parse(pressed)
        E = self._E
        for button, code in self._keys.items():
            if (button in new) != (button in self.state):
                self.device.write(E.EV_KEY, code, int(button in new))
        if self.layout.directions == 'dpad':
            for axis, neg, pos in ((E.ABS_X, 'left', 'right'), (E.ABS_Y, 'up', 'down')):
                value = int(pos in new) - int(neg in new)
                self.device.write(E.EV_ABS, axis, AXIS_MIN if value < 0 else AXIS_MAX if value else 0)
        self.device.syn()
        self.state = new
        self.updated = time.monotonic()

    update = set_state  # the name arcade/stream.py has always used

    def neutralize(self):
        self.set_state([])

    def close(self):
        self.device.close()


class UInputGamepadProvider:
    info = INFO

    def __init__(self, codes=None, *, vendor=0x1209, product_base=0xA001, name='Avrana Player {n}', evdev=None):
        self.codes = dict(ARCADE_CODES if codes is None else codes)
        self.vendor = vendor
        self.product_base = product_base
        self.name = name
        self._evdev = evdev

    def _module(self):
        if self._evdev is None:
            import evdev  # noqa: PLC0415 - system package on the Pi (python3-evdev)
            self._evdev = evdev
        return self._evdev

    def open(self, slot, layout):
        unmapped = [b for b in layout.buttons if b not in self.codes]
        if unmapped:
            raise ValueError(f'no uinput code for {unmapped}')
        return UInputGamepad(self._module(), slot, layout, self.codes, vendor=self.vendor,
                             product=self.product_base + slot, name=self.name.format(n=slot + 1))
