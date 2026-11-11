#!/usr/bin/env python3
"""Validate every dataset JSON file parses as a list of BenchmarkCase.

Exit code 1 if any file is invalid; per-file case counts otherwise.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.dataset_registry import DATASETS_DIR, list_datasets, load_dataset  # noqa: E402

logger = logging.getLogger("seed_datasets")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    metas = list_datasets()
    if not metas:
        print(f"no dataset files found in {DATASETS_DIR}")
        return 0

    failures: list[str] = []
    for meta in metas:
        try:
            cases = load_dataset(meta.name)
        except ValueError as exc:
            failures.append(f"{meta.name}: {exc}")
            print(f"INVALID  {meta.name}: {exc}")
            continue
        print(f"ok       {meta.name}: {len(cases)} cases, categories={meta.categories}")

    for name, message in failures:
        logger.error("dataset %s invalid: %s", name, message)
    print(f"{len(metas) - len(failures)}/{len(metas)} dataset files valid in {DATASETS_DIR}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
