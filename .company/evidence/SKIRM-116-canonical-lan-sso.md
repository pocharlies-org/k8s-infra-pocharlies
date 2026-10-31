# SKIRM-116 · evidencia

Solo lectura sobre el cluster. Nada aplicado, nada reiniciado.

## 1. Render (el path que usa la app `k8s-infra`: `.`, tronco `main`)

- `kubectl kustomize .` desde la raiz de la rama: PASS, rc=0, 342 documentos.
- La IngressRoute `canonical-hosts-lan` es la unica que cambia (el diff de la rama toca un fichero de manifiesto).

## 2. `kubectl diff --server-side --force-conflicts` de esa IngressRoute (dry-run del servidor)

Sin `--force-conflicts` falla por propiedad de campos con `argocd-controller` (`.spec.routes`); con el, es solo un dry-run y no persiste nada.
PASS: el unico recurso que cambia es `traefik-lan/canonical-hosts-lan`, y solo en `.spec.routes` de los dos hosts (mas `generation`).

```diff
@@ -517,6 +517,7 @@   (whatsapp /api/public)       +    priority: 300
@@ -526,12 +527,24 @@  (whatsapp /qr)               +    priority: 300
                                          + Host(`whatsapp.e-dani.com`) && ClientIP(`10.42.0.0/16`)   priority: 200, sin middleware
                                          ~ Host(`whatsapp.e-dani.com`)   + middlewares sso-chain (keycloak), priority: 100
@@ -541,6 +554,7 @@   (whatsapp-pro /api/public)  +    priority: 300
@@ -550,12 +564,24 @@  (whatsapp-pro /qr)           +    priority: 300
                                          + Host(`whatsapp-pro.e-dani.com`) && ClientIP(`10.42.0.0/16`)   priority: 200, sin middleware
                                          ~ Host(`whatsapp-pro.e-dani.com`)   + middlewares sso-chain (keycloak), priority: 100
```

(Resumen de las 77 lineas del diff; no hay ningun otro hunk.)

## 3. `sso-chain` existe

`kubectl get middlewares.traefik.io -A`: `keycloak/sso-chain` (128 d) y `whatsapp-mcp/connector-public-api-deny` (13 d). PASS. El provider `kubernetescrd` de traefik-lan tiene `allowCrossNamespace=true`, y el resto del fichero ya usa `sso-chain` de `keycloak`.

## 4. Prioridades y comportamiento: Traefik v3.7.1 (la misma imagen que traefik-lan), local, fuera del cluster

Se genero la config con las rutas reales de `whatsapp` y `whatsapp-pro` del fichero (mas `lan-instagram-callback`, prioridad 400), cambiando solo el CIDR `10.42.0.0/16` por `127.0.0.0/16` (misma longitud) para probar con origenes de loopback: `127.0.0.1` hace de pod y `127.1.0.1` de dispositivo de la LAN. Los middlewares se sustituyen por una cabecera `X-Mw` que el backend devuelve (`sso`, `deny`, `none`).

Prioridades calculadas por la API de Traefik con la rama:

```
400 whatsapp  /oauth/instagram/callback          (lan-instagram-callback, sin tocar)
300 whatsapp  /api/public    y  /qr              300 whatsapp-pro /api/public y /qr
200 whatsapp  ClientIP       y  whatsapp-pro ClientIP
100 whatsapp  (catch-all)    y  whatsapp-pro (catch-all)
```

Resultado `whatsapp.e-dani.com` (`whatsapp-pro.e-dani.com` da lo mismo, medido):

| origen | peticion | antes (`main`) | ahora (rama) |
| --- | --- | --- | --- |
| pod | GET /status, GET /api/v1/me, POST /api/v1/messages/send | none | none |
| pod | GET /qr/page | sso | sso |
| pod | GET /api/public/chats | deny | deny |
| LAN | GET /status, GET /api/v1/me, POST /api/v1/messages/send | **none (abierto)** | **sso** |
| LAN | GET /qr/page | sso | sso |
| LAN | GET /api/public/chats | deny | deny |
| ambos | GET /oauth/instagram/callback | instagram | instagram |

Control: la misma rama SIN `priority:` explicito (prioridad por longitud de regla, 55 para ClientIP frente a 48 de `/qr`) deja pasar `GET /qr/page` desde el pod con `mw=none`. Por eso las cuatro reglas por host llevan prioridad explicita.

## 5. Tests

`python3 -m pytest tests/test_canonical_host_routing_contract.py`: 7 pasan, incluido el nuevo `test_whatsapp_lan_hosts_ask_sso_except_pods_and_keep_qr_and_public_deny_on_top`. Falla 1 que ya fallaba en `main`: `test_all_new_lan_routes_use_canonical_names_and_public_wildcard` (la constante `CANONICAL_LAN_HOSTS` aun lista `vault.e-dani.com`, cuya ruta retiro SC-699 fase 6, bbe6d71). No es de este cambio y este fichero no lo ejecuta el CI.

## 6. Criterios de la historia

- LAN sin sesion, `/status` y `/api/v1/*` de los dos hosts: la regla lleva `sso-chain` y la simulacion lo confirma (sso). Con sesion = 200 lo prueba qa en vivo tras el merge.
- Pod 10.42.x: la regla `ClientIP` sin middleware conserva el comportamiento de hoy (none). Los POST de synapse tras el cambio se miran en Loki tras el merge (qa/sre).
- Ningun pod reiniciado; diff solo en la IngressRoute: PASS (render y `kubectl diff`).
- Antes del merge, sre confirma los 173 POST: PENDIENTE, bloquea el merge (escrito en la PR).
