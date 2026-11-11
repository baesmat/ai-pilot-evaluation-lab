"""Endpoint validation - SSRF safeguards for user-configured inference URLs.

The application contacts administrator-configured endpoints only. These
helpers enforce:

- http/https schemes only
- explicit host allowlist (env ``ENDPOINT_ALLOWLIST``)
- no credentials embedded in URLs (credentials travel in headers)
- redirect targets re-validated against the same allowlist

Limitations (documented in docs/security.md): DNS rebinding and IP-literal
spoofing between resolution and connection are out of scope for this
demonstration; the allowlist is exact-host match.
"""

from __future__ import annotations

from urllib.parse import urlparse

import httpx

DEFAULT_ALLOWLIST = ["127.0.0.1", "localhost"]


class EndpointValidationError(ValueError):
    """Raised when an endpoint configuration is not acceptable."""


def validate_endpoint(url: str, allowlist: list[str] | None = None) -> str:
    """Normalise and validate an endpoint URL. Returns the normalised URL."""
    if not url or not isinstance(url, str):
        raise EndpointValidationError("endpoint URL is required")
    parsed = urlparse(url if "//" in url else f"//{url}", scheme="http")

    if parsed.scheme not in ("http", "https"):
        raise EndpointValidationError(f"unsupported URL scheme: {parsed.scheme!r} (use http/https)")
    if not parsed.hostname:
        raise EndpointValidationError("endpoint URL has no host")
    if parsed.username or parsed.password:
        raise EndpointValidationError("credentials in URLs are not supported; use headers")

    hosts = allowlist if allowlist is not None else DEFAULT_ALLOWLIST
    host = parsed.hostname.lower()
    if host not in {h.lower() for h in hosts}:
        raise EndpointValidationError(
            f"host {host!r} is not in the endpoint allowlist {sorted(hosts)}"
        )
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


def validate_redirect(url: str, allowlist: list[str] | None = None) -> str:
    """Validate a redirect target before following it."""
    return validate_endpoint(url, allowlist)


def request_with_safe_redirects(
    client: httpx.Client, method: str, url: str, allowlist: list[str], **kwargs
) -> httpx.Response:
    """Perform a request following redirects manually with allowlist checks."""
    current = validate_endpoint(url, allowlist)
    for _ in range(4):
        resp = client.request(method, current, follow_redirects=False, **kwargs)
        if resp.has_redirect_location:
            loc = resp.headers.get("location", "")
            if not loc:
                return resp
            current = validate_redirect(_absolute(loc, str(resp.request.url)), allowlist)
            continue
        return resp
    return resp


def _absolute(location: str, base: str) -> str:
    import urllib.parse

    return urllib.parse.urljoin(base, location)
