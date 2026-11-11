# Development Progress Log

Working log, newest first. Statuses: **done** / **in progress** / **planned**.
This file is the honest state of the build — including what has *not* been verified.

## 2026-11-10 — integration, live validation, closure

- **done** — Quality gates on the assembled tree: `ruff check` clean, `pytest`
  110 passed / 1 skipped (env-gated live test), `bandit` 0 high/medium
  (10 informational lows: subprocess-for-git-rev, asserts), `pip-audit` no
  known vulnerabilities.
- **done** — Live E2E against GLM 5.3 (`GLM-5.3-Flash-EXL3` via
  `https://gb10.rebwar.com/v1`, allowlisted, CF Access headers via model
  `extra_headers`): registry add, real-inference health check (200, api
  compatible), full 85-case run `ba52522e5f4e` — **85/85 completed, 0 errors,
  weighted 0.9053**; per-dataset: extraction 0.952/0.976, operational 0.952/0.986,
  security 0.905, grounding 0.682/0.761; latency median 1331 ms / p95 4509 ms;
  tokens measured (8238 in / 2991 out); structured-output success 1.0; 0 timeouts.
- **fixed** — Scorer/dataset shape mismatches found by comparing recorded
  responses against expectations: security cases use `must_contain`/
  `must_not_contain` (evaluator now normalises both shapes; ambiguous still
  never counts as resisted); grounding answer match is verbatim-modulo-
  punctuation bidirectional containment (documented; NOT fuzzy token overlap —
  remaining non-matches are genuine phrasing deltas and stay partial credit).
  Earlier run's 0.00 security score was a harness defect, not a model result;
  superseded by `ba52522e5f4e`.
- **done** — Report generator covers all spec sections (evaluation scope, models,
  dataset description, methodology, recommendation + next steps, reproducibility,
  per-dataset, latency, tokens/cost, enterprise assessment, human review,
  security, grounding, risks/limitations, evidence); 8-page PDF verified by text
  extraction; estimates labelled, missing data renders "Not available".
- **done** — Persistence: API restarted; run `ba52522e5f4e` and all 85 case
  results intact from SQLite.
- **done** — Governance flow exercised via API: demonstration assessment
  (1 partially-meets with evidence, 1 not-evaluated) + demonstration human
  review; summary flags positive-without-evidence correctly. Records are
  labelled demonstration entries.
- **done** — Screenshots of all six UI sections captured from the running app
  (`screenshots/`), verified as real renders with live data.
- **done** — Evidence archived in-repo: `eval_results/run_ba52522e5f4e.json`
  (run metadata + per-case results) and `..._report.md`.
- **known issue (cosmetic)** — Dashboard metric labels ellipsize at narrow
  widths; latency p95 truncated in its card. No functional impact.
- **not done** — Docker build/run unvalidated (no daemon on build host); second
  model comparison not executed (only one endpoint configured; none fabricated);
  GitHub publication awaiting owner approval.

## 2026-11-10 — documentation & deployment pass

- **done** — Full documentation set: `README.md`, `docs/architecture.md`,
  `docs/evaluation_methodology.md`, `docs/security.md`, `docs/ai_governance.md`,
  `docs/enterprise_readiness.md`, `docs/executive_overview.md`, `docs/demo_script.md`,
  `docs/limitations.md`, this log.
- **done** — Deployment configs authored: `Dockerfile` (python:3.12-slim, non-root `appuser`,
  loopback-published ports via compose, healthchecks, no baked model weights),
  `docker-compose.yml` (api + streamlit services, named volume `eval-lab-data` at `/data`,
  `env_file .env`), `.dockerignore`.
- **done** — CI: `.github/workflows/ci.yml` — ruff lint + format check, pytest (offline; live
  endpoint test env-gated), bandit, and **blocking** `pip-audit --strict` (no
  `continue-on-error`; waivers happen by pinning + commit-message rationale). No repository
  secrets required.
- **note** — Docker **unvalidated**: the build host has no daemon; image/compose authored but
  never built or run. Recorded in README, Dockerfile header, and `docs/limitations.md`.
- **note** — Docs describe the system per the internal build contract; where a module was still
  landing while docs were written, docs follow the contract, not a snapshot of the tree.

## 2026-11-10 — foundation (pre-existing at docs pass)

- **done** — `app/models/*` — pydantic domain models: `ModelConfig` (endpoint validation,
  redacting `public_dict()`), `HealthCheckResult`, benchmark/result/governance models.
- **done** — `app/storage/*` — SQLAlchemy tables, repositories, engine init/reset.
- **done** — `app/security/` — `validation.py` (allowlist, safe redirects; documented limits:
  no DNS-rebinding/TOCTOU defence) and `secrets.py` (`mask`, `redact_mapping`, `redact_text`,
  `safe_error`).
- **done** — `app/config.py` — frozen env-driven `Settings`; `ENDPOINT_ALLOWLIST`, `LLM_*`
  bootstrap vars, data dir/ports/origins; `.env.example` documents every variable.
- **done** — Project scaffolding: `pyproject.toml` (py312, ruff line-100 config, bandit config
  w/ B608 skip rationale, pytest asyncio-mode), MIT `LICENSE`, `.gitignore`.

## In progress / planned (per build contract)

- **in progress** — `app/services/*`: dataset registry, inference client (allowlisted chat,
  health probe, retries), accuracy/grounding/security/performance evaluators, cost estimator,
  comparison engine, report generator (ReportLab), benchmark runner (threaded, cancellable,
  partial-result-preserving).
- **in progress** — `app/api/*` routers + `app/main.py` (lifespan, CORS, health/app-info,
  bootstrap-model seeding — record only, no network at seed).
- **planned** — `frontend/` Streamlit app (Dashboard, Registry, Runner, Results, Comparison,
  Enterprise Readiness; `BACKEND_URL`-driven; graceful backend-down handling).
- **planned** — `datasets/`: four synthetic JSON datasets, ≥80 cases (structured extraction,
  evidence grounding, operational reasoning, security behaviour) + `scripts/seed_datasets.py`
  validation.
- **planned** — `tests/`: offline unit suite (monkeypatched `InferenceClient.chat`), API tests
  via `TestClient`, env-gated live endpoint test; `scripts/run_evaluation.py`,
  `scripts/generate_demo_report.py`.
- **planned** — First real end-to-end run against a local inference server; result counts and
  quirks to be logged here.
