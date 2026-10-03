# Handoff del equipo (3 oct 2026)

Lo escribió Daniel con Claude el 3 de octubre, día 9 de 10. La entrega es el **5 de octubre** (`AGENTS.md` sección 3). El equipo quedó en dos personas, Daniel y Kmilo. **Desde la tarde del 3 de octubre, Kmilo sigue solo con todo lo restante.** Lo que exige cuentas de Daniel está en la sección 5.

Este documento dice qué hay en `main`, qué falta y quién lo toma. El detalle técnico está en los documentos que enlaza.

## 1. Estado

- **`main` incluye todo hasta el PR #36.** No quedan PRs abiertos y la CI está en verde.
- **App pública: <https://alterego-silk.vercel.app>** (proyecto `alterego` en Vercel).
  - Cada merge a `main` se despliega solo a producción.
  - El login usa Supabase, con las cuatro personas de `data/fixtures/personas.json` (tres clientes y un agente).
- **Supabase: un solo proyecto, `AlterEgo`, que también es producción.** El diseño de `docs/SUPABASE_VERCEL.md` habla de dos proyectos (dev y demo), pero el de demo nunca se creó.
  - El 3 de octubre se aplicaron las migraciones 0001 a 0004.
  - `bank` se publicó con paridad: 253 clientes (las 3 personas y los 250 del held-out, listados en `data/serving_customers.json`), 902 productos, 385 transacciones y 18 quejas.
  - El rol `app_gateway` tiene login.
- **Held-out (250 casos, congelado el 30 de septiembre):**
  - Corrida ciega: 63,6 % de resolución segura y 12,4 % de inseguros (#12).
  - Después de los fixes: 98,1 % y 8,0 %. Los 20 inseguros son los 20 casos `high_fraud_anomaly`: sin el archivo del modelo, `POL-ESC-ML-RISK` nunca se dispara.

| Gate del plan | Estado |
| --- | --- |
| G0, decisiones | Hecho (26 sep) |
| G1, conversación en español de punta a punta | Hecho (27 sep) |
| G2, suite congelada y modelo mejor que el baseline | A medias: la suite está congelada, pero el modelo de riesgo no tiene medición de punta a punta y faltan las etiquetas humanas |
| G3, URL pública | A medias: la URL sirve `main`, pero el canario no existe |
| G4, entrega | Pendiente |

### Qué entró desde el 29 de septiembre

- **30 sep:** se congeló el held-out y entraron seis fixes, cada uno con su test (#12 a #14).
- **1 oct:**
  - el explicador de la política con BM25 (#15 a #22);
  - el runtime separado del grupo `dev` (#23);
  - E5 medido solo offline (#24).
- **2 oct:**
  - las respuestas a las TQ (#27);
  - el banco de preguntas redactado por un LLM y el explicador encendido (#28);
  - el login con Supabase, con `APP_ENV` que falla cerrado (#29);
  - la configuración de Vercel (#30).
- **3 oct:**
  - el pooler sin prepared statements (#31);
  - el handoff que dice "riesgo no calificado" y el bloqueo solo de tarjetas activas (#32);
  - el README final (#33);
  - el arreglo del entrypoint para Vercel (#34);
  - la lista de clientes publicada (#35);
  - las respuestas de Claude, tareas 1 y 2 de 7 (#36).

## 2. Cómo arrancar (Kmilo)

1. `git pull`, y después `docker compose build dev`: el lock cambió (`anthropic` entró al runtime con el #36).
2. En tu `.env`, pon `APP_ENV=development`. Si queda vacío, la app corre como producción y no arranca sin `SUPABASE_URL` (`CLAUDE.md`, Gotchas).
3. Para correr la suite como la corre la CI: `docker compose run --rm dev`.
4. **La suite held-out está congelada.** No se editan sus casos ni se ajusta un umbral mirando sus resultados. Un bug que revele se arregla con un test propio (`CLAUDE.md`).
5. **Flujo de trabajo:**
   - una rama desde `main` por cambio;
   - TDD con un commit Red, uno Green y uno de docs;
   - el PR se mergea con la CI en verde.
   - En los PR, el check de Vercel sale rojo ("Deployment was blocked"): es la verificación de autor del plan Hobby, no un error del código.

## 3. Pendientes y dueño propuesto

Actualización de la tarde del 3 de octubre: **Kmilo toma todo.** La columna Dueño queda solo como referencia de quién conoce cada tema. Las tareas que necesitan cuentas de Daniel (Supabase, Anthropic, Vercel) dependen de los accesos de la sección 5.

Los dueños son una propuesta y quedan por confirmar. Kmilo toma eval y ML; Daniel, despliegue, seguridad y entrega.

### A. Bloquea la entrega

| # | Tarea | Dueño |
| --- | --- | --- |
| A1 | **Seguridad antes de hacer público el repo** (regla 10). El 2 de octubre la secret key de Supabase y la contraseña de la base quedaron en un chat, y ese proyecto hoy es producción. Hay que rotar las dos, más la key de Anthropic y las claves de las personas (`python -m src.auth.seed_personas --email-pattern '<el mismo patrón de correo del alta>' --reset-passwords`), y correr gitleaks sobre todo el historial. | Daniel |
| A2 | **Borrar las filas de la prueba de humo en producción.** Una de esas conversaciones abrió un caso real para `cliente-hasta-150`, y como el cargo ya tiene caso abierto, la demo de esa persona no puede abrir otro. Se hace en el SQL Editor (el MCP de Supabase rechaza `DELETE`); el SQL va abajo. | Daniel |
| A3 | **Corregir los docs que dicen que no hay despliegue:** README (estado y limitaciones), `AGENTS.md` sección 9 (la línea "not deployed yet"), `CLAUDE.md` y `docs/PLAN.md`. | Daniel |
| A4 | **TQ-034 y TQ-035** (decididas el 2 oct, sin código). La TQ-034 son los dos denominadores en `src/eval/metrics.py`. La TQ-035: el juez cuenta como insegura una abstención en un caso que necesitaba humano. Eso cambia las cifras, así que hay que recalcular la corrida ciega y la posterior antes de las slides. También falta commitear el reporte del held-out (TQ-019). | Kmilo |
| A5 | **La entrega.** Slides en inglés, video de 3 minutos, repo público `factored-hackathon-2026-alterego` y correo a `hackathon.admin@factored.ai` con las credenciales de los jurados solo ahí (`docs/PLAN.md`, roadmap). | Daniel |

SQL de A2 (borra solo las dos conversaciones de prueba; la auditoría no se puede borrar, por diseño):

```sql
delete from ops.messages where conversation_id in ('CONV-3820F168B183', 'CONV-80042ABEA25C');
delete from ops.dispute_cases where conversation_id in ('CONV-3820F168B183', 'CONV-80042ABEA25C');
delete from ops.conversations where conversation_id in ('CONV-3820F168B183', 'CONV-80042ABEA25C');
select count(*) as casos_restantes from ops.dispute_cases;  -- debe dar 0
```

### B. Pesa mucho ante el jurado

| # | Tarea | Dueño |
| --- | --- | --- |
| B1 | **Modelo de riesgo** (TQ-032). Generar `models/fraud_risk_ieee.joblib` (los datos de IEEE-CIS van en `data/kaggle`; en la máquina de Daniel no están ni el modelo ni los datos). Agregar al harness un modo con el modelo, porque hoy `src/eval/` no carga el scorer, y correr el held-out con él. Es el entregable de ML obligatorio. El modelo está en el `.gitignore`, así que también hay que decidir cómo llega a Vercel. | Kmilo |
| B2 | **Etiquetas humanas y kappa** (TQ-018). El kit es para 4 personas; con dos, lo viable es que ambos etiqueten los 50 casos dobles (`data/eval/labeling/README.md`). Hay que declarar que Daniel ya vio las etiquetas de diseño. | Kmilo y Daniel |
| B3 | **Pausa de Supabase.** El proyecto Free se pausa si nadie lo usa, y el juzgamiento sigue hasta el 16 de octubre. El canario se decidió pero no se construyó. Lo mínimo es un cron de GitHub Actions que entre con una persona, o revisar el proyecto a mano el 8, el 12 y el 15. | Daniel |

### C. Si sobra tiempo

- **Respuestas redactadas por Claude Haiku: faltan las tareas 3 a 7.**
  - El plan es `docs/specs/claude-replies-v1-plan.md`. Las tareas 1 y 2 (guarda y redactor) ya están en `main`, pero nada las llama todavía.
  - Faltan el orquestador, el cableado, la verificación manual con la key real (unos 0,07 USD, ya aprobada), los docs y el PR.
  - Para que producción redacte, `ANTHROPIC_API_KEY` tiene que ir en Vercel como Sensitive.
  - Las rulings y los pendientes menores de la revisión están en la descripción del PR #36.
- **TQ-028, TQ-029 y TQ-031:** respondidas, sin código.
- **Inconsistencias en los docs:** el umbral de 0,70 en `TEAM_BRIEF_COMPLEMENTED.md`, LightGBM y ONNX en `docs/PLAN.md`, y la frase "is_fraud random".
- **Bug de demo:**
  - Después de un saludo, la conversación queda en `awaiting_clarification`, y en ese estado no se consulta el explicador.
  - Una pregunta de reglas que nombra un cargo ("¿Cuántos días tengo para disputar un cargo?") se lee como disputa.
  - Si el cliente tiene un solo cargo, abre su caso.
  - Pide un test propio y un caso en el split de desarrollo.
- **Menores:**
  - `/health` todavía dice "OmniGuard AI".
  - El advisor de Supabase avisa `search_path` mutable en `ops.reject_audit_change` y `ops.business_today` (una migración 0005 lo arregla).
- **TQ abiertas:** 002, 004, 016, 018, 019, 023, 025 y 036. Para la 036 (OpenTelemetry) se recomienda darla de baja formalmente.

## 4. Producción: cómo está armada

- **Vercel:** proyecto `alterego` en la cuenta Hobby de Daniel.
  - Un merge a `main` despliega producción; las previews de los PR se bloquean.
  - Variables de producción: `APP_ENV=production`, `SUPABASE_URL`, `DATABASE_URL` (rol `app_gateway` por el pooler en modo transacción, puerto 6543, sensible), `VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY`. Preview tiene las mismas, menos `DATABASE_URL`.
  - Todavía no hay keys de LLM en Vercel.
  - **Nunca despliegues con la CLI desde una carpeta que tenga `.env`:** la subida lo incluiría. Usa un checkout limpio.
- **Supabase:**
  - `app_gateway` solo lee `bank` y solo inserta en la auditoría.
  - Para volver a publicar `bank` se usa `python -m src.data.publish_serving --database-url ... --customers data/serving_customers.json`, con una conexión que pueda escribir `bank`. El rol `bank_publisher` quedó sin login y sin clave: se le da una clave temporal para publicar y se le quita al terminar.
- **Jev:** la key (`TYPESAFE_API_KEY`) no está en el `.env` de Daniel. Sin ella, el router usa las palabras clave.

## 5. Accesos y secretos

Daniel los pasa **por privado: nunca por el repo, por un issue ni por el chat de un asistente de IA.** Ninguno está en git.

- **Supabase.** Invitar a Kmilo a la organización "Chackmilo's Org", donde está el proyecto AlterEgo. Con eso Kmilo puede:
  - entrar al SQL Editor (la limpieza de A2);
  - rotar las claves (A1);
  - crear su propia secret key, que necesita para `seed_personas`.
- **Claves de producción:**
  - **La clave de `app_gateway`.** Con ella se arma la `DATABASE_URL` de producción, que hace falta para un despliegue propio o para correr la API local contra producción.
  - **Las claves de las personas.** Están en `personas.local.json`, que está en el `.gitignore`. Si no llegan, Kmilo las regenera con `seed_personas --reset-passwords` usando su secret key.
  - **`VITE_SUPABASE_URL` y `VITE_SUPABASE_PUBLISHABLE_KEY`**, para `frontend/.env.local`. Son públicas por diseño y también están en el dashboard (Project Settings, API Keys).
- **Otras keys:** las de AWS del diccionario de datos, para la ingesta desde S3. Kmilo puede usar su propia key de Anthropic, y la de Jev si la tiene.
- **Vercel.** El proyecto `alterego` está en la cuenta Hobby de Daniel, y Hobby no admite colaboradores. **Lo más probable es que un merge hecho por Kmilo quede bloqueado ("Deployment was blocked") y que producción no se actualice.** Hay que comprobarlo con el primer merge. Las opciones son:
  - a. Kmilo crea su propio proyecto en Vercel con las mismas variables de la sección 4 y despliega con la CLI desde un checkout limpio. La URL cambia: en la entrega va la nueva.
  - b. Daniel hace los merges finales.
  - c. El proyecto pasa a un equipo Pro, en prueba, y Daniel invita a Kmilo.
- **Lo que quedó solo en la máquina de Daniel (en el `.gitignore`):** los handoffs de sesión de Claude y el registro de la ejecución del plan de Claude replies. Lo esencial de ambos está en este documento y en la descripción del PR #36.

## 6. Preguntas para Kmilo

1. ¿Tienes la key de Jev?
2. ¿Tienes los datos de IEEE-CIS para regenerar el modelo de riesgo?
3. ¿Cuál de las opciones de Vercel de la sección 5 vas a usar para desplegar?
