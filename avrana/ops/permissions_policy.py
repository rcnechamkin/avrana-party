"""The appliance's Permissions-Policy for game pages, built from grants (AVR-62 section 4).

PROTOTYPE for docs/design/proposals/2026-10-26-package-permissions-presentation.md (decision D2 open): the
pure header and nginx map. Nothing installs the map, edits the nginx location or reloads nginx.

The header is the box's, built from what the appliance granted, never from what a package asks for: every
browser feature a game could use is denied (`feature=()`) unless a grant opens it to the game's own origin
(`feature=(self)`). Geolocation, USB, serial, Bluetooth, screen capture, payment and WebAuthn are never
opened to a game. `motion_sensors` is the proposal's addition (D1); until the contract has it, a grant of it
cannot exist, and the map below simply never sees one.
"""
import re

# The browser features a grant opens, by contract permission name.
OPENS = {
    'camera': ('camera',),
    'microphone': ('microphone',),
    'motion_sensors': ('accelerometer', 'gyroscope', 'magnetometer'),
    'controllers': ('gamepad',),
}
NEVER = ('bluetooth', 'display-capture', 'geolocation', 'payment', 'publickey-credentials-get', 'serial', 'usb')
SELF_ALWAYS = ('fullscreen',)
FEATURES = tuple(sorted({f for fs in OPENS.values() for f in fs} | set(NEVER)))
GAME_ID = re.compile(r'^[a-z][a-z0-9_-]{0,39}\Z')


def header(granted):
    """The Permissions-Policy value for a game granted `granted` (contract permission names). Unknown
    names open nothing."""
    opened = {f for name in (granted or ()) for f in OPENS.get(name, ())}
    parts = [f'{f}=(self)' if f in opened else f'{f}=()' for f in FEATURES]
    parts += [f'{f}=(self)' for f in SELF_ALWAYS]
    return ', '.join(parts)


DENY_ALL = header(())


def nginx_map(grants, variable='avrana_permissions_policy', key='native_game'):
    """An nginx `map` from the game id to its header, default deny-all. `grants` is {game id: [granted]}.
    A game id that is not a plain id is refused rather than written into nginx configuration."""
    lines = [f'map ${key} ${variable} {{', f'    default "{DENY_ALL}";']
    for game_id in sorted(grants):
        if not GAME_ID.match(str(game_id)):
            raise ValueError(f'not a game id: {game_id!r}')
        value = header(grants[game_id])
        if value != DENY_ALL:
            lines.append(f'    {game_id} "{value}";')
    lines.append('}')
    return '\n'.join(lines) + '\n'
