import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import requests


@dataclass(frozen=True)
class BmcSecret:
    username: str
    password: str


class SecretProvider(Protocol):
    def bmc_credentials(self, site_name: str) -> BmcSecret | None:
        ...


class EnvSecretProvider:
    def bmc_credentials(self, site_name: str) -> BmcSecret | None:
        username = os.getenv(f"STRATAONE_BMC_USERNAME_{_env_key(site_name)}") or os.getenv("STRATAONE_BMC_USERNAME")
        password = os.getenv(f"STRATAONE_BMC_PASSWORD_{_env_key(site_name)}") or os.getenv("STRATAONE_BMC_PASSWORD")
        if username and password:
            return BmcSecret(username=username, password=password)
        return None


class FileSecretProvider:
    def __init__(self, path: Path) -> None:
        self.path = path

    def bmc_credentials(self, site_name: str) -> BmcSecret | None:
        payload = self._payload()
        secret = payload.get("sites", {}).get(site_name) or payload.get("default")
        return _secret_from_payload(secret)

    def _payload(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if isinstance(payload, dict) else {}


class HashicorpVaultSecretProvider:
    def __init__(self) -> None:
        self.addr = os.getenv("STRATAONE_VAULT_ADDR", "").rstrip("/")
        self.token = os.getenv("STRATAONE_VAULT_TOKEN", "")
        self.path = os.getenv("STRATAONE_VAULT_PATH", "secret/data/strataone")

    def bmc_credentials(self, site_name: str) -> BmcSecret | None:
        if not self.addr or not self.token:
            return None
        response = requests.get(
            f"{self.addr}/v1/{self.path}",
            headers={"X-Vault-Token": self.token},
            timeout=float(os.getenv("STRATAONE_VAULT_TIMEOUT", "5")),
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {}).get("data", payload.get("data", {}))
        secret = data.get("sites", {}).get(site_name) or data.get("default")
        return _secret_from_payload(secret)


def get_secret_provider() -> SecretProvider:
    provider = os.getenv("STRATAONE_VAULT_PROVIDER", "env").lower()
    if provider == "file":
        return FileSecretProvider(Path(os.getenv("STRATAONE_VAULT_FILE", ".strataone/secrets.json")))
    if provider in {"hashicorp", "vault", "hashicorp-vault"}:
        return HashicorpVaultSecretProvider()
    return EnvSecretProvider()


def resolve_bmc_credentials(site_name: str, params: dict[str, Any]) -> BmcSecret | None:
    username = params.get("username")
    password = params.get("password")
    if username and password:
        return BmcSecret(username=str(username), password=str(password))
    return get_secret_provider().bmc_credentials(site_name)


def resolve_bmc_credentials_from_ref(secret: Any) -> BmcSecret | None:
    if secret is None:
        return None
    payload = secret.model_dump(mode="json") if hasattr(secret, "model_dump") else dict(secret)
    metadata = payload.get("metadata") or {}
    provider = payload.get("provider")
    reference = str(payload.get("reference") or "")
    if provider == "env":
        username_env = metadata.get("username_env")
        password_env = metadata.get("password_env")
        if not username_env and ":" in reference:
            username_env, password_env = reference.split(":", 1)
        elif not username_env:
            username_env = f"{reference}_USERNAME"
            password_env = f"{reference}_PASSWORD"
        username = os.getenv(str(username_env))
        password = os.getenv(str(password_env))
        if username and password:
            return BmcSecret(username=username, password=password)
    if provider == "file":
        file_path = Path(metadata.get("file") or os.getenv("STRATAONE_VAULT_FILE", ".strataone/secrets.json"))
        payload = FileSecretProvider(file_path)._payload()
        return _secret_from_payload(payload.get(reference) or payload.get("refs", {}).get(reference))
    return None


def _secret_from_payload(secret: Any) -> BmcSecret | None:
    if not isinstance(secret, dict):
        return None
    username = secret.get("username")
    password = secret.get("password")
    if username and password:
        return BmcSecret(username=str(username), password=str(password))
    return None


def _env_key(site_name: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in site_name).upper()
