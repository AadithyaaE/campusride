"""MongoDB connection strings are logged without their credentials (deployment safety)."""

from app.core.db import redact_uri


def test_atlas_credentials_are_hidden() -> None:
    uri = "mongodb+srv://campusride:S3cret%21pw@cluster0.abcd.mongodb.net/?retryWrites=true&w=majority"
    out = redact_uri(uri)
    assert "S3cret" not in out and "campusride:" not in out
    assert out == "mongodb+srv://***@cluster0.abcd.mongodb.net/?retryWrites=true&w=majority"


def test_uri_without_credentials_is_unchanged() -> None:
    assert redact_uri("mongodb://localhost:27017") == "mongodb://localhost:27017"
