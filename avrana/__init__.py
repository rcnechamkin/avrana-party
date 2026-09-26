"""Avrana Party platform code shared by the appliance services (stdlib only).

avrana.contracts   Game Contract v0, the capability vocabulary, the appliance profile, the
                   per-seat capability evaluation and the web catalog build.
avrana.providers   Provider boundaries (runtime, input, presentation) and the adapters that the
                   arcade uses today.
avrana.web         The Full Mode web shell build and a local dev server (tests only).

Nothing here needs the Pi. Hardware-facing adapters import their system modules lazily, so every
module imports on any machine with Python 3.11+.
"""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = REPO_ROOT / 'contracts'
WEB_DIR = REPO_ROOT / 'web' / 'party'
