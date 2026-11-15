Rol: pm · Fecha: 2026-10-09T00:45:00Z · Sesión: enc-analista-DGX-188-2807ec3d · Estado: LISTO

# DGX-188 — Programa cuota 1Password: firmar la lectura (a) ya verde, migrar los 15 PushSecret y cerrar la casa

## Objetivo

El suelo estructural ya no existe: con 1Password Connect (INFRA-511/523) los ExternalSecret no gastan cuota y la métrica lleva meses en success≈26-32/24h (umbral 250) con error=0, medido hoy. Queda la lectura formal de (a) con su 70-qa.md (un curl, en el turno), migrar los 15 `PushSecret` de hermes que aún gastan la cuota por el store SDK cortando la deriva de nuevos, y el cierre documental de los hijos.

Repo: k8s-infra-pocharlies (store SDK y PushSecrets en `platform/external-secrets/`, tronco `main`). Solapes declarados: INFRA-511 (Connect, To Do con spec LISTO — entregó el suelo bajo, no duplicar), INFRA-533 (PR 243 abierta: store SDK a la última wave — no pisarla), DGX-505/506/507 (OnChange + detector + regla única, Done 08-10), SC-699/SC-490 (no se pisa ni revierte nada).

## Desatasco

Por qué se atascó esta vez y qué cambia:

1. **El CTO (08-10 14:20-15:10Z) se quedó esperando un fichero de terminación que nadie escribía:** lanzó la lectura formal (a) como trabajo en segundo plano (`scratchpad/p3c.py`, `p3c-medida.py`) y se puso a vigilar `p3c.log.done`, que el job nunca tocó — murió o ni arrancó. El despertador lo encontró 6 h después en lo mismo y devolvió la épica. **Qué cambia:** la lectura (a) es un `curl` de un segundo — se ejecuta SINCRÓNICO en el turno, nunca como job en segundo plano con marca de `.done`. Prohibido esperar ficheros de terminación en esta épica.
2. **Dato nuevo que cambia la historia 2:** los PushSecret sobre el store SDK son 15, no 13 — desde el último barrido nacieron dos MÁS (`hermes-api-key-main`, `hermes-api-key-qa-pagos`) apuntando otra vez al SDK. No es solo migrar: hay que cortar la deriva (el patrón que crea PushSecret nuevos los está poniendo en el store SDK).
3. **Lo que ya NO existe (no repetir):** DGX-505/506/507 Done el 08-10 (OnChange, detector, regla única — PR 266 fusionada). La premisa del suelo ya la entregó Connect; la lectura lleva verde desde el 05-10. Regla fijada: una ventana de lectura se toma en cuanto se abre, y se juzga por métrica + sonda medidas, nunca por proyección.

## Criterios de aceptación

- [ ] (a) Suelo ESO: `success` < 250 llamadas/24h sostenido 48 h, controller sin reinicio en la ventana, con desglose por `status` y `call`, firmado en 70-qa.md.
      Comando: `curl -sG "http://10.43.33.43:8428/api/v1/query" --data-urlencode 'query=sum by (call,status) (increase(externalsecret_provider_api_calls_count{provider="1Password/SDK"}[48h]))'` + `kubectl get pods -n external-secrets-operator -o jsonpath='{.items[*].status.startTime} {.items[*].status.containerStatuses[0].restartCount}'`.
      Esperado: success < 500/48h y error 0. Medido 09-10 00:04Z: success 32/24h, error 0. VERDE desde el 05-10 — falta solo la firma qa (historia 1), tomada SINCRÓNICA en el turno (leer la métrica con curl y escribir 70-qa.md en el mismo turno; nunca como job en segundo plano con fichero .done — así se atascó el CTO el 08-10).
- [ ] (b) Cero ExternalSecret con el error literal `could not get secret data from provider` y cero ES con `Ready!=True`.
      Comando: `kubectl get es -A -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(i["metadata"]["namespace"]+"/"+i["metadata"]["name"]) for i in d["items"] for c in i.get("status",{}).get("conditions",[]) if "could not get secret data from provider" in str(c.get("message",""))]'`
      Esperado: salida vacía. Medido 09-10 00:04Z: could-not 0, not-ready 0 (incluido keycloak/chat-agentgateway-keycloak-bootstrap, Ready=True — cierra DGX-316 como CUMPLE medido). CUMPLE.
- [ ] (c) Ningún objeto que GASTE la cuota sobre el store SDK `onepassword` por debajo de 24 h sin excepción documentada; los ES sobre `onepassword-connect` no cuentan (no gastan). Cero referencias al SDK tras la historia 2.
      Comando: `kubectl get es,ces,pushsecret -A -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(i["kind"],i["metadata"]["namespace"]+"/"+i["metadata"]["name"]) for i in d["items"] for ref in ([i["spec"]["secretStoreRef"]] if i["spec"].get("secretStoreRef") else i["spec"].get("secretStoreRefs",[]) if i["spec"].get("secretStoreRefs") else [((i["spec"].get("generator") or {}).get("secretStoreRef") or {})]) if ref.get("name")=="onepassword"]'`
      Esperado: salida vacía tras la historia 2. Medido 09-10 00:04Z: 0 ES/CES sobre SDK; 15 `PushSecret` de `hermes` (hermes-api-key-*, refresh 24h) sí — dos más que el 08-10 (`hermes-api-key-main`, `hermes-api-key-qa-pagos`): quien crea PushSecret nuevos los sigue poniendo en el store SDK. Son el consumo ESO restante de (a). Historia 2.
- [ ] (d) La cuota de la cuenta no se agota: `account read_write` muy por debajo de 1000 y estable.
      Comando: `T=$(kubectl get secret onepassword-service-account -n external-secrets-operator -o jsonpath='{.data.token}'); OP_SERVICE_ACCOUNT_TOKEN=$T op service-account ratelimit` (no consume).
      Medido 09-10 00:04Z: `account read_write 1000 25 975` — 25/24h (eran 966 en septiembre). CUMPLE; se re-sondea al cerrar.
- [ ] (e) Todo entregado por PR contra el tronco que lee ArgoCD, verificado en el objeto vivo. Ya cumplido: PRs 222/223/227/236/242 (k8s-infra) fusionadas; app k8s-infra Synced Healthy (sync 08-10 03:33Z); CI del tronco verde (medido 08-10: check-runs de origin/main todos success — cierra DGX-318, cuyo criterio era desbloquear ese CI). Sin trabajo nuevo; se re-verifica al cerrar.
- [ ] (f) Cero hijos abiertos al cerrar (transiciones de `pm` + `80-validacion-pm.md` + `90-informe-cierre.html` con las secciones de resumen-entrega.md):
      DGX-505/506/507 Done el 08-10 (solo comprobación de papeles); DGX-472/473/474 (QA) → cerrar con su 70-qa.md; DGX-475 (Review) → cerrar con su nota; DGX-316 → CUMPLE medido (Ready=True, evidencia en (b)); DGX-318 → cerrada de hecho por CI verde en el tronco (evidencia en (e)); DGX-508 → veredicto de security en su issue (historia 3). Ya cerradas como sustituidas (PM 05-10): DGX-271, DGX-278, DGX-476, SC-1659.

## Restricciones

- GitOps: siempre PR, nunca push ni merge directo al tronco; el merge lo pulsa el CTO.
- No se revierte nada de SC-699/SC-490 ni de INFRA-511/523 (Connect es la solución viva).
- La historia 2 no puede tocar el store SDK sin coordinar con INFRA-533 (PR 243 abierta: lo mueve a la última wave); si la 243 fusiona primero, la migración de PushSecret se hace sobre su resultado.
- No se borra el store `onepassword` (SDK) hasta que el comando de (c) dé vacío, y por PR.
- `prune: false` en la app external-secrets no se toca. No se borra Vault ni objetos vivos.
- La cuota es ventana deslizante de 24 h COMPARTIDA con el `op` humano y el detector (CronJob cada 4h, ~6-12 llamadas/día); `op service-account ratelimit` no consume.
- Horas siempre UTC real (`date -u`).

## Trabajo reciente (24 h)

- 09-10 00:42Z (re-verificado, valores idénticos al pase de las 00:10Z): success 58/48h (32/24h), error 0, (b) 0/0, 15 PushSecret sobre SDK, cuenta 26/1000, app Synced Healthy, PR 243 (INFRA-533) sigue abierta, 0 sesiones vivas.
- 09-10 (comentario del supervisor, hora Jira): el despertador devuelve la épica — la sesión CTO del 08-10 (14:20-15:10Z) quedó esperando 6 h el fichero `p3c.log.done` de la lectura formal, que el job en segundo plano nunca escribió. Causa del desatasco, resuelta en el plan (lectura sincrónica, historia 2).
- 08-10 13:54Z: DGX-507 Done (PR 266 «una sola regla para recoger un secreto» fusionada); DGX-505 Done 12:26Z, DGX-506 Done 13:10Z.
- 08-10: nacieron 2 PushSecret nuevos sobre el store SDK (`hermes-api-key-main`, `hermes-api-key-qa-pagos`) — la deriva sigue abierta; 15 refs SDK hoy.
- 08-10 ~06:50Z: PR 265 (StorageClass) aplicada — app k8s-infra Synced Healthy otra vez; sin efecto en cuota, no invalida el t0.
- 09-10 00:04Z y 00:42Z (sesiones de plan, medido en vivo): success 32/24h y 58/48h, error 0, (b) 0/0, 15 PushSecret sobre SDK, cuenta 26/1000, PR 243 (INFRA-533) sigue abierta, 0 sesiones vivas en el tema.

## Diseño

Diseñador: no — no hay interfaz: una lectura métrica, una PR de migración de PushSecret y transiciones de Jira.

## Historias previstas

1. `Story — Migrar los 15 PushSecret hermes-api-key-* del store SDK onepassword a onepassword-connect por PR en k8s-infra (coordinando con la PR 243 de INFRA-533 si fusiona antes) Y cortar la deriva: el sitio donde se declaran los PushSecret nuevos (plantilla/valores de hermes) debe apuntar al store connect, no al SDK — nacieron 2 nuevos sobre el SDK en un día; con ello el comando de (c) da vacío` (dueño: devops).
2. `Task — Lectura formal (a): tomarla SINCRÓNICA en el turno (curl + 70-qa.md en el mismo turno, nunca job en background con .done — así se atascó el CTO el 08-10), con desglose por status y call y sonda de cuenta` (dueño: qa).
3. `Task — Cierre: pedir el veredicto de security en DGX-508 (comentario en su issue), transiciones pm de 472/473/474/475/505/506/507/316/318/508, 80-validacion-pm.md + 90-informe-cierre.html (secciones de resumen-entrega.md)` (dueño: pm).

## Tamaño

S — una lectura métrica de un curl ya verde, una PR de migración de 15 PushSecret (y su plantilla), un veredicto de security y transiciones de Jira. El suelo lo entregó INFRA-511/523.

## Dificultad

Dificultad: media — trabaja sobre algo que ya existe (migrar PushSecret a un store Connect en producción, firmar una lectura, un runbook y papeles); toca credenciales e infraestructura pero no crea nada nuevo desde cero ni hace migraciones de datos irreversibles (criterio de Dani, 06-10).

## Trampas verificadas (no se vuelven a descubrir)

- FALSO hallazgo del 07-10 a corregir: el store SDK NO fue retirado por la PR 257 (esa es INFRA-628, CPU de keycloak). Medido 08-10: store vivo y 13 PushSecret gastando por él. La retirada del store es parte del cierre de esta épica, no historia pasada.
- Nunca lanzar la lectura de métricas como job en segundo plano con fichero `.done`: es un curl de un segundo; vigilar un flag que nadie escribe atascó al CTO 6 h (08-10). Las comprobaciones de esta épica son sincrónicas en el turno.
- Los PushSecret nuevos siguen naciendo sobre el store SDK (2 en un día): migrar sin corregir la plantilla/valores de hermes deja la deriva abierta y el comando de (c) vuelve a llenarse.
- Con Connect el `refreshInterval` dejó de ser proxy del gasto: los ES sobre `onepassword-connect` refrescan y NO gastan cuota. Juzgar (c) por el intervalo sin mirar el store sale mal.
- Los PushSecret usan el campo `secretStoreRefs` (plural), no `secretStoreRef`: un filtro que solo mire el singular los pasa por alto — son los 15 que quedan sobre el SDK.
- La métrica de ESO y la cuenta de 1Password no cuadran (SDK ~2 peticiones por llamada + gasto humano/MCP/detector): reportar las dos cifras, siempre brutas.
- El t0 de una lectura lo invalida CUALQUIER despliegue con efecto en cuota: re-fijar tras el último y tomar la lectura en cuanto la ventana se abre, no reaparcarla.
- Los values del operador que lee ArgoCD están en k8s-gitops-pocharlies deploy/prod (el de k8s-infra es señuelo); el fichero del store SÍ está en k8s-infra.
- Un ES de provider en error aborta el sync ENTERO de su app.
- El checkout de ~/k8s/... puede estar en la rama de otra sesión: leer del tronco con `git show origin/main:FICHERO`.
- El grep recursivo del host con el `grep` del x86 (ugrep) da 0 falso en rutas raras: medir con `/usr/bin/grep -r`.
