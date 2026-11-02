import json
from datetime import date

import httpx
import pytest

from pep_scraper.yuvomi_client import YuvomiClient, YuvomiError
from pep_scraper.yuvomi_plan import (
    ExistingExtra,
    ExistingOverride,
    ExistingType,
    ShiftTypeSpec,
)

KEY = "test-key-123"


def _client(handler: httpx.MockTransport) -> YuvomiClient:
    return YuvomiClient("https://y.example", KEY, transport=handler)


def test_list_shift_types_sends_api_key() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        assert req.headers["X-API-Key"] == KEY
        assert req.url.path == "/api/v1/schedule/shift-types"
        row = {
            "id": 4,
            "short_code": "U",
            "name": "Urlaub",
            "icon": "palmtree",
            "created_at": "2026-10-26T21:14:59Z",
        }
        return httpx.Response(200, json={"data": [row]})

    assert _client(httpx.MockTransport(handle)).list_shift_types() == (
        ExistingType(4, "U", "Urlaub", "palmtree", "2026-10-26T21:14:59Z"),
    )


def test_create_shift_type_body() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        assert req.method == "POST"
        assert json.loads(req.content) == {
            "name": "N003 21:45-06:15",
            "short_code": "N003",
            "start_time": "21:45",
            "end_time": "06:15",
            "color": "#ABB3FF",
        }
        return httpx.Response(
            201,
            json={
                "data": {
                    "id": 11,
                    "short_code": "N003",
                    "name": "N003 21:45-06:15",
                    "icon": None,
                    "created_at": "2026-11-01T23:28:24Z",
                }
            },
        )

    spec = ShiftTypeSpec("N003", "N003 21:45-06:15", "21:45", "06:15", "#ABB3FF")
    assert _client(httpx.MockTransport(handle)).create_shift_type(spec) == ExistingType(
        11, "N003", "N003 21:45-06:15", None, "2026-11-01T23:28:24Z"
    )


def test_update_shift_type_body() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        assert (req.method, req.url.path) == ("PUT", "/api/v1/schedule/shift-types/7")
        assert json.loads(req.content) == {
            "name": "Nachtdienst",
            "icon": "moon",
            "start_time": "21:45",
            "end_time": "06:15",
        }
        return httpx.Response(200, json={"data": {}})

    spec = ShiftTypeSpec("N003", "Nachtdienst", "21:45", "06:15", "#ABB3FF", "moon")
    _client(httpx.MockTransport(handle)).update_shift_type(7, spec)


def test_list_overrides_query() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        assert dict(req.url.params) == {
            "user_id": "4",
            "from": "2026-11-01",
            "to": "2026-11-30",
        }
        row = {
            "user_id": 4,
            "date_key": "2026-11-05",
            "shift_type_id": None,
            "note": None,
        }
        return httpx.Response(200, json={"data": [row]})

    got = _client(httpx.MockTransport(handle)).list_overrides(
        4, date(2026, 11, 1), date(2026, 11, 30)
    )
    assert got == (ExistingOverride(date(2026, 11, 5), None, ""),)


def test_put_and_delete_override() -> None:
    seen: list[tuple[str, str, object]] = []

    def handle(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content) if req.content else dict(req.url.params)
        seen.append((req.method, req.url.path, body))
        return httpx.Response(200, json={"data": {}})

    client = _client(httpx.MockTransport(handle))
    client.put_override(4, date(2026, 11, 5), 7, "pep-scraper")
    client.delete_override(4, date(2026, 11, 6))
    assert seen == [
        (
            "PUT",
            "/api/v1/schedule/overrides/2026-11-05",
            {"user_id": 4, "shift_type_id": 7, "note": "pep-scraper"},
        ),
        ("DELETE", "/api/v1/schedule/overrides/2026-11-06", {"user_id": "4"}),
    ]


def test_http_error_raises_without_leaking_key() -> None:
    def handle(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "Forbidden.", "code": 403})

    with pytest.raises(YuvomiError, match="403.*Forbidden") as info:
        _client(httpx.MockTransport(handle)).list_shift_types()
    assert KEY not in str(info.value)


def test_transport_error_wrapped() -> None:
    def handle(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=req)

    with pytest.raises(YuvomiError, match="boom"):
        _client(httpx.MockTransport(handle)).list_shift_types()


def test_list_overrides_drops_other_users() -> None:
    def handle(_req: httpx.Request) -> httpx.Response:
        rows = [
            {
                "user_id": 4,
                "date_key": "2026-11-05",
                "shift_type_id": 1,
                "note": "pep-scraper",
            },
            {
                "user_id": 3,
                "date_key": "2026-11-06",
                "shift_type_id": 1,
                "note": "pep-scraper",
            },
        ]
        return httpx.Response(200, json={"data": rows})

    got = _client(httpx.MockTransport(handle)).list_overrides(
        4, date(2026, 11, 1), date(2026, 11, 30)
    )
    assert [o.day for o in got] == [date(2026, 11, 5)]


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>not json</html>"),
        httpx.Response(200, json={"data": [{"no_id": 1}]}),
    ],
)
def test_malformed_response_raises_yuvomi_error(response: httpx.Response) -> None:
    with pytest.raises(YuvomiError):
        _client(httpx.MockTransport(lambda _r: response)).list_shift_types()


def test_extras_roundtrip() -> None:
    seen: list[tuple[str, str]] = []

    def handle(req: httpx.Request) -> httpx.Response:
        seen.append((req.method, req.url.path))
        if req.method == "GET":
            rows = [
                {
                    "id": 9,
                    "user_id": 4,
                    "date_key": "2026-11-05",
                    "shift_type_id": 2,
                    "note": "pep-scraper",
                },
                {
                    "id": 8,
                    "user_id": 3,
                    "date_key": "2026-11-05",
                    "shift_type_id": 2,
                    "note": "pep-scraper",
                },
            ]
            return httpx.Response(200, json={"data": rows})
        if req.method == "POST":
            assert json.loads(req.content) == {
                "user_id": 4,
                "date_key": "2026-11-06",
                "shift_type_id": 2,
                "note": "pep-scraper",
            }
            return httpx.Response(201, json={"data": {"id": 10}})
        return httpx.Response(204)

    client = _client(httpx.MockTransport(handle))
    extras = client.list_extras(4, date(2026, 11, 1), date(2026, 11, 30))
    assert extras == (ExistingExtra(9, date(2026, 11, 5), 2, "pep-scraper"),)
    client.add_extra(4, date(2026, 11, 6), 2, "pep-scraper")
    client.delete_extra(9)
    assert seen[-1] == ("DELETE", "/api/v1/schedule/extras/9")


@pytest.mark.parametrize(("status", "gone"), [(204, True), (404, True), (409, False)])
def test_delete_shift_type(status: int, gone: bool) -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(status, json={"error": "x"})
    )
    assert _client(transport).delete_shift_type(5) is gone


def test_delete_shift_type_other_error_raises() -> None:
    transport = httpx.MockTransport(
        lambda _r: httpx.Response(500, json={"error": "kaputt"})
    )
    with pytest.raises(YuvomiError, match="500"):
        _client(transport).delete_shift_type(5)


def test_list_shift_types_reads_times() -> None:
    row = {"id": 4, "name": "N", "start_time": "21:45:00", "end_time": "06:15"}

    def handle(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [row]})

    (t,) = _client(httpx.MockTransport(handle)).list_shift_types()
    assert (t.start_time, t.end_time) == ("21:45", "06:15")
