Rol: pm · Fecha: 2026-09-26T07:22:26+00:00 · Sesión: 80bad5c5-3906-4add-9b3e-0b749633b5af · Estado: LISTO

# SC-699 — Migrar los ExternalSecret del clúster de HashiCorp Vault a 1Password y retirar Vault

## Objetivo

Rematar la migración Vault→1Password, que está al 87 % medida hoy (211 de 245 ExternalSecret leen ya de `onepassword`): cerrar los 32 `vault-backend` restantes, los 2 PRs abiertos, el espejo 1Password→Vault y el único ES en error, y entregar el paquete de evidencia que precede al borrado de Vault. El borrado (fase 6) es irreversible y NO se ejecuta sin la consulta a Dani con el paquete cerrado — la cadena se detiene ahí.

Repo: k8s-infra-pocharlies (el trabajo restante cae mayormente en `dgx-infra` y `k8s-gitops-pocharlies`, y un ES drift en `k8s-agentgateway-pocharlies`; los tres están en esta épica — no se divide más: es el tail de una sola cadena secuencial). Épica hermana a no duplicar: **DGX-188** cerró la cuota 1Password fijando todos los ES a `refreshInterval: 24h` — no reintroducir la restricción de 6h de la descripción original.

## Estado medido hoy (26-09 ~07:20Z, base del plan — no volver a descubrirlo)

- 245 ES vivos: **211 `onepassword` / 32 `vault-backend` / 1 `kubernetes-cnpg` / 1 kubernetes (hermes, fuera de alcance)**. 1 solo ES en `SecretSyncedError`: `litellm/litellm-alibaba-2` (store onepassword, pide el item `alibaba-model-studio-2` — **verificado hoy por SA: no existe** entre los 187 items del vault `k8s-pocharlies`; su hermano `alibaba-model-studio` sí, con campos username/password/notesPlain, y está Ready).
- Los 32 `vault-backend` = **27 del guion del operador** (`huerfanos/`, sin manifiesto ArgoCD) + `synapse/synapse-secrets` (muere con Vault) + **4 de deriva**: `chat/chat-agentgateway-client` (PR dgx-infra **#410 abierto**, bloqueado por siembra), `control-nexus/opencode-x86-server-auth`, `llm/voicelab-amqp` (los dos bajo ArgoCD en `dgx-infra`, sin PR aún) y **`cto-office-mcp/cto-office-opencode-auth`, nacido hoy 06:46Z** bajo la app `agentgateway-mcp` (repo `k8s-agentgateway-pocharlies`, tronco `main`), creado por la sesión CTO VIVA de SC-320 (proceso `a5814f9f` activo ahora). Lee `secret/opencode/x86/server_password` del KV — la misma ruta que el drift de control-nexus — y está Ready contra vault-backend.
- **2 PRs abiertos**: k8s-infra **#144** (retiro del espejo 1Password→Vault; MERGEABLE, su único bloqueante — el lector `hermes/harbor-runtime-pull` vía k8s-openclaw-qwen36 **#334** — está **MERGED**, el camino está libre) y dgx-infra **#410** (no fusionar hasta que el campo `chat_agentgateway_client_secret` exista en el item `agentgateway-prod` de 1Password — **verificado hoy por SA: el campo no está** en la lista de 17 field-ids del item; verificar la siembra con un ES de un solo uso antes de asumir nada).
- **El espejo sigue vivo**: ns `onepassword-sync` con 4 PushSecret `Synced` escribiendo en Vault (`infra-harbor-k8s-runtime-pull`, `minio-backup-user`, `skirmshop-catalog-api`, `skirmshop-drive-s3-app`). `dgx-dashboard-env-to-vault` sigue en git (`dgx-infra/k8s/control-nexus-backend/dgx-dashboard-env-eso.yaml`) sin desplegar → **retirar** (decisión del CTO 11-09).
- App `vault` Synced/Healthy, ns `vault` Active (129 d). Carga 1Password **cerrada** (106/106 items + 27 sobrantes del KV, verify idéntico). Campos vacíos resueltos (`op item edit` admite vacío). OpenClaw **descomisionado** → el bloque de 18 ES Helm de openclaw está **obsoleto** (no planificarlo).
- Herramientas y paquetes listos en `~/k8s/_ops/vault-to-1password/`: `inventory.py`, `hashes.py`, `rewrite.py`, `migrate.py`; guion `huerfanos/aplicar.sh` (19 + 5 C-own); `fase6-evidencia/OPERADOR-FINAL.md` (ítems a–g) y `CHECKLIST-FASE6.md` (orden exacto residual). Baseline de hashes: `artifacts/after-2026-09-18.tsv` (802 claves).
- **Anomalía medida hoy**: `artifacts/values.json` (1487 B, 18-09) **sigue en disco** pese a que el spec anterior decía `shred` hecho. No se ha leído su contenido. Debe `shred -u` en cuanto las siembras pendientes estén cargadas (historia 6).
- Manos del operador pendientes (ningún rol de la cadena puede escribirlas): snapshot raft (ítem a), guion de huérfanos (b), siembras 1Password (ítem c: `alibaba-model-studio-2` y `agentgateway-prod/chat_agentgateway_client_secret`), ns `onepassword-sync` (g), rotación Cloudflare `cfut_…` (e — **PARA SECURITY**), confirmación espejo Skirmshop (f), push rama `sc498-aurora-retiro-vault-runtime` + `gh pr edit 24`.

## Criterios de aceptación

- [ ] **C1 — Solo `synapse-secrets` lee de Vault.** `kubectl get es -A -o jsonpath='{range .items[?(@.spec.secretStoreRef.name=="vault-backend")]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}'` → exactamente una línea: `synapse/synapse-secrets`. Hoy: 32 líneas.
- [ ] **C2 — Cero errores de sincronización.** `kubectl get es -A -o json | python3 -c "import json,sys; d=json.load(sys.stdin); print(sum(1 for i in d['items'] for c in i['status'].get('conditions',[]) if c['type']=='Ready' and c['status']!='True'))"` → `0`. Hoy: `1` (litellm/litellm-alibaba-2).
- [ ] **C3 — Espejo retirado.** `kubectl get ns onepassword-sync` → `Error from server (NotFound)` y `kubectl get pushsecret,clusterpushsecret -A` → `No resources found`. Hoy: ns Active con 4 PushSecret Synced.
- [ ] **C4 — Ningún valor cambió.** `cd ~/k8s/_ops/vault-to-1password && ./hashes.py artifacts/after-final.tsv && diff artifacts/after-2026-09-18.tsv artifacts/after-final.tsv` → sin pares de misma clave con sha256 distinto (solo líneas NEW/GONE justificadas una por una; p. ej. la rotación Cloudflare es GONE/NEW esperado y se nombra).
- [ ] **C5 — Vault borrado (solo tras el OK de Dani).** `kubectl get ns vault` → NotFound, `kubectl get app -n argocd vault` → NotFound, `kubectl get clustersecretstore vault-backend` → NotFound. Y `kubectl get es -A` sigue en `0` errores tras el cascade (ningún ES vivo quedó apuntando a nada).
- [ ] **C6 — Documentación alineada.** `grep -il 'unseal\|desellar' ~/k8s/k8s-gitops-pocharlies/docs/runbook-vault-unseal.md ~/k8s/k8s-gitops-pocharlies/docs/runbook-restore-velero.md ~/k8s/k8s-gitops-pocharlies/docs/runbook-restore-etcd-snapshot.md ~/k8s/dgx-infra/CLAUDE.md` → ninguno manda desellar un Vault que ya no existe (borrados o reescritos con nota histórica); y el item `k3s • Vault Unseal Keys (CRITICAL)` ya no está en 1Password (`op item get` del operador → not found).
- [ ] **C7 — Paquete de evidencia cerrado antes de C5.** Existe `fase6-evidencia/DECISIONES-FASE6.md` con una línea por cada uno de los 8 "no sé" del KV (`artifacts/kv-tree-unclassified-resuelto-2026-09-11.tsv`) + confirmación del espejo Skirmshop, y `SNAPSHOT.md` con ruta + sha256 + tamaño de un snapshot raft **fuera del clúster** (`sha256sum ~/backups/vault-raft-*.snap` → hash, fichero >10 MB). La consulta a Dani se emite con este paquete adjunto. Y `artifacts/values.json` ya no existe (`ls` → No such file).
- [ ] **C8 — Git limpio de PushSecret a Vault.** `grep -rn 'vault' ~/k8s/dgx-infra/k8s --include='*.yaml' | grep -i pushsecret` → vacío (el fichero `dgx-dashboard-env-eso.yaml` retirado por PR).

## Restricciones

- **Fase 6 (C5/C6) NO se ejecuta sin respuesta de Dani** a la consulta con el paquete C7. Nunca `kubectl delete` la Application `vault` (el finalizer vuelve y cascadea): es `argocd app delete vault --cascade`, deliberado.
- **Cuota 1Password Families**: 1.000 peticiones/día y 100 escrituras/hora para toda la cuenta. Las siembras (ítem c: `alibaba-model-studio-2` + campo de `agentgateway-prod`) son escrituras del operador; agruparlas en una ventana.
- **`refreshInterval: 24h` en todo ES nuevo o tocado** — lo fijó DGX-188 (épica hermana, Dueña de la cuota); la restricción original de 6h está MUERTA, no reintroducirla.
- Siempre PR contra el tronco que lee ArgoCD (`dgx-infra` → `master`, `k8s-gitops-pocharlies` → `deploy/prod`, `k8s-agentgateway-pocharlies` → `main` verificado hoy, el resto desde `.spec.source.targetRevision`).
- **Sesión viva SC-320** (proceso `a5814f9f`, épica SC-320 en In Progress) creó hoy el ES drift de cto-office-mcp apuntando a vault-backend. Avisarla (comentario en SC-320 o `agent-sessions`) de que los ES nuevos van a `onepassword` y que su ES entra en la barrida — no duplicar su trabajo ni tocar el suyo.
- **DO-NOT-APPLY** `huerfanos/migrados/skirmshop__shared-postgres-superuser.yaml.rej` (store vivo `kubernetes-cnpg`, contraseña cambiada a propósito). Los 36 ficheros del piloto **nunca a mano** — convergen vía sus plantillas (ya fusionadas).
- No tocar los 2 ES del provider kubernetes (`hermes-studio-telegram-token`, cnpg) — fuera de alcance.
- `synapse/synapse-secrets` es la única excepción viva a C1: muere con el cascade de la fase 6.
- `values.json` (1487 B, aún en disco hoy): no leerlo a un transcript, no commitearlo, `shred -u` en cuanto las siembras estén cargadas (dentro de C7). No regenerarlo salvo siembra puntual, y entonces 0600 + `shred -u` al acabar.
- Rotación del token Cloudflare `cfut_…` (volcado a un transcript el 11-09): lo decide y ejecuta el rol **security**, no el developer.
- Las manos del operador (listas en `OPERADOR-FINAL.md`) se piden como tales con comando exacto; ningún rol de la cadena aplica sobre objetos vivos.
- SA token de 1Password para comprobaciones de existencia: `~/k8s/_ops/vault-to-1password/.sa-token` (0600) — vale listar títulos y field-ids; nunca volcar valores.

## Trabajo reciente (24 h)

- 26-09 ~03:38Z · Sesión `6dc5a2d9` (PM) reescribió el spec desde el estado del clúster (LISTO, 8 criterios, 7 historias) — este spec parte del suyo.
- 26-09 ~05:26Z · Sesión `aa6f8a0d` (PM) re-verificó sin deriva (211/31/1/1) y re-adjuntó. **Esta sesión (`80bad5c5`, 07:20Z) encuentra +1 de deriva**: `cto-office-mcp/cto-office-opencode-auth` creado 06:46Z por la sesión CTO viva de SC-320 → C1 pasa de 31 a 32, la barrida de deriva pasa de 2 a 3 ES en 2 repos, y se añade el aviso a SC-320.
- 26-09 · Medido con el SA de 1Password: `alibaba-model-studio-2` **no existe** (historia 1 sigue needing siembra) y `agentgateway-prod` **no tiene** el campo `chat_agentgateway_client_secret` (dgx-infra #410 sigue gated). PRs #144 (MERGEABLE) y #410 siguen OPEN; espejo vivo con 4 PushSecret Synced.
- 26-09 · **Anomalía**: `values.json` sigue en disco pese al shred declarado en el spec anterior → se incorpora a C7.
- 18-09→26-09 (contexto ya absorbido por el spec anterior): k8s-openclaw-qwen36 #334 fusionado (libera el #144), nacieron los drifts de dgx-infra, DGX-188 cerró la cuota a 24h.

## Diseño

Diseñador: no — no hay ninguna interfaz: todo el trabajo es manifiestos, objetos de clúster y 1Password.

## Historias previstas

1. **Arreglar `litellm-alibaba-2`** (dueño: devops) — sembrar el item `alibaba-model-studio-2` en el vault `k8s-pocharlies` (mano del operador, 1 escritura, valor del segundo account Alibaba que creó el ES) → C2.
2. **Fusionar el retiro del espejo** (dueño: devops) — re-verificar k8s-infra #144 (MERGEABLE, bloqueante #334 merged), merge + sync, y mano del operador `kubectl delete ns onepassword-sync` (ítem g) → C3.
3. **Desbloquear y fusionar dgx-infra #410** (dueño: devops) — campo ausente verificado hoy: siembra de `agentgateway-prod/chat_agentgateway_client_secret` por el operador (ítem c), comprobar con un ES de un solo uso, entonces merge + sync → parte de C1.
4. **Barrida de deriva (3 ES, 2 repos)** (dueño: developer) — PR con `rewrite.py` en `dgx-infra` para `control-nexus/opencode-x86-server-auth` y `llm/voicelab-amqp` (ítems + 24h) y retirar `dgx-dashboard-env-to-vault` del git; PR en `k8s-agentgateway-pocharlies` (main) para `cto-office-opencode-auth`; aviso a SC-320 de que sus ES nuevos van a `onepassword` → parte de C1 y C8.
5. **Guion del operador + seguridad** (dueña: devops prepara, aplica el operador; rotación Cloudflare: security) — `huerfanos/aplicar.sh` (19 + 5 C-own), confirmación espejo Skirmshop (f), rotación `cfut_…` (e), push rama aurora + `gh pr edit 24` → C1 casi completo.
6. **Paquete de evidencia y consulta a Dani** (dueño: devops, la emite el CTO) — re-run `inventory.py` + `hashes.py` (C4), snapshot raft final (a), `DECISIONES-FASE6.md` con los 8 "no sé" (C7), `shred -u artifacts/values.json` (C7), y la única consulta a Dani con todo adjunto. **La cadena se detiene aquí.**
7. **Fase 6 — borrar Vault** (dueño: devops; SOLO tras el OK de Dani) — borrar CSS `vault-backend`, quitar `infra/vault.yaml` + el `ignoreDifferences` del caBundle del kustomization raíz de k8s-gitops (`deploy/prod`), `argocd app delete vault --cascade`, los 3 runbooks + `CLAUDE.md`, retirar el item de unseal keys → C5, C6.

## Tamaño

M — el grueso (inventariado, carga a 1Password, reescritura de 105 ficheros, 26 repos, paquetes) está hecho y medido; queda el tail secuencial de 7 historias cortas y un paso irreversible gated. No se divide: cada resto es un eslabón de la misma cadena y partirla solo añade coordinación.

## Dificultad

Dificultad: alta — toca credenciales y secretos de todo el clúster, más de un repo (k8s-infra, dgx-infra, k8s-gitops, k8s-agentgateway), un paso irreversible (borrado de Vault con PVC y auto-unseal), y la épica ya se atascó dos veces (sesiones CTO soltadas, 17-09 y 26-09).
