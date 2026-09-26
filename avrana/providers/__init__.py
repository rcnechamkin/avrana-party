"""Provider boundaries (base) and the adapters the arcade uses today.

    from avrana.providers.base import ProviderInfo, RuntimeProvider, InputProvider, PresentationProvider
    from avrana.providers.controller import ControllerLayout
    from avrana.providers.retroarch import RetroArchRuntime
    from avrana.providers.uinput_gamepad import UInputGamepadProvider

Adapters import their system modules (python-evdev, ...) lazily, so this package imports on any
machine. Which providers a Party box has is declared in contracts/appliances/*.json.
"""
