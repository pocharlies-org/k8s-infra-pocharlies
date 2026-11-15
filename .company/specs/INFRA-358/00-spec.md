Rol: pm · Fecha: 2026-10-01T22:10:00Z · Sesión: cd8bfb36-11f6-4166-b4c3-10845df8ace4 · Estado: LISTO

## Objetivo

Que el conector `workspace` MCP (AgentGateway) exponga `calendar_update_event`, `calendar_delete_event` y `calendar_get_event` además de las ya existentes `calendar_list_events` / `calendar_create_event`, para que un agente resuelva duplicados y correcciones de eventos sin salir de MCP ni pedir borrado manual en la UI de Google. No hay solapes: INFRA-296 (`drive_create_file`) es otra tool del mismo repo y no cubre esto; verificado hoy que `origin/main` de `k8s-agentgateway-pocharlies` tiene 0 funciones update/delete/get y el pod servido tampoco.

Repo: k8s-agentgateway-pocharlies

Nota de repo: el código NO está en k8s-infra-pocharlies. Vive en `/home/dibanez/k8s/k8s-agentgateway-pocharlies`, rama trunk = `main`, archivo `backends/workspace/gws-shim.py` (MCP stdio self-owned, serverInfo "google-workspace" 0.2.0). El despliegue es el namespace `workspace-mcp` (deploy/workspace-mcp, imagen mcp-stdio-pool-bridge v0.1.9) con el código servido desde el configmap `gws-shim-src` vía `configMapGenerator` (regeneración documentada en `backends/workspace/README.md:51-52`).

## Criterios de aceptación

- [ ] 1. Tras el deploy, `tools/list` del endpoint `/workspace` vivo expone las 3 tools nuevas. Comando (desde el x86, `KUBECONFIG=/home/dibanez/.kube/config` no hace falta para el proxy):
  ```
  SID=$(curl -s -D - -o /dev/null -X POST http://127.0.0.1:8790/workspace \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","clientInfo":{"name":"qa","version":"0"},"capabilities":{}}}' \
    | tr -d '\r' | awk -F': ' '/^mcp-session-id/{print $2}')
  curl -s -X POST http://127.0.0.1:8790/workspace \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -H "mcp-session-id: $SID" \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
    | grep -oE 'calendar_(update|delete|get)_event' | sort -u
  ```
  Salida esperada: exactamente 3 líneas: `calendar_delete_event`, `calendar_get_event`, `calendar_update_event`.

- [ ] 2. El configmap `gws-shim-src` desplegado contiene las 3 funciones nuevas. Comando:
  ```
  kubectl get cm -n workspace-mcp gws-shim-src -o jsonpath='{.data.gws-shim\.py}' | grep -cE 'def calendar_(update|delete|get)_event'
  ```
  Salida esperada: `3`.

- [ ] 3. E2e update: crear un evento de prueba (cuenta `pocharlies@gmail.com`, título `INFRA-358 test <fecha>`), actualizarle summary y hora con `calendar_update_event`, y comprobar con `calendar_get_event` y `calendar_list_events` que ambos cambios se reflejan. Comando: flujo de tools MCP contra `http://127.0.0.1:8790/workspace` (initialize → tools/call), o vía las tools `mcp__google-workspace__*` de una sesión de la compañía. Salida esperada: el get/list devuelve el summary nuevo y la hora nueva; el `event_id` no cambia.

- [ ] 4. E2e delete: borrar por `event_id` el evento de prueba con `calendar_delete_event` y comprobar que desaparece. Salida esperada: la respuesta del delete incluye el resumen del evento borrado (verificación visible), y `calendar_get_event` posterior responde error/no-encontrado y `calendar_list_events` ya no lo muestra.

- [ ] 5. `calendar_delete_event` sin `event_id` devuelve error claro y no borra nada (sin hard-delete silencioso). Comando: tools/call `calendar_delete_event` con solo `user_google_email` (u otros campos) y sin `event_id`. Salida esperada: `isError` / mensaje de error que nombra `event_id` como obligatorio; ningún evento desaparece (comprobable listando antes y después sobre el calendario de prueba).

- [ ] 6. El registro de tools sigue siendo consistente con el checker de CI. Comando (en `/home/dibanez/k8s/k8s-agentgateway-pocharlies`):
  ```
  python3 scripts/check-mcp-coverage.py
  ```
  Salida esperada: exit 0, sin avisos de tools sin cubrir (las 3 nuevas registradas en la lista workspace ~línea 432 y en el mapa `GATEWAY_WRITE` ~línea 793 — update/delete/get como operaciones de escritura según el checker).

## Restricciones

- No añadir scopes OAuth nuevos: se usan los ya concedidos `CAL_RO` (calendar.readonly, línea 276) y `CAL_RW` (calendar.events, línea 277). `calendar_get_event` puede ir con CAL_RO o CAL_RW; update y delete con CAL_RW, igual que create.
- Superficie aditiva: `calendar_list_events` y `calendar_create_event` no cambian de nombre, firma ni comportamiento (contrato consumido por los roles).
- Semántica `calendar_id` por defecto `primary`, idéntica a create/list. Cuentas: el mismo enum ya configurado (info@e-dani.com, me@e-dani.com, lays84.mv@gmail.com, pocharlies@gmail.com, daniel.ibanez@alphalinkcrossfit.com) con identity binding ON — no tocar `identity-bindings.yaml`.
- `calendar_delete_event` exige `event_id` exacto (sin borrado por query/heurística) y devuelve el resumen del evento borrado. Documentar en la descripción de la tool el flujo listar-primero → confirmar → borrar.
- Las pruebas e2e usan SIEMPRE un evento de prueba creado por la propia prueba (cuenta `pocharlies@gmail.com`), nunca eventos reales; la prueba termina borrándolo.
- Despliegue por GitOps: PR a `main` de k8s-agentgateway-pocharlies con el configmap `gws-shim-src` regenerado (README.md:51-52); nunca `kubectl apply` suelto del shim.
- No hay interfaz de usuario: son tools MCP.

## Trabajo reciente (24 h)

Nada que afecte: verificado por el analista (2026-10-01) — sesiones vivas sin relación con el área, brain sin hallazgos del área en 24 h, y el repo tuvo commits recientes de social/contratos pero ninguno en `backends/workspace`. Comprobado en esta sesión: `git show origin/main:backends/workspace/gws-shim.py | grep -cE 'def calendar_(update|delete|get)_event'` → `0`. Nota: la skill `google-calendar-ops` NO está en el x86 (buscar en el Mac/Hogar al actualizarla).

## Diseño

Diseñador: no — no hay interfaz, son tools MCP (schema de argumentos y descripción de tool como única superficie visible).

## Historias previstas

- S1 — developer: implementar `calendar_get_event`, `calendar_update_event` y `calendar_delete_event` en `backends/workspace/gws-shim.py` (handlers, registro en dict de tools ~1325-1381, `TOOL_SCOPES` ~1413, semántica `calendar_id=primary`, salvaguardas del delete), actualizar `scripts/check-mcp-coverage.py` (lista workspace + `GATEWAY_WRITE`) y regenerar el configmap `gws-shim-src`. Repo k8s-agentgateway-pocharlies, PR → main.
- S2 — developer: desplegar (merge a main → ArgoCD `workspace-mcp`) y ejecutar el e2e real update+delete sobre evento de prueba (criterios 1-5 en vivo).
- S3 — qa: verificar criterios 1-6 con evidencia pegada (comando + salida real, incluido el caso de error del criterio 5).
- S4 — developer: actualizar la skill `google-calendar-ops` (retirar "No delete/update tool — anything created can only be removed by hand" y documentar el flujo listar → update/delete por id). Buscar la skill en el Mac/Hogar, no está en el x86.

## Dificultad

Dificultad: media — funcionalidad nueva con lógica en un solo repo, sin decisión de arquitectura, usando el scope OAuth calendar.events YA concedido; hay que mirar qué existe antes de escribir para no duplicar.
