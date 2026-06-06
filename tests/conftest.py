import pytest
import httpx
import os


@pytest.fixture(autouse=True)
def default_authenticated_test_client(monkeypatch):
    monkeypatch.setenv("STRATAONE_AUTH_ENABLED", "true")
    monkeypatch.setenv("STRATAONE_BOOTSTRAP_TOKEN", "test-bootstrap")

    original_request = httpx.Client.request

    def request_with_default_auth(self, method, url, *args, **kwargs):
        headers = dict(kwargs.pop("headers", {}) or {})
        if os.getenv("STRATAONE_TEST_DEFAULT_AUTH", "true").lower() in {"1", "true", "yes", "on"}:
            headers.setdefault("Authorization", "Bearer test-bootstrap")
        kwargs["headers"] = headers
        return original_request(self, method, url, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "request", request_with_default_auth)
