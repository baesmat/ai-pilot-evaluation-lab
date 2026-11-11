# AI Governance — Concepts Mapped to the AI Pilot Evaluation Lab

This document explains how widely used AI-risk-management **concepts** (after the NIST
AI Risk Management Framework: Govern, Map, Measure, Manage) relate to what this tool does.
It is a **conceptual orientation, not a certification, attestation, or compliance claim.** This
project is an independent demonstration and is aligned with no formal programme; using it does not
make anything NIST-conformant, audited, or approved.

## Govern — who decides, and on what record

- The tool's role is deliberately narrow: produce evidence and **advisory** outcomes. All four
  report verdicts — *Candidate for Further Evaluation*, *Additional Testing*, *Not Recommended*,
  *Insufficient Data* — route to humans. There is **no “production approved” state anywhere in the
  system**: approval is an institutional act outside the tool.
- Governance artefacts are first-class data: enterprise-readiness checklists per model
  (category / item / status / rationale / evidence) and human review records. Positive statuses
  **without recorded rationale or evidence are flagged** (`positive_without_evidence`) in completion
  summaries — the tool makes evidence gaps visible instead of letting a green checkbox stand alone.
- Every run is traceable: app version, git commit, scoring version, dataset sha256s, generation
  params, timestamps. The audit trail answers “which scores, from which inputs, under which
  configuration” — the precondition for any later governance review.

## Map — what is being evaluated, and context

- The model registry records hosting type, context window, declared capabilities, and costs —
  the deployment-context fields a mapping exercise needs, kept beside the results.
- Dataset registry with content-hashed versions makes the *measurement instrument* itself
  traceable: two evaluations are comparable only when dataset versions, scoring version, and
  generation params match, and the comparison engine says so explicitly.

## Measure — how evidence is produced

- Deterministic, version-pinned scoring (`SCORING_VERSION`) across declared methods; field-level
  credit; denominators always published for grounding rates; ambiguous security verdicts never
  counted as successes.
- Honest labelling as a measurement discipline: measured vs estimated vs unavailable is carried
  through every metric, cost, and report. A number that cannot be known is shown as
  “Not available”, never fabricated — including token counts and costs.
- Known measurement limits (small synthetic *n*, single-run variance, author bias) are documented
  in `evaluation_methodology.md` and `limitations.md` rather than smoothed over.

## Manage — acting on the evidence

- Comparison outputs begin with **eligibility warnings** (differing datasets, versions, params,
  case counts) — the tool refuses to present an apples-to-oranges ranking silently.
- Cancellation, per-case error capture, and partial-result preservation mean a failed or stopped
  evaluation still yields its evidence; nothing is silently dropped.
- Human review is a stored, citable layer. The machine score is input to judgement, explicitly not
  the judgement itself.

## What this is not

- Not a NIST AI RMF implementation, profile, or assessment; it borrows vocabulary and structure.
- Not a regulatory, HIPAA, or security-compliance instrument of any kind.
- Not a substitute for institutional review, procurement, or approval processes — benchmark
  results **support decisions; they never replace institutional governance.**

## Suggested usage discipline

1. Register the deployment context honestly (hosting, limits, costs) before evaluating.
2. Run evaluations; keep the reproducibility block with any exported number.
3. Record human review with rationale — positive claims without evidence get flagged.
4. Treat reports as advisory inputs to a documented human decision. The decision and its record
   live in your governance process, not in this tool.
