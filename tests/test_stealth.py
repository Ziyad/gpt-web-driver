import types

from spec2_hybrid.stealth import stealth_init


class FakePage:
    def __init__(self):
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)


def test_stealth_init_sends_disable_calls():
    uc = types.SimpleNamespace()
    uc.cdp = types.SimpleNamespace()
    uc.cdp.runtime = types.SimpleNamespace(disable=lambda: ("runtime.disable",))
    uc.cdp.log = types.SimpleNamespace(disable=lambda: ("log.disable",))
    uc.cdp.debugger = types.SimpleNamespace(
        disable=lambda: ("debugger.disable",),
        set_breakpoints_active=lambda *, active: ("debugger.set_breakpoints_active", active),
    )

    page = FakePage()
    import asyncio

    asyncio.run(stealth_init(page, uc_module=uc))

    assert page.sent == [
        ("runtime.disable",),
        ("log.disable",),
        ("debugger.disable",),
        ("debugger.set_breakpoints_active", False),
    ]
