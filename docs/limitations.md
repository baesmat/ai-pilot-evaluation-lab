# Known Limitations

Stated plainly, because a demo that hides its weaknesses is asking to be trusted too much.

## Deployment & environment

- **Docker is untested on the build host.** The `Dockerfile` and `docker-compose.yml` were authored
  against the spec, but the machine they were written on has **no Docker daemon** — neither image
  has been built nor either container run. The compose path is **provided-but-unvalidated**; the
  documented venv quickstart (`uvicorn app.main:app` + `streamlit run`) is the path that reflects
  reality. Expect first-contact friction (path, permission, or healthcheck details) on the first
  real `docker compose up`.
- Single-user, single-host posture. No authentication on the API or UI: anyone who can reach the
  ports can use them. Fine for loopback; if you bind beyond localhost, add a proxy with auth —
  and treat that as new, untested surface.
- SQLite only. Adequate for one evaluator; not a concurrent-multi-user store.
- No backup mechanism. `APP_DATA_DIR` is the whole world; copy it yourself.

## Measurement validity

- **Small synthetic datasets (≥80 cases total, tens per category).** Percentages move several
  points when a handful of cases flip. No confidence intervals are claimed — at this *n*, none
  would be honest. Differences under ~10 points between models are noise until re-run.
- **Single-run variance is not aggregated.** The tool runs each configuration once by default;
  latency, token counts, and error mixes vary run-to-run with load and provider conditions.
  Consequential comparisons need re-runs, inspected per-case.
- **Author bias.** The same people wrote the datasets, the expected answers, and the scorers.
  Canonical answer formats favour models that happen to phrase things that way; grounding contexts
  are marker-formatted, which favours regex-anticipated citation styles. Results measure these
  fixtures, not your documents or workload.
- **Ambiguous security verdicts.** The security evaluator returns `ambiguous` (0.5) whenever task
  markers are partially present or the response is unparseable-but-nonempty. Ambiguous is never
  counted as resisted — but it is also *not resolved*: a run dominated by `ambiguous` security
  results tells you the check failed to discriminate, not that the model is fine. Read the
  per-case records, and expect to add explicit markers to the case definitions.
- **Rubric under-crediting by design.** Criteria without machine-checkable `check` configs score
  zero with a “requires human review” note until reviewed. Conservative, but it depresses rubric
  scores relative to a human-graded run.
- **Latency excludes failures.** Percentiles cover successful cases only; a model that times out
  30% of the time looks faster than its users will experience. `timeout_count` is reported — look
  at it.

## Numbers and labelling

- **Every cost is an estimate** and labelled as such: hosted figures come from declared per-million
  prices in the registry; local-infrastructure cost exists only if hardware/power/utilisation
  fields were provided. Missing inputs → `unavailable` with the missing field named — never zero,
  never invented. Treat all of it as arithmetic sanity checks, not quotes.
- **Token counts** are `measured` only when the provider reports usage; otherwise `estimated` or
  `unavailable`, mixed sources flagged. The tool does not infer tokens from text length.
- **`git_commit` is `None` outside a repository** — reports show it as absent rather than
  fabricating a revision.

## Comparisons

- Comparison eligibility warnings fire on differing dataset versions, scoring versions, generation
  params, concurrency, hosting type, and >10% case-count gaps — but the comparison still renders.
  The warning is the safety mechanism, not a block: read it.
- Weighted scores depend on declared case weights; weight choices are judgement calls recorded in
  the datasets, not validated psychometrics.

## Process

- The readiness checklist records assertions; **positive items without rationale/evidence are
  flagged, not accepted** — but nothing prevents anyone from entering them.
- No import/migration of results between database instances; the SQLite file is the artefact.
- Live-endpoint integration tests exist but are env-gated and skipped unless
  `AILIVE_TEST=1` (+ `AILIVE_BASE_URL`/`AILIVE_MODEL`) — CI runs unit tests only, so provider
  regressions surface in manual runs, not the pipeline.
