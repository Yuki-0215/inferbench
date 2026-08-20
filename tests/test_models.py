import pytest
from pydantic import ValidationError

from inferbench.models import RunCreate


def test_endpoint_requires_absolute_http_url():
    with pytest.raises(ValidationError):
        RunCreate(endpoint="localhost:8000/v1/chat/completions")


def test_extra_body_cannot_override_protocol_fields():
    with pytest.raises(ValidationError):
        RunCreate(extra_body={"stream": False})


def test_models_endpoint_is_normalized_to_chat_completions():
    config = RunCreate(endpoint="https://example.com/v1/models")
    assert config.endpoint == "https://example.com/v1/chat/completions"
