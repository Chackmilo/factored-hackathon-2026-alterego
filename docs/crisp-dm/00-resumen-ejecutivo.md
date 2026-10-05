# Resumen ejecutivo

AlterEgo es la entrega de Daniel Camilo Pardo y Kmilo Aparicio al Factored AI & Data Hackathon 2026. Recibe disputas de cargos no reconocidos de LATAM Bank, un banco sintético, en español y portugués: encuentra el cargo, aplica una política escrita, abre el caso solo después de releerlo, ofrece bloquear la tarjeta con el sí del cliente y pasa a un humano lo demás. Nunca mueve dinero ([`README.md`](../../README.md)).

En la suite held-out congelada de 250 conversaciones guionizadas, la corrida ciega resolvió sola y bien el 63,6 % (68 de 107) de los casos elegibles, contra 3,7 % (4 de 107) del pipeline inicial. Tras el análisis de errores, la misma suite da 98,1 % (105 de 107). Los resultados inseguros bajaron de 48,8 % (122 de 250) a 15,6 % (39 de 250) en la corrida ciega y a 8,0 % (20 de 250) después. Son resultados offline, no ganancias de producción, y la cifra posterior reutiliza los casos que guiaron los arreglos (`AGENTS.md` sec. 4, regla 11; TQ-033).

## El problema y la pregunta

Las quejas tienen la peor resolución en primer contacto del banco (43,6 %, contra 91,5 % de los contactos transaccionales), y las disputas de cargos ("Cargo no reconocido" 18,3 % y "Cobro indebido" 18,2 %) suman cerca del 36 % de las 67.095 quejas ([`AGENTS.md`](../../AGENTS.md) sec. 6 y 7). La pregunta, textual de [`docs/PLAN.md`](../PLAN.md) sec. 1:

> **¿Puede un sistema de intake de disputas en español y portugués resolver de forma segura y verificada los cargos no reconocidos elegibles de LATAM Bank, logrando más resolución segura automatizada que el baseline actual, sin aumentar los resultados inseguros y con latencia y costo medidos?**

## La solución

El modelo propone y la política determinista decide (`docs/PLAN.md` sec. 2). Cada turno recorre cinco etapas (`src/orchestrator/dispute_orchestrator.py`):

- **Understand:** un extractor ES/PT de palabras clave lee el mensaje enmascarado; no decide.
- **Decide:** la política v2.3 como código evalúa sus cláusulas en orden fijo y cita su id, como `POL-ESC-500`.
- **Act:** abre el caso u ofrece el bloqueo, que se aplica solo tras el sí del cliente.
- **Verify:** relee lo escrito antes de confirmar; si no coincide, pasa a humano.
- **Escalate:** un handoff estructurado llega a la consola HITL.

## Resultados clave

| Sistema y corrida | Resolución segura automatizada (elegibles) | En alcance | Resultados inseguros |
| --- | --- | --- | --- |
| Pipeline inicial | 3,7 % (4 de 107) | 1,7 % (4 de 230) | 48,8 % (122 de 250) |
| Propuesto, corrida ciega (30-sep) | 63,6 % (68 de 107) | 29,6 % (68 de 230) | 15,6 % (39 de 250) |
| Propuesto, tras el análisis (4-oct) | 98,1 % (105 de 107) | 45,7 % (105 de 230) | 8,0 % (20 de 250) |

Fuentes: [`reports/eval_heldout_blind.md`](../../reports/eval_heldout_blind.md) y [`reports/eval_heldout.md`](../../reports/eval_heldout.md). El "propuesto" corre en modo solo reglas. El techo en alcance es 46,5 % (107 de 230). Los 20 inseguros restantes son compras extranjeras de alto riesgo que, sin modelo de riesgo, abren caso donde la etiqueta pide humano ([06-evaluacion.md](06-evaluacion.md)).

## Qué corre en producción y qué no

<https://alterego-silk.vercel.app> corre, desde el 5-oct, el código de `main` en `58ab501`: la política v2.3, el modelo de riesgo (califica los cargos Web y App), Jev detrás del router con tope de 2 USD al día y el extractor como respaldo, el explicador de políticas con BM25 y el login de Supabase. No corren las respuestas de Claude (2 de 7 tareas, sin conectar) ni E5, que no cabe en el bundle. Toda respuesta es una plantilla. Ninguna corrida mide esa combinación junta ([07-despliegue.md](07-despliegue.md)).

## Limitaciones honestas

- La suite dejó de ser ciega tras la primera corrida, y sus etiquetas son de diseño, sin kappa (TQ-018).
- Los datos no traen portugués: todo caso en portugués lo generó el equipo.
- `is_fraud` no tiene señal en el banco (ROC AUC 0,497, [`reports/ml_full/fraud_risk.md`](../../reports/ml_full/fraud_risk.md)); el modelo transferido de IEEE-CIS no está validado en el banco.
- El explicador acierta el 36,7 % (11 de 30) de las acciones en test y cita mal en el 27,3 % (3 de 11) de sus respuestas ([`reports/rag_benchmark.md`](../../reports/rag_benchmark.md)).
- Sin idempotencia, reintentos acotados ni prueba de carga (`README.md`, "Limitations").

## Estado al 4-oct y pendientes

La lista completa de pendientes, con lo que se cerró el 5-oct (modelo reproducible y en git, held-out con el modelo, intervalos, EDA de las features, E5 y Jev medidos, y los dos bugs de conversación arreglados), está en [09-plan-de-pendientes.md](09-plan-de-pendientes.md).

- **Producción** sirve `58ab501` (PR #63) desde el 5-oct. Vercel Hobby bloqueó los merges de #56 a #63, hechos por otra cuenta, porque solo despliega commits atribuidos a la cuenta dueña (estados de despliegue de GitHub).
- **Repo privado** cuyo historial enlaza el PDF del diccionario de datos, con llaves de AWS de solo lectura (`AGENTS.md` regla 10). El PR #49 no reescribió el historial; la auditoría del 4-oct, no comprometida, recomienda publicar `factored-hackathon-2026-alterego` desde una copia sin historial.
- **`cliente-hasta-150`** tiene un caso abierto sobre su cargo (`docs/HANDOFF.md`, A2; la auditoría registra `CASE-ECB3AEEF4C1B`) y no muestra `POL-AUT-150`. Se borra desde el SQL Editor de Supabase ([01-guia-de-uso.md](01-guia-de-uso.md), sección 1.5).
- **Correo de entrega:** dice "52.4%, 123/230" (son 131 de 250) y atribuye 25,0 / 85,1 ms a "native hardware" ([06-evaluacion.md](06-evaluacion.md), sección 3).
- **Claves y pausa:** el repo no registra la rotación de las claves expuestas el 2-oct, y Supabase Free pausa un proyecto inactivo: revisarlo el 8, 12 y 15 de octubre (`docs/HANDOFF.md`, A1 y B3).

## Para saber más

[README.md](README.md) (cómo leer la guía), [01-guia-de-uso.md](01-guia-de-uso.md), [02-entendimiento-del-negocio.md](02-entendimiento-del-negocio.md), [03-entendimiento-de-los-datos.md](03-entendimiento-de-los-datos.md), [04-preparacion-de-los-datos.md](04-preparacion-de-los-datos.md), [05-modelado.md](05-modelado.md), [06-evaluacion.md](06-evaluacion.md), [07-despliegue.md](07-despliegue.md) y [08-iteraciones-y-decisiones.md](08-iteraciones-y-decisiones.md).
