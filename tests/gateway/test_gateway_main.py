import pytest

from nova.gateway.main import safe_start


class GoodAdapter:
    name = "good"

    def __init__(self):
        self.started = False

    async def start(self):
        self.started = True


class BadAdapter:
    name = "bad"

    async def start(self):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_safe_start_isolates_failures():
    good = GoodAdapter()
    await safe_start(good)
    assert good.started is True
    # A failing adapter must not raise out of safe_start.
    await safe_start(BadAdapter())
