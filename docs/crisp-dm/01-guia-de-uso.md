# Guía de uso

Cinco recorridos prácticos: probar la demo publicada, correr el sistema en local, reproducir la evaluación, reconstruir datos y modelo, y resolver los problemas frecuentes. Los bloques de comandos copian tal cual los que documenta el repo ([`CLAUDE.md`](../../CLAUDE.md), "Commands"; [`README.md`](../../README.md), "Quick start"); las variantes que no están ahí se marcan. Cómo está armado el despliegue se explica en [07-despliegue.md](07-despliegue.md).

Los comandos están en sintaxis de bash. En Windows PowerShell 5.1, `&&` no existe y el prefijo `VAR=valor comando` no funciona: separe con `;` y defina la variable antes (nota general de PowerShell, no del repo).

## 1. Probar la demo en producción

La demo está en <https://alterego-silk.vercel.app>. Corre en modo solo reglas más el explicador de políticas BM25: sin modelo de riesgo, sin Jev y sin respuestas redactadas por Claude (`README.md`, "Limitations").

### 1.1 Ingresar

1. Abra la URL. La pantalla pide email y contraseña: son cuentas de Supabase Auth creadas por script, y no hay registro desde la app ([`frontend/README.md`](../../frontend/README.md), "Sign-in"; [`docs/specs/supabase-login-v1.md`](../specs/supabase-login-v1.md) sec. 3.2).
2. Use las credenciales que el equipo comparte por privado. Salen de `personas.local.json`, un archivo que está en `.gitignore` y que escribe `src.auth.seed_personas` (spec, sec. 3.3). Nunca van en el repo, en un issue ni en un chat ([`docs/HANDOFF.md`](../HANDOFF.md) sec. 5).
3. Tras ingresar, el front lee `GET /api/v1/auth/me`. Un cliente ve el chat y el agente ve la consola.
4. La sesión vive en `sessionStorage`: termina al cerrar la pestaña. "Salir" cierra solo la sesión de ese navegador, porque cada persona de demo es una cuenta compartida (`frontend/README.md`).

### 1.2 Las cuatro personas

Las personas vienen de [`data/fixtures/personas.json`](../../data/fixtures/personas.json) (`team-generated`); los `customer_id` son clientes de la muestra del dataset (`synthetic-organizer`) publicados en `bank` ([`data/serving_customers.json`](../../data/serving_customers.json)).

| Label | Rol | `customer_id` | Escenario | Mensaje sugerido | Resultado esperado |
| --- | --- | --- | --- | --- | --- |
| `cliente-hasta-150` | Cliente | `CLI-00SA0N9OQTM0` | Un cargo de 150 USD o menos, en ventana | `No reconozco un cargo de 113.65 USD del 3 de junio` | `AUTONOMOUS_RESOLUTION`: caso abierto sin humano, con `POL-AUT-150` (candidato a crédito que decide un humano) o `POL-AUT-INTAKE`. **Hoy no**: ver 1.5 |
| `cliente-mas-de-500` | Cliente | `CLI-0085D5JD85CX` | Un cargo de más de 500 USD | `No reconozco un cargo de 4259.97 USD del 12 de junio` | `MANDATORY_HITL_ESCALATION` con `POL-ESC-500`; la respuesta trae la referencia del handoff y la consola lo muestra |
| `cliente-tarjeta-perdida` | Cliente | `CLI-02ARMH0UANWD` | Tarjeta perdida, una sola tarjeta activa y un cargo de 500 USD o menos | `Perdí la tarjeta y no reconozco un cargo de 168.88 USD del 9 de junio` | Caso abierto y oferta de bloqueo en la misma respuesta (`POL-AUT-LOCK`). La tarjeta se bloquea solo después del "Sí" del cliente |
| `agente` | Agente | Ninguno | Consola HITL | No aplica | Ve el handoff de la disputa de más de 500 USD y el bloqueo |

Fuentes de la tabla: `data/fixtures/personas.json`; `docs/specs/supabase-login-v1.md` sec. 3.4; [`src/rules/dispute_policy.py`](../../src/rules/dispute_policy.py). El cargo de 168,88 USD supera 150, así que su caso cita `POL-AUT-INTAKE`, no `POL-AUT-150` (inferido de la política).

Escriba "Perdí la tarjeta", no "Perdí mi tarjeta": la segunda frase no está en `STOLEN_CARD_KEYWORDS` y, sin Jev, no dispara la oferta de bloqueo (`docs/specs/supabase-login-v1.md` sec. 3.4). En portugués la lista reconoce "roubaram", "roubo", "perdi o cartão" y "extraviei", no "perdi meu cartão" (`src/rules/dispute_policy.py`).

### 1.3 Más mensajes de prueba, en español y portugués

Salen de los casos de desarrollo ([`data/eval/dev_cases.jsonl`](../../data/eval/dev_cases.jsonl)), de los tests y del banco de preguntas de política, que usan clientes de prueba. Con una persona de demo, un monto que no coincide con sus cargos lleva a una aclaración con la lista de sus movimientos recientes (`dispute_orchestrator.py`).

| Qué muestra | Mensaje | Resultado esperado | Fuente |
| --- | --- | --- | --- |
| Disputa en portugués | `Não reconheço uma compra de 120 dólares no Cine Premium` | Caso si el monto coincide; si no, aclaración (`CLARIFICATION_REQUIRED`) con la lista | `tests/test_dispute_orchestrator.py` |
| Disputa vaga | `Tenho uma cobrança estranha`, y luego el número de la lista (`1`) | Aclaración; después el turno se decide sobre el movimiento elegido | DEV-016 |
| Pregunta de reglas (ES) | `¿Cuántos días tengo para disputar un cargo?` | `POLICY_EXPLANATION` con `[POL-WIN-60]` si el gate de BM25 confía; si no, una respuesta que pregunta el tema, o `SAFE_POLICY_ABSTENTION` | `tests/test_policy_rag.py` (con un gate que siempre confía); PR #46 |
| Pregunta de reglas (PT) | `Qual é a quantidade de dias que eu tenho para abrir uma contestação?` | Igual que la anterior; el banco espera `POL-WIN-60` | D-02 de `data/eval/policy_questions_dev.jsonl` |
| Fuera de alcance | `Quero um empréstimo para minha casa` | `SAFE_POLICY_ABSTENTION` | DEV-006 |
| Escalamiento legal | `Si no me resuelven voy a poner la queja en la CONDUSEF` | `MANDATORY_HITL_ESCALATION` con `POL-ESC-LEGAL` | DEV-011 |
| Angustia | `Estou desesperado, não tenho como pagar as contas, não reconheço uma compra de 40 dólares na Farmácia` | Con un cargo que coincida, `MANDATORY_HITL_ESCALATION` con `POL-ESC-DISTRESS`. Si el monto no coincide, primero una aclaración: `POL-CLARIFY` va antes de las escalaciones en la política. **No lo pruebe con una persona de demo** (sección 1.5) | DEV-012; `src/rules/dispute_policy.py` |

Lo que abra una prueba queda para los siguientes usuarios de la persona (sección 1.5). El explicador BM25 falla con preguntas parafraseadas: acierta el 36,7 % de las acciones del split de test (11 de 30) ([`reports/rag_benchmark.md`](../../reports/rag_benchmark.md)), así que una pregunta sin respuesta no es un error de la demo.

### 1.4 Cómo leer una respuesta

El chat muestra el texto y, debajo, una línea de estado ([`frontend/src/Chat.tsx`](../../frontend/src/Chat.tsx)):

| Campo | Qué significa |
| --- | --- |
| Estado | `new`, `awaiting_clarification`, `awaiting_lock_confirmation`, `closed` o `escalated` |
| Resultado | `AUTONOMOUS_RESOLUTION` (caso abierto sin humano), `CLARIFICATION_REQUIRED`, `MANDATORY_HITL_ESCALATION`, `SAFE_POLICY_ABSTENTION` o `POLICY_EXPLANATION` |
| Cláusulas | Ids de la política v2.3 que deciden el turno, como `POL-WIN-60` o `POL-ESC-500` |
| Caso | `CASE-` más 12 caracteres: el caso abierto y releído antes de responder, o el que ya existía para ese cargo |
| Escalación | `HO-` más 12 caracteres: el handoff que verá la consola. No confundir con los casos del held-out (`HO-001` a `HO-250`) |

Ids y resultados: [`src/ops/store.py`](../../src/ops/store.py), `src/rules/dispute_policy.py`, [`src/orchestrator/dispute_orchestrator.py`](../../src/orchestrator/dispute_orchestrator.py). En una aclaración aparecen botones con los movimientos; ante la oferta de bloqueo, "Sí" y "No" ("Sim" y "Não"). El idioma detectado en el primer mensaje manda sobre el selector ES/PT, y después del estado `new` ya no cambia aunque el cliente cambie de lengua (`dispute_orchestrator.py:171`; inferido de la lectura del código, [07-despliegue.md](07-despliegue.md), sección 9).

### 1.5 Cuidado: las personas comparten estado

Todos los que ingresan con una persona ven y cambian el mismo cliente en `ops`. Lo que deja una prueba afecta a la siguiente:

- **Un caso abierto apaga `POL-AUT-150`.** `ops.v_customer_policy_facts` suma los casos de `ops` creados desde `business_today() - 90`, sin límite superior, y `business_today()` está fijo en 2026-06-17 ([`supabase/migrations/0003_bank.sql`](../../supabase/migrations/0003_bank.sql)). Un caso creado hoy cuenta para siempre, y `POL-AUT-150` exige cero quejas en 90 días.
- **Un cargo con caso abierto no abre otro.** La respuesta repite el número del caso existente y la auditoría registra `DUPLICATE_CASE_PREVENTED`.
- **Un bloqueo verificado deja la tarjeta `Blocked`.** La vista `ops.v_product_status` la muestra bloqueada, el bloqueo no se vuelve a ofrecer y el gateway rechaza bloquearla de nuevo (`src/tools/gateway_postgres.py`).
- **Un handoff por angustia (`SEVERE_DISTRESS`) marca al cliente durante 30 días de reloj real:** sus disputas siguientes sobre un cargo en ventana pasan a humano (`POL-ESC-DISTRESS` decide o queda como cláusula secundaria), y sus preguntas de reglas no van al explicador (`src/ops/store.py`, `case_memory`; `src/rules/dispute_policy.py`).

**Estado de hoy.** Una conversación de la prueba de humo del 3-oct abrió un caso real sobre el cargo del escenario de `cliente-hasta-150` (113,65 USD del 3 de junio) (`docs/HANDOFF.md` sec. 3, A2). La auditoría del 4-oct, que no está comprometida en el repo, registra sobre ese cargo el caso `CASE-ECB3AEEF4C1B`, de una prueba del 4-oct. Mientras exista un caso abierto, esa persona no puede mostrar `POL-AUT-150`, y un nuevo intento recibe `DUPLICATE_CASE_PREVENTED`. El estado de las otras personas no se verificó para esta guía.

**Cómo resetear.** Solo desde el SQL Editor de Supabase, con una cuenta del proyecto: el rol de la app no tiene `DELETE` y el MCP del repo es de solo lectura. El SQL de [`docs/HANDOFF.md`](../HANDOFF.md) sec. 3, A2 borra mensajes, casos y conversaciones de dos conversaciones de prueba del 3-oct; para otras se cambian los ids. Sus handoffs y bloqueos las referencian y se borran antes (inferido de `supabase/migrations/0001_ops.sql`). La auditoría no se puede borrar, por diseño.

### 1.6 La consola del agente

Ingrese con la persona `agente`. La consola está en inglés y tiene cinco pestañas: Questions, Cases, Handoffs, Locks y Audit log ([`frontend/src/Console.tsx`](../../frontend/src/Console.tsx)). Qué muestra cada una y qué puede hacer el agente está en [07-despliegue.md](07-despliegue.md#4-consola-hitl-y-auditoría). En Cases, el filtro de candidatos a crédito permite aprobar o rechazar la marca de `POL-AUT-150`. Aprobar no mueve dinero: registra la decisión humana (regla 8, [`AGENTS.md`](../../AGENTS.md) sec. 4).

## 2. Correr en local

### 2.1 Requisitos

- Python 3.12 y [`uv`](https://github.com/astral-sh/uv), o solo Docker: el contenedor `dev` corre cualquier comando en Linux (`CLAUDE.md`).
- Node 22 o superior para el front (`frontend/README.md`).
- Los datos del banco. La API de disputas necesita el lakehouse `data/lakehouse.duckdb`, que se construye desde S3 con las llaves de AWS (sección 4), o un Postgres con `bank` publicado detrás de `DATABASE_URL` (`README.md`, "Quick start").

### 2.2 Pasos

1. Instale dependencias: `uv sync`. Con Docker, `docker compose build dev` la primera vez y cada vez que cambie `uv.lock`.
2. Copie `.env.example` a `.env` y deje `APP_ENV=development`. Sin esa línea, la app corre como producción y no arranca sin `SUPABASE_URL`. El `.env` está en `.gitignore`: nunca lo commitee.
3. Construya el lakehouse de muestra (sección 4.1).
4. Levante la API desde la raíz del repo:

   ```bash
   uv run uvicorn src.api.app:app --reload --port 8000   # API, Swagger at /docs; serves frontend/dist when built
   docker compose run --rm -p 8000:8000 dev uvicorn src.api.app:app --reload --host 0.0.0.0 --port 8000   # API from the dev container
   ```

   El servicio `dev` define `APP_ENV=test`, así que el emisor local queda activo (`docker-compose.yml`). Si el puerto 8000 está ocupado, vea la sección 5.

5. Compile el front, que la API sirve en `/`:

   ```bash
   cd frontend && npm install && npm run build
   ```

   Para desarrollo del front, `npm run dev` abre `http://localhost:5173` y redirige `/api` al puerto 8000.

6. Ingrese. Sin `VITE_SUPABASE_URL` ni `VITE_SUPABASE_PUBLISHABLE_KEY` en `frontend/.env.local`, el front muestra el selector local: unos clientes de la muestra y el botón "Enter HITL console as agent". Con las dos variables, pide email y contraseña de Supabase (`frontend/README.md`).

Alternativas: `docker-compose up --build -d` levanta la API y el front en una imagen, con `APP_ENV=development` y el lakehouse leído de `./data`. Solo con la API: `GET /api/v1/auth/personas`, `POST /api/v1/auth/test-session` y luego `POST /api/v1/disputes/conversations` y `.../messages` con el token como `Bearer` (`README.md`, "Quick start").

### 2.3 Variables de entorno (solo nombres)

| Variable | Para qué | Dónde |
| --- | --- | --- |
| `APP_ENV` | `development` o `test` activan el emisor local; cualquier otro valor es producción | `.env` |
| `LAKEHOUSE_PATH`, `OPS_DB_PATH` | Lakehouse DuckDB y base de operación local | `.env` |
| `DATABASE_URL` | Postgres con `bank` y `ops`; reemplaza a los dos anteriores | `.env` |
| `SUPABASE_URL` | JWKS y emisor de Supabase; obligatoria en producción | `.env` |
| `SUPABASE_SECRET_KEY` | Solo para `seed_personas` en su máquina; nunca en Vercel ni en el front | `.env` |
| `LOCAL_ISSUER_ENABLED` | Emisor local; con `true` fuera de development o test la app no arranca | `.env` |
| `FRAUD_MODEL_PATH` | Modelo de riesgo; por defecto `models/fraud_risk_ieee.joblib` | `.env` |
| `RAG_GATE_PATH` | Gate del explicador; por defecto `data/rag_gate.json` | `.env` |
| `TYPESAFE_API_KEY`, `LLM_DAILY_BUDGET_USD` | Jev y su tope diario (2 USD por defecto) | `.env` |
| `ANTHROPIC_API_KEY` | Hoy solo registra la elección del router; no hay llamada a Claude | `.env` |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Ingesta desde S3 | `.env` |
| `TEST_DATABASE_URL` | Activa los tests de Postgres | Shell o contenedor `dev` |
| `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` | Ingreso con Supabase en el front | `frontend/.env.local` |

Fuentes: [`.env.example`](../../.env.example), [`src/api/dispute_routes.py`](../../src/api/dispute_routes.py), `CLAUDE.md` ("Gotchas"), `frontend/README.md`.

## 3. Reproducir la evaluación y los benchmarks

Corra todo en el contenedor `dev`, que reproduce la CI (Linux, Python 3.12, Postgres 17). El 29-sep, Windows Application Control bloqueó las DLL de duckdb, pandas y scikit-learn de un `.venv` del host (`CLAUDE.md`, "Gotchas"), y sin esas librerías la corrida falla (inferido). Cualquier comando de esta sección corre con el prefijo `docker compose run --rm dev` en lugar de `uv run` (`CLAUDE.md`, "Commands": "any command runs in the dev container").

```bash
docker compose run --rm dev                           # suite as CI runs it (Linux, Python 3.12, Postgres 17), the same on Mac and Windows
uv run python -m src.eval.run data/eval/dev_cases.jsonl --out reports/eval_dev --repeats 3   # evaluation, baseline vs proposed: reports/eval_dev.json and .md
uv run python -m src.eval.run data/eval/heldout_cases.jsonl --out reports/eval_heldout --repeats 3   # frozen held-out suite
uv run python -m src.eval.run data/eval/heldout_cases.jsonl --out reports/eval_heldout_model --repeats 3 --systems proposed --model models/fraud_risk_ieee.joblib   # the held-out with the transferred risk model the API serves (B1); without --model the run is rules-only
uv run python -m src.eval.rag_benchmark --out reports/rag_benchmark   # policy explainer on the policy question bank (Task 1.2); add --e5 models/e5-small to measure E5 beside BM25, --write-gate data/rag_gate.json to turn the explainer on
uv run python -m src.rag.onnx_retriever download      # E5 int8 model into models/e5-small (git-ignored, 135 MB), pinned revision, SHA-256 checked
```

Ejemplo con el prefijo (variante, no documentada tal cual): `docker compose run --rm dev python -m src.eval.run data/eval/heldout_cases.jsonl --out reports/eval_heldout_local --repeats 3`. El contenedor monta el repo en `/app` y tiene `/opt/venv/bin` en el `PATH` (`docker-compose.yml`, `Dockerfile`).

**Salidas.** Cada corrida escribe `<out>.json` y `<out>.md` (`src/eval/run.py`). Con el `--out` documentado, la corrida pisa el reporte commiteado; por eso el ejemplo usa otra ruta, que luego se compara con `git diff --no-index`. `--write-gate` reescribe el archivo que enciende el explicador en producción; no lo use para probar.

**Cifras de referencia** (arquitectura en solo reglas, offline sobre casos guionizados; no son ganancias en producción, regla 11). El held-out en `9efb497` da resolución segura 98,1 % (105 de 107), inseguros 8,0 % (20 de 250) y resultado exacto 88,4 % (221 de 250) ([`reports/eval_heldout.md`](../../reports/eval_heldout.md)). Esa corrida reusa los casos que guiaron los arreglos; la ciega dio 63,6 % (68 de 107) y 15,6 % (39 de 250) ([`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md)). El desarrollo da 9 de 9 resoluciones seguras y 0 de 19 inseguros ([`reports/eval_dev.md`](../../reports/eval_dev.md)). La latencia depende de la máquina: 161,6 / 662,1 ms (p50 / p95) en el contenedor `dev` de un portátil Windows, y 25,0 / 85,1 ms en otra máquina el 3-oct (`README.md`, "Results"). La corrida con `--model` necesita el archivo del modelo (sección 4.4), y sus cifras solo están en los cuerpos de los PR #44 y #45. Juicio y métricas: [06-evaluacion.md](06-evaluacion.md).

**Suites congeladas.** El held-out tiene su SHA-256 en `data/eval/heldout_cases.sha256`, y `.gitattributes` mantiene LF para que el hash valga en Windows. Se comprueba con un comando estándar, no documentado en el repo (en Git Bash o Linux), o con `tests/test_heldout_suite.py`, que compara el mismo hash:

```bash
sha256sum data/eval/heldout_cases.jsonl   # debe coincidir con data/eval/heldout_cases.sha256
```

`uv run python -m src.eval.heldout` reconstruye la suite desde el lakehouse de muestra y debe reproducir ese hash. Por defecto escribe sobre `data/eval/heldout_cases.jsonl`, así que revise `git status` después. El benchmark del explicador rechaza el split de test si no coincide con su `.sha256`. Nunca edite un caso del held-out ni ajuste un umbral con sus resultados (`CLAUDE.md`, "Gotchas").

## 4. Reconstruir datos y modelo

Lo que no está en git y hay que regenerar: los lakehouses (`*.duckdb`), el esquema `bank` en Postgres, los datos de IEEE-CIS (`data/kaggle/`) y el modelo (`models/*.joblib`) (`.gitignore`). Las suites, los fixtures y el corpus sí están en git. La procedencia de cada artefacto está en [04-preparacion-de-los-datos.md](04-preparacion-de-los-datos.md), sección 10.

### 4.1 Lakehouse

```bash
uv run python -m src.data.ingestion                   # build the sample data/lakehouse.duckdb from S3 (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY in .env)
uv run python -c "from pathlib import Path; from src.data.ingestion import run_ingestion_pipeline as run; run(sample_only=False, db_path=Path('data/lakehouse_full.duckdb'))"   # full 2023 to 2026 history; the module CLI builds only the sample
```

Las llaves de AWS vienen del diccionario de datos de los organizadores y van solo en el `.env` local, nunca en un archivo versionado, un issue o un chat. La muestra trae 25.000 clientes con sus productos, quejas de 2026 y transacciones de junio de 2026; la carga completa baja unos 800 MB de S3 (`CLAUDE.md`, `src/data/`). Corra desde la raíz del repo y con el lakehouse cerrado en cualquier notebook.

### 4.2 Copia de servicio en Postgres

1. Aplique `supabase/migrations/*.sql` en orden de nombre, como dueño del proyecto (Supabase CLI o psql), o con `OpsStore.apply_postgres_migration` (`CLAUDE.md`).
2. Publique el subconjunto minimizado con una conexión que pueda escribir `bank`. `app_gateway` solo lee `bank` (`docs/HANDOFF.md` sec. 4):

   ```bash
   uv run python -m src.data.publish_serving --database-url postgresql://... --source data/lakehouse.duckdb   # minimized bank subset to Postgres (apply supabase/migrations first)
   ```

   Para publicar solo los 253 clientes de la demo y del held-out, agregue `--customers data/serving_customers.json`. El script vacía y recarga `bank`, comprueba paridad y nunca toca `ops` (`src/data/publish_serving.py`).

### 4.3 Personas de Supabase Auth

```bash
uv run python -m src.auth.seed_personas --email-pattern 'you+{label}@gmail.com' --dry-run   # demo personas in Supabase Auth from data/fixtures/personas.json (SUPABASE_URL and SUPABASE_SECRET_KEY in .env); without --dry-run it writes, and the passwords go to the git-ignored personas.local.json
```

Con `--reset-passwords` también da contraseñas nuevas a las cuentas existentes. El script nunca imprime una contraseña ni una clave (`docs/specs/supabase-login-v1.md` sec. 3.3).

### 4.4 Modelo de riesgo transferido de IEEE-CIS

1. Con una cuenta de Kaggle, acepte las reglas de la competencia IEEE-CIS Fraud Detection y baje `train_transaction.csv` y `train_identity.csv` a `data/kaggle/` ([`docs/specs/fraud-risk-model-v1-ieee-cis.md`](../specs/fraud-risk-model-v1-ieee-cis.md) sec. 7).
2. Construya la carga completa del lakehouse (sección 4.1): el umbral sale de la ventana Web y App del banco.
3. Entrene:

   ```bash
   uv run python -m src.ml.fraud_risk_transfer --competition data/kaggle --lakehouse data/lakehouse_full.duckdb --out reports/ml --model models/fraud_risk_ieee.joblib   # risk model transferred from IEEE-CIS (files in data/kaggle, git-ignored); logs the run to MLflow in ./mlflow.db and ./mlruns
   ```

Salidas: el bundle en `models/`, los reportes en `reports/ml/` y la corrida en MLflow local. El reporte registrado da ROC AUC 0,817 en el split de test de la competencia, con umbral 0,0669 ([`reports/ml/fraud_risk_transfer.md`](../../reports/ml/fraud_risk_transfer.md)). Un reentrenamiento en el contenedor dio 0,815 y umbral 0,0694: cercano, no idéntico (cuerpo del PR #45). La API carga el bundle desde `FRAUD_MODEL_PATH` cuando crea el orquestador, en el primer pedido (`get_orchestrator`, `src/api/dispute_routes.py`).

Las fuentes se contradicen sobre la licencia de los datos: `README.md` ("Limitations") y la respuesta de TQ-032 dicen que los mentores aprobaron el uso; la respuesta de TQ-026, su fila en [`docs/PLAN.md`](../PLAN.md) y el spec del modelo (sec. 7) dicen que sigue pendiente.

## 5. Problemas frecuentes

| Problema | Causa | Solución |
| --- | --- | --- |
| La app no arranca: "needs SUPABASE_URL" | `APP_ENV` falta, está en blanco o no es `development` ni `test`: eso es producción | `APP_ENV=development` en `.env` |
| La imagen de Docker sola se cierra | La imagen corre como producción | `-e APP_ENV=development`, o `SUPABASE_URL` |
| 401 "Invalid session token." tras un reinicio | El emisor local cambia de clave en cada proceso, y `--reload` reinicia | Pida un token nuevo |
| `/api/v1/auth/personas` da 404 | `APP_ENV` no es `development` ni `test` | Corrija `APP_ENV` |
| El front muestra el modo de ingreso equivocado | Vite lee `frontend/.env*`, no el `.env` raíz, y fija el modo al compilar | Variables en `frontend/.env.local` y recompilar |
| "Cannot open file ... being used by another process"; todo turno va a humano | DuckDB admite un solo proceso escritor, como un notebook abierto | Cierre el otro proceso |
| La ingesta falla en la primera lectura de S3 | Sin llaves de AWS, `get_db_connection` salta la configuración de S3 sin avisar | Llaves en `.env` |
| "México" sale como "MÃ©xico" | Lectura sin `encoding="utf-8"`: Windows usa cp1252 | Siempre `encoding="utf-8"` (`tests/test_text_encoding.py`) |
| Falla `import duckdb`, pandas o scikit-learn en Windows | Application Control bloquea las DLL del `.venv` del host | Contenedor `dev` |
| Al contenedor `dev` le falta un paquete | Cambió `uv.lock` | `docker compose build dev` |
| El puerto 8000 está ocupado | Otro proceso lo usa | `-p 8001:8000` y `http://localhost:8001` con el front compilado; el proxy de Vite apunta a 8000 (`frontend/vite.config.ts`; inferido) |
| No encuentra `data/lakehouse.duckdb` | Es una ruta relativa | Corra desde la raíz del repo |
| La suite pasa sin revisar los datos | `tests/test_data_integrity.py` se salta sin lakehouse | Construya el lakehouse y córralo |
| Los tests de Postgres se saltan | Falta `TEST_DATABASE_URL` | `docker compose run --rm dev`, que la define |
| Llamadas a Jev con costo | Un `TYPESAFE_API_KEY` en `.env` las activa | Déjela vacía salvo que quiera gastarlas |
| `POL-ESC-ML-RISK` nunca se dispara | Falta el archivo del modelo | Sección 4.4, o `FRAUD_MODEL_PATH` |
| Fechas de ventana corridas un día | `CAST(transaction_date AS DATE)` ignora el desfase de 6 h; "hoy" es 2026-06-17 | Use `process_date` |
| Una pregunta de reglas recibe una cláusula o una abstención, no el flujo de disputa | Con `data/rag_gate.json`, el explicador está encendido | `RAG_GATE_PATH` a una ruta sin archivo lo apaga |
| El check de Vercel sale rojo en los PR | Verificación de autor del plan Hobby, no un error del código | Ninguna (`docs/HANDOFF.md` sec. 2) |

Fuentes de la tabla: `CLAUDE.md` ("Gotchas"), `frontend/README.md`, `docs/HANDOFF.md`, [`AGENTS.md`](../../AGENTS.md) sec. 7.

## Fuentes

- [CLAUDE.md](../../CLAUDE.md) ("Commands", "Gotchas")
- [README.md](../../README.md) ("Quick start", "Results", "Limitations")
- [frontend/README.md](../../frontend/README.md)
- [docs/HANDOFF.md](../HANDOFF.md) secs. 2, 3, 4 y 5
- [docs/specs/supabase-login-v1.md](../specs/supabase-login-v1.md) secs. 3.2, 3.3 y 3.4
- [docs/specs/fraud-risk-model-v1-ieee-cis.md](../specs/fraud-risk-model-v1-ieee-cis.md) sec. 7; [docs/PLAN.md](../PLAN.md) (fila del modelo transferido); [data/fixtures/team_questions.json](../../data/fixtures/team_questions.json) (TQ-026, TQ-032)
- [data/fixtures/personas.json](../../data/fixtures/personas.json), [data/eval/dev_cases.jsonl](../../data/eval/dev_cases.jsonl), [data/eval/policy_questions_dev.jsonl](../../data/eval/policy_questions_dev.jsonl)
- [reports/eval_heldout.md](../../reports/eval_heldout.md), [reports/eval_heldout_blind.md](../../reports/eval_heldout_blind.md), [reports/eval_dev.md](../../reports/eval_dev.md), [reports/rag_benchmark.md](../../reports/rag_benchmark.md), [reports/ml/fraud_risk_transfer.md](../../reports/ml/fraud_risk_transfer.md)
- Código y configuración: `src/api/dispute_routes.py`, `src/orchestrator/dispute_orchestrator.py`, `src/rules/dispute_policy.py`, `src/ops/store.py`, `src/tools/gateway_postgres.py`, `src/eval/run.py`, `src/eval/heldout.py`, `frontend/src/Chat.tsx`, `frontend/src/Console.tsx`, `supabase/migrations/`, `docker-compose.yml`, `Dockerfile`, `.env.example`, `.gitignore`
- Tests: `tests/test_dispute_orchestrator.py`, `tests/test_policy_rag.py`, `tests/test_heldout_suite.py`
- PR #44, #45 y #46 (cuerpo leído con `gh pr view`)
- Auditoría del 4-oct, no comprometida en el repo (solo el id del caso abierto de `cliente-hasta-150`)
