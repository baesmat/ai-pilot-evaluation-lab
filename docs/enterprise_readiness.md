# Enterprise Readiness Assessment

The lab includes a structured readiness checklist **per model**, stored in the same database as
the benchmark evidence. Its purpose is to force explicit, evidenced answers to adoption questions —
and to make gaps visible. It is a demonstration of record-keeping discipline, **not** a certification
checklist, and completion of it does not approve anything for production.

## Categories and items

Each item is recorded as `{category, item, status, rationale, evidence}`. Statuses follow a simple
scale (e.g. `not_started / in_progress / satisfied / not_applicable / blocker` — the UI presents the
allowed set; the API accepts the recorded values). The default status is **not** positive: items
start unassessed.

| Category | Example items (illustrative, configured in `app/models/governance.py`) |
|---|---|
| Technical integration | API stability, authentication method, timeout/retry behaviour, context-window fit |
| Performance & capacity | Latency targets, throughput under expected load, concurrency limits |
| Cost | Metered pricing confirmed, budget owner identified, estimate vs actual tracking |
| Data & privacy | Data-flow diagram exists, retention understood, **organisational policy review status** (recorded, not assumed) |
| Security | Endpoint exposure, secret handling, dependency posture — evidence links, not assertions |
| Vendor & support | SLA, escalation path, exit plan / model portability |
| Observability | Logging availability, error-rate visibility, drift monitoring plan |
| Legal & governance | Intended-use statement, human-oversight plan, review owner sign-off **tracked as pending until a human records it** |

The concrete item list is data, not code-locked: extend it to your organisation's review template.

## How completion is scored

- `GET /api/assessments/{model_id}/summary` returns counts by status, plus **`positive_without_evidence`**:
  items marked satisfied whose `rationale`/`evidence` fields are empty. These are flagged, not
  accepted — a positive claim without recorded evidence is treated as an open item.
- `not_applicable` items are excluded from completion denominators and should carry a rationale
  saying why.
- `blocker` items surface prominently; they do not gate anything automatically — a human decides.

## Relationship to benchmark results

Reports (PDF/Markdown) include the readiness assessment beside the benchmark evidence. The
recommendation engine is conservative and cross-references both: e.g. strong scores with an
**incomplete assessment** yield *Candidate for Further Evaluation* at best — never a stronger
verdict than the evidence record supports. All outcomes remain advisory.

## Operating discipline

1. Fill items with rationale + evidence links as they are verified, not aspirationally.
2. Revisit the assessment when the model endpoint, version, or deployment context changes; the
   assessment is versioned only by its `updated_at` — re-check after changes.
3. Treat the summary counts as a gap list for a human reviewer, the same way benchmark scores are
   inputs and not verdicts.

## Explicit non-claims

This checklist does not certify, approve, or declare compliance with any standard or regulation.
It records what your reviewers asserted, when, and on what evidence — the rest is your
governance process.
