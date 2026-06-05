import base64
import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable

from fastapi import Header, HTTPException, Request, Response, status
from starlette.middleware.base import BaseHTTPMiddleware

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
    tenant_id: str = "default"


def auth_enabled() -> bool:
    return os.getenv("STRATAONE_AUTH_ENABLED", os.getenv("STRATAONE_AUTH_REQUIRED", "true")).lower() in {"1", "true", "yes", "on"}


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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        headers = security_headers()
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    _buckets: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next) -> Response:
        if not rate_limit_enabled():
            return await call_next(request)
        limit = int(os.getenv("STRATAONE_RATE_LIMIT_REQUESTS", "120"))
        window = float(os.getenv("STRATAONE_RATE_LIMIT_WINDOW_SECONDS", "60"))
        key = _rate_limit_key(request)
        now = time.monotonic()
        bucket = [stamp for stamp in self._buckets.get(key, []) if now - stamp < window]
        if len(bucket) >= limit:
            retry_after = max(1, int(window - (now - bucket[0])))
            response = Response("rate limit exceeded", status_code=status.HTTP_429_TOO_MANY_REQUESTS)
            response.headers["Retry-After"] = str(retry_after)
            return response
        bucket.append(now)
        self._buckets[key] = bucket
        return await call_next(request)


def rate_limit_enabled() -> bool:
    return os.getenv("STRATAONE_RATE_LIMIT_ENABLED", "true").lower() in {"1", "true", "yes", "on"}


def security_headers() -> dict[str, str]:
    csp = os.getenv(
        "STRATAONE_CONTENT_SECURITY_POLICY",
        "default-src 'self'; connect-src 'self' http://localhost:8080 http://127.0.0.1:8080; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'",
    )
    headers = {
        "Content-Security-Policy": csp,
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    }
    if os.getenv("STRATAONE_HSTS_ENABLED", "false").lower() in {"1", "true", "yes", "on"}:
        headers["Strict-Transport-Security"] = os.getenv("STRATAONE_HSTS_VALUE", "max-age=31536000; includeSubDomains")
    return headers


def authenticate(authorization: str | None, store: StrataStore) -> AuthContext:
    if not auth_enabled():
        return AuthContext(username="local-dev", roles=["Platform Admin"], permissions={"*"})
    token = _bearer_token(authorization)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bearer token required")
    bootstrap = os.getenv("STRATAONE_BOOTSTRAP_TOKEN", "")
    if bootstrap and token == bootstrap:
        return AuthContext(username="bootstrap", roles=["Platform Admin"], permissions={"*"}, tenant_id="*")
    token_map = _configured_tokens()
    subject = token_map.get(token)
    if subject is not None:
        username, roles, tenant_id = subject
        permissions = _permissions_for_roles(roles, store)
        return AuthContext(username=username, roles=roles, permissions=permissions, tenant_id=tenant_id)
    session_user = store.get_session_user(token_hash(token), datetime.now(UTC).isoformat())
    if session_user is None or session_user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid bearer token")
    username, roles = session_user.username, session_user.roles
    permissions = _permissions_for_roles(roles, store)
    return AuthContext(username=username, roles=roles, permissions=permissions, tenant_id=session_user.tenant_id)


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


def _configured_tokens() -> dict[str, tuple[str, list[str], str]]:
    mapping: dict[str, tuple[str, list[str], str]] = {}
    configured = os.getenv("STRATAONE_API_TOKENS", "")
    for entry in configured.split(";"):
        if not entry.strip() or "=" not in entry:
            continue
        token, subject = entry.split("=", 1)
        username, _, roles_text = subject.partition(":")
        role_text, _, tenant_text = roles_text.partition("@")
        roles = [role.strip() for role in role_text.split(",") if role.strip()]
        mapping[token.strip()] = (username.strip() or "api-token", roles, tenant_text.strip() or "default")
    return mapping


def _permissions_for_roles(roles: list[str], store: StrataStore) -> set[str]:
    permissions: set[str] = set()
    for role_name in roles:
        role = store.get_role(role_name)
        if role is None:
            continue
        permissions.update(role.permissions)
    return permissions


def _rate_limit_key(request: Request) -> str:
    token = _bearer_token(request.headers.get("Authorization"))
    if token:
        return f"token:{token_hash(token)}"
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",", 1)[0].strip() if forwarded else ""
    if not ip and request.client:
        ip = request.client.host
    return f"ip:{ip or 'unknown'}:{request.url.path}"
