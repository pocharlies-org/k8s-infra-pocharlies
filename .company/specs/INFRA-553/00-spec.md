Rol: pm · Fecha: 2026-10-04T23:07:00Z · Sesión: 0f69fc74-559f-4899-b85e-42d51895ff90 · Estado: LISTO

# INFRA-553 — Vault leila en el brain y puerta de privacidad (hija A de INFRA-546)

## Objetivo
La instancia `leila` existe de verdad en el brain de prod (colecciones Qdrant y grafo FalkorDB propios, visible en `/instances` y en la vista Brain de DGX-491) y ningún agente ni persona con instancia personal puede leerla. No rehace el modelo de espacios por cuenta de INFRA-487.
Repo: skirmshop-brain-v2 (código y puerta); el ConfigMap/overlay de prod vive en skirmshop-brain-k8s (`apps/brain/overlays/prod`, tronco main); el enrutado de perfiles Hermes en k8s-openclaw-qwen36-pocharlies (`helm/hermes/values.yaml`, tronco deploy/prod).

## Criterios de aceptación
Medido hoy: `leila` YA está en `SUPPORTED_INSTANCES` y `PERSONAL_INSTANCES` del ConfigMap `skirmshop-brain-config`, pero no existe ninguna colección `leila_*` en Qdrant y `personal_documents` tiene 386115 puntos, de ellos 43 con `account=leila`.
- [ ] Colecciones propias. `KEY=$(kubectl get secret skirmshop-brain-secrets -n skirmshop-brain-prod -o jsonpath='{.data.QDRANT_API_KEY}' | base64 -d); curl -s -H "api-key: $KEY" http://$(kubectl get svc aiops-qdrant -n aiops -o jsonpath='{.spec.clusterIP}'):6333/collections | python3 -c "import json,sys;print(sorted(c['name'] for c in json.load(sys.stdin)['result']['collections'] if c['name'].startswith('leila_')))"` → incluye al menos `leila_documents` y `leila_concepts` (hoy: lista vacía).
- [ ] Grafo propio. Por redis.from_url(FALKORDB_URL) en un pod del brain (lo ejecuta devops/qa; pm no tiene exec): `GRAPH.LIST` contiene `leila_v2` (patrón `instance_id`+`_v2` de `src/config.py`, igual que `claude_personal_v2`).
- [ ] Catálogo. `curl -s -H "X-API-Key: $BRAIN_KEY" https://brain.e-dani.com/instances` (la ruta exacta la fija el plan del architect) lista `leila` con su recuento de documentos (0 antes de la hija B).
- [ ] Vista Brain. La vista Brain del dashboard (DGX-491) muestra la fila `leila` sin cambiar el diseño de la vista: captura de qa; si DGX-491 no está desplegada, el criterio pasa a «`/instances` responde con `leila` y la captura queda como deuda con nombre».
- [ ] Puerta entre vaults. Con el email de Leila (cabecera `X-Email` de oauth2-proxy), `POST /search` sobre `instance=personal` → 403; sobre `instance=leila` → 200. Con `me@e-dani.com` (en `OPERATOR_EMAILS`), `instance=leila` → 403 salvo decisión del architect registrada en la historia; el resultado real se pega en `50-entrega.md`. La puerta se escribe en `src/auth.py` (hoy las instancias personales las abre `OPERATOR_EMAILS=me@e-dani.com`: no hay allowlist por instancia).
- [ ] Perfiles Hermes. `/usr/bin/grep -n -A12 'instanceByProfile' helm/hermes/values.yaml` (en k8s-openclaw-qwen36-pocharlies, trunk) → ningún perfil apunta a `leila` salvo `secretaria-leila`, y `hogar`, `jarvis`, `secretaria`, `secretaria-dani`, `secretaria-casa`, `studio` siguen en `personal`. Un recall de uno de ellos sobre un dato sembrado solo en `leila` devuelve 0 resultados.
- [ ] Plan previo. `nota-architect-plan.md` adjunto a esta épica antes de tocar código, con la decisión instancia-nueva-en-servicio-multitenant frente a configuración del catálogo.

## Restricciones
- Servidor único skirmshop-brain; sin servidores nuevos ni mezclar con claude-personal.
- Seguridad (CTO dispatcha `security` antes del build): PARA SECURITY: ¿la puerta por email por instancia es suficiente cuando `personal` y `leila` comparten el mismo despliegue y la misma api-key de máquina, o hay que quitar `leila` del alcance de la clave compartida del dashboard?
- Cambiar el ConfigMap de prod: PR contra main de skirmshop-brain-k8s; nunca kubectl a mano.
- No rediseñar el modelo de espacios de INFRA-487 ni la ingesta por ventanas de INFRA-364.

## Trabajo reciente (24 h)
- INFRA-364 ya corre en prod: CronJob `whatsapp-mcp/brain-windows` activo cada 30 min (no suspendido; en 3d23h).
- INFRA-487 y DGX-491 sin cambios; DGX-491 tiene plan y revisiones de architect (PR 71, 940, 941).
- INFRA-478 (hija de INFRA-473) en In Progress.

## Diseño
Diseñador: no — solo añade una fila/instancia a la vista Brain que DGX-491 ya diseña.

## Historias previstas
- Plan de arquitectura: instancia nueva frente a catálogo (dueño: architect).
- Alta de la instancia `leila`: colecciones, grafo y `/instances` (dueño: developer).
- Puerta de acceso por instancia en `src/auth.py` (dueño: developer; revisión: security).
- Enrutado de perfiles Hermes y ConfigMap de prod (dueño: devops).
- Verificación de no-fuga entre vaults (dueño: qa).

## Tamaño
M

## Dificultad
Dificultad: alta — crea el gate de acceso entre vaults de dos personas sobre un servicio compartido y un fallo expone mensajes privados.
