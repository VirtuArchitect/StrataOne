import pytest


@pytest.fixture(autouse=True)
def default_local_test_auth(monkeypatch):
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "false")

