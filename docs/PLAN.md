# Plan del equipo: intake de disputas

Actualizado: 2026-09-26. Este archivo es la fuente canónica de la pregunta problema, la planeación y la hoja de ruta. Hay dos copias para compartir: el [Claude Doc](https://claude.ai/code/artifact/d6c4ec29-af5e-4435-88d8-bd05f4f9d603) y la [página de Notion](https://app.notion.com/p/3e77b60f246881bd8b16c760101f058d). Si una copia difiere de este archivo, gana este archivo.

Construimos un sistema de intake de disputas en español y portugués que resuelve, protege o escala cada cargo no reconocido con acciones verificadas. Entregamos el 5 de octubre de 2026; hoy cerramos el día 2 de 10.

## 1. Pregunta problema

**¿Puede un sistema de intake de disputas en español y portugués resolver de forma segura y verificada los cargos no reconocidos elegibles de LATAM Bank, logrando más resolución segura automatizada que el baseline actual, sin aumentar los resultados inseguros y con latencia y costo medidos?**

Las quejas son el contacto más costoso del banco. Datos sintéticos del organizador: 686.296 interacciones y 67.095 quejas (`AGENTS.md` sección 7).

| Motivo de contacto | Volumen | Resolución en primer contacto | Requiere seguimiento | Minutos promedio |
| --- | --- | --- | --- | --- |
| Queja | 17,1% | 43,6% | 63% | 7,2 |
| Transaccional | 35,0% | 91,5% | 22% | 3,7 |

"Cargo no reconocido" (18,3%) y "Cobro indebido" (18,2%) suman el 36% de las quejas. Además, `transactions.is_fraud` da una etiqueta real para entrenar un modelo.

**Hipótesis**, todas sobre la misma suite held-out de 250 casos:

1. El sistema propuesto supera al baseline en resolución segura automatizada.
2. Los resultados inseguros no aumentan; se reportan como conteos con denominador.
3. El modelo de riesgo sin `fraud_score` supera a la línea base de reglas en la ventana temporal held-out.

**Cómo se mide:** las métricas oficiales, definidas en `docs/TEAM_BRIEF_COMPLEMENTED.md` sección 5. Resolución segura automatizada con el porcentaje de casos intentados, contención, calidad de escalamiento (transferencias omitidas e innecesarias), resultados inseguros, latencia p50 y p95, y costo por caso intentado y por resolución exitosa. Todo se corta por idioma, segmento y país.

**Límites conocidos:** el dataset no tiene portugués ni Brasil, así que los casos en portugués son generados por el equipo. El techo de $500 limita la contención a cerca del 53% de los cargos. La trampa de duplicados sigue sin resolver.

## 2. Planeación

**Alcance.** Un solo workflow: intake de disputas de transacciones. Dos acciones reales: abrir el caso y el bloqueo preventivo de tarjeta. Tres tipos de caso: normal, ambiguo o no soportado, y los que requieren humano. Español y portugués. Queda fuera mover dinero, aprobar créditos y cualquier otro workflow.

**Principio.** El modelo propone y la política determinista decide. El `customer_id` sale siempre del token de sesión, nunca del modelo ni del cuerpo de la petición.

**Supuestos.** "Hoy" es 2026-06-17, la fecha final del dataset. Todo el dataset es sintético. Los casos en portugués se etiquetan como generados por el equipo.

### Registro de decisiones

Se consulta al equipo antes de actuar sobre una fila Propuesta o Abierta. Al cerrar una, se cambia su estado aquí con la fecha.

| Decisión | Estado | Resolución o propuesta |
| --- | --- | --- |
| Equipo | Decidida (26 sep) | 2 personas: Frente A (datos, ML y evaluación) y Frente B (agente, backend y UI); falta nombrar quién toma cada uno |
| Nombre del equipo y repo | Decidida (26 sep) | AlterEgo; repo público `factored-hackathon-2026-alterego` |
| Idioma | Decidida (26 sep) | Inglés para los entregables (README, reporte, slides, video); el plan interno sigue en español |
| Fuente canónica del plan | Decidida (26 sep) | Este archivo; Notion es la copia con la que el equipo se sincroniza |
| Base de operación | Decidida (26 sep) | SQLite `data/ops.sqlite` para casos, bloqueos, sesiones y auditoría; DuckDB solo lectura para la app |
| Understand y conversación | Decidida (26 sep) | Capa inicial "Jev" (por aclarar qué es), luego un LLM que gestiona la conversación con el cliente; toda decisión y acción determinista queda en código. El extractor ES/PT por palabras clave queda como respaldo y como línea base |
| Datos que ve el LLM | Propuesta | Solo el mensaje enmascarado. El LLM redacta con marcadores (`{monto}`, `{caso}`) y el código los rellena con datos verificados: no ve registros ni puede inventar hechos |
| Uso de datos en el despliegue y en el LLM | Abierta | Pregunta enviada a mentores en `#technical-help` |
| Flujo de git | Decidida (26 sep) | Ramas y un commit por fase con la suite en verde |
| `fraud_score` | Decidida (26 sep, por los datos) | Filtra la etiqueta: fuera del modelo y del baseline |
| Workflow | Propuesta | Intake de disputas; alternativa: elegibilidad de crédito |
| Crédito provisional | Propuesta | Solo marca de candidato para revisión humana (regla 8); el código aún lo trata como acción autónoma |
| Política de disputas | Propuesta | Cláusulas y orden del brief v2.1 |
| Techo de escalamiento de $500 | Propuesta | Mantenerlo y reportar el techo de contención de ~53% |
| Baseline | Propuesta | El pipeline inicial del repo, medido en la misma suite |
| Reconstruir o evolucionar | Propuesta | Evolucionar: conservar la estructura y construir el stack de disputas al lado |
| Explicaciones de política | Propuesta | Política como código con ids de cláusula; RAG solo si sobra tiempo |
| Componentes aprendidos | Propuesta | Modelo de fraude obligatorio; el clasificador de intención queda fuera (somos 2) |
| Tamaño de la suite held-out | Propuesta | 150 casos con las mismas categorías y proporciones (somos 2); el brief dice 250 |
| Profundidad en portugués | Propuesta | Solo mensajes y respuestas en PT, generados por el equipo |
| UI y despliegue | Propuesta | Streamlit; Docker en Render o Fly.io con URL pública; qué datos lleva depende de la respuesta de mentores |
| Confirmación del bloqueo preventivo | Abierta | ¿El cliente confirma antes del bloqueo? |
| Cargo disputable y palabras de angustia | Abierta | Cláusulas `POL-DISP-TYPE` y `POL-ESC-DISTRESS` del brief |

### Frentes de trabajo

Somos 2: un frente por persona, y los días 9 y 10 se trabajan juntos.

| Frente | Entregables clave |
| --- | --- |
| A: datos, ML y evaluación | Contratos, hora local, tipo de cambio por fecha, muestra abril-junio, carga completa para ML, LightGBM sin `fraud_score`, MLflow, harness, suite y reporte de métricas |
| B: agente, backend y UI | SQLite de operación, gateway con verificación, política v2.1, orquestador de cinco etapas, capa inicial y LLM de conversación, sesión JWT, guardas de entrada, Streamlit, despliegue |
| Ambos (días 9 y 10) | README, reporte y slides en inglés, video, entrega |

## 3. Hoja de ruta

Cinco fases hasta el 5 de octubre; cada una cierra con un gate verificable. Primero se construye un flujo mínimo de punta a punta y después se amplía. G1 es el gate crítico: sin una conversación completa y verificada, el modelo y la UI no suman.

```mermaid
gantt
    title Hoja de ruta hasta el 5 de octubre de 2026
    dateFormat YYYY-MM-DD
    axisFormat %d %b
    section Base y plan
    Auditoría, brief v2.1 y plan :active, f0, 2026-09-25, 2d
    G0 Decisiones confirmadas :milestone, g0, 2026-09-26, 0d
    section Flujo mínimo
    Datos correctos, orquestador y API :f1, 2026-09-27, 2d
    G1 Conversación ES de punta a punta :crit, milestone, g1, 2026-09-28, 0d
    section Modelo y UI
    LightGBM, capa LLM y Streamlit ES/PT :f2, 2026-09-29, 2d
    G2 Modelo supera al baseline :milestone, g2, 2026-09-30, 0d
    section Evaluación
    Suite de 250 casos, métricas y deploy :f3, 2026-10-01, 2d
    G3 Métricas y URL pública :milestone, g3, 2026-10-02, 0d
    section Entrega
    Docs, slides, video y envío :f4, 2026-10-03, 3d
    G4 Enviado :milestone, g4, 2026-10-05, 0d
```

| Día | Fecha | Frente A: datos, ML y evaluación | Frente B: agente, backend y UI | Listo cuando |
| --- | --- | --- | --- | --- |
| 2 | 26 sep | Confirmar el desfase horario en un CSV crudo; commitear el código sin trackear | Cerrar decisiones; enviar la pregunta a mentores | G0: cada decisión Propuesta confirmada o cambiada |
| 3 | 27 sep | Contratos, hora local, tipo de cambio por fecha, muestra abril-junio, sondeo de duplicados y del prefijo de respaldo (máximo 2 h) | SQLite de operación con auditoría; guardas y valores del diccionario en el gateway; cláusulas v2.1 | Cada arreglo tiene un test que falló primero; la ingesta corre con los contratos en verde |
| 4 | 28 sep | Carga de transacciones 2023-2026 y features; baseline de reglas sin `fraud_score` | Orquestador de cinco etapas y varios turnos detrás de FastAPI y la sesión JWT; capa inicial y extractor; búsqueda del cargo y aclaración; handoff | G1: una conversación en español recorre la API y termina en un caso verificado |
| 5 | 29 sep | LightGBM contra baseline, split temporal, umbral por costo, MLflow; conectar el riesgo a la política | LLM de conversación ES/PT con marcadores; guardas de PII LATAM y etiquetas escapadas | El modelo supera al baseline en la ventana held-out; conversaciones ES y PT pasan por el LLM |
| 6 | 30 sep | Harness de evaluación y los primeros 60 casos | Streamlit: chat ES/PT y consola HITL | G2: los tres tipos de caso corren en la UI en ambos idiomas |
| 7 | 1 oct | Suite completa con procedencia; baseline contra propuesto, 3 repeticiones, cortes por idioma, segmento y país | Reintentos acotados, fallback seguro, simulación de fallas de herramientas, trazas | El reporte cubre cada métrica oficial con denominadores |
| 8 | 2 oct | Arreglar lo que falle y análisis de errores | Despliegue con los datos que aprueben los mentores | G3: una URL pública sirve la demo |
| 9 | 3 oct | README, arquitectura y reporte en inglés; volver a correr el notebook | Limitaciones y ruta a producción en inglés | Cada afirmación de los docs coincide con el código y los datos |
| 10 | 4-5 oct | Slides en inglés; video de 3 minutos | Repo público `factored-hackathon-2026-alterego`; correo de entrega | G4: entrega enviada a `hackathon.admin@factored.ai` |

Recortes ya aplicados por ser 2: el clasificador de intención y el texto de política en portugués; la suite baja a 150 casos si el equipo lo confirma. Si hay atraso, siguen: trazas con OpenTelemetry (queda el log de auditoría) y una consola HITL mínima. Nunca se recorta el flujo de punta a punta, la verificación de acciones, el handoff, la comparación con el baseline, el tracking del modelo, el despliegue ni el video.

## Fuentes

- [Problem Statement oficial (Google Doc)](https://docs.google.com/document/d/18AwONT8hQupRcfNPLFrPo6fHOJ_OUn1nBf-3jMnla2c/edit)
- [LATAM Bank Dataset Summary (PDF)](https://drive.google.com/file/d/1V7n9v0zuv9SYzpW2AzPnssgAp5X_buXc/view)
- [LATAM Bank Complete Data Dictionary (PDF)]([link to the organizer's data dictionary removed])
- Slides del kickoff: `docs/Datathon_2026_Kickoff.pdf` (copia local, fuera de git)
- `AGENTS.md`: reglas, hallazgos de datos verificados (sección 7) y brechas del código (sección 9)
- `docs/TEAM_BRIEF_COMPLEMENTED.md` v2.1: especificación de la política, del handoff y de la evaluación
