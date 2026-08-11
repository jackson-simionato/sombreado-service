import logging
from contextlib import contextmanager

import pytest

from sombreado.route_reads.current import CurrentRouteReadService


class _FakeSession:
    def __init__(self) -> None:
        self.connection_calls = 0

    def connection(self):
        self.connection_calls += 1
        return object()


class _FakeStore:
    def __init__(self) -> None:
        self.session_obj = _FakeSession()

    @contextmanager
    def session(self):
        yield self.session_obj


@pytest.mark.asyncio
async def test_run_session_logs_connect_and_query_ms(caplog):
    store = _FakeStore()
    service = CurrentRouteReadService(store)

    with caplog.at_level(logging.INFO):
        result = await service._run_session("search_route_candidates", lambda _session: ["ok"])

    assert result == ["ok"]
    assert store.session_obj.connection_calls == 1
    records = [record for record in caplog.records if "db_session operation=" in record.getMessage()]
    assert len(records) == 1
    message = records[0].getMessage()
    assert "operation=search_route_candidates" in message
    assert "connect_ms=" in message
    assert "query_ms=" in message
