#!/usr/bin/env python3
"""Generate a PDF + markdown report for the most recent completed run (or --run-id).

Outputs are written to the configured reports directory (``APP_DATA_DIR``/reports).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.storage.database import init_engine  # noqa: E402
from app.storage.repositories import (  # noqa: E402
    AssessmentRepository,
    ReviewRepository,
    RunRepository,
)

logger = logging.getLogger("generate_demo_report")


def _pick_run(run_id: str | None) -> str:
    repo = RunRepository()
    if run_id:
        if repo.get(run_id) is None:
            raise SystemExit(f"run {run_id!r} not found")
        return run_id
    for run in repo.list(limit=200):
        if run.status == "completed":
            return run.id
    raise SystemExit("no completed runs found; run an evaluation first")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a demonstration report.")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from app.services.report_generator import generate_markdown, generate_report

    settings = get_settings()
    init_engine(settings.database_url)

    run_id = _pick_run(args.run_id)
    run_repo = RunRepository()
    run = run_repo.get(run_id)
    assert run is not None
    results = run_repo.case_results(run_id)
    assessment = AssessmentRepository().get(run.model_id)
    reviews = ReviewRepository().for_model(run.model_id)

    out_dir = Path(settings.reports_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = out_dir / f"report_{run_id}.pdf"
    md_path = out_dir / f"report_{run_id}.md"

    generated = generate_report(run, results, assessment, reviews, pdf_path)
    md_path.write_text(generate_markdown(run, results, assessment, reviews), encoding="utf-8")

    print(f"run:     {run_id} (model {run.model_id})")
    print(f"pdf:      {generated}")
    print(f"markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
