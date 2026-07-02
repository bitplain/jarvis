from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import Settings

QueryParamValue = str | int | float | bool | None
WHOOP_AUTHORIZATION_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
WHOOP_TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
WHOOP_API_BASE_URL = "https://api.prod.whoop.com/developer/v2"
WHOOP_SCOPES = ("offline", "read:profile", "read:sleep", "read:recovery", "read:cycles")
WHOOP_HTTP_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class WhoopTokenSet:
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str
    token_type: str = "bearer"


class WhoopClientError(RuntimeError):
    def __init__(self, code: str, *, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


class WhoopUnauthorizedError(WhoopClientError):
    pass


class WhoopRateLimitError(WhoopClientError):
    pass


class WhoopServerError(WhoopClientError):
    pass


class WhoopBadResponseError(WhoopClientError):
    pass


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    scopes: tuple[str, ...] = WHOOP_SCOPES,
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
        }
    )
    return f"{WHOOP_AUTHORIZATION_URL}?{query}"


async def exchange_code_for_tokens(
    *,
    code: str,
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> WhoopTokenSet:
    return await _with_client(
        http_client,
        lambda client: _post_token(
            client,
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.whoop_client_id,
                "client_secret": settings.whoop_client_secret,
                "redirect_uri": settings.whoop_redirect_uri,
            },
        ),
    )


async def refresh_access_token(
    *,
    refresh_token: str,
    settings: Settings,
    http_client: httpx.AsyncClient | None = None,
) -> WhoopTokenSet:
    return await _with_client(
        http_client,
        lambda client: _post_token(
            client,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": settings.whoop_client_id,
                "client_secret": settings.whoop_client_secret,
                "scope": "offline",
            },
        ),
    )


async def get_profile(
    *,
    access_token: str,
    http_client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    return await _with_client(
        http_client,
        lambda client: _get_json(
            client,
            "/user/profile/basic",
            access_token=access_token,
        ),
    )


async def get_sleep_collection(
    *,
    access_token: str,
    start: datetime,
    end: datetime,
    http_client: httpx.AsyncClient | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    return await _with_client(
        http_client,
        lambda client: _get_collection(
            client,
            "/activity/sleep",
            access_token=access_token,
            start=start,
            end=end,
            limit=limit,
        ),
    )


async def get_recovery_collection(
    *,
    access_token: str,
    start: datetime,
    end: datetime,
    http_client: httpx.AsyncClient | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    return await _with_client(
        http_client,
        lambda client: _get_collection(
            client,
            "/recovery",
            access_token=access_token,
            start=start,
            end=end,
            limit=limit,
        ),
    )


async def get_cycle_collection(
    *,
    access_token: str,
    start: datetime,
    end: datetime,
    http_client: httpx.AsyncClient | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    return await _with_client(
        http_client,
        lambda client: _get_collection(
            client,
            "/cycle",
            access_token=access_token,
            start=start,
            end=end,
            limit=limit,
        ),
    )


class WhoopClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def refresh_access_token(self, **kwargs: Any) -> WhoopTokenSet:
        return await refresh_access_token(settings=self.settings, **kwargs)

    async def get_profile(self, **kwargs: Any) -> dict[str, Any]:
        return await get_profile(**kwargs)

    async def get_sleep_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await get_sleep_collection(**kwargs)

    async def get_recovery_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await get_recovery_collection(**kwargs)

    async def get_cycle_collection(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await get_cycle_collection(**kwargs)


async def _with_client[T](
    http_client: httpx.AsyncClient | None,
    call: Callable[[httpx.AsyncClient], Awaitable[T]],
) -> T:
    if http_client is not None:
        return await call(http_client)
    async with httpx.AsyncClient(timeout=WHOOP_HTTP_TIMEOUT_SECONDS) as client:
        return await call(client)


async def _post_token(client: httpx.AsyncClient, data: dict[str, str]) -> WhoopTokenSet:
    try:
        response = await client.post(
            WHOOP_TOKEN_URL,
            data=data,
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        raise WhoopClientError("whoop_http_error") from exc
    _raise_for_status(response)
    payload = _json_object(response)
    try:
        return WhoopTokenSet(
            access_token=str(payload["access_token"]),
            refresh_token=str(payload["refresh_token"]),
            expires_in=int(payload["expires_in"]),
            scope=str(payload.get("scope") or ""),
            token_type=str(payload.get("token_type") or "bearer"),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise WhoopBadResponseError("whoop_token_response_invalid") from exc


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    *,
    access_token: str,
    params: dict[str, QueryParamValue] | None = None,
) -> dict[str, Any]:
    response = await _safe_get(client, path, access_token=access_token, params=params or {})
    payload = _json_object(response)
    return payload


async def _get_collection(
    client: httpx.AsyncClient,
    path: str,
    *,
    access_token: str,
    start: datetime,
    end: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    next_token: str | None = None
    for _ in range(20):
        params: dict[str, QueryParamValue] = {
            "limit": limit,
            "start": start.isoformat(),
            "end": end.isoformat(),
        }
        if next_token:
            params["nextToken"] = next_token
        payload = await _get_json(client, path, access_token=access_token, params=params)
        page_records = payload.get("records")
        if not isinstance(page_records, list):
            raise WhoopBadResponseError("whoop_collection_response_invalid")
        records.extend(record for record in page_records if isinstance(record, dict))
        token = payload.get("next_token") or payload.get("nextToken")
        if not token:
            break
        next_token = str(token)
    return records


async def _safe_get(
    client: httpx.AsyncClient,
    path: str,
    *,
    access_token: str,
    params: dict[str, QueryParamValue],
) -> httpx.Response:
    url = f"{WHOOP_API_BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    for attempt in range(2):
        try:
            response = await client.get(url, params=params, headers=headers)
        except httpx.HTTPError as exc:
            raise WhoopClientError("whoop_http_error") from exc
        if response.status_code in {502, 503, 504} and attempt == 0:
            continue
        _raise_for_status(response)
        return response
    raise WhoopServerError("whoop_server_error", status_code=503)


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code == 401:
        raise WhoopUnauthorizedError("whoop_unauthorized", status_code=401)
    if response.status_code == 429:
        raise WhoopRateLimitError("whoop_rate_limited", status_code=429)
    if response.status_code >= 500:
        raise WhoopServerError("whoop_server_error", status_code=response.status_code)
    if response.status_code >= 400:
        raise WhoopClientError("whoop_client_error", status_code=response.status_code)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise WhoopBadResponseError("whoop_json_invalid") from exc
    if not isinstance(payload, dict):
        raise WhoopBadResponseError("whoop_json_not_object")
    return payload
