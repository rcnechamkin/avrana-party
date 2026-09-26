"""Controller layouts: the semantic buttons a game's phone controller sends.

The layout is declared by the Game Contract ("input": {"buttons", "directions"}); input providers
map the names to their own device codes, and the phone page renders one control per name. A
test checks that the arcade's layout, its contract and its page all agree.
"""
from dataclasses import dataclass

DIRECTION_NAMES = {'dpad': ('up', 'down', 'left', 'right'), 'none': (), 'analog': ()}


@dataclass(frozen=True)
class ControllerLayout:
    buttons: tuple
    directions: str = 'dpad'

    def __post_init__(self):
        if self.directions not in DIRECTION_NAMES:
            raise ValueError(f'directions must be one of {sorted(DIRECTION_NAMES)}')
        if len(set(self.buttons)) != len(self.buttons) or set(self.buttons) & set(DIRECTION_NAMES['dpad']):
            raise ValueError('buttons must be unique and must not reuse direction names')

    @property
    def names(self):
        """Every name a snapshot may contain."""
        return frozenset(self.buttons) | frozenset(DIRECTION_NAMES[self.directions])

    def parse(self, values):
        """Validate one snapshot from a phone: a list of at most len(names) known names.
        Raises ValueError('Invalid controller state') on anything else (the arcade's historical
        message). Returns the held names as a frozenset."""
        names = self.names
        if (not isinstance(values, list) or len(values) > len(names)
                or any(not isinstance(v, str) or v not in names for v in values)):
            raise ValueError('Invalid controller state')
        return frozenset(values)

    @classmethod
    def from_contract(cls, input_block):
        """Build from a validated Game Contract 'input' block (controller models only)."""
        if input_block.get('model') == 'browser_native':
            raise ValueError('a browser_native game has no controller layout')
        return cls(buttons=tuple(input_block.get('buttons', ())), directions=input_block.get('directions', 'dpad'))
