"""Secret redaction for logs, reports and API responses."""

from __future__ import annotations

import re

SECRET_KEYS = ("key", "secret", "token", "password", "authorization", "credential")

_BEARER = re.compile(r"(bearer\s+)[\w.\-~_+=/%]{8,}", re.IGNORECASE)
_KV_SECRET = re.compile(
    r"(?P<prefix>(?:api[_-]?key|token|secret|password|authorization)\s*[=:]\s*)(?P<value>[^\s,;'\"]{4,})",
    re.IGNORECASE,
)


def mask(value: str | None, keep: int = 4) -> str:
    if not value:
        return ""
    return value[:keep] + "***" if len(value) > keep + 2 else "***"


def redact_mapping(data: dict, keys: tuple[str, ...] = SECRET_KEYS) -> dict:
    """Return a copy of ``data`` with secret-ish values masked."""
    out = {}
    for k, v in data.items():
        if isinstance(v, dict):
            out[k] = redact_mapping(v, keys)
        elif any(s in k.lower() for s in keys) and isinstance(v, str) and v:
            out[k] = v[:2] + "***" if len(v) > 4 else "***"
        else:
            out[k] = v
    return out


def redact_text(text: str) -> str:
    """Mask bearer tokens and key=value secrets embedded in free text."""
    text = _BEARER.sub(r"\1***", text)
    return _KV_SECRET.sub(lambda m: f"{m.group('prefix')}***", text)


def safe_error(exc: BaseException | str) -> str:
    """An error string safe for logs/reports: message only, secrets redacted."""
    msg = str(exc)
    return redact_text(msg)
