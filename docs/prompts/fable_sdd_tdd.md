<!-- Uso: abre Claude Code en la raíz del repo con Fable 5.1 (esfuerzo high) y pega este archivo como primer mensaje. Para otra porción, cambia solo la sección "Porción de esta sesión". -->

# Desarrollo guiado por spec y por tests, con optimización medida

## Contexto

Somos AlterEgo, un equipo de 4 personas en el Factored AI & Data Hackathon 2026. Construimos el intake de disputas de transacciones de LATAM Bank en español y portugués, y entregamos el 5 de octubre de 2026. Los jueces premian primero que el sistema funcione y después el rigor: cada decisión trazable a una regla escrita, comparación honesta contra baselines y ninguna acción reportada sin verificar. Desde el día 3, nuestro criterio de listo es "cada arreglo tiene un test que falló primero" (`docs/PLAN.md`, hoja de ruta). Por eso trabajas con desarrollo guiado por spec y por tests: cada línea nueva responde a una cláusula escrita, un test la fija y cada mejora queda medida.

Corres en Claude Code dentro del repo y `CLAUDE.md` ya está en tu contexto. Lee también `AGENTS.md` (reglas de la sección 4, hallazgos de datos de la sección 7, brechas de la sección 9), el registro de decisiones de `docs/PLAN.md` y las secciones de `docs/TEAM_BRIEF_COMPLEMENTED.md` que toque la porción.

## Porción de esta sesión

- **Porción:** motor de política de disputas llevado a la spec v2.3 (`src/rules/dispute_policy.py`, frente B).
- **Spec:** brief v2.3, sección 2, Decision 4 (cláusulas, orden y matriz de monedas), más las filas Decididas del registro de decisiones que la afecten.
- **Fuera de la porción:** gateway, orquestador, Jev, LightGBM y el baseline. Una cláusula que depende de un componente que aún no existe (señales de Jev, score de LightGBM) se especifica y se prueba contra su contrato de entrada: un campo tipado alimentado con valores de fixture. El componente no se construye aquí. Una cláusula que vive en otra capa, como `POL-SEC-SESSION` en auth y gateway, queda marcada en la matriz como fuera de la porción.
- **Medición:** el embudo de la política sobre los cargos disputables de junio en `data/lakehouse.duckdb`, abierto en solo lectura. El notebook reporta 8.967 cargos disputables: 55,1% `POL-AUT-INTAKE`, 39,5% `POL-ESC-500` y 5,4% candidatos a `POL-AUT-150`.

## La spec manda

Precedencia cuando las fuentes chocan: enunciado oficial, reglas de `AGENTS.md` sección 4, brief v2.3 y, al final, el código. Código que contradice la spec es una brecha que cierras. Un test existente que codifica la versión vieja (v2.0) se actualiza en el mismo commit que cierra la brecha, y el informe lo nombra. Si la spec te parece equivocada, la dejas intacta en el código y escribes la propuesta, con su evidencia, en la sección de preguntas de la spec de la porción.

## Método

### Fase 1: spec de la porción (la única parada)

Escribe `docs/specs/<porción>.md` con tres partes:

1. **Matriz de trazabilidad:** una fila por cláusula con su id, la regla en una línea, las entradas que usa, el resultado esperado, el estado en el código (cumple, falta o diverge, con `archivo:línea`) y el nombre del test que la fija.
2. **Criterios de aceptación** en forma Dado / Cuando / Entonces, uno por comportamiento, con los bordes: exactamente $500, días 60 y 61, cargo fechado después de hoy, 2 y 3 cargos en 48 h, y los empates entre cláusulas que prueban el orden.
3. **Supuestos** que tomaste donde la spec calla y **preguntas** que solo el equipo puede decidir.

La fase termina cuando cada cláusula de la spec tiene su fila y cada criterio tiene nombre de test. Muéstrame la matriz, los supuestos y las preguntas, y espera mi aprobación. Con la aprobación, la spec es el primer commit de la rama.

### Fase 2: rojo, verde, refactor

Recorre los criterios aprobados en el orden de la política:

- **Rojo:** escribe el test y córrelo. Cuenta como rojo solo si falla en la aserción del comportamiento; un `ImportError` o un `NameError` todavía no es rojo.
- **Verde:** el cambio mínimo que lo hace pasar.
- **Refactor** con la suite completa en verde (`uv run pytest -q`).
- **Commit** con el test y el código juntos. Mensaje en inglés, con el id de cláusula en el asunto y el fallo rojo en el cuerpo (`Red: <test>: <aserción>`), para que el historial muestre la trazabilidad.

Nombra cada test con su id de cláusula (`test_pol_win_60_...`) para que la matriz se verifique con grep. Un test enfocado por criterio, del tamaño de los tests vecinos; los scripts de prueba rápida van al scratchpad, fuera del repo.

La fase termina cuando cada fila de la matriz dice "cumple" con su test en verde y la suite completa pasa. Antes de darla por cerrada, pide a un subagente de contexto limpio que audite la matriz contra la spec y el código, fila por fila, y corrige lo que encuentre.

### Fase 3: medir y optimizar con trinquete

Optimizar significa mover las métricas de la pregunta problema (brief sección 5) sin romper la spec. Funciona como un trinquete: un cambio se queda solo si los resultados inseguros no suben y las escalaciones omitidas no suben (una escalación omitida cuesta 10 veces una innecesaria). Cumplido eso, se busca más resolución segura automatizada, y después menos latencia y costo.

1. **Línea base:** mide la porción antes de tocar nada y explica cada diferencia con los números del notebook.
2. **Intentos:** cada intento es una hipótesis medida antes y después sobre la misma carga, con denominadores. Lo que no pasa el trinquete se revierte.
3. **Perillas:** los umbrales y el orden que fija la spec ($150, $500, riesgo 0,70, 60 días, 48 h) son spec. Moverlos es un cambio de spec y va como fila "Propuesta", con su evidencia, al registro de decisiones de `docs/PLAN.md`. Solo ajustas los umbrales que la spec delega al split de desarrollo (los de Jev y el umbral de LightGBM por costo).
4. **Datos de ajuste:** el split de desarrollo o los fixtures. La suite held-out se congela con hash el 30 de septiembre y queda fuera de todo ajuste.

Registra cada intento en una tabla dentro de la spec de la porción: hipótesis, cambio, métrica antes y después, n y decisión. Si la porción no tiene perillas legítimas, la fase termina con la línea base y las propuestas.

## Límites

- Trabaja en una rama nueva, creada desde la actual al empezar y nombrada por la porción. Haces commits; el push, el PR y el merge quedan para el equipo.
- Si otro proceso bloquea el lakehouse, lo reportas y sigues con lo que no depende de él; los procesos ajenos se dejan corriendo.
- `.env`, keys y filas del dataset quedan fuera del código, los logs y los prompts.
- Un solo workflow. Lo que exija tocar el baseline, el gateway o el orquestador va como seguimiento.
- En documentos que lee una persona, sin rayas (em dash o en dash): usa comas, puntos, paréntesis o dos puntos.

## Cómo trabajas

- Con la fase 1 aprobada, trabajas de forma autónoma hasta cerrar las fases 2 y 3. Te detienes solo ante una acción destructiva o un cambio de alcance que el equipo deba decidir. Un paso decidido se ejecuta; anunciarlo y terminar el turno lo deja sin hacer.
- Un bug, un problema de rendimiento o una conducta que la porción no menciona va como seguimiento en el informe, no como cambio en esta rama.
- Edita de forma quirúrgica: cambia las líneas necesarias en vez de reescribir archivos enteros.
- Antes de reportar progreso, contrasta cada afirmación con una salida de herramienta de esta sesión. Lo no verificado se reporta como pendiente.

## Informe final

Abre con el resultado en una frase. Después: la matriz final, la evidencia de rojo de cada criterio (test y aserción), la salida final de pytest, la tabla de optimización con denominadores, los supuestos, y los seguimientos y preguntas abiertas para el equipo. Escribe frases completas, sin las abreviaturas que hayas inventado mientras trabajabas.
