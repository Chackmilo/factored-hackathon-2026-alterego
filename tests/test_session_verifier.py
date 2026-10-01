"""POL-SEC-SESSION: ES256 against a JWKS, claims from app_metadata, no shared secret, local issuer outside production."""
import os
import subprocess
import sys
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from src.auth import session as session_module
from src.auth.session import (
    LOCAL_ISSUER,
    SessionVerifier,
    create_test_session,
    decode_session_token,
    local_issuer,
)

REPO = Path(__file__).resolve().parents[1]
NO_DOTENV = "import dotenv; dotenv.load_dotenv = lambda *args, **kwargs: False; "  # python -c finds the .env of any parent folder


def _claims(**overrides):
    now = int(time.time())
    base = {"iss": LOCAL_ISSUER, "aud": "authenticated", "sub": "u-1", "session_id": "S-1", "iat": now, "exp": now + 600,
            "app_metadata": {"customer_id": "CLI-1", "app_role": "customer"}}
    base.update(overrides)
    return base


def test_local_es256_token_yields_customer_session():
    session = decode_session_token(create_test_session("CLI-1", app_role="customer"))
    assert session.customer_id == "CLI-1" and session.app_role == "customer" and session.auth_user_id == "local-user-CLI-1"


def test_expired_token_is_rejected():
    with pytest.raises(HTTPException) as exc:
        decode_session_token(create_test_session("CLI-1", ttl_seconds=-30))
    assert exc.value.status_code == 401


@pytest.mark.parametrize("bad_token", [
    jwt.encode(_claims(), "factored-datathon-hackathon-secret-key-2026", algorithm="HS256"),          # the old shared secret
    jwt.encode(_claims(), key=None, algorithm="none"),                                                    # alg none
    jwt.encode(_claims(), ec.generate_private_key(ec.SECP256R1()), algorithm="ES256", headers={"kid": "local-forged"}),  # other key
    "not-a-token",
])
def test_forged_tokens_get_401(bad_token):
    with pytest.raises(HTTPException) as exc:
        decode_session_token(bad_token)
    assert exc.value.status_code == 401


@pytest.mark.parametrize("override", [{"aud": "anon"}, {"iss": "https://other.supabase.co/auth/v1"}])
def test_wrong_audience_or_issuer_get_401(override):
    token = local_issuer().issue(_claims(**override))
    with pytest.raises(HTTPException) as exc:
        decode_session_token(token)
    assert exc.value.status_code == 401


def test_role_comes_from_app_metadata_not_user_metadata():
    token = local_issuer().issue(_claims(user_metadata={"app_role": "agent", "customer_id": "CLI-OTHER"}))
    session = decode_session_token(token)
    assert session.app_role == "customer" and session.customer_id == "CLI-1"


def test_agent_token_without_customer_id_uses_auth_user_as_actor():
    session = decode_session_token(create_test_session(None, app_role="agent"))
    assert session.customer_id is None and session.actor_id == "local-user-agent"


def test_supabase_jwks_path_verifies_project_tokens():
    """A JWKS standing in for the project's endpoint: the token must carry the project issuer and a known kid."""
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = jwt.algorithms.ECAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk.update({"kid": "sb-key-1", "alg": "ES256", "use": "sig"})
    verifier = SessionVerifier(supabase_url="https://proj.supabase.co", jwks={"keys": [jwk]})
    good = jwt.encode(_claims(iss="https://proj.supabase.co/auth/v1"), key, algorithm="ES256", headers={"kid": "sb-key-1"})
    assert verifier.verify(good).customer_id == "CLI-1"
    unknown_kid = jwt.encode(_claims(iss="https://proj.supabase.co/auth/v1"), key, algorithm="ES256", headers={"kid": "sb-key-9"})
    with pytest.raises(HTTPException):
        verifier.verify(unknown_kid)


def test_production_refuses_the_local_issuer(monkeypatch):
    token = create_test_session("CLI-1")  # minted while the local issuer is enabled
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("LOCAL_ISSUER_ENABLED", "true")
    with pytest.raises(RuntimeError):
        session_module.local_issuer_enabled()
    monkeypatch.delenv("LOCAL_ISSUER_ENABLED")
    assert session_module.local_issuer_enabled() is False
    with pytest.raises(HTTPException) as exc:  # a local token is worthless in production
        decode_session_token(token)
    assert exc.value.status_code == 401


def _import_app(**env):
    """Import the API in a fresh interpreter, as uvicorn does at startup, with these environment overrides."""
    return subprocess.run([sys.executable, "-c", "import src.api.app"], cwd=REPO,
                          env={**os.environ, **env}, capture_output=True, text=True)


def test_the_app_refuses_to_start_with_the_local_issuer_in_production():
    result = _import_app(APP_ENV="production", LOCAL_ISSUER_ENABLED="true")
    assert result.returncode != 0
    assert "LOCAL_ISSUER_ENABLED=true is not allowed with APP_ENV=production" in result.stderr


def test_the_app_starts_in_production_without_the_local_issuer():
    result = _import_app(APP_ENV="production", LOCAL_ISSUER_ENABLED="false", SUPABASE_URL="https://proj.supabase.co")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("app_env", ["production", "preview"])
def test_without_supabase_url_the_app_refuses_to_start(app_env):
    """Outside development and test only Supabase tokens pass: without the project URL nobody could sign in."""
    result = _import_app(APP_ENV=app_env, LOCAL_ISSUER_ENABLED="false", SUPABASE_URL="")
    assert result.returncode != 0
    assert f"APP_ENV={app_env} needs SUPABASE_URL" in result.stderr


@pytest.mark.parametrize("app_env", [None, "", "preview"])
def test_only_development_and_test_turn_the_local_issuer_on(monkeypatch, app_env):
    """Fails closed: no APP_ENV, a blank one or any other value means production."""
    if app_env is None:
        monkeypatch.delenv("APP_ENV", raising=False)
    else:
        monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.delenv("LOCAL_ISSUER_ENABLED", raising=False)
    assert session_module.local_issuer_enabled() is False


@pytest.mark.parametrize("app_env", [None, ""])
def test_without_app_env_the_app_runs_as_production(app_env):
    """A deploy that forgets APP_ENV issues no local tokens. No .env may supply the variable here."""
    env = {k: v for k, v in os.environ.items() if k not in ("APP_ENV", "LOCAL_ISSUER_ENABLED")}
    if app_env is not None:
        env["APP_ENV"] = app_env
    env["SUPABASE_URL"] = "https://proj.supabase.co"
    code = NO_DOTENV + ("import src.api.app; from src.core.config import settings; "
                        "from src.auth.session import local_issuer_enabled; print(settings.app_env, local_issuer_enabled())")
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["production", "False"]
