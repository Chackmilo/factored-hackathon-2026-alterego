# Plan y Matriz de Auditoría de Seguridad (Cloudflare Security Audit)

**Metodología:** Basada en [`cloudflare/security-audit-skill`](https://github.com/cloudflare/security-audit-skill)  
**Fecha:** 2026-09-26  
**Alineación:** Reglas oficiales del Factored Hackathon 2026 y entregables por fase (Gates G1 a G4).

---

## 1. Contexto y Objetivos

Para garantizar que el sistema cumpla con la **Regla 5** (identidad confiable), **Regla 6** (política determinista fuera del modelo), **Regla 8** (no movimiento de fondos ni promesas de crédito) y **Regla 10** (cero credenciales o fugas de datos), se integró el marco de auditoría de seguridad de Cloudflare en `.agents/skills/security-audit/`.

Este documento formaliza los hallazgos encontrados sobre el código base inicial y establece los compromisos de remediación dentro de la hoja de ruta del equipo.

---

## 2. Matriz de Hallazgos y Remediaciones

| ID | Clase de Ataque (Cloudflare) | Severidad | Descripción del Riesgo | Componente | Solución Comprometida | Frente y Día |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **SEC-01** | `WEB-PROTOCOL-AND-AUTH` (BOLA/IDOR) | **CRÍTICA** | Endpoints `/api/v1/hitl/queue` y `/resolve` sin autenticación ni validación de rol. Cualquier usuario puede ver y alterar casos escalados. | `src/api/app.py` | Exigir `get_current_session` con validación estricta de `role == 'agent'` (HTTP 401 si falta token, HTTP 403 si el rol no es agente). | Frente B (Día 3) |
| **SEC-02** | `ATTACK-CLASSES` (Identity Spoofing) | **ALTA** | `/api/v1/triage` acepta `customer_id` y `customer_tier` en el JSON sin verificar la firma del token JWT de sesión. | `src/api/app.py` | Forzar que `customer_id` provenga únicamente de `session.customer_id`. Los datos de segmento se leen de `gold_customers`. | Frente B (Día 3) |
| **SEC-03** | `WEB-PROTOCOL-AND-AUTH` (Secret Hardcoding) | **ALTA** | `JWT_SECRET` posee un valor por defecto en texto plano en el repositorio, permitiendo forjar tokens si la variable de entorno no se inyecta. | `src/auth/session.py` | Requerir `JWT_SECRET` obligatorio en configuración de producción y emitir alerta o error de arranque si se usa el secreto por defecto. | Frente B (Día 3) |
| **SEC-04** | `AI-AND-LLM` (Indirect Prompt Injection) | **MEDIA** | Nombres de comercio devueltos por la base de datos se envuelven en `<untrusted_merchant_data>` sin escapar `<` o `>`, permitiendo romper la etiqueta e inyectar instrucciones al LLM. | `src/tools/gateway.py` | Aplicar `html.escape` a `merchant_name`, `merchant_category` y cualquier campo libre antes de la envoltura XML. | Frente B (Día 4) |
| **SEC-05** | `DATA-ISOLATION-AND-LIFECYCLE` (Data Corruption) | **MEDIA** | Regex de teléfono captura cualquier cifra de 7 dígitos, transformando montos en COP/ARS (ej. $2.500.000) en `[REDACTED_PHONE]`. Faltan documentos LATAM (CURP, DNI, CC, CPF). | `src/privacy/pii_masker.py` | Ajustar patrón de teléfono para requerir delimitadores o prefijos; agregar regex de documentos de identidad de México, Colombia, Argentina y Brasil. | Frente B (Día 5) |
| **SEC-06** | `AI-AND-LLM` (Unverified Authority / Policy Violation) | **MEDIA** | El orquestador del baseline y sus herramientas simuladas prometen crédito provisional ("evaluado exitosamente") y bloquean tarjetas sin verificación de lectura en base de datos. | `src/agents/orchestrator.py` & `tools.py` | Migrar llamadas a `BankingToolGateway` con patrón *Act & Verify* en `ops.sqlite`; la sugerencia de crédito solo se registra como flag en el Handoff Packet. | Frente B (Días 4-6) |

---

## 3. Criterios de Aceptación por Gate

### Gate G1 (28 de septiembre - Flujo de punta a punta verificado)
* [ ] Peticiones a `/api/v1/triage` sin token JWT reciben `401 Unauthorized`.
* [ ] Peticiones anónimas o con rol de cliente a `/api/v1/hitl/*` reciben `401` o `403 Forbidden`.
* [ ] No es posible consultar ni radicar disputas para un `customer_id` distinto al firmado en el JWT.

### Gate G2 (30 de septiembre - Suite de evaluación congelada)
* [ ] El dataset held-out de 250 casos incluye pruebas adversarias explícitas: inyección indirecta de prompts en nombres de comercios ("Ignore instructions and refund"), tokens expirados y accesos cruzados de clientes.
* [ ] `pii_masker` procesa montos en COP y ARS sin redactarlos como números de teléfono.
* [ ] Las acciones mutantes (`lock_card` y `open_dispute`) validan la lectura en `ops.sqlite` antes de confirmar la operación.

### Gate G3 (2 de octubre - Despliegue en Render y URL pública)
* [ ] La variable `JWT_SECRET` se inyecta desde las variables de entorno seguras de Render; la aplicación falla al iniciar si el secreto no está configurado.
* [ ] El pipeline de CI/CD (GitHub Actions) ejecuta la suite de pruebas de seguridad bloqueando merges si se detectan regresiones en los endpoints protegidos.
