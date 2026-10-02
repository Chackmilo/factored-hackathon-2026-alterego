# Spec: respuestas redactadas por Claude Haiku (v1)

Estado: diseño aprobado por secciones en el chat el 2026-10-02 (Daniel); este documento lo fija para su revisión escrita. Rama: `feat/claude-replies`, desde `main` en `7484976`.

- **Porción:** Claude Haiku 4.5 redacta la prosa de las aclaraciones (el saludo incluido) y de los escalamientos de la política, en español y portugués. El código protege los datos con fichas, valida el borrador y lo rellena; si algo falla, responde la plantilla de hoy.
- **Manda:** la regla 6 de `AGENTS.md` (el modelo propone, el código decide), la regla 10 (ni credenciales ni registros del dataset en llamadas a modelos externos), las filas "Understand y conversación", "Proveedor del LLM", "Datos que ven los modelos" y "Keys y presupuesto" de `docs/PLAN.md`, y el Sistema 2 de `docs/JEV_TYPESAFE_AI.md` sección 4.
- **Ya en el código:** `UnderstandRouter` (`src/understand/router.py`) elige `reply_engine` (`claude` con key y presupuesto, `template` sin ellos) y lo audita, pero ninguna llamada a Claude existe: la respuesta es siempre la plantilla. `LlmBudget` (`src/llm/budget.py`) controla el tope diario y anota el gasto en `ops.llm_usage`.
- **Fuera:** sección 7.

## 1. Problema

En la prueba del navegador del 2 oct, un cliente que escribió "hola" recibió "No encontramos un cargo que coincida con su descripción. ¿Podría indicarnos la fecha, el monto o el comercio del movimiento?" seguido de la lista de sus movimientos. La política acierta (`POL-CLARIFY`), pero el texto suena a formulario. El kickoff pide mantener el contexto conversacional y aclarar con naturalidad, y el plan ya decidió (26 sep) que Claude Haiku 4.5 redacta sobre plantillas con datos verificados. La key de Anthropic existe desde el 2 oct.

## 2. Decisiones del 2 oct

| Id | Decisión | Descartado y por qué |
| --- | --- | --- |
| D1 | Claude redacta solo las aclaraciones de la política (el saludo incluido) y sus escalamientos. Las confirmaciones (caso abierto, tarjeta bloqueada), las abstenciones, la oferta de bloqueo, los handoffs operativos (banco caído, verificación fallida) y las respuestas del explicador de política siguen con la plantilla | Todas las respuestas: Claude tocaría números de caso y confirmaciones verificadas, con más riesgo, costo y latencia. Solo el saludo: no mejora el resto de las aclaraciones |
| D2 | Reescritura con fichas: Claude recibe la prosa con los datos reemplazados por fichas y la devuelve redactada con las mismas fichas; el código valida y rellena | Una frase de apertura y la plantilla intacta: el resto sigue rígido. Redacción libre con los datos: Claude vería montos y comercios del banco, contra "Datos que ven los modelos" y la regla 10 |
| D3 | Sin LangGraph: el orquestador determinista se queda | Migrar a LangGraph a tres días de la entrega; su especialista ReAct deja que el LLM elija herramientas que escriben (regla 6). Ver `docs/reviews/2026-09-26-reuso-lead-agent-crm-starter.md` |

## 3. Diseño

### 3.1 Prosa y anexo

Cada respuesta del alcance de D1 tiene dos partes:

- **Prosa:** la explicación de la decisión (`DisputePolicyDecision.explanation_es` o `explanation_pt`), que el orquestador hoy pone primero en `result.reply`.
- **Anexo:** lo que el orquestador agrega después: la lista de movimientos (`_format_candidates`) en una aclaración, y la referencia del handoff (`TEXT["handoff_ref"]`) en un escalamiento.

Solo la prosa va a Claude. El anexo lo arma siempre el código, igual que hoy, así que la lista de cargos y las referencias no cambian nunca.

### 3.2 Guarda (`src/llm/reply_guard.py`, nuevo y determinista)

- `protect(prose, known_values)` reemplaza, en orden de aparición, cada dato por una ficha `⟦1⟧`, `⟦2⟧`, ...: fechas ISO, montos y cualquier otro número, ids (`CASE-`, `HO-`, `LOCK-`, `CLI-`, `PRD-` seguidos de su código), fragmentos de tarjeta (`...W7T0`) y los valores del banco que el orquestador conoce para el turno (comercio, tipo y estado del movimiento). Devuelve el esqueleto y el mapa ficha a valor.
- `restore(draft, mapping)` rechaza el borrador (`GuardRejected` con un motivo) si falta una ficha o aparece dos veces, si trae una ficha desconocida, si queda algún dígito fuera de las fichas, si contiene una URL o un email, si está vacío o si supera el mayor de dos largos: 600 caracteres o el doble del esqueleto. Si pasa, devuelve el texto con los valores restaurados.

### 3.3 Redactor (`src/llm/reply_writer.py`, nuevo)

- `ClaudeReplyWriter` usa el SDK oficial `anthropic` con el modelo fijado `claude-haiku-4-5-20251001` (la constante `CLAUDE_MODEL` del router), `timeout` de 5 s, `max_retries=1` y `max_tokens=400`, sin thinking.
- Recibe el esqueleto, el mensaje del cliente ya enmascarado (`PIIMasker`) y el idioma. El prompt vive en `src/llm/prompts/reply_v1.md`; su SHA-256 corto es la versión del prompt que se audita. El mensaje del cliente va entre etiquetas `<customer_message>` como dato, nunca como instrucción.
- El prompt pide: redactar en el idioma del cliente, con el mismo significado y la misma pregunta, en tono cercano y breve; conservar cada ficha exactamente una vez; no agregar cifras, nombres, enlaces ni promesas (reembolsos, créditos, plazos que la prosa no trae); saludar de vuelta si el cliente saludó; devolver solo el texto.
- Devuelve el borrador con `model`, `request_id` y tokens de entrada y salida. Un timeout, un error de conexión o de la API, o `stop_reason == "refusal"` se convierten en `WriterUnavailable` con el motivo.

### 3.4 Orquestador

- Donde hoy fija `reply=self._text(decision, language)`, el orquestador pide la prosa a un método nuevo. Este usa Claude solo si el turno está en el alcance de D1, si el orquestador tiene un redactor y si la decisión del router para el turno es `reply_engine == "claude"`. Si no, devuelve la plantilla.
- Con Claude: `protect`, el redactor, `restore`. Cualquier excepción (`WriterUnavailable`, `GuardRejected`, `BudgetExceeded`) devuelve la plantilla.
- Cada turno del alcance deja una fila de auditoría `REPLY_DRAFTED` con `engine` (`claude` o `template`), `fallback_reason`, `model`, `request_id` y `prompt_version`. Nunca guarda el borrador rechazado ni el mensaje crudo.
- Cada llamada que respondió se anota con `LlmBudget.record(provider="anthropic", purpose="reply", ...)` con sus tokens reales.
- `get_orchestrator()` construye el redactor solo si existe `ANTHROPIC_API_KEY`. Sin ella el orquestador no tiene redactor y todo sigue como hoy.

### 3.5 Router

Su decisión no cambia. Solo cambia la docstring, que hoy dice que Claude "does not run here yet".

## 4. Archivos

| Archivo | Cambio |
| --- | --- |
| `src/llm/reply_guard.py` | Nuevo: `protect`, `restore`, `GuardRejected` |
| `src/llm/reply_writer.py` | Nuevo: `ClaudeReplyWriter`, `ReplyDraft`, `WriterUnavailable` |
| `src/llm/prompts/reply_v1.md` | Nuevo: el prompt versionado |
| `src/orchestrator/dispute_orchestrator.py` | La prosa del alcance de D1 pasa por el redactor; auditoría `REPLY_DRAFTED` |
| `src/api/dispute_routes.py` | `get_orchestrator()` conecta el redactor cuando hay key |
| `src/understand/router.py` | Docstring |
| `pyproject.toml`, `uv.lock` | `anthropic` como dependencia de runtime, versión fijada; el lock se regenera en el contenedor dev |
| `tests/test_reply_guard.py`, `tests/test_reply_writer.py`, `tests/test_dispute_orchestrator.py` | Tests de la sección 5 |
| `scripts/llm/check_replies.py` | Nuevo: verificación manual con la key real (sección 5) |
| `CLAUDE.md`, `AGENTS.md` sección 9, `docs/PLAN.md`, `docs/SUPABASE_VERCEL.md` 6.3 | Estado, decisiones del 2 oct (D3 cierra la fila "LangGraph y LangSmith") y bundle medido |

## 5. Pruebas

- **Guarda**, en ES y PT, con borradores maliciosos: una cifra inventada, una ficha faltante, duplicada o desconocida, una URL, un email, un texto vacío o demasiado largo, un borrador que repite instrucciones inyectadas. Y uno bueno que se restaura exacto.
- **Redactor**, con un cliente falso y sin red: arma el pedido con el modelo fijado, el idioma y el mensaje entre etiquetas; un timeout, un error de la API y un `refusal` dan `WriterUnavailable`.
- **Orquestador**, con un redactor falso: una aclaración y un escalamiento usan el borrador cuando la guarda pasa, y el anexo queda idéntico al de la plantilla; las confirmaciones, las abstenciones, la oferta de bloqueo y el explicador nunca llaman al redactor; cada motivo de fallback queda en `REPLY_DRAFTED`; sin key o sin presupuesto, la plantilla.
- **Dependencias:** `tests/test_runtime_dependencies.py` acepta `anthropic` porque pasa a runtime.
- **Evaluación:** el harness sigue en modo solo reglas (sin redactor), así que sus cifras no cambian.
- **Verificación manual** (`scripts/llm/check_replies.py`, con la key real, unas diez frases en ES y PT, costo de centavos): reporta la tasa de borradores que pasan la guarda, la latencia p50 y p95 y el costo. Daniel revisa los textos. El resultado va al reporte con el modelo y la versión del prompt.

## 6. Criterios de aceptación

1. Con key y presupuesto, "hola" y un mensaje ambiguo reciben una aclaración redactada por Claude en ES y en PT, y la lista de movimientos es idéntica a la de la plantilla.
2. Un escalamiento de la política recibe la prosa redactada y la misma referencia de handoff.
3. Las respuestas fuera del alcance de D1 nunca llaman a Claude.
4. Ninguna respuesta lleva una cifra, un id, una URL o un email que el código no haya puesto (tests de la guarda).
5. Cualquier falla de Claude responde la plantilla dentro de unos 10 s (5 s más un reintento) y deja su motivo en la auditoría.
6. Las cifras del harness no cambian; la suite y el CI quedan en verde; el bundle medido sigue bajo 500 MB.
7. La verificación manual queda registrada con la tasa de la guarda, la latencia y el costo.

## 7. Fuera de este lote

El LLM de apoyo para extraer monto, fecha y comercio; Claude como clasificador de intención (brazo de la hipótesis 4); redactar las confirmaciones, las abstenciones o las respuestas del explicador; streaming; memoria de turnos anteriores en el prompt (Claude ve solo el mensaje del turno); la key de Jev (variable de entorno aparte).

## 8. Riesgos

| Riesgo | Mitigación |
| --- | --- |
| Claude borra fichas o agrega cifras | La guarda lo rechaza y responde la plantilla; la verificación manual mide la tasa |
| Claude cambia el sentido o promete algo (un reembolso) | El prompt lo prohíbe y el alcance excluye las confirmaciones; la guarda no ve el sentido, así que Daniel revisa las frases de la verificación manual |
| Latencia: unos 1 a 2 s más por turno del alcance | Timeout de 5 s y un reintento; luego la plantilla |
| Inyección de prompt desde el mensaje del cliente | El mensaje va como dato entre etiquetas; la guarda bloquea cifras, enlaces y emails; el texto no ejecuta nada |
| Anthropic guarda entradas y salidas hasta 30 días | Solo viajan el mensaje enmascarado y la prosa con fichas; va en las limitaciones del reporte (fila "Retención de proveedores externos") |
| Costo | Unos 0,002 USD por respuesta, bajo el tope de 2 USD diarios de `LlmBudget` |
