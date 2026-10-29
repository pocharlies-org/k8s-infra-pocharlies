Rol: pm · Fecha: 2026-10-02T10:30:38Z · Sesión: 396ca9c6-b131-42a7-a64c-e0c74937fa3f · Estado: LISTO

# INFRA-410 — Synapse Hogar · clasificador de movimientos por LLM con taxonomía dinámica

## Objetivo

Que la categorización contable de los movimientos del tenant `family` (Synapse Hogar) la decida el LLM local con taxonomía viva — categorías nuevas propuestas y aprobadas por humano, semántica de gasto neto (liquidaciones de tarjeta y traspasos no suman), cuotas de préstamo como servicio de deuda y patrones periódicos pre-categorizados. **Solape medido con INFRA-351** (spec LISTO, 01-10): allí el corpus/brain-search, la salida enriquecida `comercio_real/confianza/evidencia` y la tabla few-shot de ejemplos; aquí SOLO el cómo contable (subtipos, `es_gasto_neto`, catálogo extensible, recurrencia del perfil personal y alertas de importe). El retrieval y el bucle few-shot NO se rehacen aquí — se consumen de 351 (historias S1/S2 de 351). **Dependencia dura: arrancar después de que INFRA-351 esté desplegado** (enlace Blocks creado; mismo repo y mismos ficheros — hacerlo antes garantiza conflictos).

Repo: `skirmbooks-gestoria-src` (adapters/banking, tronco `main`) + GitOps `k8s-skirmbooks-pocharlies` (ArgoCD app `skirmbooks`, targetRevision `main` — medido 02-10: HEAD branch `main`).

## Qué existe hoy (medido 02-10 sobre origin/main, para el tech-lead)

- **El clasificador personal**: `adapters/banking/src/synapse_adapter_banking/personal_categorizer.py` — taxonomía FIJA en código: `PERSONAL_CATEGORY_CODES` (frozenset de 16 códigos) con guarda de importación contra `CATEGORY_DISPLAY` (emoji+etiqueta), `_RULES` regex, y hook LLM solo al caer a `otros`. Esto es exactamente lo que la épica convierte en catálogo vivo.
- **El catálogo YA es una tabla**: `gestoria_accounting.expense_categories` (migración 0005: `tenant_id TEXT`, `code`, `label`, `color_oklch`, `pgc_accounts`, `display_order`, `is_active`, UNIQUE tenant+code), sembrada para `family` vía plantilla `expense_categories_template_personal` (migración 0039). La heurística en código es la que ignora la tabla; el trabajo es al revés: leer el catálogo y añadirle columnas.
- **Recurrencia YA existe (perfil empresa)**: tabla `gestoria_banking.movement_recurrence` (migración 0040, `is_recurring`/`is_payroll`, firma 3-way) + comando `banking.recurrence.detect` (`handlers.py:3771`, `lookback_months=12`) + su uso en `classify_movement` empresa (`handlers.py:3500` "patrón recurrente"). F3 = cablear esa máquina al perfil personal + el aviso de cambio de importe, no inventarla.
- **Reglas regex por concepto**: `gestoria_banking.movement_category_overrides` (UNIQUE tenant+pattern) ya alimenta el path empresa como guarda de alta confianza — es el destino natural de la promoción de patrones (F4) sin tabla nueva.
- **Corrección humana**: handler `banking.set_category` (`handlers.py:3601`) + callback Telegram `bc:cat:<uuid>:<code>` → `banking.family.set_category`; teclado estático en `cobros_report.py::build_category_keyboard` (sale de `askable_codes()` sobre el frozenset).
- **El total del briefing**: `cobros_report.py:77-78` — `total_out = sum(abs(amount) for r in gastos)` por puro signo del importe. Ahí entra `es_gasto_neto` (F2): hoy una liquidación de 2.420 € suma igual que un café.
- **Pipeline vivo**: PSD2 EnableBanking (`skirmbooks-banking-daily-sync` 06:40) → `gestoria_banking.bank_movements` → sweep `skirmbooks-personal-classifier-sweep` (07:00, `banking.classify_personal`, `handlers.py:3666`) → digest `skirmbooks-hogar-cobros-digest` (07:20) al grupo Hogar `-1003749364241`, topic "🏦 Banca". Deploy y CronJobs medidos activos por INFRA-351 el 01-10.
- **LLM**: alias `tooling` vía LiteLLM in-cluster, `allow_cloud_fallback=False`, allowlist `_ON_PREM_MODELS={tooling,smart,fast}` (`adapters/fiscal-validator/.../llm.py`) — patrón que 351 ya usa.

## Criterios de aceptación

- [ ] **C1 — `PRES.*` recurrente se clasifica solo como cuota de préstamo.** Tras el deploy y 1+ corridas del sweep, todo movimiento `PRES.%` reciente sale con la categoría nueva, sin pregunta:
  ```
  kubectl -n databases exec postgres-shared-2 -- psql -U postgres -d skirmbooks -c \
    "SELECT DISTINCT coalesce(category,'<null>') FROM gestoria_banking.bank_movements \
     WHERE tenant_id='family' AND concept ILIKE 'PRES.%' AND value_date >= now()-interval '30 days'"
  ```
  Esperado: una sola fila `cuota_prestamo` (sin `<null>` ni `otros`). Si en la ventana no hay PRES. reales, qa lo reproduce con un Job one-shot en ns `skirmshop` (patrón del C1 de INFRA-351): insertar 3 movimientos sintéticos `PRES.32687471025` `-409,39` en el día 1 de 3 meses consecutivos, correr `banking.recurrence.detect` + `banking.classify_personal`, y exigir `category='cuota_prestamo'` en los tres y **0 filas** en `gestoria_banking.movement_alert_log` para esos movimientos (no preguntó).
- [ ] **C2 — `T. VISA CLASSIC` no suma en el total de gastos y se marca como liquidación de tarjeta.** Dos partes:
  (a) catálogo:
  ```
  kubectl -n databases exec postgres-shared-2 -- psql -U postgres -d skirmbooks -c \
    "SELECT code, es_gasto_neto FROM gestoria_accounting.expense_categories \
     WHERE tenant_id='family' AND code IN ('liquidacion_tarjeta','traspaso_interno') ORDER BY code"
  ```
  Esperado: 2 filas con `es_gasto_neto = f`.
  (b) digest real: leer el último mensaje del topic "🏦 Banca" del grupo Hogar `-1003749364241` vía MCP `hermes` (`messages_read`) tras la corrida de las 07:20 UTC con un `T. VISA CLASSIC` en la ventana. Esperado: el total "🔴 Gastos:" NO incluye su importe, y la línea aparece con `💳 Liquidación tarjeta` (o la etiqueta que el digest elija) fuera del subtotal.
- [ ] **C3 — un concepto resuelto una vez por humano no vuelve a preguntar.** qa: (1) coge un movimiento familiar aún en `otros`, lo resuelve por el botón de Telegram; (2) inserta un movimiento hermano de la misma familia de concepto (Job one-shot, mismo prefijo normalizado), corre el sweep y comprueba:
  ```
  kubectl -n databases exec postgres-shared-2 -- psql -U postgres -d skirmbooks -c \
    "SELECT category, (SELECT count(*) FROM gestoria_banking.movement_alert_log a \
      WHERE a.movement_id = m.id) AS preguntas FROM gestoria_banking.bank_movements m \
     WHERE m.tenant_id='family' AND m.id='<uuid-hermano>'"
  ```
  Esperado: `category` = la elegida por el humano (o la categoría propuesta y aprobada que le dé el LLM a partir de su familia) y `preguntas = 0`.
- [ ] **C4 — catálogo extensible por aprobación humana (proponer → aprobar → usar).** Tras ejercitar el flujo de propuesta en producción (el LLM propone, el humano aprueba con el botón):
  ```
  kubectl -n databases exec postgres-shared-2 -- psql -U postgres -d skirmbooks -c \
    "SELECT code, label FROM gestoria_accounting.expense_categories \
     WHERE tenant_id='family' AND code NOT IN ('vivienda','suministros','alimentacion','transporte',\
      'salud','ocio','compras','educacion','seguros','impuestos','finanzas','suscripciones',\
      'ingresos_nomina','ingresos_otros','ahorro_inversion','otros') ORDER BY created_at"
  ```
  Esperado: ≥2 filas (al menos `cuota_prestamo` y `liquidacion_tarjeta`, creadas por el flujo de aprobación, no solo por la migración de seed — qa verifica además ≥1 fila en la tabla de propuestas con `status='aprobada'` y que el teclado de recategorización incluye la categoría nueva).
- [ ] **C5 — un recurrente cuyo importe cambia >10% avisa.** Job one-shot: mover el importe de un recurrente conocido un +15%, correr el digest. Esperado: el mensaje del topic "🏦 Banca" contiene una línea de aviso (⚠️) que nombra el concepto y el cambio de importe. Verifica: `messages_read` del grupo Hogar tras la corrida forzada.

## Restricciones

- **On-prem obligatorio**: solo alias `tooling` vía LiteLLM in-cluster, `allow_cloud_fallback=False` y allowlist `_ON_PREM_MODELS` intactos (texto bancario PSD2, cero egress). No tocar el residente LLM ni sus réplicas.
- **No tocar la ruta empresa**: `es_gasto_neto` nace con default `true` y `subtipo` NULL → tenants `skirmshop`/empresa y su reporting PGC siguen byte a byte igual. Todo cambio de `expense_categories` es aditivo y acotado a `tenant_id='family'`.
- **Contratos intocables**: routing keys `banking.family.classify_personal`/`banking.<tenant>.classify_personal`, `banking.set_category`, `banking.recurrence.detect`, callbacks `bc:cat:<uuid>:<code>`, tablas `movement_recurrence`, `movement_category_overrides`, `movement_alert_log` — no se renombran ni cambian de semántica; lo nuevo entra añadido (columnas nuevas, tabla nueva de propuestas, callbacks nuevos `bc:prop:*`).
- **Migraciones aditivas y reversibles** (columnas con default, tablas nuevas; nunca editar una aplicada), pasan el gate de grants.
- **No duplicar INFRA-351**: la tabla few-shot y el brain-search los aporta 351; si al arrancar 351 aún no los hubiera desplegado, S3 se apoya solo en `movement_category_overrides` (ya existe) y NO construye la tabla de ejemplos.
- **Fail-open como hoy**: si el LLM o la recurrencia fallan, el digest sale con la heurística; el aviso nunca deja de llegar.
- **PRs**: código a `skirmbooks-gestoria-src` → `main`; manifiestos a `k8s-skirmbooks-pocharlies` → `main`. Nunca push directo al tronco.

## Trabajo reciente (24 h)

- 02-10 07:31 (sesión Hermes `epica-sc-1576`, perfil cto): solo el evento de creación de INFRA-410 — nadie ha trabajado en ella.
- 01-10 18:51 (sesión pm `b3e9d1f2`): spec LISTO de **INFRA-351** sobre el MISMO repo y ficheros (`personal_categorizer.py`, `cobros_report.py`, sweep, digest). Qué le hace a este plan: el retrieval del corpus y la tabla few-shot (F1/F4 de esta épica) ya están asignados allí → recortados de este alcance; y nace la dependencia Blocks (esta épica arranca tras 351).
- Nada más en 24 h: radar sin sesiones vivas sobre `skirmbooks-gestoria-src`; últimos merges del repo (INFRA-364, CVEs, ARCHITECTURE.md) no tocan adapters/banking.

## Diseño

Diseñador: no — la única superficie son mensajes de Telegram y teclados inline sobre patrones que ya existen (línea de digest, botón de categoría, botón nuevo de aprobar/rechazar propuesta), sin pantalla nueva; mismo criterio que el spec de INFRA-351. qa revisa el copy en la validación.

## Historias previstas

1. **S1 — Catálogo vivo** (dueño: developer): migración con `es_gasto_neto` (default true) y `subtipo` en `expense_categories` + tabla `category_proposals`; seed `family` (`cuota_prestamo`, `liquidacion_tarjeta`, `traspaso_interno` con sus flags); `personal_categorizer` lee el catálogo de la tabla (el frozenset pasa a seed/fallback) y `askable_codes`/teclado salen del catálogo. Repo skirmbooks-gestoria-src.
2. **S2 — Salida del clasificador con subtipo y propuesta** (dueño: developer): prompt + JSON schema `categoria/subtipo/confianza/evidencia` (amplía la salida de 351 S1), heurística `_RULES` enriquecida con `PRES.*`→cuota_prestamo y `T. VISA`→liquidacion_tarjeta, y propuesta de categoría nueva cuando nada encaja (a `category_proposals`).
3. **S3 — Bucle proponer→aprobar→usar** (dueño: developer): botones `bc:prop:*` en el digest (aprobar/rechazar), aprobación → alta en `expense_categories` + promoción de regla regex a `movement_category_overrides`; correcciones por `set_category` alimentan los ejemplos de 351 (o overrides si 351 no está).
4. **S4 — Recurrencia del perfil personal** (dueño: developer): cablear `movement_recurrence`/`banking.recurrence.detect` al sweep personal, pre-categorizar recurrentes sin preguntar, y aviso ⚠️ en el digest si el importe de un recurrente varía >10%.
5. **S5 — Semántica contable en el digest** (dueño: developer): `total_out` filtra por `es_gasto_neto`; sección "Servicio de deuda" separada para cuotas de préstamo; líneas de liquidación/traspaso fuera del subtotal (`cobros_report.py`).
6. **S6 — GitOps** (dueño: devops): imagen nueva, config del CronJob de `recurrence.detect` para `family`, PR a `k8s-skirmbooks-pocharlies` `main`.
7. **S7 — Validación E2E** (dueño: qa): C1–C5 contra producción (incluye los replays sintéticos one-shot).

## Tamaño

M — 7 historias, 1 repo de código + 1 GitOps, una semana; la infraestructura de recurrencia y catálogo ya existe y se amplía.

## Dificultad

Dificultad: media — no hay servicio ni arquitectura nueva: el pipeline (PSD2 → sweep → classifier → digest → botón) corre en producción y la épica le amplía semántica sobre el mismo repo. Las migraciones son aditivas y reversibles (columnas con default, tablas nuevas) y la ruta empresa queda intacta por default; la recurrencia y las reglas regex ya existen y se cablean, no se diseñan. No es alta: nada irreversible, sin exposición nueva, sin cambio de contratos; no es baja porque hay que mirar qué existe (frozenset vs tabla, movement_recurrence vs heurística nueva) para no duplicar ni romper el perfil empresa.
