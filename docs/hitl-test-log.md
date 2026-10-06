# Registro de pruebas HITL (manuales)

Bitácora de lo que encontramos probando el chat a mano, con los casos de evaluación candidatos que salen de cada hallazgo y las cosas por hacer. Los casos viven en `data/eval/candidates/hitl_candidates.jsonl`, fuera de las suites.

## Reglas

1. **Nada entra a una suite sin aprobación de Daniel y de Kmilo.** Cada caso candidato queda en `pendiente` hasta que los dos lo aprueben en la tabla de abajo.
2. **El held-out está congelado** (CLAUDE.md, "The held-out suite is frozen"). No se editan sus casos ni se le agregan filas: una ampliación es una versión nueva con SHA-256 nuevo y una nota en el decision log de `docs/PLAN.md`.
3. **Un caso que usamos para construir el arreglo no es held-out.** Los casos de este registro salen de mirar una falla y van a guiar el arreglo, así que su lugar es el split de desarrollo (`data/eval/dev_cases.jsonl`). Para el held-out se generan variantes nuevas (otros comercios, otro idioma, otra redacción) que nadie mire mientras arregla, y entran como held-out v2.
4. Los casos llevan `label_source: "design"` hasta que la etiqueta adjudicada los reemplace, como el resto de la suite.

Correr los candidatos: `uv run python -m src.eval.run data/eval/candidates/hitl_candidates.jsonl --out /tmp/hitl_eval --systems proposed`.

## Aprobación de casos

| Caso | Hallazgo | Destino propuesto | Daniel | Kmilo |
| --- | --- | --- | --- | --- |
| HITL-001 | H1 | dev | pendiente | pendiente |
| HITL-002 | H1 | dev | pendiente | pendiente |
| HITL-003 | H1 | dev | pendiente | pendiente |
| HITL-004 | H1, H2 | dev | pendiente | pendiente |
| HITL-005 | H1 (control) | dev | pendiente | pendiente |
| HITL-006 | H2, H3 | dev (cuando el juez lea `forbidden_options`, TODO-H3) | pendiente | pendiente |
| HITL-007 | H5 (guarda de TODO-H1, pasa hoy) | dev | pendiente | pendiente |
| Variantes held-out v2 de H1 y H2 | H1, H2 | held-out v2 | pendiente | pendiente |

## Sesión 2026-10-03, persona CLI-0071N01JUU4Z

Conversación observada (un solo cargo en la cuenta: 2026-06-12, 219.38 USD, Ferretería):

1. Cliente: "no reconozco el cargo de ointerest en mi cuenta". Bot: abre CASE-D165D8015DA9 sobre el cargo de Ferretería.
2. Cliente: "tengo una transaccion de pinterest?". Bot: "No encontramos un cargo que coincida..." y lista como opción 1 el mismo cargo de Ferretería, que ya tiene caso.
3. Cliente: "1". Bot: "Ese cargo ya tiene un caso de disputa abierto". La consola muestra `AUTONOMOUS_RESOLUTION` con las cláusulas `POL-DISP-TYPE, POL-WIN-60, POL-AUT-INTAKE`.

Resultado de los candidatos en `main` (9efb497), sistema propuesto en modo solo reglas: 4 de 7 inseguros (HITL-001 a 004, `unauthorized_action:case_opened`). HITL-005 y HITL-007 pasan, y HITL-006 pasa aunque reproduce H2, porque el juez no lo ve (H4).

### H1. El comercio que nombra el cliente se ignora y se abre caso sobre el único cargo

- **Qué pasa:** el cliente nombra un comercio (Pinterest) que no coincide con ninguno de sus cargos, y el bot abre un caso sobre el único cargo que tiene (Ferretería). Es una acción no autorizada: un caso abierto sobre un cargo que el cliente no disputó.
- **Causa:** `src/orchestrator/dispute_orchestrator.py`, `_identify_charge` (líneas 404 a 414). El comercio solo cuenta cuando coincide con un cargo (`_merchant_in_message`); cuando no coincide con ninguno, el mensaje queda "sin pista", y con intención de disputa y un único cargo ese cargo es el match. La protección de S3 solo cubre las intenciones `consulta_general` y `tarjeta_robada`. El extractor no tiene un campo de comercio: no sabe que "Pinterest" es un comercio.
- **Casos:** HITL-001 (texto literal con el error de tipeo), HITL-002 (bien escrito), HITL-003 (PT), HITL-004 (la conversación de dos turnos), HITL-005 (control: con dos cargos del mismo monto, el que nombra al comercio se abre sin preguntar, para no sobrecorregir).

### H2. La lista de movimientos ofrece cargos que ya tienen caso abierto

- **Qué pasa:** al pedir aclaración el bot lista los movimientos recientes, incluidos los que ya tienen un caso abierto. El cliente elige uno y recibe "ese cargo ya tiene un caso": un turno perdido, y en una cuenta con un solo cargo la lista no ofrece nada útil.
- **Causa:** la lista sale de los cargos del cliente sin cruzarlos con los casos del ops store. `_open_case_for` existe, pero solo se consulta después de elegir.
- **Casos:** HITL-004 (turno 2), HITL-006 (dos cargos: tras abrir caso sobre Ferretería, la lista del turno 2 debe traer solo Tienda Sur).

### H3. Un turno que solo encuentra un caso duplicado se reporta como resolución autónoma

- **Qué pasa:** el turno 3 no hace nada (el caso ya existía), pero el resultado es `AUTONOMOUS_RESOLUTION` con las cláusulas de intake. En las métricas cuenta como resolución automática segura: HITL-006 sale como 2/2 en "safe automated resolution".
- **Causa:** la rama `DUPLICATE_CASE_PREVENTED` cierra la conversación con el resultado de la política tal como venía.

### H4. El juez del harness no ve H2 ni H3

- `case_opened` mira la conversación entera, así que no distingue en qué turno ni sobre qué cargo se abrió el caso.
- No registra las opciones listadas en cada turno, así que no puede verificar que una opción no se ofrezca.

### H5. Comercio nombrado con cargos sin comercio conocido: correcto según la spec (guarda)

Persona CLI-0085D5JD85CX, dos cargos con comercio `Unknown Merchant` (2026-06-12, 4,259.97 USD y 2026-06-05, 261.69 USD).

1. Cliente: "quiero rechazar una compra de unos calzones en caricias intimas?". Bot: lista los dos cargos.
2. Cliente: "1". Bot: escala por `POL-ESC-500` (4,259.97 USD supera 500 USD), handoff HO-9A5D2938308B, sin oferta de bloqueo.

- **Veredicto:** cumple la spec v2.3. El comercio nombrado no se puede comparar con un cargo `Unknown Merchant`, así que listar es lo correcto; la escalación por monto es la cláusula que decide; y `POL-AUT-LOCK` solo ofrece bloqueo con reclamo de robo o fraude de varios cargos, no por monto alto (el resumen del brief dice que en el caso "requiere humano" se bloquea, pero la spec v2.3 lo acotó).
- **Por qué importa:** TODO-H1 no debe romperlo. Un `merchant_hint` sin coincidencia solo descarta cargos cuyo comercio se conoce; un `Unknown Merchant` sigue siendo candidato.
- **Caso:** HITL-007.
- **Detalle menor:** el texto de `POL-ESC-500` repite el monto cuando la moneda ya es USD ("4,259.97 USD, $4,259.97 USD equiv."), en `src/rules/dispute_policy.py` líneas 200 y 201. Ver TODO-H6.

## Sesión 2026-10-05, persona CLI-0085D5JD85CX, producción factored-alterego

Prueba en https://factored-alterego.vercel.app, el proyecto de Kmilo (misma base de Supabase que el de Daniel). Horas en Bogotá (UTC-5). Conversación CONV-32CB652D63F7, leída de `ops.messages`, `ops.handoffs` y `ops.audit_log`:

1. 9:11 pm. Cliente: "me acaban de atracar en el transmi y me llegaron mensajes con transacciones realizadas". Bot: "Encontramos varios cargos que podrían coincidir" y lista 1) 2026-06-12, 4,259.97 USD, Unknown Merchant y 2) 2026-06-05, 261.69 USD, Unknown Merchant.
2. Cliente: "1". Bot: escala por `POL-ESC-500`, handoff HO-F3730F255891, sin oferta de bloqueo. El riesgo del modelo es 0.01 (umbral 0.06) y el cargo es de Puebla, la ciudad del cliente.
3. 9:28 pm. Un agente (id de Supabase `6fb83aff-784e-42e8-9325-dfc59c10c1af`) marca el handoff como resuelto en la consola.
4. 9:30 pm. Cliente: "sabes si ya hay una respuesta de mi caso?". Bot: repite la misma lista de dos cargos.

En este despliegue Jev no corrió (`routing_reason: "jev unavailable: no key or SDK"`): las señales salen solo del extractor de palabras clave.

### H7. "Me acaban de atracar" no se lee como robo

- **Qué pasa:** el cliente cuenta un robo y el bot no lo reconoce. Las señales guardadas dicen `intent: consulta_general`, `stolen_card_claimed: false` y `topics: []`, así que no hay oferta de bloqueo (`POL-AUT-LOCK`) y la escalación sale solo por monto.
- **Causa:** el vocabulario de pérdida y robo del extractor (`src/understand/keyword_extractor.py`, palabras de la política S8) no incluye "atracar" ni "atraco", que son de uso común en Colombia. Jev podría leerlo, pero no tenía clave en este despliegue.
- **Pendiente:** decidir si el vocabulario crece con regionalismos (atracar, atraco, asaltar, cosquilleo, raponear) o si el robo se deja a Jev. Revisar también que `TYPESAFE_API_KEY` esté en el proyecto factored-alterego.

### H8. El paquete guarda "1" como solicitud del cliente

- **Qué pasa:** el campo `customer_request` del handoff dice "1", la respuesta de opción, no el relato del robo. El agente que abre el handoff no ve lo que el cliente contó.
- **Causa:** `src/orchestrator/dispute_orchestrator.py`, `_create_handoff` (línea 761 en `main` 7fdaa6d), arma el paquete con `customer_request=masked`, el texto enmascarado del turno que escala. Cuando ese turno es una respuesta de opción, se pierde el mensaje que inició la disputa.

### H9. El `handoff_id` queda vacío dentro del paquete

- **Qué pasa:** la fila de `ops.handoffs` tiene id (HO-F3730F255891), pero el paquete guardado trae `"handoff_id": ""`.
- **Causa:** el mismo `_create_handoff` (línea 760) construye el paquete con `handoff_id=""` antes de `insert_handoff`, que es quien genera el id, y no lo vuelve a escribir.

### H10. "Resolver" en la consola no registra qué se decidió

- **Qué pasa:** el botón solo cambia el estado a `resolved`, guarda quién y cuándo, y escribe `HANDOFF_RESOLVED` en el audit log (`src/api/dispute_routes.py`, `console_resolve_handoff`). No abre caso, no le avisa al cliente, no deja nota ni resultado, y la conversación sigue en `escalated`. Para el sistema, la decisión del agente no existe.
- **Pendiente:** es una decisión de producto, así que va como pregunta del equipo (siguiente TQ libre) antes de tocar código.

### H11. Preguntar por el estado del caso después de escalar vuelve a listar cargos

- **Qué pasa:** con la conversación en `escalated`, "sabes si ya hay una respuesta de mi caso?" recibe la misma lista de cargos, como si fuera una disputa nueva. Si el cliente responde "1" otra vez, el turno puede volver a escalar el mismo cargo.
- **Causa probable, sin verificar en código:** el turno siguiente a una escalación pasa otra vez por el flujo de disputa, y el extractor no reconoce una pregunta por el estado del caso.

### Otros

- El texto de `POL-ESC-500` vuelve a repetir el monto ("4,259.97 USD, $4,259.97 USD equiv."): ya está en TODO-H6.
- Fuera del chat: después de la 1:06 UTC del 6-Oct (la última fila borrada es de esa hora) alguien con acceso de administrador borró filas de `ops` (12 conversaciones, 3 casos, 1 bloqueo, 1 handoff, 50 mensajes, según `pg_stat_user_tables`). El rol de la API (`app_gateway`) no tiene DELETE, y el audit log, que no admite borrados, todavía nombra esos casos y ese bloqueo. Por eso la consola mostraba "No cases". No se sabe quién fue.

Casos candidatos de esta sesión: todavía no se escribieron en `hitl_candidates.jsonl` ni se reprodujeron con `src.eval.run`.

## Cosas por hacer (TODO HITL)

Ninguna se implementa hasta que Daniel y Kmilo aprueben los casos que las miden.

- [ ] **TODO-H1. Comercio nombrado sin coincidencia pide aclaración.** Ideas:
  - El extractor ES/PT saca un `merchant_hint` de frases como "cargo de X", "compra en X", "cobro de X", "cobrança da X", "compra na X", descartando las palabras de su propio vocabulario (cuenta, tarjeta, ayer, dólares...). Jev puede llenar el mismo campo (el `transaction_ref` del esquema), pero la regla no depende de Jev.
  - Comparación tolerante a errores de tipeo contra `merchant_name` (por ejemplo `difflib.SequenceMatcher` con un umbral, o distancia de edición de 2 o menos), para que "ointerest" encuentre "Pinterest" cuando exista.
  - Regla en `_identify_charge`: si hay `merchant_hint` y ningún cargo de comercio conocido coincide, se descartan los de comercio conocido; los `Unknown Merchant` siguen como candidatos (H5, HITL-007). Si no queda ninguno, no hay candidatos, y `POL-CLARIFY` pregunta con `NO_CANDIDATE_CHARGE`. Más general: el atajo del único cargo exige una pista que coincida, no basta con que ninguna contradiga.
  - La respuesta no repite el nombre que escribió el cliente (texto no confiable); dice que no encontró un cargo con ese comercio y pide fecha o monto.
- [ ] **TODO-H2. La lista no ofrece cargos con caso abierto.** Ideas:
  - Un método del ops store que devuelva los `transaction_id` con caso `Open` o `In Progress` del cliente en una sola consulta, y filtrarlos antes de armar la lista (y antes de guardar `candidate_ids`, para que el número que elige el cliente siga apuntando al cargo correcto).
  - Si el filtro deja la lista vacía, decir en una línea que sus cargos recientes ya tienen caso (con los números de caso) y pedir fecha, monto o comercio, sin lista.
  - Cuando el cliente nombra explícitamente un cargo ya disputado (por monto o comercio), se mantiene la respuesta actual "ya tiene un caso": esa respuesta sí le ahorra tiempo.
- [ ] **TODO-H3. El juez lee las opciones listadas.** El runner guarda los `transaction_id` listados en cada turno, y el juez falla el caso cuando aparece uno de `expected.forbidden_options` (HITL-006 ya trae el campo). Además, comparar el cargo del caso abierto con `target_transaction_id`, que atrapa H1 aunque el resultado coincida.
- [ ] **TODO-H4. Resultado propio para el caso duplicado.** El turno que solo encuentra un caso existente no debería contar como `AUTONOMOUS_RESOLUTION` ni mostrar cláusulas de intake. Es una decisión de métrica: proponerla como pregunta del equipo (siguiente TQ libre) antes de tocar código.
- [ ] **TODO-H5. Variantes para held-out v2.** Cuando H1 y H2 estén aprobados: generar con `src/eval/heldout.py` (semilla nueva) variantes que nadie mire durante el arreglo: comercio inexistente en ES y PT, con y sin error de tipeo, con uno y con varios cargos, y listas donde parte de los cargos ya tiene caso. Entran como held-out v2 con SHA-256 nuevo y nota en el decision log.
- [ ] **TODO-H6. Texto de `POL-ESC-500` sin monto repetido.** Cuando `transaction_currency` es USD, mostrar el monto una vez; el equivalente en USD solo para otras monedas. Cambio de plantilla con su prueba en `tests/test_dispute_policy.py`.
- [ ] **TODO-H7. Robo contado con regionalismos.** Agregar "atracar", "atraco" y similares al vocabulario de robo, con pruebas en ES y PT y un caso de control que no sea robo. Antes, decidir con el equipo si la lista crece o si esto queda en manos de Jev.
- [ ] **TODO-H8. La solicitud del cliente en el paquete.** Usar el mensaje que abrió la disputa (o los mensajes del cliente desde ese punto), no solo el turno que escala.
- [ ] **TODO-H9. `handoff_id` dentro del paquete.** Escribir el id en el paquete después de `insert_handoff`, o generarlo antes de construirlo.
- [ ] **TODO-H10. Resultado al resolver un handoff.** Proponer como TQ que "Resolver" pida un resultado (caso abierto, rechazado, cliente contactado) y una nota que quede en el audit log.
- [ ] **TODO-H11. Pregunta por el estado después de escalar.** En `escalated`, una pregunta por el caso responde con la referencia del handoff y su estado, y no vuelve a listar cargos.
