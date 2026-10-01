# Spec: ingreso con Supabase Auth en la demo (v1)

Estado: diseño aprobado por secciones en el chat el 2026-09-30; este documento lo fija para su revisión escrita. Rama: `feat/supabase-login`, desde `main` en `c1a9bfd`. Hallazgo: AUD-02 de la auditoría v3 (plan v3, ítem 6). Enmendado el mismo día por el plan de implementación (`docs/specs/supabase-login-v1-plan.md`, sección final): `APP_ENV` en blanco u otro valor, la recarga de la página y el campo `message`.

- **Porción:** ingreso con Supabase Auth en el front (`@supabase/supabase-js`), el endpoint `GET /api/v1/auth/me`, el script que crea las personas en Supabase Auth y un `APP_ENV` que falla cerrado, con una guarda de arranque.
- **Manda:** `docs/SUPABASE_VERCEL.md` sección 3 (identidad, decidida el 26-Sep) y sección 7 (el desarrollo local no necesita cuenta de Supabase), AUD-02 en `docs/reviews/2026-09-30-auditoria-adversarial-docs-resultados-codigo.md` y TQ-020 (proyecto `alterego-dev`, `https://lrddokaihdwrdtwfiale.supabase.co`, una clave ES256 en su JWKS).
- **Ya en el código:** `SessionVerifier` (`src/auth/session.py`) verifica tokens ES256 de Supabase contra el JWKS del proyecto y lee `customer_id` y `app_role` de `app_metadata`. Este lote no lo cambia.
- **Fuera:** sección 7 de este documento.

## 1. Problema

La demo publicada no tiene ingreso. `frontend/src/Login.tsx` usa `/api/v1/auth/personas` y `/api/v1/auth/test-session`, que responden 404 fuera de `APP_ENV` development o test (`src/api/dispute_routes.py`), y el front no trae `supabase-js`.

El problema contrario es peor. `APP_ENV` vale `development` cuando nadie lo define (`src/core/config.py`, `src/auth/session.py`) y la imagen Docker lo fija en `development` (`Dockerfile`, etapa final). Un deploy que olvide la variable deja abierto el emisor local: cualquiera pide en `/api/v1/auth/test-session` un token de cualquier cliente. El paso de evaluación del CI ya corre sin la variable.

## 2. Decisiones del 30-Sep

| Id | Decisión | Descartado y por qué |
| --- | --- | --- |
| D1 | Sin `APP_ENV`, el código asume `production`; en blanco o con otro valor, también | `development` por defecto: un olvido en el deploy abre el emisor local |
| D2 | Tres clientes, uno por escenario de la demo, y un agente | Los 6 del selector actual (sin curar: pueden no tener cargos disputables); un solo cliente (no muestra la demo) |
| D3 | `supabase-js` en el navegador cuando el build trae las variables de Supabase; el selector de personas sin ellas | Ingreso a través del API (las contraseñas pasarían por nuestro API, la renovación quedaría a nuestro cargo y el límite de Auth por IP sumaría a todos los usuarios detrás de Vercel); solo `supabase-js` (el desarrollo local necesitaría una cuenta de Supabase, contra la sección 7 del diseño) |
| D4 | El front se verifica sin framework de tests: `tsc` en CI más la verificación manual de la sección 5 | Agregar vitest para este lote. Playwright sigue pendiente (AUD-15) |

## 3. Diseño

### 3.1 API: `GET /api/v1/auth/me`

Va en `src/api/dispute_routes.py`, detrás de `get_current_session`, y devuelve la identidad tal como el API la verificó:

```json
{"app_role": "customer", "customer_id": "CLI-..."}
```

El agente recibe `{"app_role": "agent", "customer_id": null}`. Responde con cualquier `APP_ENV`: no pasa por `_ensure_local_issuer`. Sin token o con uno inválido, 401; con un token de cliente sin `customer_id`, 403 (los dos ya salen de `get_current_session`).

### 3.2 Front

- **Dependencia.** `@supabase/supabase-js` fijado en `2.117.2` (la última el 25-Sep), sin rango.
- **`frontend/src/supabase.ts`.** Crea el cliente solo si el build trae `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY`; si falta alguna, exporta `null` y el front queda en modo local. Opciones de `auth`: `storage: window.sessionStorage` (cerrar la pestaña cierra la sesión, como hoy), `persistSession: true`, `autoRefreshToken: true` y `detectSessionInUrl: false` (no hay magic links ni OAuth).
- **`Login.tsx`.** En modo Supabase, un formulario de email y contraseña que llama a `signInWithPassword`; si falla, dice solo "Email or password is incorrect.". No hay registro ni recuperación de contraseña. En modo local, el selector de personas de hoy.
- **Después del ingreso, en los dos modos,** el front llama a `/auth/me` y elige el chat o la consola con lo que responde. Si responde 403, cierra la sesión de Supabase y muestra el detalle del API. Al recargar la página, la sesión del front y la de Supabase siguen en `sessionStorage`; si el token ya no sirve, el primer 401 devuelve al ingreso.
- **`api.ts`.** En modo Supabase, cada petición toma el token de `supabase.auth.getSession()`, que lo renueva si venció: el chat no se cae al cumplir la hora. En modo local, el token sigue en `sessionStorage` como hoy. Un 401 cierra la sesión en los dos modos (en Supabase, `signOut({ scope: 'local' })`).
- **`Session` del front:** `{app_role, customer_id, label}`, más el token solo en modo local. `label` es el email en modo Supabase y el id de la persona en modo local; la consola muestra `label` porque el agente no tiene `customer_id`.
- **Variables.** `frontend/.env.example` con las dos variables vacías; las reales en `frontend/.env.local`, que git ignora (`*.local` en `frontend/.gitignore`). Vite lee los `.env` de `frontend/`, no los de la raíz.
- Los textos del ingreso siguen en inglés, como hoy; el chat sigue en ES/PT.

La publishable key es pública por diseño: viaja en el bundle. Con el registro apagado nadie crea cuentas, y una cuenta creada igual recibe 403 en todo, porque no tiene `customer_id` ni rol de agente.

### 3.3 Script de personas

`src/auth/seed_personas.py`, corrido con `uv run python -m src.auth.seed_personas`. Sigue el patrón de `src.data.publish_serving`, la otra herramienta de operación que escribe en Supabase. No guarda secretos: los lee del entorno al correr, y en Vercel la secret key nunca existe.

```bash
uv run python -m src.auth.seed_personas --email-pattern 'tu.correo+{label}@gmail.com' --dry-run
uv run python -m src.auth.seed_personas --email-pattern 'tu.correo+{label}@gmail.com'
```

Opciones: `--personas` (por defecto `data/fixtures/personas.json`), `--out` (por defecto `personas.local.json`), `--dry-run` y `--reset-passwords`.

- **Entrada.** `data/fixtures/personas.json`, versionado, `team-generated`:

  ```json
  {"provenance": "team-generated", "personas": [
    {"label": "cliente-hasta-150", "app_role": "customer", "customer_id": "CLI-...", "scenario": "...", "message": "..."},
    {"label": "cliente-mas-de-500", "app_role": "customer", "customer_id": "CLI-...", "scenario": "...", "message": "..."},
    {"label": "cliente-tarjeta-perdida", "app_role": "customer", "customer_id": "CLI-...", "scenario": "...", "message": "..."},
    {"label": "agente", "app_role": "agent", "customer_id": null, "scenario": "..."}
  ]}
  ```

- **Emails.** Salen de `--email-pattern`, que es obligatorio; ninguna dirección entra en git. Supabase no envía correos: el script crea las cuentas con `email_confirm: true`.
- **Claves.** `SUPABASE_URL` y `SUPABASE_SECRET_KEY` del `.env` local. El script rechaza una clave que no empiece con `sb_secret_` (por ejemplo, la publishable pegada por error) antes de cualquier llamada.
- **Llamadas,** con `httpx` (ya es dependencia) y la clave solo en el header `apikey`: según la guía de migración de Supabase, las claves nuevas no son JWT y se rechazan como `Bearer`.
  - `GET /auth/v1/settings`: avisa si el registro público sigue encendido (`disable_signup` falso).
  - `GET /auth/v1/admin/users`, página por página: encuentra cada persona por email.
  - Persona nueva: `POST /auth/v1/admin/users` con `email`, `password`, `email_confirm: true` y `app_metadata`.
  - Persona existente: `PUT /auth/v1/admin/users/{id}` solo con `app_metadata`; con `--reset-passwords`, también una contraseña nueva. Correr el script dos veces no duplica cuentas.
- **`app_metadata`.** Cliente: `{"customer_id": "CLI-...", "app_role": "customer"}`. Agente: `{"customer_id": null, "app_role": "agent"}`; el null explícito borra un id anterior. El script nunca escribe `user_metadata`, que el usuario puede editar.
- **Contraseñas.** `secrets.token_urlsafe(18)` para cada cuenta nueva o reseteada. Se escriben solo en `--out` (se agrega `personas.local.json` al `.gitignore`), una entrada por label: una cuenta creada o reseteada reemplaza la suya y las demás se conservan. El archivo se reescribe después de cada cuenta creada o reseteada, para que un error a mitad de camino no pierda contraseñas; si el archivo se pierde, `--reset-passwords` da contraseñas nuevas. Por pantalla salen el label, el rol, el `customer_id`, el email y la acción (`created`, `updated`, `would create`, `would update`), nunca una contraseña ni una clave. De ese archivo salen las credenciales del correo de entrega.
- **`--dry-run`.** Lee la configuración y los usuarios, imprime lo que haría y no escribe nada en Supabase ni en `--out`.
- **Validación,** antes de cualquier llamada: labels únicos, `app_role` en `customer` o `agent`, cada cliente con `customer_id`, el agente sin él y un `--email-pattern` que contenga `{label}` (sin él, todas las personas tendrían el mismo email). Un error de validación o una respuesta HTTP de error terminan con código distinto de 0.

### 3.4 Qué clientes son personas

Una consulta de solo lectura sobre la muestra del lakehouse (`data/lakehouse.duckdb`, en el contenedor `dev`) elige un cliente por escenario. "En ventana" es lo que dice `POL-WIN-60` (60 días por `process_date` hasta el 2026-06-17) y "disputable" es lo que dice `POL-DISP-TYPE` (`DISPUTABLE_STATUS` y `DISPUTABLE_TYPES` de `src/rules/dispute_policy.py`).

| Label | Criterio | Camino esperado |
| --- | --- | --- |
| `cliente-hasta-150` | Un cargo disputable en ventana de hasta $150 cuyo monto no repite ningún otro cargo del cliente | Abre el caso sin humano (`POL-AUT-150` o `POL-AUT-INTAKE`) |
| `cliente-mas-de-500` | Un cargo disputable en ventana de más de $500 con monto único | Pasa a humano (`POL-ESC-500`) |
| `cliente-tarjeta-perdida` | Una sola tarjeta activa y un cargo disputable en ventana de hasta $500 con monto único | Oferta de bloqueo (`POL-AUT-LOCK`); con el "sí", bloqueo y caso |
| `agente` | Sin cliente | Consola: ve el handoff del caso de más de $500 |

El cargo de `cliente-hasta-150` y el de `cliente-tarjeta-perdida` no son compras extranjeras por Web o App, para que `POL-ESC-ML-RISK` no cambie el camino cuando el deploy cargue el modelo; si el archivo del modelo está disponible, su puntaje queda además bajo el umbral del bundle. Cada cliente trae su `scenario` (el camino que muestra) y su `message` (el mensaje sugerido para la demo, con el monto y la moneda del cargo), que la verificación manda tal cual. Los ids se revisan en el PR.

Los `customer_id` son del dataset y quedan guardados en Supabase Auth, así que dependen de la respuesta de los mentores (TQ-032). Si dicen que no, se cambian por clientes del fixture del equipo; el código no cambia. El lote de deploy debe publicar estos clientes en `bank` (`data/serving_customers.json`, sección 4.2.1 del diseño).

### 3.5 `APP_ENV` falla cerrado

- `src/core/config.py` y `src/auth/session.py`: sin la variable, en blanco o con un valor distinto de `development` o `test`, `production`. El emisor local, las rutas de personas y las del starter quedan apagados.
- **Guarda de arranque.** Una función en `src/auth/session.py`, llamada al importar `src/api/app.py` junto a la guarda de SEC-03, levanta `RuntimeError` cuando `APP_ENV` no es `development` ni `test` y `SUPABASE_URL` está vacía, con el mensaje "APP_ENV={valor} needs SUPABASE_URL: without it no session token can be verified. Set SUPABASE_URL, or APP_ENV=development for local work." Sin esa URL nadie entra; mejor que el app no arranque a que responda 401 a todo.

| Dónde | Valor | Cambio |
| --- | --- | --- |
| `.env.example` | `development` | Un comentario: si falta, vale `production`. `SUPABASE_SECRET_KEY` vacía, solo para el script, nunca en Vercel ni en el front |
| `docker-compose.yml`, servicios `api` y `dev` | `development` y `test` | Ninguno |
| CI, paso de tests | `test` | Ninguno |
| CI, paso de evaluación | `test` | Nuevo: sus casos de ataque importan el app |
| `tests/conftest.py` | `test` | Nuevo: `os.environ.setdefault` antes de importar `src`, para que `uv run pytest` funcione sin `.env` (`load_dotenv` no pisa una variable definida) |
| `Dockerfile`, etapa final | `production` | Antes `development`: la imagen sola ya no arranca sin `SUPABASE_URL`, y `docker compose up` sigue igual |

## 4. Archivos

| Archivo | Cambio |
| --- | --- |
| `src/api/dispute_routes.py` | `GET /auth/me` |
| `src/auth/session.py`, `src/core/config.py`, `src/api/app.py` | Default `production` y guarda de arranque |
| `src/auth/seed_personas.py` | Nuevo |
| `data/fixtures/personas.json` | Nuevo, `team-generated` |
| `tests/test_dispute_api.py`, `tests/test_session_verifier.py`, `tests/test_seed_personas.py` (nuevo), `tests/conftest.py` | Tests de las secciones 3.1, 3.3 y 3.5 |
| `.github/workflows/ci.yml` | `APP_ENV: test` en la evaluación; el test nuevo entra en la lista de lint |
| `Dockerfile`, `.env.example`, `.gitignore` | Sección 3.5 y `personas.local.json` |
| `frontend/package.json`, `frontend/package-lock.json` | `@supabase/supabase-js` 2.117.2 |
| `frontend/src/supabase.ts` (nuevo), `api.ts`, `Login.tsx`, `App.tsx`, `Chat.tsx`, `Console.tsx`, `frontend/.env.example` (nuevo) | Sección 3.2 |
| `CLAUDE.md`, `AGENTS.md` sección 9, `README.md`, `docs/SUPABASE_VERCEL.md` (3.1 y 8) | El ingreso como queda |

## 5. Pruebas

**Automáticas.** Pares TDD (un commit `test` que falla y el `fix` que lo pone en verde, como en el lote A) para:

- `/auth/me`: un cliente recibe su `customer_id`; el agente, null; sin token, 401; un cliente sin `customer_id`, 403; responde con `APP_ENV` `production`.
- `APP_ENV`: sin la variable, en blanco o con otro valor (`preview`), el emisor local queda apagado; sin la variable o en blanco, el app corre como `production` (subproceso que anula `load_dotenv`, para que ningún `.env` lo contamine); con `production` o `preview` y sin `SUPABASE_URL`, el app no arranca y el mensaje sale por stderr. El test actual `test_the_app_starts_in_production_without_the_local_issuer` pasa a darle `SUPABASE_URL`.
- Script (`httpx.MockTransport`, sin red): una cuenta nueva lleva `app_metadata` y `email_confirm`, nunca `user_metadata`; el agente queda con `customer_id` null; una existente recibe solo `app_metadata` y su contraseña no cambia sin `--reset-passwords`; la clave viaja solo en `apikey`; una clave, un archivo o un patrón sin `{label}` fallan antes de llamar; si Supabase falla a mitad de camino, las contraseñas de las cuentas ya creadas quedan en `--out`; ninguna contraseña sale por pantalla; `--dry-run` no escribe; avisa si el registro sigue encendido.

Además: la suite completa en el contenedor `dev`, `ruff` en cada archivo tocado, el split de desarrollo sin cambios (18 de 18) y CI en verde, donde `tsc` revisa el código de los dos modos al compilar el front.

**Manuales, contra `alterego-dev`.**

1. Daniel, en el dashboard: deja el proveedor Email encendido y apaga "Allow new users to sign up"; pone `SUPABASE_URL` y `SUPABASE_SECRET_KEY` en `.env`, y `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY` en `frontend/.env.local`.
2. `seed_personas --dry-run`: confirma el header `apikey` y muestra el plan. La corrida real crea cuentas en el proyecto de Daniel, así que espera su aprobación.
3. API local (`APP_ENV=development`, `SUPABASE_URL`, el lakehouse del checkout principal) sirviendo el front construido en modo Supabase. Un script desechable fuera del repo toma las credenciales de `personas.local.json` sin imprimirlas, pide el token a Supabase y recorre `/auth/me` y el mensaje de cada escenario.
4. Daniel, en el navegador: entra con cada cliente y manda su mensaje; entra con el agente y ve el handoff del caso de más de $500; prueba una contraseña errónea; recarga la página sin perder la sesión; sale.
5. El modo local sigue: front sin variables y `docker compose up` con el selector de personas. La imagen sin variables no arranca y muestra el mensaje de la guarda.

## 6. Criterios de aceptación

1. Las cuatro personas entran en el front construido contra `alterego-dev`; cada cliente recorre su escenario y el agente abre la consola.
2. Sin `APP_ENV`, ni el app ni la imagen emiten tokens locales; en `production` sin `SUPABASE_URL`, el app no arranca.
3. El script crea o actualiza las cuatro personas sin duplicarlas y nunca muestra una contraseña.
4. El modo local funciona sin cuenta de Supabase.
5. CI en verde.

## 7. Fuera de este lote

La configuración y el deploy en Vercel; publicar `bank` y aplicar las migraciones en Supabase; el canario; el rate limit (AUD-18); la recuperación de contraseña; las personas del harness desplegado; Playwright (AUD-15); las variables `VITE_*` en la imagen Docker, que no es el destino del deploy.

## 8. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Las claves `sb_secret_` en el header `apikey` se comportan distinto de lo que dice la guía | La corrida en seco lo comprueba antes de crear cuentas |
| Los mentores no aceptan datos del dataset en Supabase (TQ-032) | Se cambian los ids por clientes del fixture del equipo; el código no cambia |
| Las personas son compartidas: el primer jurado que disputa un cargo deja su caso abierto, y el siguiente encuentra el caso ya abierto o la tarjeta ya bloqueada | El lote de deploy decide entre un juego de personas por jurado o un reinicio de `ops` para los clientes de la demo |
| La renovación del token a la hora no se ve en una prueba corta | `getSession()` renueva el token antes de cada petición; un 401 devuelve al ingreso |
| Borrar un usuario no revoca su token hasta que vence (1 hora) | Límite documentado en la sección 3.5 del diseño |
