Rol: pm · Fecha: 2026-10-04T23:07:00Z · Sesión: 0f69fc74-559f-4899-b85e-42d51895ff90 · Estado: DIVIDIDA

# INFRA-546 — Brain de Leila

## Objetivo
Leila tiene su vault `leila` en el mismo servidor skirmshop-brain (brain.e-dani.com, ns `skirmshop-brain-prod`) con su WhatsApp, Telegram y correo, y las conversaciones de Open WebUI de Dani y Leila se indexan cada una en su vault (personal→personal, leila→leila), sin que lo de Leila sea legible desde `personal`.
Solapes: INFRA-364 (ventanas) ya corre en prod y no se rediseña; INFRA-487 (filtro por cuenta/espacio, sin spec) no se rehace: aquí solo se enruta por cuenta y se gatea por instancia; INFRA-473 (correo, DIVIDIDA) aporta el pipeline de buzones que la hija B reutiliza (el buzón de Leila, `lays84.mv@gmail.com`, es uno de sus cuatro).
Repo: skirmshop-brain-v2 (las hijas añaden whatsappmcp / k8s-socialmedia-pocharlies, skirmshop-brain-k8s y k8s-openclaw-qwen36-pocharlies)

## Criterios de aceptación
Se reparten en las hijas, cada criterio en una sola:
- [ ] S1 y S5 (vault `leila` en `/instances` y en la vista Brain, y privacidad entre vaults con los perfiles Hermes): INFRA-553. Comando de partida: `curl -s -H "api-key: $KEY" http://<ClusterIP aiops-qdrant>:6333/collections` filtrado por `leila_` → hoy `[]`; debe incluir `leila_documents`.
- [ ] S2 y S4 (WhatsApp, Telegram y Gmail de Leila → `leila`, con backfill): INFRA-554. Comando de partida: `kubectl get cm social-accounts -n whatsapp-mcp -o jsonpath='{.data.social-accounts\.json}'` → la cuenta `leila` hoy lleva `brainInstance: personal`; debe ser `leila`.
- [ ] S3 (Open WebUI por usuario): INFRA-555. Comando de partida: `/usr/bin/grep -rIn -i 'open-\?webui' --exclude-dir=.git --exclude-dir=.venv .` en skirmshop-brain-v2 → sin resultados hoy.
- [ ] S6 extremo a extremo (cierra el pm; lo mide `qa` al final): un conteo real por fuente (WhatsApp, Telegram, Gmail, Open WebUI) en `leila` y en `personal`, y una frase única de cada persona buscada en ambas instancias: aparece en la suya y en la otra devuelve 0 resultados. Todos los conteos se pegan con su comando.

## Restricciones
- Fuera de alcance: servidores nuevos, rediseñar la ingesta por ventanas, app de Leila, mezclar con claude-personal.
- Las ventanas de ingesta social (INFRA-364) están ya activas: `kubectl get cronjob brain-windows -n whatsapp-mcp` → `SUSPEND False` el 04-10, anterior a la fecha de reactivación prevista (05-10); S2 no espera.
- Seguridad: S5 crea la puerta entre vaults. El CTO de INFRA-553 dispatcha `security` antes del build.
- Premisa medida: los mensajes de Leila acaban hoy en terreno de Dani: `social-accounts` manda su WhatsApp a `brainInstance: personal` y `personal_documents` tiene 43 puntos con `account=leila` y sus correos de `lays84.mv@gmail.com`. Medida: 386115 puntos en `personal_documents`.
- Decisión sobre una novedad: `leila` ya está en `SUPPORTED_INSTANCES` y `PERSONAL_INSTANCES` del ConfigMap de prod, pero sin colecciones ni grafo, así que S1 es alta de datos y de puerta, no un servicio nuevo.
- Hasta que INFRA-553 cierre, nadie mueve datos de `personal` a `leila` (la puerta primero).
- Las tres hijas nacieron en To Do: el pm no tiene la transición a Backlog (el guard la denegó). B y C llevan Blocks de A, A puede arrancar ya.

## Trabajo reciente (24 h)
- brain-windows (INFRA-364) activo en prod, la épica sigue en Backlog en Jira pese a estar desplegado.
- INFRA-473 DIVIDIDA y su hija INFRA-478 en In Progress; INFRA-487 en Backlog sin spec (solo `nota-architect-pr72.md`).
- DGX-491 (vista Brain) en To Do con plan y notas del architect.
- Epic INFRA-546 sin adjuntos previos; no existía spec sembrado.

## Diseño
Diseñador: no — S1 solo añade una instancia a la vista Brain que DGX-491 ya diseña; el resto es ingesta sin interfaz.

## Historias previstas
- INFRA-553 (A) — Vault `leila` y puerta de privacidad: architect, developer, devops, qa.
- INFRA-554 (B) — Mensajes de Leila a su vault: developer, devops, qa. Bloqueada por A.
- INFRA-555 (C) — Open WebUI por usuario: architect, developer, devops, qa. Bloqueada por A.
- S6 final de la épica madre: qa y pm.

## Tamaño
L — cuatro repositorios y tres hijas.

## Dificultad
Dificultad: alta — crea el gate de acceso entre vaults de dos personas sobre un servicio compartido y mueve datos privados.

## Hijas
Orden: A primero; B y C en paralelo cuando A cierre.
1. INFRA-553 (A) — Vault leila y puerta de privacidad. Repo: skirmshop-brain-v2.
2. INFRA-554 (B) — Mensajes de Leila a su vault. Repo: whatsappmcp. Bloqueada por A.
3. INFRA-555 (C) — Open WebUI por usuario. Repo: skirmshop-brain-v2. Bloqueada por A.
