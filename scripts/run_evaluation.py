#!/usr/bin/env python3
"""Run a benchmark evaluation synchronously from the CLI.

Usage:
    python scripts/run_evaluation.py --model-id my-model --datasets ds_a,ds_b \
        [--concurrency 2] [--limit 10] [--json-out results.json]

No endpoints are hardcoded; configuration comes from the environment
(``app.config.get_settings``).
"""

from __future__ import annotations

import argparse
import inspect
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.storage.database import init_engine  # noqa: E402
from app.storage.repositories import ModelRepository, RunRepository  # noqa: E402

logger = logging.getLogger("run_evaluation")


def _run_sync_filtered(runner, kwargs: dict) -> str:
    """Call ``runner.run_sync`` with the subset of kwargs its signature accepts."""
    accepted = set(inspect.signature(runner.run_sync).parameters)
    if not {"model_id", "dataset_names"} <= accepted:
        raise RuntimeError(
            "BenchmarkRunner.run_sync signature does not accept model_id/dataset_names"
        )
    dropped = set(kwargs) - accepted
    if dropped:
        logger.warning("run_sync ignores unsupported options: %s", sorted(dropped))
    return runner.run_sync(**{k: v for k, v in kwargs.items() if k in accepted})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a benchmark evaluation.")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--datasets", required=True, help="comma-separated dataset names")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="cap on number of cases")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument(
        "--generation-params", default=None, help="JSON object of generation parameters"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from app.services.benchmark_runner import BenchmarkRunner

    settings = get_settings()
    init_engine(settings.database_url)

    generation_params = None
    if args.generation_params:
        try:
            parsed = json.loads(args.generation_params)
        except json.JSONDecodeError as exc:
            parser.error(f"--generation-params is not valid JSON: {exc}")
        if not isinstance(parsed, dict):
            parser.error("--generation-params must be a JSON object")
        generation_params = parsed

    dataset_names = [d.strip() for d in args.datasets.split(",") if d.strip()]
    if not dataset_names:
        parser.error("--datasets must name at least one dataset")

    runner = BenchmarkRunner(ModelRepository(), RunRepository(), settings)
    try:
        run_id = _run_sync_filtered(
            runner,
            {
                "model_id": args.model_id,
                "dataset_names": dataset_names,
                "concurrency": max(1, args.concurrency),
                "generation_params": generation_params,
                "seed": args.seed,
                "limit": args.limit,
            },
        )
    except ValueError as exc:
        logger.error("evaluation refused: %s", exc)
        return 2

    repo = RunRepository()
    run = repo.get(run_id)
    results = [r.model_dump(mode="json") for r in repo.case_results(run_id)]
    payload = {
        "run": run.model_dump(mode="json") if run else {"id": run_id, "missing": True},
        "results": results,
    }
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2))
        logger.info("full results written to %s", args.json_out)

    if run is None:
        print(json.dumps({"run_id": run_id, "error": "run record missing"}))
        return 1

    summary = run.summary.model_dump() if run.summary else None
    print(json.dumps({"run_id": run_id, "summary": summary}))
    return 0 if run.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
