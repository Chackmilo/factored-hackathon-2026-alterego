# Jev (TypeSafe AI): Modelo de Sistema 1 para Decisiones Tipadas en Software

Documento de referencia tecnica y diseno de integracion para el equipo del **Factored AI & Data Hackathon 2026**.

---

## 1. Que es Jev y por que es Relevante

**Jev** (desarrollado por TypeSafe AI, fundada por Diogo Almeida, ex-investigador de OpenAI) inaugura la categoria de **System One Models (Modelos de Sistema 1)**:

* **Inspirado en Daniel Kahneman (Thinking, Fast and Slow)**: Los LLMs tradicionales corresponden al Sistema 2 (razonamiento deliberado, lento y generador de texto token por token). Jev implementa el Sistema 1: **decisiones rapidas, intuitivas y estructuradas**.
* **Un "if statement" probabilistico para codigo**: Jev no genera cadenas de texto libre, no chatea, no programa ni redacta respuestas. Su unica funcion es evaluar un estado (*state*) y responder preguntas cerradas con salidas fuertemente tipadas y calibradas.
* **Garantia de Type-Safety a nivel de formato (Cero errores de esquema)**: El espacio de salida esta prefijado por esquema. Es matematicamente imposible que retorne una clave inexistente o un JSON roto. *(Nota: esto garantiza integridad de formato, no infalibilidad semantica; el modelo aun puede clasificar erróneamente una clase y debe evaluarse)*.
* **Muestreador en Paralelo (Parallel Sampler)**: Evalua todas las variables en un unico pase de inferencia a nivel de hardware, sin decodificacion autorregresiva.
* **Latencia y Costo**: Respuestas oficiales entre **70 ms y 500 ms** (segun TypeSafe AI). Costo de entrada de $0.042 por millon de tokens ($42 por mil millones) y **tokens de salida 100% gratuitos**.
* **Algoritmo RLCD (Reinforcement Learning for Calibrated Decisions)**: A diferencia de RLHF (que induce sobreconfianza para complacer al humano), RLCD premia la calibracion empirica: si reporta 90% de probabilidad, la tasa real esperada se aproxima a ese 90%. Debe medirse empiricamente en nuestro conjunto de evaluacion en Espanol y Portugues.

---

## 2. Primitivas del SDK y su Rol en el Flujo

En Jev, el **estado (`state`) contiene los hechos observados** (el mensaje enmascarado del cliente) y las **preguntas (`questions`) contienen la interpretacion requerida**.

```python
from typesafe_sdk import TypeSafeClient, Choice, Noul, Score
```

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

| Senal de Jev | Clausula del brief | Umbral propuesto (se fija en el split de desarrollo) |
|---|---|---|
| `intent_confidence` baja | `POL-CLARIFY` | < 0.70: pedir aclaracion |
| `is_stolen_reported` incierto | `POL-CLARIFY` | entre 0.40 y 0.60: pedir aclaracion |
| `is_stolen_reported` alto | Bloqueo preventivo (accion autonoma 6) | >= 0.80: bloqueo, sujeto a la decision abierta sobre confirmacion del cliente |
| `customer_distress_score` alto | `POL-ESC-DISTRESS` | >= 2: escalamiento a humano |
| `dispute_intent = fuera_de_alcance` | `POL-DISP-TYPE` | abstencion segura |

`POL-CLARIFY` tambien se dispara cuando la busqueda encuentra 0 o 2+ cargos candidatos. `POL-ESC-LEGAL` sigue con palabras clave deterministas, auditables sin llamar a un modelo.

---

## 4. Reparticion de Roles: Jev vs. LLM vs. Codigo

| Responsabilidad | Quien lo hace | Como opera |
|---|---|---|
| **Intencion, Robo y Angustia** | **Jev (System One)** | Recibe unicamente el mensaje del cliente enmascarado. Devuelve `Choice`, `Noul` y `Score`. |
| **Extraccion de Entidades (Monto, Fecha, Comercio)** | **Regex + LLM de apoyo** | Regex determinista para formatos de moneda (COP, MXN, ARS, USD) y fechas relativas ("ayer", "12 de junio"), corriendo localmente sobre el mensaje original, antes del enmascarado (el masker actual convierte un monto COP de 7 digitos en `[REDACTED_PHONE]`). Si falla, un LLM extrae slots sobre el mensaje enmascarado. |
| **Cruce con Datos del Banco** | **Codigo Python** | Busca candidatos en `silver_transactions` filtrando estrictamente por `customer_id` de la sesion. **Jev nunca ve registros del dataset**. |
| **Politica y Permisos** | **Policy Engine (Python)** | Aplica las clausulas del brief v2.3 de forma determinista sobre las senales recibidas. |
| **Acciones y Verificacion** | **Tool Gateway (Python)** | Escribe en el store de operacion SQLite y verifica leyendo de regreso antes de confirmar; DuckDB es solo lectura para la app. |
| **Redaccion de Respuestas** | **Claude Haiku 4.5** | Redacta texto en ES/PT usando plantillas con marcadores (`{merchant}`, `{amount}`, `{complaint_id}`, `{clause_id}`) rellenados por codigo verificado. |

---

## 5. Medidas de Rigor, Reproducibilidad y Riesgos

1. **Extractor de Respaldo Obligatorio (Baseline)**:
   - Los tests unitarios y de integracion siempre se ejecutan contra el extractor de respaldo (regex + keywords) para garantizar independencia de red y costo cero en CI/CD.
2. **Mitigacion de Early Access**:
   - Si no se cuenta con API key activa de TypeSafe AI, el sistema conmuta automaticamente al baseline sin fallar.
3. **Evaluacion de Componente Aprendido**:
   - `Choice` se medira contra el extractor baseline en una suite held-out bilingue (ES/PT).
   - Se utilizara un split de desarrollo separado de la suite held-out para calibrar los umbrales (0.70, 0.40 - 0.60, 0.80) evitando data leakage.
   - Se reportara el acuerdo inter-anotador (Cohen's Kappa en muestra) sobre el etiquetado de intenciones.
4. **Versionado estricto**:
   - Dependencia fijada en `typesafe-sdk==0.7.1`.
   - Registro de la version de modelo que reporte la API (por verificar; no esta publicada) y del proveedor en cada traza del log de auditoria.
   - Tres repeticiones en corridas de evaluacion para medir variabilidad.
5. **Retencion y Privacidad de Datos**:
   - Los registros de la base de datos jamas se envian a TypeSafe ni a proveedores externos.
   - Solo viaja el mensaje enmascarado del cliente (PII redactada: sin tarjetas, telefonos ni identificaciones).
   - Se consulta formalmente a mentores sobre el uso de APIs de terceros, y a TypeSafe AI sobre su politica de retencion (no esta publicada).
6. **Acceso**:
   - Jev esta en early access con lista de espera ([console.typesafe.ai](https://console.typesafe.ai/)). Sin API key, el extractor de respaldo es el default y el baseline; `JevIntentExtractor` se conecta detras de la interfaz `IntentExtractor` sin tocar el orquestador ni la politica.
