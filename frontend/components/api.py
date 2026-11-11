"""Shared HTTP helpers for the Streamlit frontend.

All data reaches the UI through these helpers so backend-down conditions
surface as friendly warnings instead of tracebacks.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8310")
TIMEOUT_S = 30.0


class BackendError(Exception):
    """Raised when the backend API cannot be reached or returns an error."""


def _request(method: str, path: str, **kwargs: Any) -> Any:
    url = f"{BACKEND_URL}{path}"
    try:
        resp = httpx.request(method, url, timeout=TIMEOUT_S, **kwargs)
    except httpx.HTTPError as exc:  # connect / timeout / protocol errors
        raise BackendError(f"Cannot reach backend at {BACKEND_URL} ({exc.__class__.__name__})") from exc
    if resp.status_code >= 400:
        detail = _extract_detail(resp)
        raise BackendError(f"Backend returned {resp.status_code} for {method} {path}: {detail}")
    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


def _extract_detail(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return resp.text[:200]
    if isinstance(data, dict) and "detail" in data:
        return str(data["detail"])[:200]
    return str(data)[:200]


def api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    return _request("GET", path, params=params)


def api_post(path: str, json: Any = None, params: dict[str, Any] | None = None) -> Any:
    return _request("POST", path, json=json, params=params)


def api_put(path: str, json: Any = None) -> Any:
    return _request("PUT", path, json=json)


def api_delete(path: str) -> Any:
    return _request("DELETE", path)


def guard(render: Any) -> None:
    """Run a page render callable, converting BackendError into a warning."""
    try:
        render()
    except BackendError as exc:
        st.warning(f"Backend unavailable — start the API service and retry. ({exc})")
    except Exception as exc:  # noqa: BLE001 - keep the UI alive on any page error
        st.error(f"Something went wrong rendering this page: {exc}")


def backend_ok() -> bool:
    """Cheap health probe used to show a status chip in the sidebar."""
    try:
        api_get("/api/health")
    except BackendError:
        return False
    return True
