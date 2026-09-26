# Jev (TypeSafe AI): Modelo de Sistema 1 para Decisiones Tipadas en Software

Documento de referencia tecnica y diseno de integracion para el equipo del **Factored AI & Data Hackathon 2026**.

Actualizado: 2026-09-26, con la documentacion oficial de TypeSafe (docs.typesafe.ai) y el ejemplo de LangChain y TypeSafe publicado el 25 de septiembre (fuentes en la seccion 6). Lo marcado "(propuesta)" depende de filas en estado Propuesta de `docs/PLAN.md` y no cambia el brief v2.3 hasta que el equipo las apruebe.

---

## 1. Que es Jev y por que es Relevante

**Jev** (desarrollado por TypeSafe AI, fundada por Diogo Almeida, ex-investigador de OpenAI) inaugura la categoria de **System One Models (Modelos de Sistema 1)**:

* **Inspirado en Daniel Kahneman (Thinking, Fast and Slow)**: Los LLMs tradicionales corresponden al Sistema 2 (razonamiento deliberado, lento y generador de texto token por token). Jev implementa el Sistema 1: **decisiones rapidas, intuitivas y estructuradas**.
* **Un "if statement" probabilistico para codigo**: Jev no genera cadenas de texto libre, no chatea, no programa ni redacta respuestas. Su unica funcion es evaluar un estado (*state*) y responder preguntas cerradas con salidas fuertemente tipadas y calibradas.
* **Garantia de Type-Safety a nivel de formato (Cero errores de esquema)**: El espacio de salida esta prefijado por esquema. Es matematicamente imposible que retorne una clave inexistente o un JSON roto. *(Nota: esto garantiza integridad de formato, no infalibilidad semantica; el modelo aun puede clasificar erróneamente una clase y debe evaluarse)*.
* **Muestreador en Paralelo (Parallel Sampler)**: Evalua todas las variables en un unico pase de inferencia a nivel de hardware, sin decodificacion autorregresiva.
* **Latencia y Costo**: Respuestas oficiales entre **70 ms y 500 ms** (segun TypeSafe AI). Costo de entrada de $0.042 por millon de tokens ($42 por mil millones) y **tokens de salida 100% gratuitos**.
* **Algoritmo RLCD (Reinforcement Learning for Calibrated Decisions)**: A diferencia de RLHF (que induce sobreconfianza para complacer al humano), RLCD premia la calibracion empirica: si reporta 90% de probabilidad, la tasa real esperada se aproxima a ese 90%. Debe medirse empiricamente en nuestro conjunto de evaluacion en Espanol y Portugues.
* **Idioma (doc oficial, `models.md`)**: "English is the primary training language and where accuracy is currently best." Los demas idiomas funcionan pero estan menos optimizados, y la doc pide probarlos a fondo. ES y PT son exactamente ese caso: la ventaja de Jev sobre el extractor por palabras clave no esta garantizada y se mide por idioma.
* **Limites (doc oficial)**: ventana de 64k tokens (32k para el estado mas la pregunta mas larga), 250.000 tokens por segundo y 1.200 peticiones por minuto. Solo texto.
* **Medicion externa (LangChain, 25 sep 2026)**: 0.34 s por pagina con `jev-1.13.0` frente a 3.80 s de Claude Sonnet 5, sobre 6 paginas en ingles, con el mismo grafo y la misma politica. Los motores coincidieron en 4 o 5 de las 6 paginas. Es material del vendor y de su partner, con un n muy chico: sirve como hipotesis, no como evidencia de nuestro reporte.

---

## 2. Primitivas del SDK y su Rol en el Flujo

En Jev, el **estado (`state`) contiene los hechos observados** (el mensaje enmascarado del cliente) y las **preguntas (`questions`) contienen la interpretacion requerida**.

```python
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score
```

Las tres preguntas de las secciones A, B y C viajan en una sola llamada (un pase de inferencia). Forma de la llamada segun la doc oficial del SDK; la app es async, asi que se usa `AsyncTypeSafeClient`:

```python
client = AsyncTypeSafeClient()  # lee TYPESAFE_API_KEY
response = await client.system_one(
    state={"message": masked_message},
    questions={
        "intent": intent_question,
        "stolen_card": stolen_card_question,
        "distress": distress_question,
    },
)
response.choices["intent"].choice          # opcion con mayor probabilidad
response.choices["intent"].probabilities   # distribucion completa
response.nouls["stolen_card"].noul         # probabilidad de "si", 0 a 1
response.scores["distress"].score          # valor esperado, ver seccion D
response.model, response.request_id        # van al log de auditoria
```

El modelo se elige con el campo `model` de la peticion (`POST /v1/systemone`). El nombre exacto del argumento en `typesafe-sdk==0.7.1` esta por verificar.

### A. `Choice`: Clasificacion de Intencion (Triaje de Entrada)
Distribuye la probabilidad entre un conjunto cerrado de opciones nombradas (hasta 255 opciones). Retorna la opcion ganadora, el indice de confianza y la distribucion probabilistica.

```python
intent_question = Choice(
    instructions="Clasifica la intencion principal del mensaje del cliente bancario.",
    criteria={
        "cargo_no_reconocido": "El cliente afirma no reconocer una transaccion o compra en su cuenta.",
        "cobro_indebido": "El cliente reconoce el comercio pero impugna cobro duplicado o monto erroneo.",
        "tarjeta_robada": "El cliente reporta perdida fisica, hurto de plastico o fraude masivo.",
        "consulta_general": "Pregunta general sobre saldo, extracto o movimientos.",
        "fuera_de_alcance": "Solicitud de creditos, prestamos u operaciones fuera del alcance de disputas."
    }
)
```

### B. `Noul`: Deteccion Booleana Calibrada (Senales de Seguridad y Ambiguedad)
Responde con una probabilidad continua entre `0.0` y `1.0`:
* `noul >= 0.80`: Señal contundente positiva.
* `noul <= 0.20`: Señal contundente negativa.
* `0.40 <= noul <= 0.60`: **Zona de incertidumbre o ambiguedad**, senal para solicitar aclaracion (`POL-CLARIFY`).

```python
stolen_card_question = Noul(
    instructions="El cliente afirma haber perdido el plastico o sufrido robo fisico de la tarjeta?",
    criteria={
        "true": "El plastico fue extraviado, clonado con perdida fisica o robado.",
        "false": "El cliente conserva su tarjeta fisica y solo impugna un cargo remoto o no reconocido."
    }
)
```

`criteria` de `Noul` es un `NoulCriteria`, que en el SDK es un `TypedDict` con claves `true` y `false`, asi que el dict de arriba es valido.

### C. `Score`: Escala Ordenada de Angustia / Severidad
Ubica el caso en una escala ordinal de 0 a 3 para capturar el nivel de angustia del cliente y cerrar la decision de palabras de angustia para el escalamiento.

```python
distress_question = Score(
    instructions="Evalua el nivel de angustia o vulnerabilidad manifestado por el cliente.",
    criteria=[
        "0: Tono neutral, consulta habitual sin urgencia.",
        "1: Preocupacion moderada por la transaccion.",
        "2: Fuerte alteracion, afectacion de subsistencia o saldo esencial.",
        "3: Situacion de crisis extrema o fraude masivo en curso."
    ]
)
```

### D. Como leer las salidas

Salen de la doc oficial (`responses.md`) y de lo que el ejemplo de LangChain tuvo que corregir en su primera corrida real. Cada punto cambia un umbral de la seccion 3.

1. **`Score.score` es un valor esperado, no un nivel.** La doc lo define como "the probability-weighted average of the rubric levels. May fall between integer levels". Un caso claramente de nivel 2 puede salir 1.8. Nunca se compara con un entero exacto: se leen bandas. En el ejemplo de LangChain, la condicion `score == 0` casi nunca se cumplio, y la primera version entrego paginas no relevantes como si lo fueran, sin ningun error visible.
2. **`confidence` mide concentracion de la distribucion, no acierto.** En un `Score`, un caso que queda entre dos niveles da confianza baja aunque la direccion sea clara. En el ejemplo, filtrar con `confidence < 0.8` mando 5 de 6 paginas a revision humana. Regla: una banda decisiva se acepta tal cual; la confianza solo filtra la banda del medio.
3. **En `Choice`, decide la masa de probabilidad del camino, no la opcion ganadora (propuesta).** `cargo_no_reconocido`, `cobro_indebido` y `tarjeta_robada` llevan todas a la ruta de disputa. Primero se decide con la suma de sus probabilidades (disputa, consulta o fuera de alcance). Despues se elige la subcategoria del caso, que es la unica que puede requerir una pregunta propia. Asi, un reparto 50/50 entre dos tipos de disputa no dispara una aclaracion sobre si hay disputa.
4. **Los umbrales no se trasladan entre motores.** La confianza la define cada proveedor: en el ejemplo, cambiar solo la formula de confianza del adaptador del LLM movio el acuerdo entre motores de 4/6 a 5/6 sin tocar ningun umbral. Cada motor (Jev, SemIf, Claude como clasificador) tiene sus propios umbrales, fijados en el split de desarrollo y guardados en configuracion por motor.
5. **Cada umbral se fija por costo asimetrico.** El ejemplo escala a un abogado desde una probabilidad de privilegio de 0.2 porque omitir un documento privilegiado cuesta mucho mas que una revision de mas. Cada umbral de la seccion 3 lleva escrita su razon de costo.

---

## 3. Principio Rector: "Jev Interpreta, el Codigo Gobierna"

Jev **no decide acciones de negocio ni ejecuta politicas**. Sus salidas entran como campos tipados de `DisputePolicyInput`, y la politica las evalua en el orden de la especificacion canonica: `docs/TEAM_BRIEF_COMPLEMENTED.md`, Decision 4 (v2.3). Este documento no repite ese orden; solo mapea cada senal a su clausula:

```python
# Campos nuevos en DisputePolicyInput (ademas de los actuales)
dispute_intent: str             # Jev Choice, o el extractor de respaldo
intent_confidence: float        # confianza de Jev Choice
is_stolen_reported: float       # Jev Noul, 0.0 a 1.0
customer_distress_score: float  # Jev Score, 0.0 a 3.0
```

| Senal de Jev | Clausula del brief | Umbral del brief v2.3 | Umbral de partida propuesto (se fija por motor en el split de desarrollo) | Razon de costo |
| --- | --- | --- | --- | --- |
| Intencion (`Choice`) | `POL-CLARIFY` | `intent_confidence` < 0.70: pedir aclaracion | (propuesta) Masa de disputa (`cargo_no_reconocido` + `cobro_indebido` + `tarjeta_robada`) entre 0.30 y 0.70: pedir aclaracion. Por encima, sigue la disputa; por debajo, consulta o fuera de alcance (seccion 2.D, punto 3) | Aclarar de mas cuesta un turno; seguir sin una disputa real abre un caso erroneo |
| Robo de tarjeta (`Noul`) | `POL-CLARIFY` y bloqueo preventivo (accion autonoma 6) | Entre 0.40 y 0.60: aclarar; >= 0.80: bloqueo | (propuesta) >= 0.50: ofrecer el bloqueo, sin zona de aclaracion aparte. El cliente confirma el bloqueo con Si o No (decidido el 26 sep), y esa confirmacion ya cumple el papel de la aclaracion | Ofrecer un bloqueo de mas cuesta una pregunta; no ofrecerlo deja activa una tarjeta robada |
| Angustia (`Score`, 0 a 3) | `POL-ESC-DISTRESS` | >= 2: escalar a humano | (propuesta) Banda: `score` >= 1.5 escala. La confianza no filtra esta senal (seccion 2.D, puntos 1 y 2) | Un escalamiento omitido a un cliente en crisis cuesta mas que un traspaso de mas |
| `dispute_intent = fuera_de_alcance` | `POL-DISP-TYPE` | Abstencion segura | Sin cambio: abstencion cuando `fuera_de_alcance` es la opcion ganadora con confianza decisiva; si no es decisiva, se aclara | Abstenerse de mas deja sin atender una disputa real; el caso se aclara antes de abstenerse |

Si el equipo aprueba los umbrales propuestos, se actualizan en el brief las lineas de `POL-CLARIFY`, `POL-ESC-DISTRESS` y el bloqueo de tarjeta de la accion autonoma 6.

`POL-CLARIFY` tambien se dispara cuando la busqueda encuentra 0 o 2+ cargos candidatos. `POL-ESC-LEGAL` sigue con palabras clave deterministas, auditables sin llamar a un modelo.

---

## 4. Reparticion de Roles: Jev vs. LLM vs. Codigo

| Responsabilidad | Quien lo hace | Como opera |
|---|---|---|
| **Intencion, Robo y Angustia** | **Jev (System One)** | Recibe unicamente el mensaje del cliente enmascarado. Devuelve `Choice`, `Noul` y `Score`. |
| **Extraccion de Entidades (Monto, Fecha, Comercio)** | **Regex + LLM de apoyo** | Regex determinista para formatos de moneda (COP, MXN, ARS, USD) y fechas relativas ("ayer", "12 de junio"), corriendo localmente sobre el mensaje original, antes del enmascarado (el masker actual convierte un monto COP de 7 digitos en `[REDACTED_PHONE]`). Si falla, un LLM extrae slots sobre el mensaje enmascarado. |
| **Cruce con Datos del Banco** | **Codigo Python** | Busca candidatos en `silver_transactions` filtrando estrictamente por `customer_id` de la sesion. **Jev nunca ve registros del dataset**. |
| **Politica y Permisos** | **Policy Engine (Python)** | Aplica las clausulas del brief v2.3 de forma determinista sobre las senales recibidas. |
| **Acciones y Verificacion** | **Tool Gateway (Python)** | Escribe en el esquema `ops` de Supabase Postgres y verifica leyendo de regreso antes de confirmar; la app lee `bank` y nunca abre DuckDB (`docs/SUPABASE_VERCEL.md`). |
| **Redaccion de Respuestas** | **Claude Haiku 4.5** | Redacta texto en ES/PT usando plantillas con marcadores (`{merchant}`, `{amount}`, `{complaint_id}`, `{clause_id}`) rellenados por codigo verificado. |

**Contrato comun del clasificador (propuesta).** `IntentExtractor` devuelve siempre la misma respuesta tipada (opcion, probabilidades, `noul`, `score`, confianza, modelo), sea cual sea el motor. Hay cuatro implementaciones posibles detras de la misma interfaz, con el mismo orquestador y la misma politica: el extractor por palabras clave (baseline), Jev, SemIf (plan B, seccion 5) y Claude Haiku como clasificador. Esta ultima es un adaptador que le pide al LLM una probabilidad por opcion o por nivel, y no una etiqueta; la confianza se calcula en codigo. El adaptador del ejemplo de LangChain (`llm_classifier.py`) cubre `Score` y `Noul` pero no `Choice`, asi que para la intencion hay que extenderlo.

**Salidas estructuradas del LLM de apoyo.** En el ejemplo, `with_structured_output(method="json_schema")`, que usa las salidas estructuradas nativas de Anthropic, gasto 2.4 veces menos tokens de entrada que el modo por defecto de function calling, con el mismo resultado (medido con Claude Sonnet 5). Aplica a la extraccion de slots; falta verificar que Haiku 4.5 soporte ese modo.

---

## 5. Medidas de Rigor, Reproducibilidad y Riesgos

1. **Extractor de Respaldo Obligatorio (Baseline)**:
   - Los tests unitarios y de integracion siempre se ejecutan contra el extractor de respaldo (regex + keywords) para garantizar independencia de red y costo cero en CI/CD.
   - (propuesta) El adaptador de Jev tambien se prueba sin red ni key, como en el ejemplo de LangChain: un clasificador stub con respuestas fijas por cada rama de la politica, valores fraccionarios en las fronteras (1.49 y 1.5 de angustia, 0.49 y 0.5 de robo, 0.30 y 0.70 de masa de disputa) y un test del cliente real sobre `httpx2.MockTransport`. Esto choca con la recomendacion H05 de la revision adversarial (no escribir codigo de Jev antes de tener key); lo decide el equipo.
2. **Mitigacion de Early Access**:
   - Si no se cuenta con API key activa de TypeSafe AI, el sistema conmuta automaticamente al baseline sin fallar.
   - (propuesta) Plan B: el ejemplo de LangChain llama al modelo de decision SemIf (`semif-qwen3.5-4b`) por el LangSmith Gateway con solo la key de LangSmith, con el mismo contrato de clasificador (paquete `langchain-typesafe`). Si en la fecha de corte no hay key de Jev, se prueba SemIf antes de sacar la hipotesis 4. Por verificar: costo, retencion de datos, calidad en ES y PT, y si tiene pesos abiertos para correrlo local. La doc oficial de TypeSafe y la del proveedor en LangChain no lo mencionan.
3. **Evaluacion de Componente Aprendido**:
   - `Choice` se medira contra el extractor baseline en una suite held-out bilingue (ES/PT).
   - Se utilizara un split de desarrollo separado de la suite held-out para calibrar los umbrales de la seccion 3, por separado para cada motor (seccion 2.D, punto 4), evitando data leakage.
   - Se reportara el acuerdo inter-anotador (Cohen's Kappa en muestra) sobre el etiquetado de intenciones.
   - (propuesta) Comparacion con el mismo orquestador y la misma politica, cambiando solo el motor del clasificador (contrato comun de la seccion 4). Por motor se reporta: latencia por llamada, latencia de punta a punta, tokens de entrada y salida, costo, acuerdo entre motores y distribucion de resultados, como en `compare.py` del ejemplo. A eso se suma lo que el ejemplo no reporta: exactitud y calibracion contra nuestras etiquetas, cortadas por idioma.
4. **Versionado estricto**:
   - Dependencia fijada en `typesafe-sdk==0.7.1`, verificada en PyPI (publicada el 21 sep 2026). El SDK saco 5 versiones en 12 dias, asi que no se actualiza durante el hackathon.
   - Modelo fijado en `jev-1.13.0`. Los alias `jev-latest` y `jev-preview` apuntan hoy a esa version, pero se mueven solos con cada release; la doc oficial recomienda fijar la version para no perder los umbrales ajustados.
   - Cada respuesta trae `model` (la version que respondio) y `request_id`; los dos van al log de auditoria en cada llamada, junto con el proveedor.
   - Tres repeticiones en corridas de evaluacion para medir variabilidad.
5. **Retencion y Privacidad de Datos**:
   - Los registros de la base de datos jamas se envian a TypeSafe ni a proveedores externos.
   - Solo viaja el mensaje enmascarado del cliente (PII redactada: sin tarjetas, telefonos ni identificaciones).
   - Se consulta formalmente a mentores sobre el uso de APIs de terceros, y a TypeSafe AI sobre su politica de retencion. La doc oficial tiene una pagina `legal.md` que falta leer y citar.
   - (propuesta) Persistencia minima: el handoff y el log de auditoria guardan el mensaje enmascarado, los ids y los valores de las senales, nunca el texto crudo. Es el mismo criterio del ejemplo de LangChain, que manda al revisor humano solo scores e ids para no copiar contenido privilegiado al checkpoint.
   - (propuesta) LangSmith no se usa salvo que los mentores permitan enviar datos a un tercero, porque sus trazas llevan el estado completo.
6. **Acceso**:
   - Jev esta en early access con lista de espera ([console.typesafe.ai](https://console.typesafe.ai/)). Sin API key, el extractor de respaldo es el default y el baseline; `JevIntentExtractor` se conecta detras de la interfaz `IntentExtractor` sin tocar el orquestador ni la politica.

---

## 6. Relacion con LangGraph y fuentes

**LangGraph (propuesta: no adoptarlo).** El ejemplo de LangChain arma el flujo como un grafo con checkpoints, `interrupt()` para la revision humana y trazas en LangSmith. No lo adoptamos para el orquestador por tres razones: B es la ruta critica a G1 y una dependencia nueva no cabe; un checkpoint no es el sistema de registro, porque la regla 7 exige leer de vuelta del store de operacion; y nuestros turnos son cortos, con el estado ya en Postgres (`ops`). Tomamos sus patrones, que no dependen del framework:

* El ruteo es una funcion pura de Python sobre las senales tipadas, con umbrales como constantes con nombre y su razon escrita.
* La revision humana y la confirmacion del cliente son estados explicitos del orquestador (`awaiting_confirmation`, `awaiting_clarification`), el equivalente de `interrupt()`.
* El clasificador se inyecta, asi que se puede cambiar de motor y probar sin red.
* El modelo generativo solo corre en la rama que lo necesita: redaccion de respuestas y, si falla la regex, extraccion de slots.

Fuentes:

* [Blog de LangChain, "Building production agents with Jev and LangGraph"](https://www.langchain.com/blog/building-prod-with-jev-and-langgraph) (Sydney Runkle y Hunter Lovell, 25 sep 2026).
* [Gist con el codigo, los tests y las mediciones del ejemplo](https://gist.github.com/sydney-runkle/a632ba4ea0b2b72501dfa4b6ab2a7d8a).
* [Doc oficial de TypeSafe](https://docs.typesafe.ai): `models.md`, `sdk/python/api/types/questions.md` y `sdk/python/api/types/responses.md`.
* PyPI: `typesafe-sdk` 0.7.1 y `langchain-typesafe` 0.0.1a3 (alpha).
