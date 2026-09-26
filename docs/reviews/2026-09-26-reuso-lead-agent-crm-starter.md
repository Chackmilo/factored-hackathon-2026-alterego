# Reuso del lead-agent-crm-starter en el proyecto de disputas

Fecha: 2026-09-26 (día 2). Rama de trabajo: `feat/dispute-stack`.

Fuente: repo `Chackmilo/lead-agent-crm-starter`, commit `a94366d` (único commit, creado el 2026-09-24). Es un repo privado de Daniel; pide acceso si necesitas abrir los archivos citados.

Qué es el starter: plantilla de agente de leads con CRM y operador humano. Backend en FastAPI, LangGraph y PostgreSQL; dashboard en React, Vite y Tailwind; canales Telegram, WhatsApp y un widget de webchat.

Método: solo lectura del código completo (unas 5.000 líneas). No se instaló ni se ejecutó nada. El fallo del build de Docker y del test `tests/test_guards.py` se deducen del código y no se verificaron corriéndolos.

Para qué sirve este archivo: decidir qué piezas del starter entran al proyecto, con qué cambios y cuáles no. Las rutas de la forma `core/...` o `dashboard/...` son del starter; los enlaces relativos son de este repo.

## 1. Resumen

El starter aporta sobre todo tiempo al frente C: un dashboard en React que compila y sirve de punto de partida para la consola HITL. Al frente B le aporta tres patrones pequeños: guardas deterministas sobre el texto de salida, idempotencia por clave única y un runner de migraciones. El núcleo del agente no sirve, porque deja que el LLM llame herramientas que modifican datos, y eso contradice la regla 6 de [AGENTS.md](../../AGENTS.md#L68).

Nada se copia tal cual. Cada pieza llega con los arreglos de la sección 6 y con sus identificadores y textos de la consola en inglés.

## 2. Antes de copiar: procedencia

- El starter se creó el 24 de septiembre y el build del hackathon empezó el 25. En los PDFs oficiales no hay ninguna frase que prohíba usar código previo (búsqueda de "prior", "existing code", "template", "starter", "reuse", "license" en el enunciado y el kickoff). Aun así, hay que declararlo en el README como código previo del equipo (regla 11, [AGENTS.md](../../AGENTS.md#L78)). Si hay dudas, se puede preguntar en `#technical-help` junto con la pregunta abierta sobre el uso de datos.
- `tests/test_purity.py` del starter no entra a este repo. Contiene nombres de clientes anteriores y un número que parece un documento de identidad, y este repo va a ser público (regla 10, [AGENTS.md](../../AGENTS.md#L75)).
- Los identificadores del starter están en español (`actualizar_ficha_lead`, `mover_etapa_pipeline`). Al portarlos se pasan a inglés, según la convención de [AGENTS.md](../../AGENTS.md#L317).

## 3. Qué reusar

| Pieza del starter | Archivos | Uso en el plan | Frente | Cambios obligatorios |
| --- | --- | --- | --- | --- |
| Dashboard React + Vite + Tailwind | `dashboard/src/App.tsx`, `components/Inbox.tsx`, `ChatView.tsx`, `ContactPanel.tsx`, `vite.config.ts` (proxy a `/api`) | Base de la consola HITL: lista de casos, detalle del caso y del handoff, visor de auditoría ([PLAN.md](../PLAN.md#L70)) | C | Textos de la UI en inglés ([PLAN.md](../PLAN.md#L49)). Tipos generados desde OpenAPI en lugar de `types.ts` escrito a mano ([PLAN.md](../PLAN.md#L53)). Sacar `Kanban.tsx` (el plan dice "sin dashboard"). Autenticación con JWT de rol `agent` en lugar de cookie de sesión ([PLAN.md](../PLAN.md#L71)). No copiar el bug 6.1 |
| Vista de aprobar borradores en `ChatView.tsx` (líneas 102 a 117) | `dashboard/src/components/ChatView.tsx` | Aprobar o rechazar candidatos a crédito provisional en la consola ([PLAN.md](../PLAN.md#L56)) | C | Cambiar "aprobar mensaje" por "aprobar o rechazar candidato". Mostrar el resultado solo después de la lectura de verificación (regla 7) |
| Dockerfile en dos etapas (Node construye el front, Python lo sirve) y montaje de `dist` con `StaticFiles` | `Dockerfile`, `main.py:104-115` | React servido por FastAPI en un solo contenedor en Render ([PLAN.md](../PLAN.md#L53)) | B | Arreglar `.dockerignore` e instalar con `uv sync` y el lockfile (bug 6.2). Sin Postgres |
| Detector de placeholders `PLACEHOLDER_REGEX` y `check_no_placeholders` | `core/guards/deterministic.py:16` y `69-74` | Confirmar que no queda ningún `{monto}` o `{caso}` sin rellenar después de que el código completa el texto de Claude ([PLAN.md](../PLAN.md#L63)). Los transcripts del dataset ya traen placeholders sin rellenar, así que es un modo de falla conocido | B | Aplicarlo sobre el texto final, después de rellenar. Ampliar el patrón a llaves simples (`{monto}`), que el regex actual no detecta |
| Allowlist de URL y de email | `core/guards/deterministic.py:42-66` | Impedir que Claude invente enlaces o correos en respuestas al cliente | B | Aplicarlo sobre el texto final (bug 6.3). Tratar el email del propio cliente como permitido o enmascararlo antes (bug 6.4). Detectar también dominios sin `http` |
| Palabras clave de alto riesgo | `core/guards/deterministic.py:19-39` | Respaldo por palabras clave de `POL-ESC-LEGAL` y `POL-ESC-DISTRESS` ([PLAN.md](../PLAN.md#L59)) | B | Normalizar tildes y tolerar variantes (bug 6.5). Agregar la lista en portugués |

## 4. Qué adaptar (solo la idea)

| Idea | Dónde está en el starter | Uso en el plan | Cómo hacerlo aquí |
| --- | --- | --- | --- |
| Idempotencia con clave única | `core/memory/repository.py:230-288`, columna `idempotency_key UNIQUE` en `migrations/001_initial_core.sql` | El gateway necesita claves de idempotencia ([AGENTS.md](../../AGENTS.md#L280)) | En SQLite, un solo `INSERT ... ON CONFLICT(idempotency_key) DO NOTHING RETURNING`. Si no devuelve fila, leer la existente y devolver al llamador que la acción ya existía, para que no la repita (bug 6.6) |
| Runner de migraciones con tabla `schema_migrations` | `core/memory/database.py:38-69` | Esquema de `data/ops.sqlite`: casos, bloqueos, sesiones y auditoría ([PLAN.md](../PLAN.md#L54)) | Unas 30 líneas con `sqlite3`: aplicar cada `.sql` pendiente dentro de una transacción y registrar su nombre |
| Tope diario de gasto del LLM | `core/memory/repository.py:402-430` | La demo pública en Render con una key de Anthropic necesita un tope; conecta con la decisión abierta "Keys y presupuesto" ([PLAN.md](../PLAN.md#L75)) | Atómico (`UPDATE ... SET n = n + 1 WHERE n < :limite RETURNING n`), por sesión y global, y con un largo máximo del mensaje (bug 6.7) |
| Prompts en archivos, renderizados con Jinja | `core/config.py:178-201` | El reporte debe declarar versiones de prompts ([AGENTS.md](../../AGENTS.md#L99)): el hash del archivo sirve como versión | Jinja usa `{{ }}`, así que no choca con los marcadores `{monto}`. Sin `autoescape` para `.md` |
| Escaneo de secretos con gitleaks | Mencionado en el README del starter | El repo va a ser público y el PDF del diccionario trae keys de AWS (regla 10) | Agregar gitleaks al GitHub Action sobre todo el historial, no solo el último commit |

## 5. Qué descartar y por qué

| Pieza del starter | Motivo |
| --- | --- |
| Grafo de LangGraph: supervisor, especialista ReAct y nodo de calidad (`core/graph/`) | El especialista es un loop donde el LLM llama herramientas que escriben en la base; la regla 6 exige que la política determinista decida ([AGENTS.md](../../AGENTS.md#L68)). El nodo de calidad reescribe el texto con un LLM después de las guardas. El plan pide una máquina de estados de cinco etapas |
| PostgreSQL y `AsyncPostgresSaver` | El plan decidió SQLite para la operación y DuckDB de solo lectura ([PLAN.md](../PLAN.md#L54)). Además el starter usa el checkpointer mal (anexo, punto A1) |
| Login con Argon2, cookies de sesión y chequeo CSRF (`core/crm_api/auth.py`) | El plan usa JWT con claim `role`, y [src/auth/session.py](../../src/auth/session.py) ya existe. Con el token en un header, el chequeo CSRF por `Origin` no hace falta |
| Canales Telegram y WhatsApp, `InboundBatcher`, `outbound_throttle` | Son otros canales. La regla 1 no da puntos por extras ([AGENTS.md](../../AGENTS.md#L59)) |
| Widget `widget.js` y el SSE del webchat | El chat del cliente va en React con botones para los cargos candidatos y la confirmación del bloqueo ([PLAN.md](../PLAN.md#L70)). Request y response alcanzan; el SSE agrega un punto de falla sin necesidad |
| Herramientas del agente (`core/tools/native.py`) | Llevan `contact_id` en el closure, pero las decide el LLM. El gateway del proyecto ya las reemplaza con verificación de propiedad y lectura de verificación |
| `tests/test_purity.py` | Ver sección 2 |

## 6. Bugs del starter que no hay que copiar

Estos afectan piezas de las secciones 3 y 4. Cada arreglo debería llegar con un test que falle primero.

| ID | Bug | Dónde | Qué hacer al portar |
| --- | --- | --- | --- |
| 6.1 | La ficha carga los valores enmascarados (`ca••••om`) en inputs editables y "Guardar" envía el diccionario completo: guardar cualquier campo sobreescribe los datos sensibles reales con los asteriscos | `dashboard/src/components/ContactPanel.tsx:27`, `63-70`, `164-167` | En la consola, mostrar los campos enmascarados como solo lectura y enviar solo los campos editados |
| 6.2 | El build de Docker falla: `.dockerignore` excluye `dashboard/src/` (el front queda sin fuentes) y `*.md` (falta `README.md`, que exige `pyproject.toml`, y los prompts `.md` no entran a la imagen). Además `uv pip install -e .` corre con solo `pyproject.toml` copiado y hatchling no encuentra ningún paquete | `.dockerignore:14`, `.dockerignore:16`, `Dockerfile:34-35` | No excluir fuentes ni `.md` necesarios. Copiar `pyproject.toml` y `uv.lock` y correr `uv sync --frozen --no-dev` |
| 6.3 | Las guardas corren antes de que un LLM "pula" el texto, y el texto pulido se envía sin volver a revisarlo | `core/graph/quality.py:39` y `58-73` | Las guardas van siempre sobre el texto que se envía |
| 6.4 | La guarda de email marca como alucinación cualquier correo fuera de la lista blanca, incluido el del cliente, y fuerza un traspaso a humano | `core/guards/deterministic.py:57-66` | Permitir el email verificado del cliente o enmascararlo antes de la guarda |
| 6.5 | Las palabras clave usan `\b` sin normalizar: "demandar" no coincide con "demanda" y "reclamación" no coincide con "reclamacion". El test `tests/test_guards.py:18` espera lo contrario y debería fallar | `core/guards/deterministic.py:35` | Normalizar con `unicodedata` (NFKD, sin tildes, minúsculas) y usar raíces o listas de variantes, con tests en ES y PT |
| 6.6 | Un envío duplicado devuelve la fila existente, pero la ruta despacha el mensaje otra vez. El resultado del envío se ignora y el mensaje queda como `sent` aunque falle. La inserción verifica y después inserta, sin atomicidad | `core/crm_api/routes_chat.py:113-128`, `core/memory/repository.py:244-278` | Ver la fila de idempotencia en la sección 4. Registrar una acción como hecha solo después de la lectura de verificación (regla 7) |
| 6.7 | El tope diario es global y no atómico: un atacante lo agota para todos y las peticiones concurrentes lo superan. `slowapi` está instalado pero no se usa, `WEBCHAT_SESSION_MAX_MESSAGES` no se aplica y el texto no tiene largo máximo | `core/memory/repository.py:402-430`, `core/channels/webchat.py:96-117` | Ver la fila del tope en la sección 4 |
| 6.8 | CORS cae en `["*"]` con credenciales si la lista de orígenes queda vacía | `main.py:80` | Lista explícita de orígenes; sin comodín cuando hay credenciales |
| 6.9 | La IP del cliente sale del primer valor de `X-Forwarded-For`, que controla el cliente; el rate limit del login se evade rotando el header | `core/crm_api/auth.py:44-50` | Usar `request.client.host` y restringir `--forwarded-allow-ips` a la red del proxy. En Render, verificar cómo llega la IP real antes de fijar el valor |
| 6.10 | Valores de campos sensibles escritos en logs de nivel INFO | `core/tools/native.py:47`, `core/graph/specialist.py:65` | No registrar valores de campos del cliente; solo nombres de campo e ids |
| 6.11 | Las listas de conversaciones devuelven los atributos del contacto sin enmascarar, aunque la ficha individual sí los enmascara | `core/memory/repository.py:139`, `154`, `202` | Enmascarar en la capa de servicio, no solo en un endpoint |

## 7. Próximos pasos propuestos

Todos son propuestas. Según [PLAN.md](../PLAN.md#L42), hay que consultarlas con el equipo antes de actuar.

1. Agregar al registro de decisiones de [PLAN.md](../PLAN.md) una fila "Reuso del starter" en estado Propuesta, que apunte a este archivo.
2. Frente C: abrir una rama con el dashboard del starter como scaffold de la consola, ya en inglés, contra el mock del contrato OpenAPI.
3. Frente B: portar primero las guardas de salida, la idempotencia y el runner de migraciones, con los tests de la sección 6 fallando antes del arreglo.
4. Agregar gitleaks al GitHub Action antes de que el repo sea público.
5. Declarar en el README qué piezas vienen del starter y en qué commit.

## Anexo: otros hallazgos de la revisión del starter

No afectan a este proyecto si se respeta la sección 5, pero sirven si alguien sigue usando el starter para otros fines.

- A1. `core/graph/builder.py:73-75` crea `AsyncPostgresSaver(conn)` dentro de `async with pool.connection()` y guarda el grafo en caché: la conexión vuelve al pool y queda compartida. El pool tampoco usa `autocommit=True`, que la documentación de langgraph-checkpoint-postgres exige para `setup()`.
- A2. Telegram no funciona en producción: el polling solo corre fuera de producción (`main.py:53`) y no existe ruta de webhook. `TELEGRAM_WEBHOOK_SECRET` no se usa.
- A3. El webhook de WhatsApp acepta cualquier petición si `WHATSAPP_APP_SECRET` está vacío (`core/channels/whatsapp.py:101`).
- A4. El borrado de un contacto no borra sus checkpoints de LangGraph, que guardan el historial completo.
- A5. Nada crea mensajes en estado `draft`, así que el flujo de aprobar borradores del CRM no se usa.
- A6. El SSE del CRM no emite eventos para mensajes entrantes de clientes, solo para acciones del operador.
- A7. Si el especialista agota sus 4 iteraciones, envía al cliente el contenido de un `ToolMessage` (`core/graph/specialist.py:80`).
- A8. El widget abre sesión y SSE en cada visita a la página, antes del aviso de privacidad (`dashboard/public/widget.js:193`).
- A9. `SECRET_KEY`, `FORWARDED_ALLOW_IPS` y `ATTACHMENTS_DIR` están configurados pero ningún código los usa.
