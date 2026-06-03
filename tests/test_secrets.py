import json

from strataone.secrets import resolve_bmc_credentials


def test_file_secret_provider_resolves_site_specific_bmc_credentials(tmp_path, monkeypatch) -> None:
    secret_file = tmp_path / "secrets.json"
    secret_file.write_text(
        json.dumps(
            {
                "default": {"username": "default-user", "password": "default-pass"},
                "sites": {"branch-001": {"username": "site-user", "password": "site-pass"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("STRATAONE_VAULT_PROVIDER", "file")
    monkeypatch.setenv("STRATAONE_VAULT_FILE", str(secret_file))

    secret = resolve_bmc_credentials("branch-001", {})

    assert secret.username == "site-user"
    assert secret.password == "site-pass"
