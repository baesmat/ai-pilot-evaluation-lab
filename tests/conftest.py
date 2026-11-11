"""Shared fixtures: isolated sqlite engine, fake completions, sample cases.

Unit tests never touch the network: inference is faked at the
``InferenceClient.chat`` method boundary.
"""

from __future__ import annotations

import pytest

from app.models.benchmark import BenchmarkCase
from app.models.result import TokenUsage
from app.services.inference_client import CompletionResult
from app.storage.database import init_engine, reset_engine


@pytest.fixture()
def tmp_db(tmp_path):
    """Fresh sqlite engine per test; resets the process-wide engine."""
    reset_engine()
    init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    yield tmp_path
    reset_engine()


def make_completion(**overrides) -> CompletionResult:
    defaults = dict(
        content="answer",
        raw={"choices": []},
        latency_ms=12.5,
        time_to_first_token_ms=None,
        token_usage=TokenUsage(),
        model_reported="test-model",
        finish_reason="stop",
        request_attempt=1,
    )
    defaults.update(overrides)
    return CompletionResult(**defaults)


def make_case(**overrides) -> BenchmarkCase:
    defaults = dict(
        id="case-1",
        dataset="demo",
        category="general",
        prompt="Say answer.",
        evaluation_method="exact_match",
        expected_answer="answer",
    )
    defaults.update(overrides)
    return BenchmarkCase(**defaults)


@pytest.fixture()
def completion_factory():
    return make_completion


@pytest.fixture()
def case_factory():
    return make_case
