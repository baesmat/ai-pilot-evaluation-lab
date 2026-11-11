# Executive Overview — AI Pilot Evaluation Lab

*Independent technology demonstration. Not affiliated with any institution. All outcomes are
advisory inputs to human decisions — this tool does not approve, certify, or replace governance.*

## The problem

When an organisation considers deploying an LLM, the decision needs evidence: how accurately does
the model extract the fields we care about, does it ground answers in the material it is given,
does it behave sensibly when a prompt contains embedded instructions, and what does it cost and how
fast is it? Answering this by improvising prompts in a chat window produces impressions, not
comparable records — and impressions do not survive contact with a procurement conversation.

## What this tool is

A self-contained evaluation lab, run on one machine, that turns a model pilot into a repeatable
measurement exercise:

1. **Register** candidate models — local (e.g. a llama.cpp-style server) or hosted APIs — with
   health checks that verify real compatibility before anything is trusted.
2. **Evaluate** against fixed question sets (four synthetic datasets, 80+ cases) spanning
   structured extraction, grounded answering and abstention, procedural instruction-following, and
   prompt-injection resistance. Scoring is deterministic, per-answer-part, and version-pinned.
3. **Compare** runs side by side — with explicit warnings whenever the comparison would otherwise
   be unfair (different question sets, settings, or case counts).
4. **Report**: a PDF (or Markdown) document with per-dataset results, latency, error rates,
   labelled cost *estimates*, the recorded readiness checklist, and a full provenance block
   (software version, code commit, dataset checksums, sampling settings, timestamps).

Everything is stored locally in one SQLite file; nothing leaves the machine except requests to the
endpoints you configure.

## What it deliberately does *not* do

- **No approval workflow.** Verdicts stop at *Candidate for Further Evaluation / Additional
  Testing / Not Recommended / Insufficient Data*. The decision — and the record of it — belongs to
  your governance process.
- **No compliance or certification claims.** No regulatory, security, or privacy attestation is
  implied by any score or report.
- **No invented numbers.** Token counts are labelled measured, estimated, or unavailable; costs
  are always estimates; missing data prints as “Not available”.
- **No telemetry and no network beyond your endpoints** (host-restricted by an allowlist).

## How to read the results

- Scores come from small synthetic question sets. Treat differences of a few percentage points as
  noise; re-run consequential comparisons and inspect per-answer records, not just totals.
- Latency figures reflect the measured window and load, not a capacity guarantee.
- Cost figures are arithmetic from declared prices — a sanity check, not a quote.
- Where the machine cannot judge (open-ended rubric items), the result says “requires human
  review” and contributes nothing until a person does.

## Who does what

| Role | Uses |
|---|---|
| Evaluator / engineer | Registry, runner, per-case results, comparison warnings |
| Reviewer / decision-maker | PDF reports, readiness checklist gaps, human-review records |
| Security-minded reader | `docs/security.md` — controls **and their documented limits** |

## Bottom line

The lab's value is disciplined evidence: the same questions, the same scoring, the same recorded
conditions, every time — with honest labelling of what is measured, what is estimated, and what is
unknown. It makes the pilot comparable and the trade-offs visible. Adopting a model remains a
human, governed decision that this tool informs but does not make.

*Further reading: `docs/evaluation_methodology.md` (methods and limits), `docs/architecture.md`
(system design), `docs/ai_governance.md` (decision-record discipline), `docs/limitations.md`
(known weaknesses, stated plainly).*
