import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from fastapi import Header, HTTPException, status

from strataone.store import StrataStore


ALL_PERMISSIONS = {
    "read-sites",
    "create-sites",
    "update-sites",
    "delete-sites",
    "read-jobs",
    "run-validate",
    "run-plan",
    "run-inventory",
    "run-preflight",
    "generate-artifacts",
    "mount-iso",
    "read-providers",
    "manage-providers",
    "read-settings",
    "manage-settings",
    "manage-access",
    "read-inventory",
    "write-inventory",
    "read-audit",
    "export-reports",
    "worker-execute",
}


@dataclass(frozen=True)
class AuthContext:
    username: str
    roles: list[str]
    permissions: set[str]


def auth_enabled() -> bool:
    return os.getenv("STRATAONE_AUTH_ENABLED", os.getenv("STRATAONE_AUTH_REQUIRED", "false")).lower() in {"1", "true", "yes", "on"}


def cors_origins() -> list[str]:
    configured = os.getenv("STRATAONE_CORS_ORIGINS", "http://localhost:8088,http://127.0.0.1:8088")
    origins = [origin.strip() for origin in configured.split(",") if origin.strip()]
    if auth_enabled() and "*" in origins:
        raise RuntimeError("STRATAONE_CORS_ORIGINS cannot include '*' when STRATAONE_AUTH_ENABLED=true")
    return origins


def require_permission(permission: str, store: StrataStore) -> Callable[[str | None], AuthContext]:
    def dependency(authorization: str | None = Header(default=None)) -> AuthContext:
        context = authenticate(authorization, store)
        if "*" in context.permissions or permission in context.permissions:
            return context
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"permission required: {permission}")

    return dependency


def authenticate(authorization: str | None, store: StrataStore) -> AuthContext:
    if not auth_enabled():
        return AuthContext(username="local-dev", roles=["Platform Admin"], permissions={"*"})
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bearer token required")
    bootstrap = os.getenv("STRATAONE_BOOTSTRAP_TOKEN", "")
    if bootstrap and token == bootstrap:
        return AuthContext(username="bootstrap", roles=["Platform Admin"], permissions={"*"})
    token_map = _configured_tokens()
    subject = token_map.get(token)
    if subject is not None:
        username, roles = subject
        permissions = _permissions_for_roles(roles, store)
        return AuthContext(username=username, roles=roles, permissions=permissions)
    session_user = store.get_session_user(token_hash(token), datetime.now(UTC).isoformat())
    if session_user is None or session_user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")
    username, roles = session_user.username, session_user.roles
    permissions = _permissions_for_roles(roles, store)
    return AuthContext(username=username, roles=roles, permissions=permissions)


def create_password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    iterations = 210_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$".join(
        [
            "pbkdf2_sha256",
            str(iterations),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str | None) -> bool:
    if not stored_hash:
        return False
    try:
        algorithm, iterations_text, salt_text, digest_text = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations_text))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expiry(minutes: int | None = None) -> str:
    ttl = minutes or int(os.getenv("STRATAONE_SESSION_TIMEOUT_MINUTES", "60"))
    return (datetime.now(UTC) + timedelta(minutes=ttl)).isoformat()


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


def _configured_tokens() -> dict[str, tuple[str, list[str]]]:
    mapping: dict[str, tuple[str, list[str]]] = {}
    configured = os.getenv("STRATAONE_API_TOKENS", "")
    for entry in configured.split(";"):
        if not entry.strip() or "=" not in entry:
            continue
        token, subject = entry.split("=", 1)
        username, _, roles_text = subject.partition(":")
        roles = [role.strip() for role in roles_text.split(",") if role.strip()]
        mapping[token.strip()] = (username.strip() or "api-token", roles)
    return mapping


def _permissions_for_roles(roles: list[str], store: StrataStore) -> set[str]:
    permissions: set[str] = set()
    for role_name in roles:
        role = store.get_role(role_name)
        if role is None:
            continue
        permissions.update(role.permissions)
    return permissions
