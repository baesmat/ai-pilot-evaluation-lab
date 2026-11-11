# 5-Minute Demo Script

One terminal, one browser window. Start both services before the audience arrives
(`uvicorn app.main:app --host 127.0.0.1 --port 8310`, then `streamlit run frontend/streamlit_app.py`).
Have a model registered and **one completed run** in the database so minute 3 always has data —
if the live run misbehaves, switch to the prepared one and keep talking.

Framing sentence to open with: *“This is an independent demonstration of disciplined evaluation —
every number you'll see is measured, estimated, or explicitly unavailable, and none of it approves
anything by itself.”*

| Minute | On screen | Say |
|---|---|---|
| **0–1** | Dashboard | “This is the whole system: a registry of candidate models, fixed question sets, deterministic scoring, and reports — all local, no telemetry. The metrics row is live from the API: registered models, completed runs, total benchmark cases.” Point at the recent-runs table: “Every run here is reproducible — dataset checksums, sampling settings, code commit.” |
| **1–2** | Model Registry | “Before anything is scored, the endpoint has to prove itself.” Click **Health check** on a registered model. Show the result: real round-trip latency, whether the API shape is well-formed, whether token usage is reported, streaming support. “Note the API key is masked everywhere — registry, logs, reports.” Mention the allowlist once: “The app only talks to hosts on a configured list — that's a deliberate SSRF control, with documented limits.” |
| **2–3** | Evaluation Runner | Select the model, tick two datasets (point at the case counts), open *advanced* to show temperature / max tokens / concurrency — “all recorded per run.” Click **Start**. While it runs: “Results persist per question the moment they're scored — cancel or crash and nothing is lost. Errors are captured per case, never silently dropped.” |
| **3–4** | Benchmark Results | Open the prepared run (or this one if finished). Expand one case: prompt, expected answer, actual output, per-field scores, latency. “Scoring is field-level — a JSON answer that's half right gets half credit, and an unparseable answer gets zero, not a guess.” Show the grounding block: “Abstention is graded — a correct ‘I can't answer that’ *earns points*; a fabricated citation loses them. Every rate shows its denominator.” Show a labelled estimate: “Costs always say ‘estimated’. Anything unknowable prints ‘Not available’ — never a made-up number.” |
| **4–5** | Model Comparison → report | Select two runs: “The warning box fires first — if these runs used different datasets or settings, the tool says so instead of ranking silently.” Then open the generated **PDF report**: provenance block, per-dataset bars, the readiness checklist with evidence gaps flagged. Close on governance: “Verdicts stop at ‘candidate for further evaluation’ or ‘insufficient data’. Adoption is a human, governed decision — this makes it an informed one.” |

## If things go wrong (30-second recoveries)

- **Backend down / UI warns**: restart the uvicorn terminal; the UI recovers on next interaction —
  say “by design, it warns instead of tracebacking.”
- **Live run stalls**: it's the demo, not the data — switch to the prepared run (`Benchmark Results`
→ run picker). Cancellation works mid-run and keeps partial results; that's itself a demo point.
- **Endpoint unreachable**: the health-check failure panel is the demo — redacted error, no secrets,
  honest `ok: false`.
- **Asked about compliance/certification**: “None claimed — deliberate. See `docs/ai_governance.md`;
  the tool records evidence, the institution decides.”

## Leave-behinds

`docs/executive_overview.md` (2 pages), a generated PDF report, and `docs/limitations.md` — hand
over the limitations doc unprompted; it is the credibility argument.
