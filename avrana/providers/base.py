"""Provider boundaries: Avrana decides, providers do.

Three seams with a consumer today (arcade/stream.py) and a second implementation in view
(PS1 on branch experiment/ps1-title-profiles):

  RuntimeProvider       start/stop/observe one game runtime process (RetroArch today)
  InputProvider         create per-seat virtual controllers and push full input snapshots
                        (uinput today; XTest for PS1)
  PresentationProvider  deliver a game's picture to seats (one shared WebRTC encode today;
                        crop, dedicated-stream and browser renderers later)

Each provider declares the runtime capabilities it offers (contracts/capabilities.v0.json) so the
appliance profile and the Capability Engine can reason about what this Party box can do without
knowing which implementation is underneath. Seat allocation, input staleness timeouts and
policy stay with Avrana, never inside a provider.

These are typing.Protocol classes: an adapter conforms by shape, it does not inherit.
"""
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

KINDS = ('runtime', 'input', 'presentation')
ISOLATION = ('global', 'private', 'n/a')


@dataclass(frozen=True)
class ProviderInfo:
    id: str                 # matches a provider id in contracts/appliances/*.json
    kind: str               # one of KINDS
    offers: tuple           # runtime capability names from the vocabulary
    implementation: str     # human description, including the upstream license where relevant
    isolation: str = 'n/a'  # input: 'global' = devices visible to every process; 'private' = one runtime

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f'kind must be one of {KINDS}')
        if self.isolation not in ISOLATION:
            raise ValueError(f'isolation must be one of {ISOLATION}')
        if not self.offers:
            raise ValueError('a provider offers at least one capability')

    def describe(self):
        out = {'id': self.id, 'kind': self.kind, 'offers': list(self.offers)}
        if self.isolation != 'n/a':
            out['isolation'] = self.isolation
        return out


@runtime_checkable
class RuntimeProvider(Protocol):
    info: ProviderInfo

    def start(self, *, stdout=None):
        """Start the runtime; returns the process handle. Raises if it is already running."""

    def running(self) -> bool:
        """True while the runtime process is alive."""

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the runtime to exit, then force it after `timeout` seconds. Idempotent."""

    def status(self) -> dict:
        """JSON-safe diagnostics (no secrets, no paths to user content)."""


@runtime_checkable
class VirtualController(Protocol):
    state: frozenset        # the semantic buttons currently held
    updated: float          # time.monotonic() of the last snapshot

    def set_state(self, pressed: Iterable[str]) -> None:
        """Apply a full snapshot of held buttons (validated against the layout)."""

    def neutralize(self) -> None:
        """Release everything (stale input, disconnect, takeover)."""

    def close(self) -> None:
        """Destroy the device."""


@runtime_checkable
class InputProvider(Protocol):
    info: ProviderInfo

    def open(self, slot: int, layout) -> VirtualController:
        """Create the controller for a 0-based slot. Create controllers before the runtime starts
        so the runtime sees them at launch."""


@runtime_checkable
class PresentationProvider(Protocol):
    info: ProviderInfo

    def request_keyframe(self, reason: str) -> None:
        """Ask the encoder for a fresh keyframe (a viewer joined or lost packets)."""

    def status(self) -> dict:
        """JSON-safe diagnostics: viewers, encoders."""
