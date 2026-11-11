# Security Posture

A localhost demonstration's security posture, stated exactly — including what is **not** covered.
Nothing here is a compliance claim or an audit result.

## Network exposure

- **Loopback by default.** The API binds `APP_HOST=127.0.0.1:8310`; the UI binds localhost:8501.
  Nothing is reachable from other machines unless you deliberately change the bind address or
  publish ports. The Dockerfile/compose keep host publication on `127.0.0.1` (`127.0.0.1:8310:8310`,
  `127.0.0.1:8501:8501`); *inside* the container the services bind `0.0.0.0` solely so the
  published loopback mapping works — reachability from outside the host is still governed by the
  published-port binding.
- **CORS** is a single configured origin (`APP_FRONTEND_ORIGIN`, default `http://127.0.0.1:8501`) —
  not `*`.
- No TLS is terminated by this app. If you expose it beyond loopback, put a reverse proxy in front;
  that proxy is then part of your threat model, not this tool.

## Endpoint allowlist (SSRF controls) and their documented limits

Model endpoints are user/administrator-supplied URLs. `app/security/validation.py` enforces:

- `http` / `https` schemes only;
- **exact-host match** against `ENDPOINT_ALLOWLIST` (env, comma-separated; default
  `127.0.0.1,localhost`) — the app refuses to contact any other host;
- no `user:pass` embedded in URLs — credentials travel in headers only;
- redirects are **not** followed by the HTTP client; `request_with_safe_redirects` re-validates
  every hop (up to 4) against the same allowlist before following.

**Known limits, by design** (also stated in the module docstring):

- **DNS rebinding is out of scope.** A hostname in the allowlist is resolved at request time; a
  DNS record that changes between validation and connection can point elsewhere. The allowlist is
  checked by name, not re-verified against the connected IP.
- **TOCTOU between resolution and connection** is likewise not defended.
- The match is exact-host: ports and paths are unconstrained; an allowlisted host serving an
  unexpected path is reachable.
- `https` certificate verification uses default `httpx`/system trust; there is no custom-CA
  configuration surface.

For a single-user localhost tool these are reasonable trade-offs; they are **not** hardening for a
multi-tenant deployment.

## Secret handling

- Secrets live in `.env` (never committed; `.env.example` is the template) and in model records.
- `app/security/secrets.py` masks values in every outward-facing representation:
  `ModelConfig.public_dict()` redacts API keys and secret-ish extra headers (`********`);
  `redact_mapping` masks `key/secret/token/password/authorization/credential` fields recursively;
  `redact_text` masks `Bearer …` tokens and `key=value` pairs in free text.
- **All error strings are redacted before storage or display** via `safe_error()` — the runner
  wraps every per-case exception in it, and the inference client uses it for `InferenceError`
  messages. Connection errors therefore cannot leak an Authorization header into the database,
  logs, or reports.
- The UI's API-key field is a password input; the API never echoes keys back unredacted.

## No telemetry

The application makes **no** outbound network requests except to user-registered inference
endpoints (allowlist-gated) and performs **no** analytics, phone-home, update checks, or crash
reporting. Logs go to stdout/stderr via `logging`; nothing is shipped anywhere. The only
version-control integration is reading the local `git rev-parse HEAD` for the reproducibility
block (absent outside a repo — recorded as None).

## Dependency and code auditing

- Runtime deps are pinned as minimums in `pyproject.toml` and kept minimal
  (fastapi, uvicorn, pydantic, sqlalchemy, httpx, streamlit, plotly, pandas, reportlab).
- CI (`.github/workflows/ci.yml`) runs on push/PR, needs no secrets:
  - `ruff check` + `ruff format --check` — lint;
  - `pytest` — unit tests, no network (live-endpoint test is env-gated);
  - `bandit -c pyproject.toml -r app` — static analysis (B608 skipped: SQL uses constant table
    names with bound parameters);
  - `pip-audit --strict` — **blocking** dependency-vulnerability gate. There is deliberately no
    `continue-on-error`: a known CVE in the dependency tree fails the build. Waivers are made by
    pinning a fixed version with the rationale in the commit message.
- The Docker image runs as a non-root user (`appuser`, uid 1000); no model weights or credentials
  are baked into the image.

## Incident / data posture

All state is a local SQLite file plus generated PDF/Markdown reports under `APP_DATA_DIR`. Delete
the directory and there is nothing left to leak — but also no backup: this tool has no backup
mechanism, by design and by admission.
