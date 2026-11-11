"""Dataset registry: discovery, validation and content hashing of benchmark datasets.

Datasets are ``*.json`` files inside :data:`DATASETS_DIR`. Each file holds a
JSON array of :class:`app.models.benchmark.BenchmarkCase` dicts. The SHA-256 of
the file bytes is the dataset version, so any edit produces a new version.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path

from app.models.benchmark import BenchmarkCase, DatasetMeta

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
#: Override with the ``DATASETS_DIR`` environment variable.
DATASETS_DIR = Path(os.getenv("DATASETS_DIR", str(_REPO_ROOT / "datasets"))).expanduser()


def _dataset_path(name: str) -> Path:
    if not name or not isinstance(name, str):
        raise ValueError("dataset name must be a non-empty string")
    if "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError(f"invalid dataset name: {name!r}")
    return DATASETS_DIR / f"{name}.json"


def _sha256_of_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_raw_cases(name: str) -> tuple[list, Path]:
    path = _dataset_path(name)
    if not path.is_file():
        raise ValueError(f"dataset '{name}' not found in {DATASETS_DIR}")
    try:
        data = json.loads(path.read_bytes())
    except json.JSONDecodeError as exc:
        raise ValueError(f"dataset '{name}' is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"dataset '{name}' must be a JSON array of case objects")
    return data, path


def list_datasets() -> list[DatasetMeta]:
    """Scan ``DATASETS_DIR`` for ``*.json`` datasets. Unreadable files are skipped."""
    if not DATASETS_DIR.is_dir():
        return []
    metas: list[DatasetMeta] = []
    for path in sorted(DATASETS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_bytes())
        except json.JSONDecodeError as exc:
            logger.warning("Skipping unreadable dataset %s: %s", path.name, exc)
            continue
        if not isinstance(data, list):
            logger.warning("Skipping %s: not a JSON array", path.name)
            continue
        categories = sorted(
            {str(c.get("category", "")) for c in data if isinstance(c, dict) and c.get("category")}
        )
        metas.append(
            DatasetMeta(
                name=path.stem,
                title=path.stem.replace("_", " ").replace("-", " ").title(),
                description="",
                case_count=len([c for c in data if isinstance(c, dict)]),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                categories=categories,
            )
        )
    return metas


def load_dataset(name: str) -> list[BenchmarkCase]:
    """Load and validate one dataset. Every case gets ``dataset=name``."""
    data, _path = _load_raw_cases(name)
    cases: list[BenchmarkCase] = []
    for index, entry in enumerate(data):
        try:
            case = BenchmarkCase.model_validate(entry)
        except Exception as exc:  # pydantic validation error -> clear message
            raise ValueError(f"dataset '{name}' entry {index}: invalid case: {exc}") from exc
        cases.append(case.model_copy(update={"dataset": name}))
    return cases


def dataset_version(name: str) -> str:
    """SHA-256 hexdigest of the dataset file bytes."""
    _data, path = _load_raw_cases(name)
    return _sha256_of_file(path)


def load_cases(dataset_names: list[str]) -> list[BenchmarkCase]:
    """Concatenate the cases of several datasets, in the given order."""
    cases: list[BenchmarkCase] = []
    for name in dataset_names:
        cases.extend(load_dataset(name))
    return cases
