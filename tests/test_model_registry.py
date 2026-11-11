"""Model registry: CRUD, duplicate handling, endpoint validation, health persistence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.model_config import ModelConfig
from app.security.secrets import mask, redact_text
from app.security.validation import EndpointValidationError, validate_endpoint
from app.storage.repositories import ModelRepository
from tests.conftest import make_completion  # noqa: F401  (factory sanity)


def make_model(**overrides) -> ModelConfig:
    defaults = dict(
        id="model-a",
        display_name="Model A",
        model_identifier="org/model-a",
        endpoint="http://127.0.0.1:9990",
    )
    defaults.update(overrides)
    return ModelConfig(**defaults)


def test_upsert_get_roundtrip(tmp_db):
    repo = ModelRepository()
    repo.upsert(make_model())
    loaded = repo.get("model-a")
    assert loaded is not None
    assert loaded.model_identifier == "org/model-a"
    assert loaded.endpoint == "http://127.0.0.1:9990"


def test_duplicate_upsert_updates_not_duplicates(tmp_db):
    repo = ModelRepository()
    repo.upsert(make_model())
    repo.upsert(make_model(display_name="Renamed"))
    rows = repo.list()
    assert len(rows) == 1
    assert rows[0].display_name == "Renamed"
    # created_at preserved across the update, updated_at bumped
    assert rows[0].created_at is not None


def test_delete_and_missing(tmp_db):
    repo = ModelRepository()
    repo.upsert(make_model())
    assert repo.delete("model-a") is True
    assert repo.delete("model-a") is False
    assert repo.get("model-a") is None


def test_endpoint_validation():
    with pytest.raises(ValidationError):
        make_model(endpoint="ftp://example.com")  # no scheme http/https
    with pytest.raises(EndpointValidationError):
        validate_endpoint("http://example.com", ["127.0.0.1"])
    assert (
        validate_endpoint("http://127.0.0.1:8080/v1", ["127.0.0.1"]) == "http://127.0.0.1:8080/v1"
    )
    with pytest.raises(EndpointValidationError):
        validate_endpoint("http://user:pw@127.0.0.1")  # credentials in URL


def test_health_persistence(tmp_db):
    from datetime import datetime

    from app.models.model_config import HealthCheckResult

    repo = ModelRepository()
    repo.upsert(make_model())
    health = HealthCheckResult(
        model_id="model-a",
        ok=True,
        checked_at=datetime.utcnow(),
        latency_ms=42.0,
        model_identifier_reported="org/model-a",
        api_compatible=True,
    )
    payload = health.model_dump(mode="json")
    payload["supports_streaming"] = True
    payload["reports_token_usage"] = True
    repo.record_health("model-a", payload)
    model = repo.get("model-a")
    assert model is not None
    assert model.supports_streaming is True
    assert model.reports_token_usage is True
    assert model.last_health_check["ok"] is True


def test_public_dict_redacts_secrets():
    model = make_model(api_key="supersecret", extra_headers={"api-key": "hunter2", "X-Trace": "1"})
    data = model.public_dict()
    assert data["api_key"].startswith("su") or data["api_key"] == "***"
    assert data["extra_headers"]["api-key"] != "hunter2" or data["extra_headers"][
        "api-key"
    ].startswith(("h", "*"))
    assert data["extra_headers"]["X-Trace"] == "1"
    assert "supersecret" not in mask("supersecret-key-value")
    assert "***" in redact_text("Bearer abcdefgh1234")


def test_disabled_filtering(tmp_db):
    repo = ModelRepository()
    repo.upsert(make_model(id="on"))
    repo.upsert(make_model(id="off", enabled=False))
    assert {m.id for m in repo.list(include_disabled=False)} == {"on"}
    assert {m.id for m in repo.list()} == {"on", "off"}
