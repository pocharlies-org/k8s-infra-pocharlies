# SKIRM-15 — plan del tech lead (16-09-2026)

Sesión CTO: d585641f-15b0-4047-9845-6ff3a9b1e84b. Parte 1 (proxy propio, grupos, reconciler) ya en `main` (#123-#125), verificada E2E por el edge público.

## Medido antes de despachar

- ConfigMap `keycloak/oauth2-proxy-skirmbooks-config`: `set_xauthrequest = true`, `pass_user_headers = true`, `set_authorization_header = true`, `pass_access_token = true`. El middleware `sso-skirmbooks-forward-auth` ya tiene `authResponseHeaders` = Authorization, X-Auth-Request-User/-Email/-Groups, X-Forwarded-User. => el header de grupos YA llega a la app; SKIRM-17 no necesita cambio de infra por ese lado.
- `traefik-edge/edge-other-legacy-proxies` (`networking/traefik-edge/legacy-public-routes.yaml` ~L520-541): ruta `/oauth2` sin middleware -> `oauth2-proxy-skirmbooks:4180`; ruta host -> `sso-chain` (a cambiar).
- `traefik-lan/lan-skirmbooks-public-host` (`networking/traefik-lan/public-panels-lan.yaml` L83-99): priority 300, sin middleware, ClientIP LAN/tailnet/pods. NO hay ruta `/oauth2` para skirmbooks en traefik-lan (solo la hay para openclaw-readonly en `canonical-hosts-lan.yaml` L286) => hay que añadirla en el mismo PR o el callback desde LAN no completa.
- Hay test de contrato `tests/test_public_panels_lan_contract.py` que cubre ese fichero: el devops debe correrlo/ajustarlo.

## Partes

1. **SKIRM-16 (devops, repo k8s-infra-pocharlies, tronco main, rama `feat/SKIRM-16-skirmbooks-route-cutover`)**
   - edge: host rule `sso-chain` -> `sso-skirmbooks-chain`; `/oauth2` sigue sin middleware.
   - lan: `lan-skirmbooks-public-host` gana `sso-skirmbooks-chain` (D2) + nueva ruta `Host && PathPrefix(/oauth2) && ClientIP(...)` con priority > 300 -> `oauth2-proxy-skirmbooks` sin middleware.
   - Pre-merge: forward-auth alcanzable desde los pods de traefik-lan (curl al svc desde un pod de traefik-lan o desde la red del clúster: ClusterIP 10.43.170.183:4180/ping). Comprobar healthchecks de la app que pasen por el ingress (si hay probes externas, documentarlas).
   - Verificación: `kubectl diff`/render local, tests de contrato, PR contra main. No aplica nada.
2. **SKIRM-17 (developer, repo k8s-skirmbooks-pocharlies, tronco main, rama `feat/SKIRM-17-sso-logout-groups`)** — arranca cuando #16 esté mergeado (D4).
   - `SSO_LOGOUT_URL` -> `https://skirmbooks.e-dani.com/oauth2/sign_out?rd=<end_session_endpoint de auth-next/realms/edani con post_logout_redirect_uri=https://skirmbooks.e-dani.com/ y client_id=oauth2-proxy>`; botón logout en la UI.
   - Roles internos desde `X-Auth-Request-Groups` (full.path): `/skirmbooks-admins` -> admin gestoría, `/skirmbooks-users` -> usuario tenant. El 403 de `requirePlatformAdmin` se queda 403 (D3).
   - Tests unitarios del mapeo de grupos.
3. **QA** tras el merge de cada parte (evidencia pegada, 5 puntos del CTO). Cuentas de prueba vía reconciler o SA `admin-keycloack-server`, borradas después.
4. **PM**: criterios comprobables en SKIRM-16/17 antes de construir; veredicto funcional al final.

## Done
Los 6 criterios de SKIRM-15 con evidencia de qa y veredicto de pm; PRs mergeados por el CTO; ArgoCD Synced/Healthy en `k8s-infra` y `skirmbooks`.
