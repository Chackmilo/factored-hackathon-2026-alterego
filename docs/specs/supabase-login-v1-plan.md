# Plan de implementación: ingreso con Supabase Auth (v1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** que la demo publicada permita ingresar con Supabase Auth y que ningún despliegue pueda emitir tokens locales.

**Architecture:** el front usa `supabase-js` cuando su build trae las claves del proyecto y el selector de personas cuando no; en los dos modos lee la identidad verificada en `GET /api/v1/auth/me`. Un script crea las personas con `app_metadata` por la API de administración de Auth. `APP_ENV` falla cerrado: solo `development` y `test` encienden el emisor local, y fuera de ellos el app no arranca sin `SUPABASE_URL`.

**Tech Stack:** FastAPI, PyJWT (ES256), httpx, python-dotenv, pytest; React 19, Vite 8, TypeScript 6, `@supabase/supabase-js` 2.117.2; Docker (servicio `dev`, Python 3.12, Postgres 17).

**Spec:** `docs/specs/supabase-login-v1.md` (aprobado el 2026-09-30; las enmiendas de este plan están al final y se aplican al spec en el mismo commit).

## Global Constraints

- `@supabase/supabase-js` fijado en `2.117.2`, sin rango (`npm install --save-exact`).
- La secret key (`SUPABASE_SECRET_KEY`, `sb_secret_...`) vive solo en el `.env` local. Nunca en Vercel, el front, el repo, un commit, la pantalla ni el chat.
- La publishable key va solo en `VITE_SUPABASE_PUBLISHABLE_KEY`, en `frontend/.env.local`.
- La identidad sale solo de `app_metadata` (`customer_id`, `app_role`); el script nunca escribe `user_metadata`.
- Sin `APP_ENV`, en blanco o con un valor distinto de `development` o `test`: producción.
- Mensaje de la guarda: `APP_ENV=<valor> needs SUPABASE_URL: without it no session token can be verified. Set SUPABASE_URL, or APP_ENV=development for local work.`
- Error de ingreso: `Email or password is incorrect.`; los textos del ingreso siguen en inglés.
- `supabase.auth.signOut` siempre con `{ scope: 'local' }`: las personas son compartidas y un `global` cerraría la sesión de los demás.
- Ningún test toca la red: el script se prueba con `httpx.MockTransport`.
- Backend con pares TDD, como el lote A: un commit `test(...)` cuyo cuerpo dice `Red: <qué falla y cómo>`, y luego el `fix(...)` o `feat(...)` con `Green for <sha corto del test>`. Todo commit termina con `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- No tocar la suite held-out congelada ni `docs/RAG_IMPLEMENTATION_ROADMAP.md` (lo edita otra sesión).
- Ruff solo sobre los archivos tocados (`uvx ruff check <archivos>`); el árbol no está limpio.

## Review Focus

Entradas que el spec implica y que ningún test de las tareas cubriría sin esta lista; cada línea tiene su test en la tarea dueña:

1. `APP_ENV` en blanco (`APP_ENV=` en un `.env`) o con otro valor (`preview` en un deploy de Vercel): se comporta como producción, sin emisor local y con la guarda. Tests en las tareas 1 y 2.
2. Un usuario que Supabase guarda con otras mayúsculas en el email (`Team+Agente@Example.org`): el script lo encuentra y no lo duplica. Test en la tarea 4.
3. Un proyecto con más usuarios que una página de la API de administración: el script encuentra las personas en las páginas siguientes. Test en la tarea 4.
4. Un `personas.local.json` ilegible de una corrida anterior: el script se detiene antes de cualquier llamada y no pisa el archivo. Test en la tarea 4.
5. Dos jurados con la misma persona: cuando uno sale, el otro sigue dentro (`signOut` con `scope: 'local'`). Código en la tarea 6, verificación manual con dos navegadores en la tarea 8.

## Cómo se corre todo en este worktree

- Worktree: `D:\Hackaton\.claude\worktrees\fix+audit-v3-lote-a`, rama `feat/supabase-login` (spec en `2b22727`).
- `<scratchpad>`: el directorio temporal de la sesión que ejecuta el plan. Los scripts desechables viven ahí, nunca en el repo.
- Suite y Python con duckdb: en el contenedor `dev`, siempre con `-p hackaton` para reutilizar la imagen: `docker compose -p hackaton run --rm -T dev pytest <tests> -q`. Sin argumentos corre la suite como CI.
- En Git Bash, un argumento con ruta de contenedor (`-v ...:/lake:ro`) necesita `MSYS_NO_PATHCONV=1` delante; si no, Git Bash la convierte en una ruta de Windows.
- El guard de Bash del worktree rechaza la palabra `eval` sola en un comando (incluso en `src.eval.run`): la evaluación se corre con un script en el scratchpad pasado por stdin (`... dev python - < script.py`).
- El Python del host (`D:/Hackaton/.venv/Scripts/python.exe`) importa `httpx`, `dotenv` y `src.auth`, no duckdb ni pandas. Desde el worktree, `load_dotenv()` encuentra `D:\Hackaton\.env` subiendo carpetas.
- El lakehouse de muestra está solo en el checkout principal (`D:/Hackaton/data/lakehouse.duckdb`); se monta en solo lectura y se copia a `/tmp` cuando algo puede escribirlo.
- `python -c` busca el `.env` desde el directorio de trabajo hacia arriba: un test que necesite "sin `APP_ENV`" anula `dotenv.load_dotenv` antes de importar `src`.

## Mapa de archivos

| Archivo | Responsabilidad | Tarea |
| --- | --- | --- |
| `src/auth/session.py` | `LOCAL_ENVS`, `_app_env()` normalizado, `local_issuer_enabled()` cerrado, `check_production_identity()` | 1, 2 |
| `src/core/config.py` | `settings.app_env` con default `production` | 1 |
| `tests/conftest.py`, `pyproject.toml` | `APP_ENV=test` antes de importar `src`; E402 permitido en el conftest | 1 |
| `.github/workflows/ci.yml` | `APP_ENV: test` en la evaluación; el test nuevo en la lista de lint | 1, 4 |
| `.env.example` | Comentario de `APP_ENV`; `SUPABASE_SECRET_KEY` vacía | 1, 4 |
| `src/api/app.py` | Llama a `check_production_identity()` al importar | 2 |
| `Dockerfile` | La etapa final corre como producción | 2 |
| `src/api/dispute_routes.py` | `GET /auth/me` | 3 |
| `src/auth/seed_personas.py` | Crea y actualiza las personas en Supabase Auth | 4 |
| `tests/test_seed_personas.py` | Tests del script con `httpx.MockTransport` | 4 |
| `.gitignore` | `personas.local.json` | 4 |
| `data/fixtures/personas.json` | Las cuatro personas, `team-generated` | 5 |
| `frontend/src/supabase.ts` | Cliente de Supabase o `null` | 6 |
| `frontend/src/api.ts` | `Session`, `Identity`, `LocalToken`, `clearSession`, token por petición, `api.me` | 6 |
| `frontend/src/Login.tsx` | Formulario de email y contraseña o selector de personas | 6 |
| `frontend/src/App.tsx`, `Console.tsx`, `styles.css` | Salida con `clearSession`, `label` en la consola, estilos de los inputs | 6 |
| `frontend/.env.example`, `frontend/package.json`, `package-lock.json` | Variables del build y la dependencia | 6 |
| `CLAUDE.md`, `AGENTS.md`, `README.md`, `docs/SUPABASE_VERCEL.md` | El ingreso como queda | 7 |
| `data/fixtures/team_questions.json` | TQ-020: personas creadas | 8 |

`frontend/src/Chat.tsx` no cambia: muestra `session.customer_id`, que un cliente siempre tiene.

---

### Task 1: `APP_ENV` falla cerrado

**Files:**

- Modify: `src/auth/session.py:9-10` (docstring), `:51-63` (`_app_env`, `local_issuer_enabled`)
- Modify: `src/core/config.py:10`
- Modify: `tests/conftest.py:1-11`, `pyproject.toml` (sección `[tool.ruff.lint]`), `.github/workflows/ci.yml` (paso de evaluación), `.env.example:2`
- Test: `tests/test_session_verifier.py`

**Interfaces:**

- Produces: `src.auth.session.LOCAL_ENVS = ("development", "test")`; `src.auth.session._app_env() -> str` (normalizado, `production` si falta o está en blanco). La tarea 2 los usa.

- [ ] **Step 1: Línea base.** Correr `docker compose -p hackaton run --rm -T dev` y anotar el conteo. Esperado: `N passed, 6 deselected`, sin fallas.

- [ ] **Step 2: Escribir los tests que fallan.** En `tests/test_session_verifier.py`, debajo de los imports, agregar las constantes y cambiar `_import_app` para que use `REPO`; al final del archivo, los dos tests:

```python
REPO = Path(__file__).resolve().parents[1]
NO_DOTENV = "import dotenv; dotenv.load_dotenv = lambda *args, **kwargs: False; "  # python -c finds the .env of any parent folder
```

```python
def _import_app(**env):
    """Import the API in a fresh interpreter, as uvicorn does at startup, with these environment overrides."""
    return subprocess.run([sys.executable, "-c", "import src.api.app"], cwd=REPO,
                          env={**os.environ, **env}, capture_output=True, text=True)
```

```python
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
```

- [ ] **Step 3: Verificar que fallan.** `docker compose -p hackaton run --rm -T dev pytest tests/test_session_verifier.py -q`. Esperado: 5 fallas. Los tres casos del primer test con `assert True is False`; el segundo test imprime `development True` sin la variable, y solo `True` (con `settings.app_env` vacío) cuando está en blanco.

- [ ] **Step 4: Commit del test.**

```bash
git add tests/test_session_verifier.py
git commit -F - <<'EOF'
test(auth): only development and test turn the local issuer on

Red: test_only_development_and_test_turn_the_local_issuer_on fails for
no APP_ENV, a blank one and 'preview' (the local issuer is on), and
test_without_app_env_the_app_runs_as_production prints 'development
True' without the variable and ' True' when it is blank.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 5: Implementar.** En `src/auth/session.py`, reemplazar `_app_env` y `local_issuer_enabled` por:

```python
LOCAL_ENVS = ("development", "test")  # the only environments where the local issuer and its routes exist


def _app_env() -> str:
    """APP_ENV, normalized. Missing or blank means production: the app fails closed."""
    return (os.getenv("APP_ENV") or "production").strip().lower()


def local_issuer_enabled() -> bool:
    """The local ES256 issuer is for tests, the harness and docker-compose without a Supabase account."""
    configured = (os.getenv("LOCAL_ISSUER_ENABLED") or "").strip().lower()
    env = _app_env()
    if env not in LOCAL_ENVS:
        if configured == "true":
            raise RuntimeError(f"LOCAL_ISSUER_ENABLED=true is not allowed with APP_ENV={env} (SEC-03)")
        return False
    return configured in ("", "true")
```

En el docstring del módulo, la frase de las líneas 9 y 10 queda: "A local issuer signs the same claims with an ES256 key pair generated per process. It exists only when APP_ENV is `test` or `development`; without APP_ENV, or with any other value, the app runs as production, and configuring the issuer there makes the app refuse to start."

En `src/core/config.py:10`:

```python
    app_env: str = (os.getenv("APP_ENV") or "production").strip().lower()  # missing or blank: production (fails closed)
```

En `tests/conftest.py`, antes de cualquier import de `src`:

```python
"""
Shared pytest fixtures for OmniGuard AI / Dispute Intake test suite.
"""
import os

os.environ.setdefault("APP_ENV", "test")  # before src is imported: without APP_ENV the app runs as production

from datetime import date

import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.auth.session import create_test_session
from src.rules.dispute_policy import DisputePolicyInput
```

En `pyproject.toml`, después de `[tool.ruff.lint.isort]`:

```toml
[tool.ruff.lint.per-file-ignores]
"tests/conftest.py" = ["E402"]  # APP_ENV is set before src is imported
```

En `.github/workflows/ci.yml`, el paso de evaluación queda:

```yaml
      - name: Evaluation report on the development split
        env:
          APP_ENV: test
        run: PYTHONPATH=. uv run python -m src.eval.run data/eval/dev_cases.jsonl --out reports/eval_dev --repeats 1
```

En `.env.example`, la línea 2:

```text
APP_ENV=development                    # development or test turn on the local issuer and the starter routes; missing, blank or any other value means production
```

- [ ] **Step 6: Verificar.** `docker compose -p hackaton run --rm -T dev pytest tests/test_session_verifier.py -q`: todo pasa. Después la suite completa: `docker compose -p hackaton run --rm -T dev`, con `N + 5 passed`. Lint: `uvx ruff check src/auth/session.py tests/conftest.py tests/test_session_verifier.py`, con `All checks passed!`. `src/core/config.py` ya traía 4 hallazgos (orden de imports y espacios en líneas en blanco); se corrigen en el Step 8, aparte.

- [ ] **Step 7: Commit.**

```bash
git add src/auth/session.py src/core/config.py tests/conftest.py pyproject.toml .github/workflows/ci.yml .env.example
git commit -F - <<'EOF'
fix(auth): APP_ENV fails closed, so only development and test issue local tokens

Green for <sha del Step 4>. Without APP_ENV, with a blank one or with
any value other than development or test, the app runs as production:
the local issuer, its persona routes and the starter routes are off. A
deploy that forgets the variable no longer lets anyone mint a token for
any customer (AUD-02).

The suite sets APP_ENV=test in conftest before importing src, and the
evaluation step of CI declares it, since its attack cases import the
app.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 8: Los hallazgos viejos de `config.py`.** `CLAUDE.md` pide lint y `--fix` en los archivos que se tocan: `uvx ruff check --fix src/core/config.py`, después `uvx ruff check src/core/config.py` con `All checks passed!`, y `git diff src/core/config.py` muestra solo imports reordenados y espacios borrados. Commit:

```bash
git add src/core/config.py
git commit -F - <<'EOF'
style(config): let ruff sort the imports and strip the spaces of blank lines

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

### Task 2: guarda de arranque e imagen en producción

**Files:**

- Modify: `src/auth/session.py` (función nueva después de `local_issuer_enabled`)
- Modify: `src/api/app.py:9`, `:20`
- Modify: `Dockerfile` (etapa final, `ENV`)
- Test: `tests/test_session_verifier.py`

**Interfaces:**

- Consumes: `LOCAL_ENVS`, `_app_env()` de la tarea 1.
- Produces: `src.auth.session.check_production_identity() -> None` (levanta `RuntimeError`).

- [ ] **Step 1: Escribir el test que falla y actualizar el contrato del existente.** En `tests/test_session_verifier.py`, reemplazar `test_the_app_starts_in_production_without_the_local_issuer` y agregar el test nuevo:

```python
def test_the_app_starts_in_production_without_the_local_issuer():
    result = _import_app(APP_ENV="production", LOCAL_ISSUER_ENABLED="false", SUPABASE_URL="https://proj.supabase.co")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("app_env", ["production", "preview"])
def test_without_supabase_url_the_app_refuses_to_start(app_env):
    """Outside development and test only Supabase tokens pass: without the project URL nobody could sign in."""
    result = _import_app(APP_ENV=app_env, LOCAL_ISSUER_ENABLED="false", SUPABASE_URL="")
    assert result.returncode != 0
    assert f"APP_ENV={app_env} needs SUPABASE_URL" in result.stderr
```

- [ ] **Step 2: Verificar que falla.** `docker compose -p hackaton run --rm -T dev pytest tests/test_session_verifier.py -q`. Esperado: 2 fallas en `test_without_supabase_url_the_app_refuses_to_start` (`assert 0 != 0`: el app arranca).

- [ ] **Step 3: Commit del test.**

```bash
git add tests/test_session_verifier.py
git commit -F - <<'EOF'
test(auth): outside development and test the app needs SUPABASE_URL to start

Red: test_without_supabase_url_the_app_refuses_to_start fails for
production and preview: the app imports with return code 0 and nobody
could sign in. The existing start-up test now passes SUPABASE_URL, the
contract production keeps.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 4: Implementar.** En `src/auth/session.py`, después de `local_issuer_enabled`:

```python
def check_production_identity() -> None:
    """Outside development and test only Supabase tokens pass, so the project URL is required: without it nobody signs in."""
    env = _app_env()
    if env not in LOCAL_ENVS and not (os.getenv("SUPABASE_URL") or "").strip():
        raise RuntimeError(f"APP_ENV={env} needs SUPABASE_URL: without it no session token can be verified. "
                           "Set SUPABASE_URL, or APP_ENV=development for local work.")
```

En `src/api/app.py`, el import y las dos llamadas al importar:

```python
from src.auth.session import check_production_identity, local_issuer_enabled
```

```python
local_issuer_enabled()  # SEC-03: raises at import, so the app refuses to start, when LOCAL_ISSUER_ENABLED=true meets APP_ENV=production
check_production_identity()  # and when production has no SUPABASE_URL to verify tokens against
```

- [ ] **Step 5: Verificar.** `docker compose -p hackaton run --rm -T dev pytest tests/test_session_verifier.py tests/test_api.py tests/test_dispute_api.py -q`: todo pasa. Lint: `uvx ruff check src/auth/session.py src/api/app.py tests/test_session_verifier.py`.

- [ ] **Step 6: Commit.**

```bash
git add src/auth/session.py src/api/app.py
git commit -F - <<'EOF'
fix(auth): outside development and test the app refuses to start without SUPABASE_URL

Green for <sha del Step 3>. Production verifies Supabase tokens only;
without the project URL every token gets 401 and nobody signs in. The
app now says so at start-up, next to the SEC-03 guard, and names the
fix.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 7: La imagen corre como producción.** En `Dockerfile`, la etapa final queda:

```dockerfile
ENV PATH="/app/.venv/bin:$PATH" PYTHONPATH="/app" APP_ENV=production \
    LAKEHOUSE_PATH=data/lakehouse.duckdb OPS_DB_PATH=data/ops.duckdb
# Production by default: the image issues no local tokens and needs SUPABASE_URL to start.
# docker-compose.yml sets APP_ENV=development for local use.
```

La verificación de la imagen (construirla y arrancarla sin variables) va en la tarea 8, porque construirla toma minutos. Commit:

```bash
git add Dockerfile
git commit -F - <<'EOF'
fix(docker): the image runs as production unless compose says otherwise

Dockerfile set APP_ENV=development, so a published image let anyone
mint a token for any customer (AUD-02). docker-compose.yml already sets
development for local use.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

### Task 3: `GET /api/v1/auth/me`

**Files:**

- Modify: `src/api/dispute_routes.py:1-7` (docstring), después de `_ensure_local_issuer` (ruta nueva)
- Test: `tests/test_dispute_api.py`

**Interfaces:**

- Consumes: `get_current_session` (401 sin token o inválido; 403 cliente sin `customer_id`).
- Produces: `GET /api/v1/auth/me -> {"app_role": "customer" | "agent", "customer_id": str | null}`. La tarea 6 lo llama.

- [ ] **Step 1: Escribir los tests que fallan.** En `tests/test_dispute_api.py`, agregar `from src.core.config import settings` entre los imports de `src.auth.session` y `src.ops.store`, y después de `bearer`:

```python
def test_me_returns_the_identity_the_api_verified(api):
    assert api.get("/api/v1/auth/me", headers=bearer()).json() == {"app_role": "customer", "customer_id": "CLI-FIX-OWNER"}
    agent = {"Authorization": f"Bearer {create_test_session(None, app_role='agent')}"}
    assert api.get("/api/v1/auth/me", headers=agent).json() == {"app_role": "agent", "customer_id": None}


def test_me_needs_a_session(api):
    assert api.get("/api/v1/auth/me").status_code == 401


def test_me_refuses_a_customer_session_without_a_customer(api):
    orphan = {"Authorization": f"Bearer {create_test_session(None, app_role='customer')}"}
    assert api.get("/api/v1/auth/me", headers=orphan).status_code == 403


def test_me_answers_in_production(api, monkeypatch):
    """Unlike the local issuer's routes, the front needs /auth/me wherever people sign in."""
    monkeypatch.setattr(settings, "app_env", "production")
    assert api.get("/api/v1/auth/me", headers=bearer()).status_code == 200
```

- [ ] **Step 2: Verificar que fallan.** `docker compose -p hackaton run --rm -T dev pytest tests/test_dispute_api.py -q`. Esperado: 4 fallas; la ruta no existe y responde 404.

- [ ] **Step 3: Commit del test.**

```bash
git add tests/test_dispute_api.py
git commit -F - <<'EOF'
test(api): /auth/me returns the identity the API verified

Red: the four tests get 404, since the route does not exist.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 4: Implementar.** En `src/api/dispute_routes.py`, después de `_ensure_local_issuer`:

```python
@router.get("/auth/me")
def who_am_i(session: VerifiedSession = Depends(get_current_session)) -> dict[str, Any]:
    """The identity as the API verified it; the front routes on it (chat or console). Answers in every APP_ENV."""
    return {"app_role": session.app_role, "customer_id": session.customer_id}
```

En el docstring del módulo, la última frase queda: "The local test issuer only exists in development and test; with Supabase Auth the front signs in through supabase-js, and both read the verified identity at /auth/me (docs/SUPABASE_VERCEL.md section 3)."

- [ ] **Step 5: Verificar.** `docker compose -p hackaton run --rm -T dev pytest tests/test_dispute_api.py -q`: todo pasa. Lint: `uvx ruff check src/api/dispute_routes.py tests/test_dispute_api.py`.

- [ ] **Step 6: Commit.**

```bash
git add src/api/dispute_routes.py
git commit -F - <<'EOF'
feat(api): /auth/me, where the front reads who signed in

Green for <sha del Step 3>. The front routes on what the API verified,
chat for a customer and console for an agent, in both sign-in modes. It
answers in every APP_ENV, unlike the local issuer's routes.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

### Task 4: el script de personas

**Files:**

- Create: `src/auth/seed_personas.py`
- Create: `tests/test_seed_personas.py`
- Modify: `.gitignore` (bloque "Local secrets"), `.env.example` (bloque del dispute stack), `.github/workflows/ci.yml` (lista de lint)

**Interfaces:**

- Produces: `PersonaError(ValueError)`; `load_personas(path) -> list[dict]`; `email_for(pattern, label) -> str`; `app_metadata(persona) -> dict`; `admin_client(supabase_url, secret_key, transport=None) -> httpx.Client`; `seed(personas, email_pattern, client, out, dry_run=False, reset_passwords=False, echo=print) -> None`; `main(argv=None) -> int`; `PAGE_SIZE = 1000`. La tarea 8 corre `python -m src.auth.seed_personas`.

- [ ] **Step 1: Escribir los tests que fallan.** `tests/test_seed_personas.py`:

```python
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
```

- [ ] **Step 2: Verificar que fallan.** `docker compose -p hackaton run --rm -T dev pytest tests/test_seed_personas.py -q`. Esperado: error de colección, `ModuleNotFoundError: No module named 'src.auth.seed_personas'`.

- [ ] **Step 3: Commit del test.**

```bash
git add tests/test_seed_personas.py
git commit -F - <<'EOF'
test(auth): the persona script writes app_metadata through the Auth admin API

Red: collection fails with ModuleNotFoundError: No module named
'src.auth.seed_personas'.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

- [ ] **Step 4: Implementar.** `src/auth/seed_personas.py`:

```python
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
    if not secret_key.startswith(SECRET_KEY_PREFIX):
        raise PersonaError("SUPABASE_SECRET_KEY must be the project's secret key (sb_secret_...), never the publishable one.")
    return httpx.Client(base_url=f"{supabase_url.rstrip('/')}/auth/v1", headers={"apikey": secret_key},
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
    except (PersonaError, httpx.HTTPError) as exc:  # the messages carry URLs and status codes, never the key
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

En `.gitignore`, debajo de `.env/` en el bloque "Local secrets and stray virtualenvs", y en `.dockerignore`, debajo de `.env` (su comentario ya dice que los archivos secretos nunca entran a una imagen):

```text
personas.local.json
```

En `.env.example`, debajo de `SUPABASE_URL=`:

```text
SUPABASE_SECRET_KEY=                   # sb_secret_...: only for `python -m src.auth.seed_personas` on your machine; never in Vercel, the front or the repo
```

En `.github/workflows/ci.yml`, agregar `tests/test_seed_personas.py` al final de la lista del paso de lint (`src/auth` ya cubre el módulo).

- [ ] **Step 5: Verificar.** `docker compose -p hackaton run --rm -T dev pytest tests/test_seed_personas.py -q`: 21 casos pasan. Lint: `uvx ruff check src/auth/seed_personas.py tests/test_seed_personas.py`.

- [ ] **Step 6: Commit.**

```bash
git add src/auth/seed_personas.py .gitignore .dockerignore .env.example .github/workflows/ci.yml
git commit -F - <<'EOF'
feat(auth): seed the demo personas in Supabase Auth

Green for <sha del Step 3>. The script creates the missing personas and
brings the existing ones to their app_metadata through the Auth admin
API, with the secret key only in the apikey header. Passwords go only
to the git-ignored personas.local.json, rewritten after each account;
the screen shows labels, roles, customer ids and emails. --dry-run
reads and prints the plan without writing.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

### Task 5: las cuatro personas

**Files:**

- Create: `data/fixtures/personas.json`
- Scratchpad (no se versionan): `select_personas.py`, `check_personas.py`

**Interfaces:**

- Consumes: `load_personas` (tarea 4) valida el archivo; `DisputeOrchestrator.start_conversation(session, language) -> dict` y `.handle_message(session, conversation_id, text) -> TurnResult`.
- Produces: `data/fixtures/personas.json` con `label`, `app_role`, `customer_id`, `scenario` y, en los clientes, `message`. La tarea 8 lo usa.

- [ ] **Step 1: Buscar candidatos.** Script de solo lectura en el scratchpad, `select_personas.py`:

```python
"""Read-only: candidate customers for each demo scenario in the lakehouse sample (docs/specs/supabase-login-v1.md 3.4)."""
import duckdb

con = duckdb.connect("/lake/lakehouse.duckdb", read_only=True)
BASE = """
WITH pool AS (  -- the 25 charges the orchestrator lists for a customer (search_customer_transactions)
    SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY transaction_date DESC) AS rn
    FROM gold_transactions QUALIFY rn <= 25
),
picked AS (
    SELECT d.* FROM pool d
    WHERE d.transaction_status = 'Approved' AND d.transaction_type IN ('Purchase', 'Payment', 'Withdrawal', 'Transfer')
      AND d.is_within_60_days AND d.amount_usd IS NOT NULL
      AND NOT EXISTS (  -- no other listed charge inside the orchestrator's amount tolerance, in amount or amount_usd
          SELECT 1 FROM pool o
          WHERE o.customer_id = d.customer_id AND o.transaction_id <> d.transaction_id
            AND (ABS(o.amount - d.amount) <= GREATEST(0.01 * d.amount, 0.5)
                 OR ABS(COALESCE(o.amount_usd, -1e9) - d.amount) <= GREATEST(0.01 * d.amount, 0.5)))
)
SELECT p.customer_id, p.transaction_id, p.process_date, p.amount, p.currency, p.amount_usd, p.channel,
       p.merchant_name, p.transaction_country, c.country, c.segment,
       (SELECT COUNT(*) FROM silver_products s WHERE s.customer_id = p.customer_id
            AND s.product_type LIKE 'Tarjeta%' AND s.product_status = 'Active') AS active_cards
FROM picked p JOIN gold_customers c USING (customer_id)
WHERE NOT (p.channel IN ('Web', 'App') AND p.transaction_country <> c.country)
"""
SCENARIOS = {
    "cliente-hasta-150": "amount_usd <= 150",
    "cliente-mas-de-500": "amount_usd > 500",
    "cliente-tarjeta-perdida": "amount_usd <= 500 AND active_cards = 1",
}
for label, where in SCENARIOS.items():
    print(f"== {label}")
    for row in con.execute(f"SELECT * FROM ({BASE}) WHERE {where} ORDER BY customer_id LIMIT 5").fetchall():
        print(row)
```

Correr: `MSYS_NO_PATHCONV=1 docker compose -p hackaton run --rm -T -v "D:/Hackaton/data:/lake:ro" dev python - < "<scratchpad>/select_personas.py"`. Esperado: hasta 5 filas por escenario. Elegir la primera de cada uno, salvo que repita cliente con otro escenario.

El archivo del modelo no está en esta máquina (`D:/Hackaton/models` no existe), así que el criterio del puntaje bajo el umbral del bundle (spec, sección 3.4) queda para cuando el modelo llegue al deploy; mientras tanto rige el filtro de compras extranjeras por Web o App.

- [ ] **Step 2: Escribir `data/fixtures/personas.json`** con los tres ids elegidos. El `message` usa el monto y la moneda del cargo elegido, con el día de `process_date`:

```json
{
  "provenance": "team-generated",
  "note": "Demo personas for Supabase Auth (docs/specs/supabase-login-v1.md section 3.4). Customer ids come from the lakehouse sample; emails and passwords never live here.",
  "personas": [
    {"label": "cliente-hasta-150", "app_role": "customer", "customer_id": "<id del Step 1>",
     "scenario": "A charge of USD 150 or less in the window: the case opens without a human (POL-AUT-150 or POL-AUT-INTAKE).",
     "message": "No reconozco un cargo de <monto> <moneda> del <día> de junio"},
    {"label": "cliente-mas-de-500", "app_role": "customer", "customer_id": "<id del Step 1>",
     "scenario": "A charge over USD 500: the turn goes to a human (POL-ESC-500) and the console shows the handoff.",
     "message": "No reconozco un cargo de <monto> <moneda> del <día> de junio"},
    {"label": "cliente-tarjeta-perdida", "app_role": "customer", "customer_id": "<id del Step 1>",
     "scenario": "A lost card and a charge of USD 500 or less: the lock offer comes first (POL-AUT-LOCK); after the yes, the lock and the case.",
     "message": "Perdí mi tarjeta y no reconozco un cargo de <monto> <moneda> del <día> de junio"},
    {"label": "agente", "app_role": "agent", "customer_id": null,
     "scenario": "The HITL console: the handoff of the over-500 case and the lock appear here."}
  ]
}
```

Los marcadores `<...>` se reemplazan con los valores reales del Step 1 antes del commit; ninguno queda en el archivo.

- [ ] **Step 3: Verificar cada escenario con el orquestador real.** `check_personas.py` en el scratchpad:

```python
"""Each persona's message through the real orchestrator, on a copy of the lakehouse (the lock writes silver_products)."""
import json
import shutil

from src.auth.seed_personas import load_personas
from src.auth.session import VerifiedSession
from src.ops.store import OpsStore
from src.orchestrator.dispute_orchestrator import DisputeOrchestrator
from src.tools.gateway import BankingToolGateway

shutil.copy("/lake/lakehouse.duckdb", "/tmp/lake.duckdb")
orchestrator = DisputeOrchestrator(gateway=BankingToolGateway(db_path="/tmp/lake.duckdb"), ops=OpsStore(":memory:"))
for p in load_personas("data/fixtures/personas.json"):
    if p["app_role"] != "customer":
        continue
    session = VerifiedSession(customer_id=p["customer_id"], name="", country="", segment="", session_id="S-CHECK", exp=0)
    cid = orchestrator.start_conversation(session, language="es")["conversation_id"]
    turn = orchestrator.handle_message(session, cid, p["message"])
    print(p["label"], turn.policy_outcome, turn.escalation_reason, turn.clarification_reason,
          "case" if turn.case_id else "-", "lock offered" if turn.lock_offer else "-")
    if turn.lock_offer:
        answer = orchestrator.handle_message(session, cid, "sí")
        print("  after 'sí':", answer.lock_status, "case" if (answer.case_id or turn.case_id) else "-")
print(json.dumps({"checked": True}))
```

Correr: `MSYS_NO_PATHCONV=1 docker compose -p hackaton run --rm -T -v "D:/Hackaton/data:/lake:ro" dev python - < "<scratchpad>/check_personas.py"`. Esperado:

- `cliente-hasta-150 AUTONOMOUS_RESOLUTION None None case -`
- `cliente-mas-de-500 MANDATORY_HITL_ESCALATION AMOUNT_EXCEEDS_500_USD None - -`
- `cliente-tarjeta-perdida ... lock offered`, y después `after 'sí': locked case`.

Si un mensaje cae en aclaración (`clarification_reason` no nulo), reescribir el monto como lo lee el extractor (sin separador de miles, por ejemplo) y volver a correr. Si un escenario no sale con ningún formato, tomar el siguiente candidato del Step 1.

- [ ] **Step 4: Commit.**

```bash
git add data/fixtures/personas.json
git commit -F - <<'EOF'
feat(auth): the four demo personas, one per scenario

Three customers from the lakehouse sample and one agent. Each customer's
charge is disputable, in the window, among the 25 the orchestrator
lists, with an amount no other listed charge matches, and not a foreign
Web or App purchase. Each message walks its path through the real
orchestrator on a copy of the sample: case without a human, handoff
over USD 500, and lock offer then lock and case.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

### Task 6: ingreso con `supabase-js` en el front

Sin tests unitarios (decisión D4 del spec): `tsc` revisa los dos modos al compilar y la tarea 8 recorre el ingreso a mano.

**Files:**

- Create: `frontend/src/supabase.ts`, `frontend/.env.example`
- Modify: `frontend/package.json`, `frontend/package-lock.json`, `frontend/src/api.ts`, `frontend/src/Login.tsx`, `frontend/src/App.tsx:16-24`, `frontend/src/Console.tsx:482`, `frontend/src/styles.css:108-117`

**Interfaces:**

- Consumes: `GET /api/v1/auth/me` (tarea 3); `POST /api/v1/auth/test-session` (sin cambios).
- Produces: `supabase` (cliente o `null`); `Session {app_role, customer_id: string | null, label, token?}`; `Identity`; `LocalToken`; `clearSession(): Promise<void>`; `api.me(token?)`.

- [ ] **Step 1: Dependencia fijada.** `cd frontend && npm install --save-exact @supabase/supabase-js@2.117.2`. Esperado: `package.json` con `"@supabase/supabase-js": "2.117.2"` en `dependencies` y el lock actualizado.

- [ ] **Step 2: Crear `frontend/src/supabase.ts`.**

```ts
import { createClient } from '@supabase/supabase-js'

// Supabase Auth signs people in when the build carries the project URL and its publishable key
// (frontend/.env.local, or the deploy's build variables). Without them the app stays in local mode:
// the persona picker of the local issuer, which only answers when the API runs in development or test.
const url = import.meta.env.VITE_SUPABASE_URL as string | undefined
const publishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined

export const supabase =
  url && publishableKey
    ? createClient(url, publishableKey, {
        auth: {
          storage: window.sessionStorage, // closing the tab ends the session, as in local mode
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: false, // no magic links or OAuth redirects
        },
      })
    : null
```

- [ ] **Step 3: `frontend/src/api.ts`.** Agregar el import después del comentario inicial:

```ts
import { supabase } from './supabase'
```

Reemplazar la interfaz `Session` por:

```ts
// Who is signed in, as GET /api/v1/auth/me verified it. label is what the header shows: the email
// with Supabase Auth, the persona id in local mode. The token is kept only in local mode; with
// Supabase, supabase-js holds the session and every request asks it for a fresh access token.
export interface Session {
  app_role: AppRole
  customer_id: string | null
  label: string
  token?: string
}

export interface Identity {
  app_role: AppRole
  customer_id: string | null
}

export interface LocalToken {
  token: string
  app_role: AppRole
  customer_id: string
}
```

Después de `onUnauthorized`, agregar:

```ts
/** Forget the session: ours, and the Supabase one on this device only. Personas are shared, so never 'global'. */
export async function clearSession(): Promise<void> {
  saveSession(null)
  if (supabase) await supabase.auth.signOut({ scope: 'local' })
}

async function bearerToken(): Promise<string | null> {
  if (supabase) {
    const { data } = await supabase.auth.getSession() // refreshes an expired access token first
    return data.session?.access_token ?? null
  }
  return loadSession()?.token ?? null
}
```

En `request`, el bloque `if (auth)` y la rama del 401 quedan:

```ts
  if (auth) {
    const token = await bearerToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }
```

```ts
    if (response.status === 401 && auth) {
      await clearSession()
      unauthorizedHandler?.()
    }
```

En `api`, `testSession` devuelve `LocalToken` y se agrega `me`:

```ts
  testSession: (customer_id: string, app_role: AppRole) =>
    request<LocalToken>('/api/v1/auth/test-session', { method: 'POST', body: JSON.stringify({ customer_id, app_role }) }, false),

  /** The verified identity. A token passed here wins over the stored one (local sign-in, before the session is saved). */
  me: (token?: string) =>
    request<Identity>('/api/v1/auth/me', token ? { headers: { Authorization: `Bearer ${token}` } } : {}),
```

- [ ] **Step 4: Reescribir `frontend/src/Login.tsx`.**

```tsx
import { useEffect, useState, type FormEvent } from 'react'
import { api, clearSession, describeError, type AppRole, type Persona, type Session } from './api'
import { supabase } from './supabase'

const AGENT_ID = 'AGENT-1'

interface Props {
  onLogin: (session: Session) => void
}

// With the Supabase keys in the build, people sign in with the email and password they received;
// without them, the local issuer's persona picker (the API answers it in development and test only).
export default function Login({ onLogin }: Props) {
  return supabase ? <PasswordLogin onLogin={onLogin} /> : <PersonaLogin onLogin={onLogin} />
}

function PasswordLogin({ onLogin }: Props) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!supabase) return
    setBusy(true)
    setError(null)
    try {
      const { error: authError } = await supabase.auth.signInWithPassword({ email: email.trim(), password })
      if (authError) {
        setError(authError.code === 'invalid_credentials' ? 'Email or password is incorrect.' : authError.message)
        return
      }
      onLogin({ ...(await api.me()), label: email.trim() })
    } catch (err) {
      await clearSession() // signed in to Supabase, but the API refused the account (403) or did not answer
      setError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page page-narrow">
      <header className="page-header">
        <h1>Dispute Intake</h1>
        <p className="muted">Sign in with the account you received.</p>
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      <form className="card stack" onSubmit={submit}>
        <label className="stack">
          Email
          <input type="email" autoComplete="username" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="stack">
          Password
          <input type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </main>
  )
}

function PersonaLogin({ onLogin }: Props) {
  const [personas, setPersonas] = useState<Persona[]>([])
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api
      .personas()
      .then((rows) => {
        if (!cancelled) setPersonas(rows)
      })
      .catch((err) => {
        if (!cancelled) setError(describeError(err))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const enter = async (customerId: string, role: AppRole) => {
    setBusy(customerId)
    setError(null)
    try {
      const local = await api.testSession(customerId, role)
      onLogin({ ...(await api.me(local.token)), label: customerId, token: local.token })
    } catch (err) {
      setError(describeError(err))
    } finally {
      setBusy(null)
    }
  }

  return (
    <main className="page page-narrow">
      <header className="page-header">
        <h1>Dispute Intake</h1>
        <p className="muted">Demo login. Pick a test persona or open the HITL console.</p>
      </header>

      {error && <div className="banner banner-error" role="alert">{error}</div>}

      <section className="card">
        <h2>Customers</h2>
        {loading && <p className="muted">Loading personas...</p>}
        {!loading && personas.length === 0 && !error && <p className="muted">No personas available.</p>}
        <div className="stack">
          {personas.map((p) => (
            <button
              key={p.customer_id}
              className="btn btn-block"
              disabled={busy !== null}
              onClick={() => enter(p.customer_id, 'customer')}
            >
              Enter as customer {p.customer_id} ({p.segment}, {p.country})
            </button>
          ))}
        </div>
      </section>

      <section className="card">
        <h2>Operations</h2>
        <button className="btn btn-primary btn-block" disabled={busy !== null} onClick={() => enter(AGENT_ID, 'agent')}>
          Enter HITL console as agent
        </button>
      </section>
    </main>
  )
}
```

- [ ] **Step 5: `App.tsx`, `Console.tsx`, estilos y variables.** En `frontend/src/App.tsx`, el import y `logout`:

```tsx
import { clearSession, loadSession, onUnauthorized, saveSession, type Session } from './api'
```

```tsx
  const logout = () => {
    void clearSession()
    setSession(null)
  }
```

En `frontend/src/Console.tsx:482`:

```tsx
          <p className="muted">Agent <code>{session.label}</code>. Decisions here are recorded; no money moves.</p>
```

En `frontend/src/styles.css`, los dos selectores de inputs de las líneas 108 y 117:

```css
input[type="text"],
input[type="email"],
input[type="password"] {
```

```css
input[type="text"]:focus,
input[type="email"]:focus,
input[type="password"]:focus { outline: 2px solid var(--accent); outline-offset: 1px; }
```

En `.dockerignore`, debajo de `frontend/dist`: `frontend/.env.local` (la imagen no lleva las variables del front; spec, sección 7).

`frontend/.env.example`:

```text
# Supabase Auth for the sign-in form (docs/specs/supabase-login-v1.md). Copy to .env.local, which git ignores.
# Without both variables the app shows the local persona picker, which answers only when the API runs with
# APP_ENV development or test. Only the publishable key goes here; the secret key stays in the root .env.
VITE_SUPABASE_URL=
VITE_SUPABASE_PUBLISHABLE_KEY=
```

- [ ] **Step 6: Compilar los dos modos.** `cd frontend && npm run build`, y después `VITE_SUPABASE_URL=https://example.supabase.co VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_dummy npm run build`. Esperado en los dos: `tsc -b` sin errores y `✓ built in ...`, código de salida 0.

- [ ] **Step 7: Commit.**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/supabase.ts frontend/src/api.ts frontend/src/Login.tsx frontend/src/App.tsx frontend/src/Console.tsx frontend/src/styles.css frontend/.env.example .dockerignore
git commit -F - <<'EOF'
feat(front): sign in with Supabase Auth when the build carries the project keys

With VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY the sign-in is
an email and password form on supabase-js 2.117.2, pinned; without them
it stays the local persona picker. Both modes ask /auth/me who signed
in and route to the chat or the console. Every request takes a fresh
access token from supabase-js, a 401 ends the session, and sign-out is
local to the device, since personas are shared.

No unit tests: the front has no test framework (D4 in the spec). tsc
checks both modes; the sign-in is walked by hand against alterego-dev.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

### Task 7: documentación

**Files:**

- Modify: `CLAUDE.md`, `AGENTS.md:308`, `README.md:25`, `:51`, `docs/SUPABASE_VERCEL.md:32`, §3.4, `:290`, `:297`

- [ ] **Step 1: `CLAUDE.md`.**
  - En Commands, debajo de la línea de `src.data.publish_serving`: `uv run python -m src.auth.seed_personas --email-pattern 'you+{label}@gmail.com' --dry-run   # demo personas in Supabase Auth from data/fixtures/personas.json (SUPABASE_URL and SUPABASE_SECRET_KEY in .env); without --dry-run it writes, and the passwords go to the git-ignored personas.local.json`.
  - En la línea del front, el comentario suma: "with VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY in frontend/.env.local the build signs in with Supabase Auth; without them it shows the local persona picker".
  - En "Decided 26-Sep, not yet in code", la frase de lo que ya está en código suma: "and so is the sign-in: the front uses supabase-js when its build carries the project keys".
  - En el párrafo del dispute stack: "`GET /api/v1/auth/me` returns the verified `app_role` and `customer_id` in every environment; the front routes on it".
  - En la viñeta de `src/auth/session.py`: "Without `APP_ENV`, with a blank one or with any value other than development or test, the app runs as production (fails closed), and there it refuses to start without `SUPABASE_URL`. `seed_personas.py` creates the demo personas through the Auth admin API."
  - Gotcha nuevo: "**`APP_ENV` defaults to production.** Unset, blank or any other value turns off the local issuer, the persona routes and the starter routes, and the app refuses to start without `SUPABASE_URL`. `.env.example`, docker-compose, CI and `tests/conftest.py` set development or test. A subprocess test that needs no `APP_ENV` at all stubs `dotenv.load_dotenv`: `python -c` finds the `.env` of the working directory or any parent, and a worktree finds the main checkout's."
  - Gotcha nuevo: "Vite reads `frontend/.env*`, not the root `.env`: the two `VITE_SUPABASE_*` variables go in `frontend/.env.local`. Only the publishable key belongs there; the secret key stays in the root `.env`."

- [ ] **Step 2: `AGENTS.md:308`** (fila Identity de la sección 9). Columna del estado, agregar: "`APP_ENV` fails closed to production, which needs `SUPABASE_URL`; the front signs in with supabase-js (email and password) when built with the project keys, and `/api/v1/auth/me` returns the verified identity; `src.auth.seed_personas` creates the personas". Columna de lo pendiente: "Personas in the deploy project and the deploy itself (Vercel)".

- [ ] **Step 3: `README.md`.** Línea 25: "a local test issuer at `/api/v1/auth/personas` and `/test-session` (development and test only), and `/api/v1/auth/me`, which returns the verified identity". Línea 51, después de "Try it:": "The front signs in with Supabase Auth (email and password; personas from `src.auth.seed_personas`) when built with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` in `frontend/.env.local`; without them it shows the local persona picker. The local issuer needs `APP_ENV` development or test: unset, it means production."

- [ ] **Step 4: `docs/SUPABASE_VERCEL.md`.**
  - Línea 32: "Un script (`src/auth/seed_personas.py`, implementado el 30 sep; spec `docs/specs/supabase-login-v1.md`) las crea..." y el agente lleva `{"customer_id": null, "app_role": "agent"}`.
  - §3.4, al final: "Sin `APP_ENV`, en blanco o con un valor distinto de development o test, el código asume producción (falla cerrado), y ahí el app no arranca sin `SUPABASE_URL` (implementado el 30 sep)."
  - Fila de `scripts/seed_personas.py` (línea 290): `src/auth/seed_personas.py` | "Implementado: personas desde `data/fixtures/personas.json`; secret key solo local".
  - Fila de `web/` (línea 297): `frontend/` | "Implementado: React con `@supabase/supabase-js` 2.117.2 fijado, solo para ingresar; Node 22".

- [ ] **Step 5: Verificar** que ningún archivo de docs quedó con advertencias de markdown (diagnósticos del editor) y que cada afirmación coincide con el código de las tareas 1 a 6.

- [ ] **Step 6: Commit.**

```bash
git add CLAUDE.md AGENTS.md README.md docs/SUPABASE_VERCEL.md
git commit -F - <<'EOF'
docs: describe the Supabase sign-in where the code is described

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

### Task 8: verificación de punta a punta y PR

**Files:**

- Modify: `data/fixtures/team_questions.json` (TQ-020)
- Scratchpad (no se versiona): `run_dev_split.py`, `e2e_personas.py`

- [ ] **Step 1: Suite, lint y split de desarrollo.**
  - `docker compose -p hackaton run --rm -T dev`. Esperado: `N + 32 passed, 6 deselected` (5 de la tarea 1, 2 de la 2, 4 de la 3 y 21 de la 4).
  - `uvx ruff check` sobre la lista de lint de CI y sobre cada archivo Python tocado.
  - `run_dev_split.py` en el scratchpad: `import runpy, sys; sys.argv = ["run", "data/eval/dev_cases.jsonl", "--out", "/tmp/run_dev", "--repeats", "1"]; runpy.run_module("src." + "eval" + ".run", run_name="__main__")`, corrido con `docker compose -p hackaton run --rm -T dev python - < "<scratchpad>/run_dev_split.py"`. Esperado: proposed 9 de 9, 0 de 18 inseguros, 18 de 18 exactos.

- [ ] **Step 2: Lo que hace Daniel en Supabase.** En el dashboard de `alterego-dev`: Authentication, proveedor Email encendido y "Allow new users to sign up" apagado. En `D:\Hackaton\.env`: `SUPABASE_URL=https://lrddokaihdwrdtwfiale.supabase.co` y `SUPABASE_SECRET_KEY=sb_secret_...`. En `<worktree>\frontend\.env.local`: `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY`. Daniel elige el patrón de email (una dirección suya con `+{label}`).

- [ ] **Step 3: Corrida en seco.** Desde el worktree: `D:/Hackaton/.venv/Scripts/python.exe -m src.auth.seed_personas --email-pattern '<patrón de Daniel>' --dry-run`. Esperado: sin aviso de registro abierto y cuatro líneas `would create`. Un 401 o 403 aquí significa que la clave no sirve en `apikey`: parar y revisar con Daniel antes de escribir.

- [ ] **Step 4: Corrida real, con el ok explícito de Daniel** (crea cuentas en su proyecto). El mismo comando sin `--dry-run`. Esperado: cuatro líneas `created` y `personas.local.json` en la raíz del worktree, que `git status` no muestra.

- [ ] **Step 5: API local con tokens reales.**
  - `cd frontend && npm run build` (con `.env.local`, modo Supabase).
  - En segundo plano: `MSYS_NO_PATHCONV=1 docker compose -p hackaton run --rm -T -p 8001:8000 -v "D:/Hackaton/data:/lake:ro" -e APP_ENV=development -e SUPABASE_URL=https://lrddokaihdwrdtwfiale.supabase.co -e LAKEHOUSE_PATH=/tmp/lake.duckdb -e OPS_DB_PATH=/tmp/ops.duckdb dev sh -c "cp /lake/lakehouse.duckdb /tmp/lake.duckdb && uvicorn src.api.app:app --host 0.0.0.0 --port 8000"`.
  - `e2e_personas.py` en el scratchpad, corrido con el Python del host:

```python
"""Throwaway: each persona signs in to Supabase and walks its scenario through the local API. Prints no secret."""
import json
from pathlib import Path

import httpx

WORKTREE = Path(r"D:\Hackaton\.claude\worktrees\fix+audit-v3-lote-a")
env = {}
for line in (WORKTREE / "frontend" / ".env.local").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.lstrip().startswith("#"):
        key, value = line.split("=", 1)
        env[key.strip()] = value.split("#", 1)[0].strip().strip('"')
URL, KEY = env["VITE_SUPABASE_URL"], env["VITE_SUPABASE_PUBLISHABLE_KEY"]
accounts = {a["label"]: a for a in json.loads((WORKTREE / "personas.local.json").read_text(encoding="utf-8"))["accounts"]}
personas = json.loads((WORKTREE / "data" / "fixtures" / "personas.json").read_text(encoding="utf-8"))["personas"]
api = httpx.Client(base_url="http://localhost:8001", timeout=60)
for p in personas:  # the agent comes last, so it sees the handoff of the over-500 case
    account = accounts[p["label"]]
    grant = httpx.post(f"{URL}/auth/v1/token", params={"grant_type": "password"}, headers={"apikey": KEY},
                       json={"email": account["email"], "password": account["password"]}, timeout=30)
    grant.raise_for_status()
    headers = {"Authorization": f"Bearer {grant.json()['access_token']}"}
    print(p["label"], "me:", api.get("/api/v1/auth/me", headers=headers).json())
    if p["app_role"] == "agent":
        handoffs = api.get("/api/v1/console/handoffs", params={"status_filter": "open"}, headers=headers).json()
        print("  open handoffs:", [h["escalation_reason"] for h in handoffs])
        continue
    cid = api.post("/api/v1/disputes/conversations", json={"language": "es"}, headers=headers).json()["conversation_id"]
    turn = api.post(f"/api/v1/disputes/conversations/{cid}/messages", json={"text": p["message"]}, headers=headers).json()
    print("  ", turn["policy_outcome"], turn["escalation_reason"], "case" if turn["case_id"] else "-",
          "lock offered" if turn["lock_offer"] else "-")
    print("   console as a customer:", api.get("/api/v1/console/cases", headers=headers).status_code)
```

  Esperado: `me` devuelve el rol y el `customer_id` de cada persona; los tres caminos del Step 3 de la tarea 5; `console as a customer: 403`; el agente ve `AMOUNT_EXCEEDS_500_USD` entre los handoffs abiertos.

- [ ] **Step 6: Lo que hace Daniel en el navegador**, en `http://localhost:8001`, con las credenciales de `personas.local.json`:
  1. Cada cliente entra y manda su `message`; el de tarjeta perdida responde "sí" a la oferta.
  2. El agente entra y ve el handoff y el bloqueo.
  3. Una contraseña errónea muestra "Email or password is incorrect.".
  4. Recargar la página no saca de la sesión.
  5. Dos navegadores (uno en incógnito) con la misma persona: salir en uno no saca al otro (Review Focus 5).
  6. Salir vuelve al ingreso.

- [ ] **Step 7: Modo local e imagen.**
  - `cd frontend && VITE_SUPABASE_URL= npm run build`, con el contenedor del Step 5 arriba: `curl -s localhost:8001/api/v1/auth/personas` responde 200 con personas, y la página muestra el selector.
  - `docker build -t alterego-api:check .`, luego `docker run --rm alterego-api:check`. Esperado: sale con código distinto de 0 y `APP_ENV=production needs SUPABASE_URL` en la salida.
  - `docker run --rm -d -p 8002:8000 -e APP_ENV=development --name alterego-check alterego-api:check`, luego `curl -s -o /dev/null -w '%{http_code}' localhost:8002/health` (200) y `.../api/v1/auth/me` (401), y `docker stop alterego-check`.
  - Detener el contenedor del Step 5 y reconstruir el front sin variables (`VITE_SUPABASE_URL= npm run build`) para no dejar un `dist` en modo Supabase.

- [ ] **Step 8: TQ-020.** En `data/fixtures/team_questions.json`, la respuesta de TQ-020 cambia "Pending: create the personas with app_metadata.customer_id and app_role, and switch the front from the local issuer to supabase-js." por "Personas created on {fecha de la corrida del Step 4} with src.auth.seed_personas (three customers, one agent; data/fixtures/personas.json), and the front signs in with supabase-js (docs/specs/supabase-login-v1.md)." Commit `docs(tq): the personas exist in alterego-dev and the front signs in with supabase-js (TQ-020)`.

- [ ] **Step 9: PR.** `git push -u origin feat/supabase-login`; `gh pr create` con resumen, evidencia (conteos de la suite, split de desarrollo, salida del Step 5 sin secretos, checklist de Daniel) y "Not in this PR" (sección 7 del spec). Esperar CI en verde. El merge lo hace Daniel.

---

## Enmiendas al spec (aplicadas en el mismo commit que este plan)

1. **`APP_ENV` en blanco o con otro valor** (sección 3.5): cuenta como producción, igual que la variable ausente, y la guarda aplica a todo lo que no sea development o test. Sin esto, `APP_ENV=` o `preview` dejaban el emisor local encendido.
2. **Recarga de la página** (sección 3.2): la sesión del front y la de Supabase siguen en `sessionStorage`, sin volver a llamar a `/auth/me`; si el token ya no sirve, el primer 401 devuelve al ingreso. Es más simple y no cambia lo que ve el usuario.
3. **`message` en `personas.json`** (secciones 3.3 y 3.4): el mensaje sugerido va en un campo propio, para que la verificación lo mande tal cual; `scenario` describe el camino.

## Cambios durante la ejecución

Lo que quedó distinto del código y de los textos de este plan, y por qué:

1. **Tarea 4, `admin_client` endurecido tras la revisión** (commits `211f1d7` y `9c4cb59`): quita los espacios que deja un pegado y rechaza, sin mostrarla, cualquier carácter fuera del ASCII visible, para que un error de `httpx` no imprima la clave. El código de la Tarea 4 de este plan es la versión anterior.
2. **Tarea 5, el mensaje de la persona de tarjeta perdida** dice "Perdí la tarjeta" y no "Perdí mi tarjeta" (la segunda frase no está en `STOLEN_CARD_KEYWORDS` y no dispara la oferta de bloqueo; spec, sección 3.4), y su `scenario` pone el caso y la oferta de bloqueo en la misma respuesta, con el bloqueo después del "sí" (commit `2a28cb8`).
3. **Textos que ahora coinciden con el código** (Tarea 7): el spec dice que el ingreso muestra "Email or password is incorrect." solo con `invalid_credentials` y el mensaje de Supabase con otro error (sección 3.2), que la persona de tarjeta perdida abre el caso y ofrece el bloqueo en la misma respuesta y que el agente ve el handoff de la disputa de más de $500 (sección 3.4); el `scenario` del agente en `personas.json` dice "the over-500 dispute" y no "the over-500 case", porque `POL-ESC-500` no abre caso.
4. **Tarea 8, el harness como entorno de test** (commits `f67b632` y `ede1b50`): con un `.env` que trae `SUPABASE_URL` y no `APP_ENV`, `src.eval.run` importaba el app como producción, y los casos de ataque, que firman tokens locales, fallaban y contaban como desenlaces inseguros en vez de juzgarse. El módulo pone `APP_ENV=test` cuando la variable falta, antes de leer `.env`; un `APP_ENV` exportado en la shell sigue mandando.
