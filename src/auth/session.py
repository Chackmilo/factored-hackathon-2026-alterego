"""
Session verification for the dispute stack (docs/SUPABASE_VERCEL.md section 3).

Identity comes from a Supabase Auth access token: ES256, verified against the project's JWKS, with
`iss = <SUPABASE_URL>/auth/v1`, `aud = "authenticated"` and a live `exp`. `customer_id` and `app_role`
come only from `app_metadata`, which only the Supabase secret key can write. There is no shared secret
in the API (SEC-03): HS256 and `alg: none` tokens get 401.

A local issuer signs the same claims with an ES256 key pair generated per process. It exists only when
APP_ENV is `test` or `development`; configuring it in production makes the app refuse to start.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

ALGORITHM = "ES256"
AUDIENCE = "authenticated"
LOCAL_ISSUER = "local-issuer"
LEEWAY_SECONDS = 5

security_bearer = HTTPBearer(auto_error=False)


@dataclass
class VerifiedSession:
    customer_id: str | None
    name: str
    country: str
    segment: str
    session_id: str
    exp: int
    app_role: str = "customer"  # "customer" or "agent" (the HITL console)
    auth_user_id: str = ""

    @property
    def actor_id(self) -> str:
        """Who acted, for the audit log: the customer id, or the auth user id for an agent without one."""
        return self.customer_id or self.auth_user_id or "unknown"


def _app_env() -> str:
    return os.getenv("APP_ENV", "development").lower()


def local_issuer_enabled() -> bool:
    """The local ES256 issuer is for tests, the harness and docker-compose without a Supabase account."""
    configured = os.getenv("LOCAL_ISSUER_ENABLED")
    env = _app_env()
    if env == "production":
        if configured and configured.lower() == "true":
            raise RuntimeError("LOCAL_ISSUER_ENABLED=true is not allowed with APP_ENV=production (SEC-03)")
        return False
    return configured is None or configured.lower() == "true"


class LocalIssuer:
    """Signs Supabase-shaped claims with a per-process ES256 key and publishes the matching JWKS."""

    def __init__(self) -> None:
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        self.kid = f"local-{uuid.uuid4().hex[:12]}"
        public_jwk = jwt.algorithms.ECAlgorithm.to_jwk(self._private_key.public_key(), as_dict=True)
        public_jwk.update({"kid": self.kid, "use": "sig", "alg": ALGORITHM})
        self.jwks = {"keys": [public_jwk]}

    def issue(self, claims: dict[str, Any]) -> str:
        return jwt.encode(claims, self._private_key, algorithm=ALGORITHM, headers={"kid": self.kid})


@lru_cache(maxsize=1)
def local_issuer() -> LocalIssuer:
    if not local_issuer_enabled():
        raise RuntimeError("The local issuer is disabled in this environment")
    return LocalIssuer()


class SessionVerifier:
    """Verifies ES256 tokens from the Supabase project JWKS and, outside production, from the local issuer."""

    def __init__(self, supabase_url: str | None = None, jwks: dict[str, Any] | None = None, issuer: str | None = None):
        self.supabase_url = (supabase_url or os.getenv("SUPABASE_URL", "")).rstrip("/")
        self.supabase_issuer = issuer or (f"{self.supabase_url}/auth/v1" if self.supabase_url else None)
        self._static_jwks = jwks  # for tests: a JWKS dict standing in for the remote one
        self._jwk_client = jwt.PyJWKClient(f"{self.supabase_url}/auth/v1/.well-known/jwks.json", cache_keys=True) \
            if (self.supabase_url and jwks is None) else None

    def _signing_key(self, kid: str | None, issuer: str | None):
        if issuer == LOCAL_ISSUER and local_issuer_enabled():
            local = local_issuer()
            if kid == local.kid:
                return jwt.PyJWK.from_dict(local.jwks["keys"][0]).key
            return None
        if issuer != self.supabase_issuer or issuer is None:
            return None
        if self._static_jwks is not None:
            for entry in self._static_jwks.get("keys", []):
                if entry.get("kid") == kid:
                    return jwt.PyJWK.from_dict(entry).key
            return None
        if self._jwk_client is not None:
            try:
                return self._jwk_client.get_signing_key(kid).key
            except jwt.PyJWKClientError:
                return None
        return None

    def verify(self, token: str) -> VerifiedSession:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != ALGORITHM:
                raise jwt.InvalidAlgorithmError("Only ES256 tokens are accepted")
            unverified = jwt.decode(token, options={"verify_signature": False})
            issuer = unverified.get("iss")
            key = self._signing_key(header.get("kid"), issuer)
            if key is None:
                raise jwt.InvalidTokenError("Unknown signing key")
            payload = jwt.decode(token, key, algorithms=[ALGORITHM], audience=AUDIENCE, issuer=issuer, leeway=LEEWAY_SECONDS)
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session token has expired. Re-authentication required.")
        except (jwt.PyJWTError, ValueError, RuntimeError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session token.")
        app_metadata = payload.get("app_metadata") or {}
        if not isinstance(app_metadata, dict):
            app_metadata = {}
        return VerifiedSession(
            customer_id=app_metadata.get("customer_id"),
            name=str(payload.get("name") or "Unknown"),
            country=str(payload.get("country") or "Unknown"),
            segment=str(payload.get("segment") or "Basic"),
            session_id=str(payload.get("session_id") or "SESS-UNKNOWN"),
            exp=int(payload.get("exp") or 0),
            app_role=str(app_metadata.get("app_role") or "customer"),
            auth_user_id=str(payload.get("sub") or ""),
        )


@lru_cache(maxsize=1)
def default_verifier() -> SessionVerifier:
    return SessionVerifier()


def create_test_session(
    customer_id: str | None,
    name: str = "Test Customer",
    country: str = "Colombia",
    segment: str = "Plus",
    ttl_seconds: int = 3600,
    app_role: str = "customer",
) -> str:
    """Mint a Supabase-shaped ES256 token with the local issuer (tests, harness, docker-compose)."""
    now = int(time.time())
    claims = {
        "iss": LOCAL_ISSUER,
        "aud": AUDIENCE,
        "sub": f"local-user-{customer_id or 'agent'}",
        "role": AUDIENCE,
        "session_id": f"SESS-{now}",
        "iat": now,
        "exp": now + ttl_seconds,
        "aal": "aal1",
        "app_metadata": {"customer_id": customer_id, "app_role": app_role},
        # informational only: policy facts come from the system of record, never from the token
        "name": name, "country": country, "segment": segment,
    }
    return local_issuer().issue(claims)


def decode_session_token(token: str) -> VerifiedSession:
    return default_verifier().verify(token)


def get_current_session(credentials: HTTPAuthorizationCredentials | None = Security(security_bearer)) -> VerifiedSession:
    """FastAPI dependency: a verified session. Customer endpoints need a customer_id in app_metadata (403 otherwise)."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authorization header.")
    session = decode_session_token(credentials.credentials)
    if session.app_role != "agent" and not session.customer_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This session carries no customer identity.")
    return session


def require_agent(session: VerifiedSession = Depends(get_current_session)) -> VerifiedSession:
    """HITL console dependency: a valid session whose app_role is 'agent' (SEC-01), else 403."""
    if session.app_role != "agent":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This endpoint requires the agent role.")
    return session
