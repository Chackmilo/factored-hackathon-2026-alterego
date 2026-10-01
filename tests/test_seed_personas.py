"""The persona script talks to Supabase Auth only through httpx.MockTransport here: no test reaches the network."""
import json

import httpx
import pytest

from src.auth import seed_personas
from src.auth.seed_personas import PersonaError, admin_client, load_personas, seed

URL = "https://proj.supabase.co"
KEY = "sb_secret_test_key"
PATTERN = "team+{label}@example.org"
CUSTOMER = {"label": "cliente-hasta-150", "app_role": "customer", "customer_id": "CLI-1"}
AGENT = {"label": "agente", "app_role": "agent", "customer_id": None}


class FakeAuth:
    """The Auth admin endpoints in memory, recording every request."""

    def __init__(self, users=(), disable_signup=True, fail_on_create=None):
        self.users = {u["email"]: u for u in users}
        self.disable_signup = disable_signup
        self.fail_on_create = fail_on_create
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/auth/v1/settings":
            return httpx.Response(200, json={"disable_signup": self.disable_signup})
        if path == "/auth/v1/admin/users" and request.method == "GET":
            page, per_page = int(request.url.params["page"]), int(request.url.params["per_page"])
            return httpx.Response(200, json={"users": list(self.users.values())[(page - 1) * per_page:page * per_page]})
        if path == "/auth/v1/admin/users" and request.method == "POST":
            body = json.loads(request.content)
            if body["email"] == self.fail_on_create:
                return httpx.Response(500, json={"msg": "boom"})
            self.users[body["email"]] = {"id": f"id-{len(self.users) + 1}", **body}
            return httpx.Response(200, json=self.users[body["email"]])
        if path.startswith("/auth/v1/admin/users/") and request.method == "PUT":
            return httpx.Response(200, json={"id": path.rsplit("/", 1)[1], **json.loads(request.content)})
        return httpx.Response(404)

    def bodies(self, method):
        return [json.loads(r.content) for r in self.requests if r.method == method]


def run(fake, personas, tmp_path, **kwargs):
    lines: list[str] = []
    with admin_client(URL, KEY, transport=httpx.MockTransport(fake)) as client:
        seed(personas, PATTERN, client, tmp_path / "personas.local.json", echo=lines.append, **kwargs)
    return lines


def saved_accounts(tmp_path):
    return json.loads((tmp_path / "personas.local.json").read_text(encoding="utf-8"))["accounts"]


def test_a_new_customer_gets_its_app_metadata_and_a_confirmed_email(tmp_path):
    fake = FakeAuth()
    run(fake, [CUSTOMER], tmp_path)
    [body] = fake.bodies("POST")
    assert body["email"] == "team+cliente-hasta-150@example.org"
    assert body["email_confirm"] is True
    assert body["app_metadata"] == {"customer_id": "CLI-1", "app_role": "customer"}
    assert "user_metadata" not in body


def test_the_agent_persona_carries_a_null_customer_id(tmp_path):
    fake = FakeAuth()
    run(fake, [AGENT], tmp_path)
    assert fake.bodies("POST")[0]["app_metadata"] == {"customer_id": None, "app_role": "agent"}


def test_an_existing_persona_keeps_its_password(tmp_path):
    fake = FakeAuth(users=[{"id": "u-7", "email": "team+cliente-hasta-150@example.org"}])
    run(fake, [CUSTOMER], tmp_path)
    assert fake.bodies("POST") == []
    assert fake.bodies("PUT") == [{"app_metadata": {"customer_id": "CLI-1", "app_role": "customer"}}]
    assert not (tmp_path / "personas.local.json").exists()


def test_reset_passwords_gives_an_existing_persona_a_new_one(tmp_path):
    fake = FakeAuth(users=[{"id": "u-7", "email": "team+cliente-hasta-150@example.org"}])
    run(fake, [CUSTOMER], tmp_path, reset_passwords=True)
    [body] = fake.bodies("PUT")
    assert saved_accounts(tmp_path) == [{"label": "cliente-hasta-150", "email": "team+cliente-hasta-150@example.org",
                                         "password": body["password"], "app_role": "customer", "customer_id": "CLI-1"}]


def test_an_existing_persona_is_found_whatever_the_case_of_its_email(tmp_path):
    fake = FakeAuth(users=[{"id": "u-3", "email": "Team+Agente@Example.org"}])
    run(fake, [AGENT], tmp_path)
    assert fake.bodies("POST") == [] and len(fake.bodies("PUT")) == 1


def test_personas_are_found_beyond_the_first_page_of_users(tmp_path, monkeypatch):
    monkeypatch.setattr(seed_personas, "PAGE_SIZE", 1)
    fake = FakeAuth(users=[{"id": "u-1", "email": "someone@else.org"}, {"id": "u-2", "email": "team+agente@example.org"}])
    run(fake, [AGENT], tmp_path)
    assert fake.bodies("POST") == [] and len(fake.bodies("PUT")) == 1


def test_the_secret_key_travels_only_in_the_apikey_header(tmp_path):
    fake = FakeAuth()
    run(fake, [CUSTOMER, AGENT], tmp_path)
    assert fake.requests
    assert all(r.headers["apikey"] == KEY and "authorization" not in r.headers for r in fake.requests)


@pytest.mark.parametrize("key", ["sb_publishable_abc", "eyJhbGciOiJIUzI1NiJ9.legacy", ""])
def test_a_key_that_is_not_a_secret_key_is_refused(key):
    with pytest.raises(PersonaError):
        admin_client(URL, key)


def test_a_missing_project_url_is_refused():
    with pytest.raises(PersonaError):
        admin_client("", KEY)


# httpx refuses an illegal header value at the first request and prints it whole in its error, and main() prints that
# error: so the key is cleaned or refused before it becomes a header, and no refusal carries any part of it.
@pytest.mark.parametrize("key", ["sb_publishable_abc", "eyJhbGciOiJIUzI1NiJ9.legacy"])
def test_a_refused_key_is_not_echoed_by_the_error(key):
    with pytest.raises(PersonaError) as refused:
        admin_client(URL, key)
    assert key not in str(refused.value)


@pytest.mark.parametrize("padded", [KEY + "\n", KEY + " ", KEY + "\r\n", "\t " + KEY + " \r\n"])
def test_whitespace_around_the_secret_key_is_stripped_before_it_becomes_a_header(padded):
    with admin_client(URL, padded) as client:
        assert client.headers["apikey"] == KEY


@pytest.mark.parametrize("separator", [" ", "\t", "\n", "\x00", "\x7f", " ", "é"])
def test_a_key_with_whitespace_or_a_stray_character_inside_is_refused_without_echoing_any_of_it(separator):
    key = f"sb_secret_ZQ7{separator}XK9"
    with pytest.raises(PersonaError) as refused:
        admin_client(URL, key)
    message = str(refused.value)
    assert not any(part in message for part in (key, "sb_secret_", "ZQ7", "XK9"))


@pytest.mark.parametrize("personas", [
    [{"label": "x", "app_role": "customer"}],                       # a customer without an id
    [{"label": "x", "app_role": "agent", "customer_id": "CLI-1"}],  # an agent with one
    [CUSTOMER, {**CUSTOMER, "customer_id": "CLI-2"}],               # a repeated label
    [{"label": "x", "app_role": "admin"}],                          # an unknown role
])
def test_an_invalid_persona_file_is_refused(tmp_path, personas):
    path = tmp_path / "personas.json"
    path.write_text(json.dumps({"personas": personas}), encoding="utf-8")
    with pytest.raises(PersonaError):
        load_personas(path)


def test_a_pattern_without_label_is_refused_before_any_call(tmp_path):
    fake = FakeAuth()
    with admin_client(URL, KEY, transport=httpx.MockTransport(fake)) as client, pytest.raises(PersonaError):
        seed([CUSTOMER], "team@example.org", client, tmp_path / "personas.local.json", echo=lambda line: None)
    assert fake.requests == []


def test_an_unreadable_credentials_file_stops_before_any_call(tmp_path):
    (tmp_path / "personas.local.json").write_text("not json", encoding="utf-8")
    fake = FakeAuth()
    with pytest.raises(PersonaError):
        run(fake, [CUSTOMER], tmp_path)
    assert fake.requests == []
    assert (tmp_path / "personas.local.json").read_text(encoding="utf-8") == "not json"


def test_no_password_reaches_the_screen(tmp_path):
    lines = run(FakeAuth(), [CUSTOMER, AGENT], tmp_path)
    passwords = [a["password"] for a in saved_accounts(tmp_path)]
    assert len(passwords) == 2
    assert not any(p in line for p in passwords for line in lines)
    assert [line.split()[0] for line in lines] == ["created", "created"]


def test_dry_run_writes_nothing(tmp_path):
    fake = FakeAuth(users=[{"id": "u-9", "email": "team+agente@example.org"}])
    lines = run(fake, [CUSTOMER, AGENT], tmp_path, dry_run=True)
    assert {r.method for r in fake.requests} == {"GET"}
    assert not (tmp_path / "personas.local.json").exists()
    assert [line[:12].strip() for line in lines] == ["would create", "would update"]


def test_passwords_of_created_accounts_survive_a_failure(tmp_path):
    second = {**CUSTOMER, "label": "cliente-mas-de-500", "customer_id": "CLI-2"}
    fake = FakeAuth(fail_on_create="team+cliente-mas-de-500@example.org")
    with pytest.raises(httpx.HTTPStatusError):
        run(fake, [CUSTOMER, second], tmp_path)
    assert [a["label"] for a in saved_accounts(tmp_path)] == ["cliente-hasta-150"]


def test_open_sign_up_is_reported(tmp_path):
    assert any("sign-up is on" in line for line in run(FakeAuth(disable_signup=False), [AGENT], tmp_path))
    assert not any("sign-up" in line for line in run(FakeAuth(disable_signup=True), [AGENT], tmp_path))
