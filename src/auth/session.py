"""
Mock OIDC/JWT Session Service for OmniGuard AI.
Enforces zero-trust customer identity: customer_id is verified from cryptographic token,
never accepted blindly from user input or model output.
"""
import os
import time
from typing import Optional
from dataclasses import dataclass
import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

JWT_SECRET = os.getenv("JWT_SECRET", "factored-datathon-hackathon-secret-key-2026")
JWT_ALGORITHM = "HS256"

security_bearer = HTTPBearer(auto_error=False)

@dataclass
class VerifiedSession:
    customer_id: str
    name: str
    country: str
    segment: str
    session_id: str
    exp: int

def create_test_session(
    customer_id: str,
    name: str = "Test Customer",
    country: str = "Colombia",
    segment: str = "Plus",
    ttl_seconds: int = 3600
) -> str:
    """
    Creates a valid signed JWT session token for testing.
    """
    now = int(time.time())
    payload = {
        "sub": customer_id,
        "name": name,
        "country": country,
        "segment": segment,
        "session_id": f"SESS-{now}",
        "iat": now,
        "exp": now + ttl_seconds
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_session_token(token: str) -> VerifiedSession:
    """
    Decodes and validates JWT token.
    Raises HTTPException 401 on expired or invalid token.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return VerifiedSession(
            customer_id=payload["sub"],
            name=payload.get("name", "Unknown"),
            country=payload.get("country", "Unknown"),
            segment=payload.get("segment", "Basic"),
            session_id=payload.get("session_id", "SESS-UNKNOWN"),
            exp=payload.get("exp", 0)
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session token has expired. Re-authentication required."
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid session token."
        )

def get_current_session(credentials: Optional[HTTPAuthorizationCredentials] = Security(security_bearer)) -> VerifiedSession:
    """
    FastAPI dependency to extract verified session from Authorization Bearer header.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header."
        )
    return decode_session_token(credentials.credentials)
