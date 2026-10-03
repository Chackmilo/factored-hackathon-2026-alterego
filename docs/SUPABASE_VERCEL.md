# Supabase y Vercel: identidad, base de operación y despliegue

Actualizado: 2026-09-26 (día 2). Estado: el equipo decidió el 26 sep reemplazar el JWT propio y la SQLite de operación por Supabase (Auth y Postgres) en el plan Free, sin Supabase Pro; desplegar en Vercel; usar Python 3.12; y correr el harness en dos modos. Lo marcado "(propuesta)" depende de filas Propuesta o Abierta de `docs/PLAN.md` y no cambia nada hasta que el equipo las apruebe.

Límites y comportamientos de Supabase y Vercel verificados el 26 sep en su documentación oficial (sección 11). Este diseño **no inspeccionó el proyecto Supabase**: el MCP de Supabase no estaba autenticado en la sesión en que se escribió. El primer paso del día 3 es una inspección de solo lectura (sección 5.6).

## 1. Resumen

- **Qué cambia.** La identidad pasa de un JWT HS256 que firmamos nosotros (`src/auth/session.py`) a Supabase Auth: el cliente y el agente ingresan con una credencial y FastAPI verifica el token de Supabase con la clave pública del proyecto. La base de operación pasa de SQLite (`data/ops.sqlite`, que no existía aún) a Postgres en Supabase. La app deja de abrir DuckDB: lee un subconjunto de servicio publicado desde gold al esquema `bank`.
- **Qué no cambia.** El lakehouse DuckDB local sigue siendo la plataforma de datos (bronze, silver, gold, ML sobre todos los años, notebook). La política sigue en Python, el modelo propone y el código decide, el gateway hace act-and-verify. Las cláusulas y su orden (brief v2.3) no se tocan.
- **Qué resuelve.** H01 (cómo obtienen su token el cliente y el agente), H15 (disco efímero: los casos y la auditoría se perdían en cada reinicio), H21 (los hechos de política en gold no veían los casos nuevos), SEC-03 (secreto por defecto en el repo), el límite de un solo escritor de DuckDB y la contradicción 11 de la revisión adversarial (el rol en el JWT).
- **Qué riesgos agrega.** Más trabajo antes de G1 en la ruta crítica de B, la pausa del plan Free de Supabase tras 7 días sin actividad (cae en plena ventana de jurados y no se paga Pro, así que se mitiga con un canario doble y revisión manual), el límite de 500 MB del bundle de Python en Vercel frente a ONNX y LightGBM, y datos del organizador alojados en un tercero (pregunta abierta a mentores). Sección 9.

El enunciado admite como fuente de identidad "mock OIDC/JWT or an identity service" (regla 5 de `AGENTS.md`). Supabase Auth es un servicio de identidad: la regla se cumple mejor que con el JWT de prueba, porque el token sale solo tras presentar una credencial.

## 2. Qué cambia, componente por componente

| Componente | Plan al cerrar G0 | Ahora | Estado |
| --- | --- | --- | --- |
| Identidad | JWT HS256 firmado con `JWT_SECRET` (`src/auth/session.py`), sin endpoint que lo emita | Supabase Auth emite el token; FastAPI verifica ES256 contra el JWKS del proyecto | Decidida (26 sep) |
| Rol de la consola | Claim `role: "agent"` | `app_metadata.app_role = "agent"`: en Supabase el claim `role` está reservado para el rol de Postgres (`authenticated`) | Decidida con la identidad; nombre del claim (propuesta) |
| Base de operación | SQLite `data/ops.sqlite` | Supabase Postgres, esquema `ops` | Decidida (26 sep) |
| Datos que lee la app | DuckDB `gold_*` y `silver_*` abiertos en solo lectura | Supabase Postgres, esquema `bank`, cargado desde gold por un script | Propuesta (consecuencia de la anterior) |
| Lakehouse, ingesta, ML, notebook | DuckDB local | Sin cambio | Decidida |
| Despliegue | Un contenedor Docker en Render | Vercel (Hobby): FastAPI como función de Python y el build de React por CDN, un solo dominio | Decidida (26 sep) |
| Reproducibilidad local | `docker-compose up` | `docker-compose up` con API más Postgres local y emisor de tokens local, sin cuenta de Supabase | Propuesta |

## 3. Identidad con Supabase Auth

### 3.1 Modelo de personas (propuesta)

- **Personas de prueba con email y contraseña.** Un script (`src/auth/seed_personas.py`, implementado el 1 oct; spec `docs/specs/supabase-login-v1.md`) las crea con la API de administración de Auth y la secret key, que vive solo en el `.env` local de quien corre el script. Cada persona de cliente lleva `app_metadata = {"customer_id": "CLI-...", "app_role": "customer"}`; la del agente de la consola lleva `{"customer_id": null, "app_role": "agent"}`.
- **Registro público deshabilitado.** Nadie crea cuentas desde la app. Una cuenta sin `customer_id` recibe 403 en los endpoints de cliente.
- **Nunca `user_metadata`.** El usuario puede editarlo y aparece en el token: no sirve para autorizar. Solo `app_metadata`, que únicamente la secret key escribe.
- **Sin magic links.** El SMTP por defecto envía 2 correos por hora por proyecto: no alcanza para una demo ni para el harness.
- **Credenciales de los jurados** en el correo de entrega, nunca en el repo, y la persona del agente con una credencial aparte (lo pedía H01).
- **Personas del harness.** Una por cliente de la suite, creadas por el mismo script en el proyecto que corresponda (sección 7).

### 3.2 Claims del access token

El token que FastAPI recibe como `Authorization: Bearer` se ve así (valores de ejemplo):

```json
{
  "iss": "https://<project-ref>.supabase.co/auth/v1",
  "aud": "authenticated",
  "sub": "8d0c1a52-...-uuid-del-usuario-de-auth",
  "role": "authenticated",
  "session_id": "3f1e...",
  "exp": 1790384400,
  "iat": 1790380800,
  "aal": "aal1",
  "app_metadata": {"customer_id": "CLI-EXAMPLE00001", "app_role": "customer"}
}
```

`sub` es el id del usuario de Auth, no el `customer_id` del dataset. El token ya no lleva nombre, país ni segmento: el brief (3.1) exigía que los hechos de política salgan del sistema de registro, y ahora salen de `bank` y `ops`. `VerifiedSession` pasa a tener `auth_user_id`, `customer_id` (o `None` para el agente), `app_role`, `session_id` y `exp`.

### 3.3 Verificación en FastAPI (propuesta)

`get_current_session` conserva su firma de dependencia, así que los endpoints no cambian. Por dentro:

1. Lee el JWKS de `https://<project-ref>.supabase.co/auth/v1/.well-known/jwks.json` (PyJWT con `PyJWKClient`, extra `pyjwt[crypto]`), con caché y una recarga cuando llega un `kid` desconocido. Supabase ya cachea el JWKS 10 minutos en su borde.
2. Acepta solo `ES256`. Un token HS256 o con `alg: none` recibe 401.
3. Exige `iss` del proyecto, `aud = "authenticated"` y `exp` con una tolerancia de pocos segundos. Vencido, 401 sin revelar nada (`POL-SEC-SESSION`).
4. Endpoints de cliente: sin `app_metadata.customer_id`, 403. Endpoints de la consola: sin `app_role = "agent"`, 403.

No hay secreto compartido en el API: SEC-03 desaparece en lugar de mitigarse. La documentación de Supabase ya no recomienda el secreto HS256 heredado.

`GET /api/v1/auth/me` devuelve la identidad verificada (`app_role` y `customer_id`) con cualquier `APP_ENV`, y el front la lee después de ingresar para elegir entre el chat y la consola (implementado el 1 oct).

### 3.4 Emisor local para tests y harness (propuesta)

Una interfaz `SessionVerifier` con dos implementaciones: la de JWKS de Supabase y una local que firma ES256 con un par de claves generado en cada corrida de tests. Usa el mismo contrato de claims. Sirve para los tests unitarios, para los casos de sesión vencida y de token forjado del harness y para `docker-compose up` sin cuenta de Supabase (el CLI de Supabase trae la misma idea: `supabase gen bearer-jwt`).

Guarda obligatoria: el verificador local solo existe con `APP_ENV` en `test` o `development`. En producción la app se niega a arrancar si alguien lo configura, y un test lo prueba (SEC-03 revisado).

Sin `APP_ENV`, en blanco o con un valor distinto de `development` o `test`, el código asume producción (falla cerrado), y ahí el app no arranca sin `SUPABASE_URL` (implementado el 1 oct).

### 3.5 Límites y trampas de Auth

- Endpoint de token (contraseña y refresh): 150 peticiones cada 5 minutos por IP, ráfagas de 30. Registro y verificación: 30 cada 5 minutos. Se pueden subir en la configuración del proyecto.
- Borrar un usuario no invalida sus access tokens: duran hasta `exp` (1 hora por defecto). Para la demo basta; se documenta como límite.
- Los cambios en `app_metadata` llegan al token en el siguiente refresh.
- Las claves heredadas `anon` y `service_role` se retiran a fines de 2026: se usan las nuevas `sb_publishable_...` (front) y `sb_secret_...` (solo el script de personas). Las nuevas no son JWT.

## 4. Datos en Supabase, según nuestra estructura

### 4.1 Principio

El lakehouse no se muda. La ingesta desde S3, la deduplicación, las marts gold, el LightGBM sobre 5 millones de transacciones y el notebook siguen en DuckDB local: es la parte que los jurados evalúan como ingeniería de datos, y el dataset completo no cabe en el plan Free (500 MB por proyecto). A Supabase va solo lo que la app necesita para atender un caso: el subconjunto de servicio de la muestra de clientes.

Dos esquemas con dueños distintos:

- **`bank`**: datos del organizador, derivados de gold (`derived` de `synthetic-organizer`). De solo lectura para la app. Se recargan completos con un script idempotente.
- **`ops`**: lo que escribe el sistema (`team-generated`): conversaciones, casos, bloqueos, handoffs y auditoría. Ninguna recarga de `bank` lo toca.

Separarlos permite recargar datos sin perder casos, dar permisos mínimos por esquema, etiquetar la procedencia por esquema y dejar claro cuál es el sistema de registro de cada lectura de verificación (regla 7): `ops` para lo que el sistema hizo, `bank` para lo que el banco sabía.

### 4.2 Qué viaja a `bank` y qué no

Conteos de la muestra actual (`data/lakehouse.duckdb`, 26 sep). Transacciones: la muestra de junio tiene 11.703 filas; de abril al 17 de junio son 54.157 filas de 18.756 de los 25.000 clientes (sondeo de solo lectura sobre S3, 26 sep). Esas son las filas máximas por tabla; la sección 4.2.1 propone publicar solo los clientes que usan los casos.

| Tabla `bank` | Origen | Filas | Columnas que viajan | Columnas que no viajan, y por qué |
| --- | --- | --- | --- | --- |
| `customers` | `gold_customers` | 25.000 | `customer_id` (PK), `full_name`, `country` (normalizado), `city`, `segment`, `registration_date`, `customer_status` | `document_number`, `document_type`, `email`, `mobile_phone`, `credit_score`, `accepts_marketing`: el flujo no los usa. Minimizar lo que sale a un tercero (regla 10, H02) |
| `products` | `silver_products` | 66.554 (23.311 tarjetas de 15.236 clientes) | `product_id` (PK), `customer_id` (FK), `product_type`, `product_status`, `currency`, `opening_date`, `expiration_date` | `product_number` (10 a 16 dígitos, con forma de número de tarjeta), saldos, límites, tasas y mora. Si la UI necesita "tarjeta terminada en", se publica solo `last4` |
| `transactions` | `gold_transactions` | 11.703 (junio); 54.157 (1 abr a 17 jun) | `transaction_id` (PK), `customer_id` (FK), `product_id` (FK), `transaction_date`, `process_date`, `transaction_type`, `amount`, `currency`, `amount_usd` (normalizado), `channel`, `merchant_name`, `merchant_category`, `transaction_country` (normalizado), `transaction_city`, `transaction_status` | `is_fraud` (la etiqueta) y `fraud_score` (la fuga). La app no los necesita, el modelo en línea no puede verlos y ningún visitante de la demo los encuentra |
| `complaints` | `silver_complaints` (2026) | 1.719 | `complaint_id` (PK), `customer_id` (FK), `creation_date`, `process_date`, `case_type`, `category`, `subcategory`, `status`, `claimed_amount`, `currency`, `is_repeat_complainer` | `description` y `resolution` (plantillas), y `affected_product_id`: el 100% de los valores no nulos apunta a productos de otro cliente (44.570 de 44.570 en todas las quejas), así que nunca es FK ni se usa en un join |
| `exchange_rates` | `bronze_daily_exchange_rates` | 13.164 | `date`, `source_currency`, `target_currency`, `exchange_rate` | Nada |

El CSV crudo trae además `transaction_category`, `branch_id`, `response_code`, `latitude` y `longitude`, que gold ya descarta; la ubicación tampoco viaja. Tamaño estimado de la muestra completa con índices: menos de 100 MB (unos 150 bytes por transacción antes de índices; por medir con `pg_total_relation_size` tras la primera carga). El techo del plan Free es 500 MB por proyecto: el tamaño no obliga a recortar.

#### 4.2.1 Qué clientes publicar, según los datos (propuesta)

Sondeo de solo lectura del 26 sep sobre S3 (transacciones del 1 abr al 17 jun 2026 de los 25.000 clientes de la muestra; cargo disputable según `POL-DISP-TYPE`; ventana medida con `process_date`):

| Qué necesita la suite (brief sección 5) | Lo que hay en los datos | Consecuencia |
| --- | --- | --- |
| Cargos disputables en ventana (normales, alto monto) | 32.109: 5.331 de hasta $150, 13.720 entre $150 y $500, 12.289 de más de $500 y 769 sin `amount_usd` | De sobra |
| Fuera de ventana (abstención) | 9.358 cargos reales de 61 a 77 días | De sobra; confirma el fixture de abstención |
| Ambiguo: dos cargos del mismo monto | 1 solo par (mismo monto y moneda, a 7 días o menos); 15 clientes con montos a menos de 5% el mismo día; 1.629 clientes con 2 o más cargos disputables en 48 h | La ambigüedad real viene de pistas vagas de fecha o comercio sobre varios candidatos (el comercio falta en el 77% de las filas), no de montos iguales. Reescribir la categoría "Ambiguous Charges" del brief |
| Varios cargos: 3 o más en 48 h | 70 clientes | Alcanza para la parte multi de los 35 casos de alto monto o multi |
| Anomalía: compra extranjera por Web o App | 429 cargos de 418 clientes | De sobra |
| Fraude real (`is_fraud`) | 42 en total (17 en abril, 16 en mayo, 9 en junio hasta el 17); 22 disputables en ventana | Justo para los 20 casos de "High Fraud Anomaly": usar todos o bajar la categoría y declararlo |
| Candidatos a `POL-AUT-150` | 1.681 cargos de 1.446 clientes | De sobra |

Lectura: los patrones escasos (ambiguo por monto, multi y fraude) se buscan en toda la muestra, y eso ocurre en DuckDB, donde se arma la suite. Supabase solo necesita los clientes que los casos usan. Como el tamaño no obliga a recortar, decide la minimización (regla 10, H02): se publican los clientes de la suite (desarrollo y held-out), las personas de la demo y el canario, con todos sus productos, quejas y transacciones de la ventana. Serán unos cientos de clientes. El script recibe esa lista (`data/serving_customers.json`, `team-generated`); hasta congelar la suite, `alterego-dev` recibe las personas y los clientes de desarrollo. Si los mentores permiten más, publicar la muestra completa es solo cambiar la lista.

### 4.3 Reglas del script de publicación (propuesta, frente A)

`src/data/publish_serving.py` lee gold en DuckDB y escribe `bank` en Postgres:

1. **Nombres y valores.** Normaliza "Mexico" a "México" en `country` y `transaction_country`, en UTF-8. Conserva los valores en español de `product_type` ("Tarjeta Crédito").
2. **Tiempo.** `transaction_date` viaja como `timestamp` sin zona, tal cual el CSV, y `process_date` como `date` tal cual. Ninguno pasa por `timestamptz`: la sesión de Postgres con otra zona correría las fechas. Nunca se recalcula `process_date` en Postgres.
3. **Montos.** Se conserva el `amount_usd` nativo cuando existe. El 5,15% de las filas en COP o ARS de abril a junio lo trae nulo (514 ARS y 755 COP: la trampa de nulos del dataset); el tipo de cambio diario de su `process_date` existe para las 1.269, así que se completan con él. Donde hay ambos, el `amount_usd` nativo difiere hasta un 2,1% del tipo diario: cerca del umbral de $500 eso puede cambiar la cláusula, así que el caso guarda qué fuente usó. Sin tipo de cambio la carga falla: nunca el respaldo `1.0` que hoy usa `gold_transactions`, que trataría pesos como dólares.
4. **Integridad.** Las FKs de `bank` se crean de verdad. Las filas huérfanas (0 en la muestra y 0 en la carga completa para las FKs que publica `bank`; el único huérfano del dataset, `customers.registration_branch_id`, no viaja) van a una tabla de cuarentena en DuckDB con su conteo, antes de cargar. Las PKs detectan IDs duplicados (0 hoy).
5. **Contratos.** Paridad de conteos por tabla entre DuckDB y Postgres, 0 huérfanos, ninguna columna prohibida en `bank` (test que lista las columnas), `max(process_date) <= 2026-06-17`.
6. **Recarga idempotente.** Vacía y carga `bank` en una sola transacción. Nunca toca `ops`.
7. **Respaldo si los mentores dicen que no.** El mismo script carga la base de fixtures del equipo con el mismo esquema, así que el cambio es de datos y no de código.

### 4.4 Esquema `ops` (propuesta, frente B)

| Tabla | Para qué | Claves y restricciones |
| --- | --- | --- |
| `ops.conversations` | Estado de la máquina de estados: idioma, estado, intentos de aclaración, señales tipadas. Nunca el texto crudo (fila "LangGraph y LangSmith" del plan) | `conversation_id` PK; `customer_id`, `session_id` del token |
| `ops.dispute_cases` | Casos abiertos por el sistema | `idempotency_key` UNIQUE; FK a `bank.transactions`; CHECK con valores del diccionario: `case_type = 'Claim'`, `category = 'Transactions'`, `subcategory IN ('Cargo no reconocido', 'Cobro indebido')`, `reception_channel = 'App'`, `status` en los estados del diccionario; índice único parcial: un solo caso abierto por (`customer_id`, `transaction_id`) |
| `ops.card_locks` | Bloqueos preventivos con la confirmación del cliente | `idempotency_key` UNIQUE; FK a `bank.products`; `confirmed_by_customer` NOT NULL |
| `ops.handoffs` | Paquete de handoff (JSON del brief 3.4) y revisión humana del candidato a crédito | `packet jsonb`, `review_status IN ('pending', 'approved', 'rejected')`, `reviewed_by`, `reviewed_at` |
| `ops.audit_log` | Auditoría append-only | Identidad `bigint`; `created_at timestamptz` (reloj real) y `business_date date` (el "hoy" simulado); `trace_id`, `session_id`, `auth_user_id`, `customer_id`, `action`, `target_id`, `verified`, `clause_ids`, `model`, `request_id`. Sin UPDATE ni DELETE para ningún rol de la app, más un trigger que los rechaza |
| `ops.llm_usage` | Tope diario de gasto del LLM (idea del starter, revisión de reuso) | Incremento atómico con `UPDATE ... WHERE n < limite RETURNING n` |

La tabla de "sesiones" que el plan le daba a SQLite desaparece: las sesiones viven en Supabase Auth y `ops` guarda solo su `session_id`.

La tarjeta no se bloquea escribiendo en `bank.products`: `bank` queda intacto y recargable. El bloqueo se escribe en `ops.card_locks` y el estado efectivo sale de una vista. La lectura de verificación lee esa vista, que es lo que el resto del sistema ve.

### 4.5 Hechos de política vivos (propuesta)

Vistas con `security_invoker = true` (las vistas de Postgres ignoran RLS si no se declaran así):

- `ops.v_product_status`: el estado de `bank.products`, reemplazado por el último bloqueo verificado de `ops.card_locks`.
- `ops.v_customer_policy_facts`: segmento, antigüedad de la cuenta, quejas de los últimos 90 días (las de `bank.complaints` más los casos de `ops.dispute_cases`) y tarjetas activas.

Con esto un cliente que abre varios casos de $150 o menos deja de verse "sin quejas en 90 días" para `POL-AUT-150` (H21), y el gotcha de gold desactualizado tras un bloqueo (`CLAUDE.md`) deja de aplicar a la app. Las vistas calculan hechos; las decisiones siguen en `src/rules/dispute_policy.py`.

### 4.6 "Hoy" y los dos relojes

Una función `ops.business_today()` devuelve `2026-06-17` y las vistas la usan. La constante de Python (`ANCHOR_DATE` y `DisputePolicyInput.current_date`) vive en un solo módulo y un test verifica que las dos coinciden. La auditoría guarda el reloj real y la fecha simulada, y la UI y el handoff muestran la simulada (H34).

### 4.7 Índices

`bank.transactions (customer_id, process_date DESC)`, `bank.products (customer_id)`, `bank.complaints (customer_id, creation_date)`, `ops.dispute_cases (customer_id, business_date)`, `ops.card_locks (product_id, created_at DESC)`. Bastan para las búsquedas de cargos candidatos, las ventanas de 48 horas de `POL-ESC-MULTI` y las features de velocidad.

## 5. Seguridad de la base (propuesta)

### 5.1 Nada expuesto por la Data API

El front usa Supabase solo para ingresar. Todo dato pasa por FastAPI, su contrato OpenAPI y sus tipos generados. Por eso `bank` y `ops` no se exponen en la Data API, `public` queda vacío y, si la configuración del proyecto lo permite sin afectar Auth, la Data API se desactiva. Desde el 28 abr 2026 las tablas nuevas de `public` ya no se exponen solas; igual se verifica la configuración del proyecto. Sin Realtime, Storage, GraphQL ni Edge Functions.

### 5.2 RLS en todas las tablas

RLS activo en cada tabla de `bank` y `ops` aunque no estén expuestas: es defensa en profundidad.

### 5.3 Rol mínimo para el API

El API se conecta con un rol propio, `app_gateway`, sin `BYPASSRLS`: `SELECT` en `bank`, `SELECT` e `INSERT` en `ops`, `UPDATE` solo en las columnas de revisión de `ops.handoffs` y de estado de `ops.conversations`, ningún `DELETE`, y solo `INSERT` en la auditoría. El API nunca usa la secret key ni el usuario `postgres`.

### 5.4 RLS por cliente (propuesta, endurecimiento del día 5)

Cada transacción del gateway empieza con `set_config('app.customer_id', <del token>, true)` y `set_config('app.app_role', ...)`. Las políticas de `app_gateway` filtran por esos valores. Un bug en el gateway ya no puede leer filas de otro cliente. El chequeo de propiedad en Python se mantiene (regla 6) y sigue devolviendo el mismo error hacia afuera para "no existe" y "no es tuyo". `SET LOCAL` funciona en el modo transacción del pooler porque vive dentro de la transacción.

### 5.5 Funciones y advisors

Ninguna función `SECURITY DEFINER` en esquemas expuestos. Los advisors de seguridad de Supabase (`get_advisors` del MCP o `supabase db advisors`) corren antes de G3 y quedan sin hallazgos.

### 5.6 Uso del MCP de Supabase

- Conexión con alcance a un proyecto: `https://mcp.supabase.com/mcp?project_ref=<ref>&read_only=true`. `read_only=true` corre todo como un usuario de Postgres de solo lectura.
- Con el proyecto demo, siempre en solo lectura. En el proyecto dev se permite escribir para iterar un esquema, con aprobación manual de cada llamada.
- El esquema canónico está en `supabase/migrations/*.sql`, revisado en un PR. El MCP inspecciona, corre advisors y ayuda a escribir migraciones; no aplica cambios sueltos que el repo no tenga.
- Riesgo de inyección: el contenido de las tablas (nombres de comercio) puede traer instrucciones. Los resultados del MCP son datos, nunca órdenes.
- Primer paso del día 3, en solo lectura: listar esquemas, tablas, extensiones, la configuración de la Data API y los advisors del proyecto, y compararlo con este documento antes de crear nada.

## 6. Despliegue en Vercel (decidido el 26 sep; los detalles marcados siguen en propuesta)

### 6.1 Topología

Un solo proyecto de Vercel. FastAPI se despliega sin configuración como una función de Python (`[tool.vercel] entrypoint = "src.api.app:app"` en `pyproject.toml`). El build de React se sirve con `app.frontend("/", directory="web/dist")`, que Vercel promueve a su CDN. Un dominio, sin CORS, igual que el plan de Render. Un script de build en `[tool.vercel.scripts]` compila el front.

Por verificar en el deploy esqueleto: que el build del proyecto de Python tenga Node para compilar el front, y que `app.frontend()` exista en nuestra versión de FastAPI. Si hay middleware de nivel superior (CORS u OpenTelemetry), Vercel deja los estáticos dentro de la función; se fuerza el CDN con `cdn = true` en `[tool.vercel.fastapi.static]`.

Configurado el 2 oct, todavía sin desplegar:

- `[tool.vercel] entrypoint = "src.api.app:app"`. Sin esa línea Vercel tomaría el `main.py` de la raíz, que es el demo del baseline.
- `[tool.vercel.scripts] build = "python scripts/deploy/vercel_build.py"` corre `npm ci` y `npm run build` en `frontend/` después de instalar Python. En Vercel se detiene si falta `VITE_SUPABASE_URL` o `VITE_SUPABASE_PUBLISHABLE_KEY`, porque sin ellas el front saldría con el selector de personas local, que responde 404 en producción.
- La app sigue montando `frontend/dist` en `/` con `StaticFiles` (no hace falta `app.frontend()`). Como no tiene middleware, Vercel promueve esos archivos al CDN.
- `vercel.json` saca del bundle `.agents`, `.archify`, `docs`, `notebooks`, `tests`, `reports`, `scripts`, `data/eval` y, del front, `node_modules`, `src` y `public`. Medido sobre el árbol: entran 105 archivos del repo (1,6 MB) más el front compilado; con los 358 MB de dependencias de la sección 6.3, el bundle queda en unos 360 MB.
- `tests/test_vercel_config.py` mantiene alineados el entrypoint, la clave de la función y las exclusiones: un archivo nuevo que la API lea en producción tiene que quedar fuera de `excludeFiles`.

Falta confirmar en el primer deploy que el build de Python tenga Node.

Respaldos, en orden: (1) un segundo proyecto de Vercel con el preset de Vite y un rewrite de `/api/*` al proyecto del API (los previews del front apuntarían al API de producción); (2) Vercel Services, que está en beta y pide permisos, así que no se usa de entrada; (3) Large Functions (beta, hasta 5 GB) o una imagen de contenedor en Vercel si el bundle no cabe.

### 6.2 Límites verificados que cambian el diseño

| Límite (26 sep) | Consecuencia |
| --- | --- |
| Python 3.12 (por defecto), 3.13 o 3.14; no hay 3.11 | Decidido: 3.12 en `.python-version`, `requires-python`, `uv.lock` y CI. Verificado el 26 sep con `uv pip compile --only-binary :all:`: los 28 paquetes directos del stack (los actuales del `pyproject.toml` más psycopg, lightgbm, onnxruntime, onnxmltools, skl2onnx, tokenizers, mlflow, pandera, anthropic y supabase) y sus 171 dependencias resuelven a la misma última versión con wheels binarias en Linux y Windows para 3.12, 3.13 y 3.14, igual que `typesafe-sdk==0.7.1` probado aparte. Empatan; 3.12 gana por ser el default de Vercel |
| Bundle de Python de 500 MB sin comprimir, sin tree-shaking | Dependencias separadas y bundle medido el 1 oct (6.3) |
| Hobby: 2 GB y 1 vCPU, 300 s por invocación | Suficiente para un turno de chat; los modelos se cargan una vez con el `lifespan` de FastAPI |
| Cuerpo de petición y respuesta de 4,5 MB | Sin impacto |
| Disco de solo lectura salvo `/tmp` | SQLite y DuckDB no sirven en la app; confirma el cambio a Postgres |
| Región por defecto `iad1` (Washington) | Crear los proyectos de Supabase en `us-east-1` para que la latencia a la base sea mínima |
| Cron en Hobby: una vez al día, con precisión de ±59 min | Alcanza para un canario diario (6.8), no para más |

### 6.3 Qué entra en la función

Hecho el 1 oct: `[project.dependencies]` lista solo lo que la API importa. Lo demás (tests, notebooks, scripts y entrenamiento: `pytest`, `httpx`, `ipykernel`, `nbclient`, `nbformat`, `matplotlib`, `seaborn`, `mlflow-skinny`, `boto3`, `alembic` y `sqlalchemy`) está en el grupo `dev`, que el builder de Python de Vercel no instala: corre `uv sync --no-dev` (`packages/python/src/uv.ts` del repo `vercel/vercel`, leído el 1 oct), igual que la imagen de producción. `tests/test_runtime_dependencies.py` recorre los módulos que la API alcanza desde `src.api.app`, con los imports dentro de funciones, y falla si alguno importa un paquete del grupo `dev`. Por eso el modelo de riesgo se sirve desde `src/ml/transfer_scorer.py`, sin el entrenamiento (`src/ml/fraud_risk_transfer.py`, que importa MLflow).

Medido en Linux con Python 3.12 (`site-packages` sin `__pycache__`): 595 MB antes y 358 MB después. Los archivos del repo suman 18,7 MB y viajan enteros salvo lo que excluya `excludeFiles` (10,4 MB son `.agents/`). Lo que más pesa sigue en runtime porque la API lo importa hoy:

| Paquete | MB | Por qué sigue |
| --- | --- | --- |
| `scipy` | 111 | Lo pide `scikit-learn` (32 MB más), que sirve el modelo de riesgo (TQ-022) |
| `duckdb` | 58 | El gateway, el ops store y `src.data` lo importan al cargar la API, aunque en Vercel se use Postgres |
| `numpy` | 57 | BM25 y el modelo de riesgo |
| `pandas` | 41 | El contrato de features del modelo de riesgo |
| `psycopg-binary` | 20 | Postgres |
| `cryptography` | 15 | La verificación ES256 de las sesiones |

Sin E5 el bundle queda en unos 377 MB. Con E5 (6.5) llegaría a unos 609 MB: con el código de hoy no cabe. Servir el modelo de riesgo en ONNX (6.4) sacaría `scikit-learn` y `scipy` (143 MB) y lo dejaría en unos 466 MB, pero TQ-022 mantuvo scikit-learn el 2 oct: en Vercel va BM25, sin E5; importar `duckdb` solo en el camino local ahorraría 58 MB más. El SDK de Anthropic y `onnxruntime` entran cuando haya código de la API que los use; hasta entonces `onnxruntime` y `tokenizers` están en el grupo `dev`, para medir E5 offline (Tarea 2.3).

### 6.4 Riesgo del runtime de inferencia

Medido el 26 sep sobre las ruedas `manylinux_2_28` para Python 3.12:

| Paquete | Sin comprimir | Librerías del sistema que exige |
| --- | --- | --- |
| `lightgbm` 4.7.0 | 9,7 MB, más `scipy` 1.18.1 (111,9 MB) como dependencia | `libgomp.so.1` (OpenMP), que la rueda no incluye |
| `onnxruntime` 1.30.0 | 63,8 MB | Ninguna fuera de libc y libstdc++ |
| `numpy` 2.5.3 | 56,4 MB | Ninguna (lo piden los dos caminos) |

Propuesta: entrenar con LightGBM y servir el modelo exportado a ONNX (`onnxmltools`) con `onnxruntime`, el mismo runtime que ya piden los embeddings del RAG. Ahorra unos 122 MB del bundle y elimina la dependencia de `libgomp`, que el runtime de Vercel puede no tener. El deploy esqueleto del día 4 lo confirma; el reporte compara las predicciones de LightGBM y de su exportación ONNX sobre el split de validación.

### 6.5 Embeddings del RAG

Los modelos multilingües pequeños pesan cientos de MB en fp32 por su vocabulario de unos 250.000 tokens. Se usa la versión cuantizada a int8, se descarga en el build y los embeddings de los unos 15 fragmentos del corpus se calculan en el build. pgvector no aporta con 15 vectores: quedan en memoria.

Medido el 1 oct en el contenedor (Tarea 2.0 de `docs/RAG_IMPLEMENTATION_ROADMAP.md`): `onnxruntime` 1.30.0 y `tokenizers` 0.23.2 suman 97 MB con sus dependencias (62 y 12 MB, más unos 20 MB de `huggingface-hub` y `hf-xet`, que pide `tokenizers`); el modelo int8 pesa 118,3 MB y el tokenizer 17,1 MB. En frío, con un hilo como la función de 1 vCPU y en 10 procesos nuevos: importar toma p50 0,65 s, crear la sesión y cargar el tokenizer p50 1,18 s (máximo 4,24 s) y la primera consulta 10 ms; en caliente, p50 8,4 ms. Hoy no cabe en el bundle (6.3).

### 6.6 Funciones sin estado

Vercel escala a varias instancias y ninguna guarda estado entre peticiones. La cola en memoria del pipeline inicial (`hitl_queue`) no funciona desplegada: el pipeline inicial es un baseline de referencia, así que corre solo en el harness y no se despliega. El estado de la conversación vive en `ops.conversations`.

### 6.7 Conexión a Postgres

Pooler de Supabase (Supavisor) en modo transacción, puerto 6543, que funciona por IPv4 (la conexión directa del plan Free es solo IPv6). psycopg 3 con `prepare_threshold=None`, porque el modo transacción no admite sentencias preparadas. Un cliente a nivel de módulo, pool de 1 conexión y `sslmode=require`. Usuario `app_gateway.<project-ref>`. En código desde el 3 oct para las conexiones del gateway y del ops store (`tests/test_pooler_connections.py`); el código abre una conexión por llamada, no un pool, y `sslmode=require` va en la propia `DATABASE_URL`.

### 6.8 Pausa de Supabase y monitoreo

El plan Free pausa un proyecto tras 7 días con poca actividad. Entregamos el 5 oct, los finalistas salen el 15 y la premiación es el 16: un jurado que abre la URL el día 13 puede encontrar la base pausada. El equipo decidió no pagar Supabase Pro (26 sep), así que la mitigación es:

1. **Canario doble e independiente.** Un cron diario de Vercel (Hobby permite uno por día, con ±59 min de precisión) y un workflow programado de GitHub Actions cada 12 horas llaman al mismo endpoint `/api/v1/canary`, protegido con un secreto (`CRON_SECRET` en el header `Authorization`). El canario ingresa con una persona dedicada en Supabase Auth (actividad de Auth), lee `bank`, escribe una entrada `CANARY` en `ops.audit_log` y la lee de vuelta (actividad de base). No abre casos, así que no ensucia los datos de la demo. Dos programadores distintos evitan que la caída de uno deje el proyecto sin tráfico.
2. **Aviso.** Si el canario falla, el workflow de GitHub Actions falla y GitHub avisa por correo a Daniel. Esto también cubre el monitoreo que pedía H14.
3. **Revisión y restauración manual.** Daniel revisa el dashboard de Supabase el 8, el 12 y el 15 oct. Si el proyecto se pausó, lo restaura desde el dashboard (un proyecto Free pausado se puede restaurar durante 90 días).
4. **Riesgo residual declarado.** La documentación de Supabase no dice qué cuenta como actividad, así que el canario reduce el riesgo pero no lo elimina. El reporte lo dice en limitaciones, y el video y las capturas quedan como evidencia de que el sistema funciona aunque la URL falle.

### 6.9 Previews, CI y cuentas

- Cada PR genera un preview. Por defecto los previews piden Vercel Authentication: Playwright necesita el secreto de "Protection Bypass for Automation".
- Dos proyectos de Supabase Free (el máximo del plan): `alterego-dev` para previews, CI end-to-end y pruebas del harness, y `alterego-demo` para producción. Las variables de entorno de Preview apuntan a dev y las de Production a demo.
- Variables del API: `SUPABASE_URL` (JWKS y emisor), `DATABASE_URL` (pooler con `app_gateway`), las keys de LLM. Del front, en build: `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY`. Nunca en Vercel: la secret key de Supabase ni las keys de AWS del diccionario.
- El plan Hobby de Vercel es personal y no comercial, y su dashboard (logs, variables) tiene un solo usuario: solo el dueño ve los logs. Por verificar en los términos vigentes. Daniel es el dueño y comparte los logs que B necesite.

### 6.10 Latencia y costo en el reporte

La latencia p50 y p95 se mide contra producción en Vercel y el arranque en frío se reporta aparte (H32). En planes gratis el costo real de cómputo es $0, así que el costo por caso se estima con la tarifa de CPU activa de Vercel Pro y la de Supabase Pro, declaradas como supuestos de una operación real, más los tokens medidos.

## 7. Pruebas, harness y desarrollo local (propuesta)

- **Migraciones versionadas** en `supabase/migrations/`. Las de `bank` y `ops` no dependen de objetos que solo existen en Supabase (nada de FKs a `auth.users`): corren igual en un Postgres 17 común. Un script de apoyo crea en CI los roles que Supabase trae (`anon`, `authenticated`) para las políticas.
- **Tests.** Los del gateway pasan del fixture de DuckDB (`tests/test_dispute_flow.py`) a un fixture de Postgres con los mismos escenarios: dueño, otro cliente y cliente inexistente. Tests nuevos: el verificador (ES256 válido; HS256, `alg: none`, `iss` o `aud` ajenos y vencido dan 401; sin `customer_id`, 403; rol de agente en la consola), permisos de `app_gateway` (no puede borrar ni editar la auditoría), contratos de publicación y la paridad de `business_today()`.
- **CI.** El GitHub Action levanta un servicio `postgres:17`, aplica las migraciones y corre `pytest`.
- **Harness con dos modos.** Local: emisor local y Postgres local con la misma publicación; corre las 3 repeticiones y los casos de sesión vencida y token forjado. Desplegado: personas reales en `alterego-dev` o demo, con un ritmo por debajo de 150 pedidos de token cada 5 minutos; de esta corrida sale la latencia reportada. El reporte dice de qué modo sale cada métrica.
- **`docker-compose up`** levanta API, Postgres y el emisor local: cualquiera reproduce el sistema sin cuenta de Supabase. El CLI de Supabase (`supabase start`) queda opcional para quien toque el flujo de ingreso.
- **Reuso del starter.** La revisión de reuso descartó su runner de migraciones y su idempotencia "porque el plan no usa Postgres". Ahora sí lo usa: esas dos piezas se reusan casi directas, con el arreglo del bug 6.6.

## 8. Qué cambia en el código cuando se salga del modo planeación

Referencia para estimar, no para ejecutar hoy.

| Archivo | Cambio |
| --- | --- |
| `src/auth/session.py` | `SessionVerifier` (JWKS y local), `VerifiedSession` con `auth_user_id`, `customer_id`, `app_role`; se elimina `JWT_SECRET` |
| `src/tools/gateway.py` | De DuckDB a psycopg: lecturas de `bank` y de las vistas, escrituras en `ops`, idempotencia, auditoría en la misma transacción, lectura de verificación en una transacción nueva |
| `src/data/db.py` | Queda para DuckDB (ingesta y notebook); una conexión nueva a Postgres para el API |
| `src/data/publish_serving.py` | Nuevo (sección 4.3) |
| `supabase/migrations/` | Nuevo: `bank`, `ops`, vistas, roles, grants, RLS |
| `src/auth/seed_personas.py` | Implementado: personas desde `data/fixtures/personas.json`; secret key solo local |
| `src/api/app.py` | Endpoints nuevos detrás de `get_current_session`; `/api/v1/canary` protegido con `CRON_SECRET`; la cola en memoria sale del despliegue |
| `vercel.json`, `.github/workflows/canary.yml` | Cron diario de Vercel y workflow programado cada 12 h contra el canario |
| `data/serving_customers.json` | Nuevo (`team-generated`): lista de clientes que se publican (suite, personas, canario) |
| `pyproject.toml`, `.python-version`, `uv.lock` | Python 3.12, grupos de dependencias, `[tool.vercel]` |
| `Dockerfile`, `docker-compose.yml` | Postgres local, emisor local |
| `tests/test_dispute_flow.py` | Fixture de Postgres; tests del verificador |
| `frontend/` | Implementado: React con `@supabase/supabase-js` 2.117.2 fijado, solo para ingresar; Node 22 o superior |

## 9. Riesgos nuevos

| # | Riesgo | Impacto | Mitigación | Dueño | Cuándo |
| --- | --- | --- | --- | --- | --- |
| R1 | Más trabajo en la ruta crítica de B antes de G1 (agrava H03) | G1 se corre y arrastra G2 y G3 | Repartir: Daniel crea proyectos, personas y el MCP; A escribe la migración de `bank` y la publicación; B el verificador, `ops` y el gateway; C el ingreso y el deploy esqueleto. G1 puede correr contra `alterego-dev` o contra Postgres local | Daniel | 27 sep |
| R2 | Pausa del plan Free en la ventana de jurados (sin Pro, decidido el 26 sep) | La URL pública falla ante un jurado | Canario doble (Vercel y GitHub Actions), aviso por correo, revisión manual el 8, 12 y 15 oct, restauración; riesgo residual declarado en el reporte | Daniel | Día 8 y del 6 al 16 oct |
| R3 | El bundle pasa 500 MB o LightGBM no importa (su rueda exige `libgomp.so.1`, medido el 26 sep) | El deploy falla el día 8 | ONNX como runtime único desde el inicio; deploy esqueleto el 28 sep con los paquetes pesados; Large Functions como respaldo | B | 28 sep |
| R4 | Arranque en frío | p95 alto | Carga en `lifespan`; arranque en frío reportado aparte | B y A | Día 7 |
| R5 | Datos del organizador en un tercero | Choque con la regla 10 si los mentores dicen que no | Columnas mínimas, sin etiqueta ni fuga ni números de tarjeta; fixture del equipo con el mismo esquema | Daniel y A | Respuesta de mentores |
| R6 | El emisor local llega a producción | Cualquiera forja tokens | Guarda de `APP_ENV`, arranque que falla y test | B | Día 3 |
| R7 | El MCP escribe donde no debe o sigue una instrucción inyectada | Pérdida o cambio de datos | `project_ref` y `read_only=true` en demo; cambios solo por migraciones revisadas | Daniel | Día 3 |
| R8 | Límites de Auth frenan el harness desplegado | Corrida incompleta | Ritmo controlado, caché de tokens, límites más altos en dev | A | Día 7 |
| R9 | Python 3.11 local frente a 3.12 en Vercel | Diferencias entre local y producción | Decidido: todo a 3.12; ningún paquete del stack pierde versión (verificado el 26 sep) | B | Día 3 |
| R10 | Hobby de un solo usuario | Solo el dueño ve logs y variables | Daniel es el dueño y comparte los logs que B necesite; sin plan pago (decidido el 26 sep) | Daniel | Día 4 |

## 10. Decisiones

Cerradas el 26 sep:

1. **Vercel en lugar de Render.** El deploy esqueleto del 28 sep es la prueba. Si el bundle falla y Large Functions no alcanza, el API se sirve como imagen de contenedor en Vercel; ya no depende de un disco local porque el estado vive en Supabase.
2. **Sin pago.** Supabase Free (sin Pro) y Vercel Hobby. La pausa se mitiga como dice la sección 6.8.
3. **Harness en dos modos**, con la latencia del modo desplegado.
4. **Python 3.12** en todo el repo: empata con 3.13 y 3.14 en todos los paquetes y es el default de Vercel.

Abiertas o en propuesta:

1. **Datos en Supabase.** El equipo pidió decidir según los datos: la sección 4.2.1 propone publicar solo los clientes de los casos, las personas y el canario, sujeto también a la respuesta de los mentores.
2. **Nombres de claims.** `app_metadata.customer_id` y `app_metadata.app_role`.
3. **Runtime de inferencia.** ONNX desde el inicio (evidencia en 6.4).

## 11. Fuentes (verificadas el 26 sep 2026)

- Supabase: [changelog](https://supabase.com/changelog), [claves de firma JWT y JWKS](https://supabase.com/docs/guides/auth/signing-keys), [API keys](https://supabase.com/docs/guides/api/api-keys), [custom access token hook](https://supabase.com/docs/guides/auth/auth-hooks/custom-access-token-hook), [rate limits de Auth](https://supabase.com/docs/guides/auth/rate-limits), [conexión a Postgres y pooler](https://supabase.com/docs/guides/database/connecting-to-postgres), [pausa de proyectos Free](https://supabase.com/docs/guides/platform/free-project-pausing), [facturación](https://supabase.com/docs/guides/platform/billing-on-supabase), [MCP](https://supabase.com/docs/guides/getting-started/mcp)
- Vercel: [runtime de Python](https://vercel.com/docs/functions/runtimes/python), [límites de funciones](https://vercel.com/docs/functions/limitations), [FastAPI en Vercel](https://vercel.com/docs/frameworks/backend/fastapi), [Services](https://vercel.com/docs/services), [cron jobs](https://vercel.com/docs/cron-jobs/usage-and-pricing)
- Repo: `AGENTS.md` (reglas y hallazgos de datos), `docs/PLAN.md` (registro de decisiones), `docs/reviews/2026-09-26-revision-adversarial-plan.md` (H01, H03, H12, H15, H21, H32, H34), `docs/reviews/2026-09-26-reuso-lead-agent-crm-starter.md`, `docs/SECURITY_AUDIT_PLAN.md`
