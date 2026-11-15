Rol: devops · Fecha: 2026-09-17 · Sesión: a5b648df-3f6e-444f-aac4-e582baafc2a8 · Estado: LISTO

# 50-entrega — Forense deriva 17-09

## Qué se hizo

Investigación forense de solo lectura (kubectl get, git show/log, diff de volcados, byte-comparison de specs) de los 69 ES vivos con store vault-backend. Sin cambios en cluster ni en repos.

## Veredicto

Hipótesis del tech-lead (reaplicación de huerfanos/vivo/) REFUTADA. Clasificación de los 69:

- **36 — cubo A: piloto CES intencional en tronco.** Hijos de los 5 ClusterExternalSecret (harbor-runtime-pull x27, harbor-runtime-pull-bootstrap x2, catalog-api-client x3, catalog-api-server x1, skirmshop-drive-s3-app x3). Vuelta a vault-backend commitida en tronco a propósito (k8s-infra main a3f79e7 "los 5 CES piloto leen de vault-backend (DGX-127)", 17-09 01:04; drive-mirror main 9fc825d DGX-130, 17-09 02:48), apps Argo Synced. El spec vivo lee claves `op/...` (el piloto copia 1Password a la ruta vault `op/...`, DGX-126) y NO coincide con vivo/ (que tiene las rutas `secret/...`); sin anotación last-applied. El creationTimestamp viejo se explica porque el controlador actualiza el ES hijo in situ al cambiar el CES padre — nunca se borraron.
- **28 — cubo D: pendientes del guion, sin cambio alguno 12-09→17-09.** Los del doc post-merge §4b (19 del paquete, spec idéntica a vivo/ porque nunca se migraron; 5 C-own con trunk ya en onepassword; 3 apps Argo sin autosync) + synapse-secrets (ruling). Cero deriva.
- **5 — cubo E: nuevos post-migración con manifiesto vault-backend en tronco.** company-metrics-mcp-secrets (agentgateway main, SC-252 12-09), hermes-secrets (openclaw deploy/prod), chat-agentgateway-keycloak-bootstrap (k8s-infra, pre-migración, desplegado 17-09), logical-dumps-minio en opencode (dgx-infra master, SC-70 12-09 — la migración #327 no tocó el ES embebido en cronjob-opencode-sqlite.yaml), messages/harbor-runtime-pull (dgx-messages main — patrón del piloto documentado en el propio fichero, no es deriva).
- **Cubos 1 (revert), 2 (revisión vieja), 3 (reaplicación as-is): vacíos.** Ningún trunk revertido (git log 12→17 sin reverts), ninguna app sincronizada a revisión vieja (todas Synced a HEAD), 0 ES con last-applied cambiaron LA/spec en la ventana, 0 flippeados tienen last-applied.

## Paquete huerfanos

vivo/ 78 ficheros todos vault-backend, migrados/ 58 todos onepassword — íntegros. Ninguno se aplicó en la ventana.

## Cómo verificarlo

- Evidencia completa: /home/dibanez/k8s/_ops/vault-to-1password/fase6-evidencia/forense-2026-09-17.md (aritmética 49→69 cerrada exacta, tabla por cubo, rastreos git).
- Reproducible: diff de raw-externalsecrets-2026-09-12.yaml contra `kubectl get externalsecret -A -o yaml` (39 flip, 12 nuevos, 20 borrados); `git -C k8s-infra-pocharlies show origin/main:platform/external-secrets/runtime-credentials.yaml` (vault-backend en trunk); `git -C k8s-skirmshop-drive-mirror-pocharlies log -1 origin/main -- k8s/s3-app-externalsecret.yaml`.

## Checklist 00-spec

- [x] Los 69 clasificados con evidencia (clasificacion.json + tabla en forense-2026-09-17.md).
- [x] Hipótesis refutada con evidencia (byte-comparison, LA annotations, git log, revisiones Argo).
- [x] Integridad del paquete verificada (78 vault / 58 op).
- [x] forense-2026-09-17.md escrito.

## Nota para el CTO

El criterio "0 vault-backend salvo ruling" choca con el piloto DGX-126/127/130 (trunk legítimo, apps Synced, 36 ES + mensajes). Decidir si el piloto convive con SC-490 o se revierte es decisión del CTO/DGX, no técnica.
