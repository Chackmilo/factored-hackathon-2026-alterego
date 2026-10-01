"""
Create or update the demo personas in Supabase Auth (docs/specs/supabase-login-v1.md section 3.3).

Each persona gets an email built from --email-pattern and an app_metadata with customer_id and app_role, the only
claims SessionVerifier reads; only the secret key can write app_metadata. New accounts get a random password that
goes only to the --out file (git-ignored), never to the screen. The secret key comes from the local .env and travels
only in the apikey header: the sb_secret_ keys are not JWTs and Supabase rejects them as a Bearer token.

    uv run python -m src.auth.seed_personas --email-pattern 'you+{label}@gmail.com' --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

ROLES = ("customer", "agent")
SECRET_KEY_PREFIX = "sb_secret_"
PAGE_SIZE = 1000


class PersonaError(ValueError):
    """A persona file, email pattern, key or credentials file that would create the wrong accounts."""


def load_personas(path: str | Path) -> list[dict[str, Any]]:
    personas = json.loads(Path(path).read_text(encoding="utf-8"))["personas"]
    labels = [p.get("label") for p in personas]
    if not all(labels) or len(set(labels)) != len(labels):
        raise PersonaError("Every persona needs a label, and labels must be unique.")
    for p in personas:
        if p.get("app_role") not in ROLES:
            raise PersonaError(f"{p['label']}: app_role must be 'customer' or 'agent'.")
        if p["app_role"] == "customer" and not p.get("customer_id"):
            raise PersonaError(f"{p['label']}: a customer persona needs a customer_id.")
        if p["app_role"] == "agent" and p.get("customer_id"):
            raise PersonaError(f"{p['label']}: the agent persona has no customer_id.")
    return personas


def email_for(pattern: str, label: str) -> str:
    if "{label}" not in pattern:
        raise PersonaError("--email-pattern must contain {label}; without it every persona gets the same email.")
    return pattern.replace("{label}", label)


def app_metadata(persona: dict[str, Any]) -> dict[str, Any]:
    """customer_id is always written, null for the agent, so an id from an earlier run never lingers."""
    customer_id = persona.get("customer_id") if persona["app_role"] == "customer" else None
    return {"customer_id": customer_id, "app_role": persona["app_role"]}


def admin_client(supabase_url: str, secret_key: str, transport: httpx.BaseTransport | None = None) -> httpx.Client:
    if not supabase_url:
        raise PersonaError("SUPABASE_URL is not set.")
    # httpx refuses an illegal header value at the first request and prints it whole, and main() prints that message:
    # so the padding a paste leaves is stripped, and anything but visible ASCII inside the key is refused here.
    key = secret_key.strip()
    if not key.startswith(SECRET_KEY_PREFIX):
        raise PersonaError("SUPABASE_SECRET_KEY must be the project's secret key (sb_secret_...), never the publishable one.")
    if not all("!" <= char <= "~" for char in key):
        raise PersonaError("SUPABASE_SECRET_KEY has a space, a control character or a non-ASCII character inside it; "
                           "paste the key again from the project's API settings.")
    return httpx.Client(base_url=f"{supabase_url.rstrip('/')}/auth/v1", headers={"apikey": key},
                        transport=transport, timeout=15.0)


def _existing_users(client: httpx.Client) -> dict[str, dict[str, Any]]:
    users: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        response = client.get("/admin/users", params={"page": page, "per_page": PAGE_SIZE})
        response.raise_for_status()
        batch = response.json().get("users") or []
        users.update({u["email"].lower(): u for u in batch if u.get("email")})
        if len(batch) < PAGE_SIZE:
            return users
        page += 1


def _read_credentials(path: Path) -> dict[str, dict[str, Any]]:
    """Passwords of earlier runs, kept so a new run never drops them. An unreadable file stops the run first."""
    if not path.exists():
        return {}
    try:
        return {a["label"]: a for a in json.loads(path.read_text(encoding="utf-8"))["accounts"]}
    except (ValueError, KeyError, TypeError) as exc:
        raise PersonaError(f"{path} is not a credentials file this script wrote ({type(exc).__name__}); "
                           "move it away and run again.") from exc


def _write_credentials(path: Path, credentials: dict[str, dict[str, Any]]) -> None:
    payload = {"note": "Passwords of the demo personas. Git-ignored: never commit, paste or share this file whole.",
               "accounts": list(credentials.values())}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def seed(personas: list[dict[str, Any]], email_pattern: str, client: httpx.Client, out: Path, dry_run: bool = False,
         reset_passwords: bool = False, echo: Callable[[str], None] = print) -> None:
    """Create the missing personas and bring the existing ones to their app_metadata. Prints no password or key."""
    emails = {p["label"]: email_for(email_pattern, p["label"]) for p in personas}
    credentials = _read_credentials(out)
    settings = client.get("/settings")
    settings.raise_for_status()
    if not settings.json().get("disable_signup", False):
        echo("warning: public sign-up is on; turn off 'Allow new users to sign up' in the project's Authentication settings")
    users = _existing_users(client)
    for p in personas:
        email = emails[p["label"]]
        user = users.get(email.lower())
        body: dict[str, Any] = {"app_metadata": app_metadata(p)}
        if user is None or reset_passwords:
            body["password"] = secrets.token_urlsafe(18)
        if dry_run:
            action = "would create" if user is None else "would update"
        elif user is None:
            client.post("/admin/users", json={"email": email, "email_confirm": True, **body}).raise_for_status()
            action = "created"
        else:
            client.put(f"/admin/users/{user['id']}", json=body).raise_for_status()
            action = "updated"
        if "password" in body and not dry_run:  # written after each account, so a later failure loses no password
            credentials[p["label"]] = {"label": p["label"], "email": email, "password": body["password"],
                                       "app_role": p["app_role"], "customer_id": p.get("customer_id")}
            _write_credentials(out, credentials)
        echo(f"{action:<12}  {p['label']:<24}  {p['app_role']:<8}  {p.get('customer_id') or '-':<16}  {email}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or update the demo personas in Supabase Auth.")
    parser.add_argument("--email-pattern", required=True, help="Email of each persona, with {label}: you+{label}@gmail.com")
    parser.add_argument("--personas", default="data/fixtures/personas.json", help="Team-generated persona list")
    parser.add_argument("--out", default="personas.local.json", help="Git-ignored file that receives the passwords")
    parser.add_argument("--dry-run", action="store_true", help="Read the settings and users, print the plan, write nothing")
    parser.add_argument("--reset-passwords", action="store_true", help="Give the existing personas a new password too")
    args = parser.parse_args(argv)
    load_dotenv()
    try:
        personas = load_personas(args.personas)
        with admin_client(os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SECRET_KEY", "")) as client:
            seed(personas, args.email_pattern, client, Path(args.out), dry_run=args.dry_run,
                 reset_passwords=args.reset_passwords)
    except (PersonaError, httpx.HTTPError) as exc:
        # URLs and status codes, never the key: admin_client validates it before it becomes a header value
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
