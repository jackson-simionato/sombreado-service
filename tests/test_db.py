import pytest

from app import db


class FakeSessionContext:
    def __init__(self) -> None:
        self.exited = False

    async def __aenter__(self) -> str:
        return "session"

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.exited = True


class FakeSessionFactory:
    def __init__(self) -> None:
        self.calls = 0
        self.context = FakeSessionContext()

    def __call__(self) -> FakeSessionContext:
        self.calls += 1
        return self.context


@pytest.mark.asyncio
async def test_get_session_opens_session_from_factory(monkeypatch):
    factory = FakeSessionFactory()
    monkeypatch.setattr(db, "_session_factory", factory)

    session_iterator = db.get_session()

    assert await anext(session_iterator) == "session"
    assert factory.calls == 1

    await session_iterator.aclose()
    assert factory.context.exited is True
