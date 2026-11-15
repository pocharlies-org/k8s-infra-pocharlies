Rol: pm · Fecha: 2026-10-01T18:51:25Z · Sesión: b3e9d1f2-5257-4b9c-99a5-080f506b5fec · Estado: LISTO

# INFRA-351 — Synapse Hogar · categorización inteligente de movimientos bancarios (LLM local + brain personal)

## Objetivo

Que el aviso diario "🏦 Hogar · movimientos nuevos" de Telegram deje de depender de la heurística regex de `personal_categorizer` y categorice los movimientos del tenant `family` (profile=personal) con el LLM local (alias `tooling`, cero egress) enriquecido con evidencia del corpus personal del brain (WhatsApp/Telegram, Gmail con adjuntos, facturas), devolviendo `comercio_real / categoria / confianza / evidencia` y preguntando con candidatos a 1 clic cuando la confianza es baja. Solapes: el corpus ya existe gracias a INFRA-119 (brain instancia `personal`, ~800k chunks; medido: WhatsApp+Telegram de Daniel 198.729 msgs y Gmail de al menos 3 buzones indexados con adjuntos); INFRA-364 (reindexado de WhatsApp por ventanas) es ejecución de Dani y NO bloquea — el corpus actual ya es consultable; INFRA-104 (expenses) comparte las tablas `gestoria_banking.bank_movements` pero su perfil es `empresa` — este epico no toca esa ruta.

Repo: `skirmbooks-gestoria-src` (adapters/banking, tronco `main`) + GitOps `k8s-skirmbooks-pocharlies` (ArgoCD app `skirmbooks`, targetRevision `main` — medido 2026-10-01).

## Qué existe hoy (medido 2026-10-01, para el tech-lead)

- **El aviso lo produce** `adapters/banking/src/synapse_adapter_banking/cobros_digest.py` → CronJob `skirmbooks-hogar-cobros-digest` (ns `skirmshop`, 07:20 UTC, activo), tenant `family`, grupo Hogar `-1003749364241`, topic "🏦 Banca". Formato en `cobros_report.py::compose_cobros_digest`.
- **Los movimientos llegan por PSD2 EnableBanking** (`psd2.base_url: https://api.enablebanking.com`, CronJob `skirmbooks-banking-daily-sync` 06:40 UTC) a `gestoria_banking.bank_movements` (Postgres `postgres-shared.databases/skirmbooks`).
- **La premisa FINDING 2026-07-03 sigue viva y además ACTIVA**: `banking.classify_personal` (gate `profile='personal'`, `allow_cloud_fallback=False`) está desplegado en `deploy/skirmbooks-banking-classifier` (ns skirmshop, 91d) y el CronJob `skirmbooks-personal-classifier-sweep` (07:00 UTC) está `suspend:false` y completando a diario (job `…-29847300` Complete hace 11 h). La heurística regex (`personal_categorizer._RULES`) es hoy la que categoriza; el hook LLM solo se invoca cuando cae a `otros`.
- **El endpoint LLM ya NO es 192.168.50.142:4000** (dato de julio, obsoleto): el deploy usa `LITELLM_BASE_URL=http://litellm.litellm.svc.cluster.local:4000/v1` y `primary_model="tooling"` (config del fiscal-validator); el alias `tooling` vive en `k8s-litellm-pocharlies/k8s/manifest.yaml:443` → `http://tooling.llm.svc.cluster.local:8000/v1` (pool tooling-resident). Allowlist on-prem fail-safe: `_ON_PREM_MODELS={tooling,smart,fast}` en `adapters/fiscal-validator/.../llm.py`.
- **La pregunta a 1 clic YA existe pero sin candidatos**: `cobros_report.py::build_category_keyboard` ofrece el teclado estático de todas las categorías (`callback_data bc:cat:<uuid>:<code>` → `banking.family.set_category`). Falta: candidatos priorizados + evidencia citada.
- **Brain**: API `POST /instances/personal/search` (src/api/search.py — `query`, `limit`; SIN filtro por fecha+importe: el metadata por doc se filtra en el llamante). Cliente reutilizable `synapse_shared/brain.py` (existe en la librería compartida; el adapter banking aún NO usa el brain — grep: cero hits). Corpus medido con `brain_search(instance=personal)`: WhatsApp/Telegram (Daniel 198.729 msgs, 50 chats) y Gmail con adjuntos (pocharlies@gmail.com, me@e-dani.com, lays84.mv@gmail.com visibles en resultados).
- **Few-shot**: no existe tabla de ejemplos etiquetados para el perfil personal. `gestoria_banking.movement_category_overrides` (regex→category, UNIQUE tenant+pattern, migración 0003) es del perfil empresa/skirmshop y no sirve tal cual como few-shot; hace falta tabla nueva (p. ej. `movement_labeled_examples`) alimentada por las respuestas del botón.
- **Salida actual del LLM**: solo `{"category": …}` (`_LLM_JSON_SCHEMA`); sin `comercio_real`, `confianza` ni `evidencia`. `bank_movements` no tiene columna de evidencia.

## Criterios de aceptación

- [ ] **C1 — "CAIXABANK PAYMENTS CONSUMER 80,52 €" resuelto solo o con pregunta.** El clasificador lo saca de `otros` (directo o vía botón). Verifica (DB, tras 1+ corridas del sweep con el cambio desplegado):
  ```
  kubectl -n databases exec postgres-shared-2 -- psql -U postgres -d skirmbooks -c \
    "SELECT concept, amount, category FROM gestoria_banking.bank_movements \
     WHERE tenant_id='family' AND concept ILIKE '%CAIXABANK%CONSUMER%' AND amount=-80.52"
  ```
  Esperado: ≥1 fila con `category` NOT NULL y `∉ ('otros','ingresos_otros')`. Si ese movimiento histórico ya estaba categorizado por la heurística, qa lo reproduce con un replay de `banking.classify_personal` sobre un movimiento sintético con ese concepto/importe (Job one-shot en ns skirmshop) y exige el mismo resultado.
- [ ] **C2 — Bizum con contexto WhatsApp citando conversación.** Al menos un movimiento Bizum de los 30 días posteriores al deploy sale categorizado con evidencia que cita una conversación de WhatsApp del brain. Verifica:
  ```
  kubectl -n databases exec postgres-shared-2 -- psql -U postgres -d skirmbooks -c \
    "SELECT concept, category, evidence FROM gestoria_banking.bank_movements \
     WHERE tenant_id='family' AND concept ILIKE '%BIZUM%' AND value_date >= now()-interval '30 days' \
     ORDER BY value_date DESC LIMIT 10"
  ```
  Esperado: ≥1 fila con `evidence` NOT NULL conteniendo referencia a conversación de WhatsApp (nombre de chat + fecha). (La columna `evidence` la introduce la migración de este epic; qa valida además que el mensaje de Telegram de ese movimiento cite la conversación.)
- [ ] **C3 — <20% no reconocido tras 4 semanas.** Medido 4 semanas después del deploy productivo:
  ```
  kubectl -n databases exec postgres-shared-2 -- psql -U postgres -d skirmbooks -c \
    "SELECT round(100.0*count(*) FILTER (WHERE category IS NULL OR category IN ('otros','ingresos_otros'))/count(*),1) AS pct_no_reconocido \
     FROM gestoria_banking.bank_movements \
     WHERE tenant_id='family' AND value_date >= now()-interval '28 days'"
  ```
  Esperado: `pct_no_reconocido < 20.0`.
- [ ] **C4 — Aviso con comercio + categoría + enlace/evidencia.** El digest diario lista cada movimiento con `comercio_real` (no el concepto PSD2 en bruto) + categoría legible, y los clasificados con evidencia incluyen la cita (WhatsApp/Gmail/factura) o enlace al detalle (`/bancos` de skirmbooks-ui). Verifica: leer el último mensaje del topic "🏦 Banca" del grupo Hogar (`-1003749364241`) vía MCP `hermes` (`messages_read`) tras la corrida de las 07:20 UTC. Esperado: cada línea de gasto/ingreso muestra comercio + `emoji Categoría`; al menos los clasificados por LLM muestran línea de evidencia.

## Restricciones

- **On-prem obligatorio**: solo alias `tooling` vía LiteLLM in-cluster, `allow_cloud_fallback=False` y allowlist `_ON_PREM_MODELS` intactos (barrera de egress del texto bancario PSD2). Cero nubes.
- **No tocar el residente LLM**: sin cambios de réplicas/perfiles en ns `llm`; el classifier es un consumidor más del alias `tooling` (tope 8 req paralelas — el barrido es de decenas de movimientos/día, no lo satura).
- **PRs**: código a `skirmbooks-gestoria-src` → `main`; manifiestos a `k8s-skirmbooks-pocharlies` → `main` (ArgoCD lee `main`, medido). Nunca push directo al tronco.
- **No tocar brain ni ingesta**: solo lectura vía `POST /instances/personal/search`. INFRA-364 (reindex WhatsApp) es de Dani; no se interviene ni se espera.
- **Contratos existentes intocables**: routing keys `banking.<tenant>.classify_personal`, `banking.<tenant>.set_category`, callback Telegram `bc:cat:<uuid>:<code>` y la tabla `movement_alert_log` no se renombran ni cambian de semántica; todo lo nuevo entra añadido (columna nueva, tabla nueva, teclado nuevo), no editando lo viejo.
- **Fail-open como hoy**: si el brain o el LLM fallan, el digest sale con la heurística; el aviso nunca deja de llegar.

## Trabajo reciente (24 h)

Nada en 24 h que afecte a este plan.

## Diseño

Diseñador: no — la única interfaz es el mensaje de Telegram (texto + teclado inline que ya existe); el cambio es de contenido (comercio, evidencia, candidatos) siguiendo el formato consolidado de `compose_cobros_digest`, no de layout. qa revisa el copy en la validación.

## Historias previstas

1. **S1 — Salida enriquecida del clasificador** (dueño: developer): prompt + JSON schema `comercio_real/categoria/confianza/evidencia` en `personal_categorizer`, búsqueda en brain `personal` como contexto (cliente `synapse_shared.brain`), columna `evidence` (migración), fail-open. Repo skirmbooks-gestoria-src.
2. **S2 — Few-shot de ejemplos etiquetados** (dueño: developer): tabla nueva de ejemplos (concepto→comercio+categoría, por tenant), inyección en el prompt, y alimentación automática desde las respuestas del botón (`set_category`). Migración + tests.
3. **S3 — Pregunta a 1 clic con candidatos** (dueño: developer): cuando confianza baja, el mensaje pregunta con los 2-3 candidatos (comercio + evidencia citada) + botón "Otras…" que despliega el teclado completo actual (patrón `bc:cat:` conservado).
4. **S4 — Formato del digest** (dueño: developer): líneas con `comercio_real` + categoría + evidencia/enlace `/bancos`; respeta 4096 y `_fit_telegram`.
5. **S5 — GitOps y credenciales** (dueño: devops): config del adapter banking con `BRAIN_URL`/instancia + api key (vault/ESO), imagen nueva del classifier, PR a k8s-skirmbooks-pocharlies `main`.
6. **S6 — Validación E2E y métrica de 4 semanas** (dueño: qa): C1-C4 contra producción; C3 se mide 4 semanas tras el deploy (queda en el tablero como verificación diferida).

## Tamaño

M — ~6 historias, 1 repo de código + 1 GitOps; sin trabajo nuevo de brain/ingesta (corpus ya indexado y consultable).

## Dificultad

Dificultad: media — no hay servicio ni arquitectura nueva: el pipeline (PSD2 → sweep → classifier → digest → botón) ya corre en producción y este epic lo enriquece. Añade una comunicación entre servicios (adapter banking → brain search), pero es lectura de un API existente vía un cliente compartido que ya existe, con fail-open; el camino LLM on-prem (FiscalLlmClient, alias `tooling`) también está desplegado y verificado. No es alta: nada irreversible, sin cambio de contratos, y el LLM solo se invoca en el tramo dudoso del barrido diario.
