"""Thin HTTP client for the Yuvomi schedule API (``/api/v1/schedule``)."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from types import TracebackType
from typing import Any, Self

import httpx

from .yuvomi_plan import ExistingOverride, ExistingType, ShiftTypeSpec

API = "/api/v1/schedule"
DEFAULT_TIMEOUT_S = 30.0


class YuvomiError(RuntimeError):
    """Yuvomi API call failed."""


class YuvomiClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._http = httpx.Client(
            base_url=base_url,
            headers={"X-API-Key": api_key, "Accept": "application/json"},
            timeout=timeout_s,
            transport=transport,
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def list_shift_types(self) -> tuple[ExistingType, ...]:
        rows = self._request("GET", "/shift-types").get("data", [])
        with _shape_errors("GET /shift-types"):
            return tuple(
                ExistingType(int(r["id"]), r.get("short_code"), str(r.get("name", "")))
                for r in rows
            )

    def create_shift_type(self, spec: ShiftTypeSpec) -> int:
        body = {
            "name": spec.name,
            "short_code": spec.short_code,
            "start_time": spec.start_time,
            "end_time": spec.end_time,
            "color": spec.color,
            "icon": spec.icon,
        }
        payload = {k: v for k, v in body.items() if v is not None}
        data = self._request("POST", "/shift-types", json=payload)
        with _shape_errors("POST /shift-types"):
            row = data.get("data", data)
            return int(row["id"])

    def list_overrides(
        self, user_id: int, start: date, end: date
    ) -> tuple[ExistingOverride, ...]:
        params = {"user_id": user_id, "from": start.isoformat(), "to": end.isoformat()}
        rows = self._request("GET", "/overrides", params=params).get("data", [])
        with _shape_errors("GET /overrides"):
            return tuple(
                ExistingOverride(
                    day=date.fromisoformat(r["date_key"]),
                    shift_type_id=r.get("shift_type_id"),
                    note=r.get("note") or "",
                )
                for r in rows
                if r.get("user_id") == user_id  # never act on other members' days
            )

    def put_override(
        self, user_id: int, day: date, type_id: int | None, note: str
    ) -> None:
        body = {"user_id": user_id, "shift_type_id": type_id, "note": note}
        self._request("PUT", f"/overrides/{day.isoformat()}", json=body)

    def delete_override(self, user_id: int, day: date) -> None:
        params = {"user_id": user_id}
        self._request("DELETE", f"/overrides/{day.isoformat()}", params=params)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._http.request(method, API + path, **kwargs)
        except httpx.HTTPError as exc:
            raise YuvomiError(f"{method} {path}: {exc}") from exc
        if response.is_error:
            status, detail = response.status_code, _error_text(response)
            raise YuvomiError(f"{method} {path} -> HTTP {status}: {detail}")
        if not response.content:
            return {}
        with _shape_errors(f"{method} {path}"):
            data = response.json()
        return data if isinstance(data, dict) else {"data": data}


@contextmanager
def _shape_errors(call: str) -> Iterator[None]:
    """Unexpected response shape -> YuvomiError (exit code 5, no traceback)."""
    try:
        yield
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise YuvomiError(f"{call}: unexpected response ({exc!r})") from exc


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error", ""))[:200]
    except ValueError:
        return response.text[:200]
