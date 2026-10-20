# SSO: un realm de Keycloak por web, siempre separado

**Norma (Dani, 20-10-2026, SC-2822).** Cada web tiene su propio realm en
`auth-next.e-dani.com`. Ningún realm, client, oauth2-proxy ni cookie se comparte
entre dos webs. Una web nueva no entra nunca en el realm `edani` ni en una cadena
existente: entra con su realm.

Por qué: Keycloak guarda **una sesión por realm y navegador**. Con todas las webs en
`edani`, entrar en `horarios.alphalinkcrossfit.com` con la cuenta del gimnasio
sustituía la sesión de `dgx.e-dani.com` con la cuenta personal, y al revés. Ni la
cookie host-only ni `prompt=login` lo evitan: la sesión que manda es la del realm.

## Qué es «una web»

La aplicación, con todos sus hosts alias (público, `.lan`, tailnet) y sus apps
nativas: `dgx.e-dani.com`, `dgx.lan.e-dani.com` y la app iOS de dgx son una web y
un realm. Dos aplicaciones distintas nunca comparten realm aunque compartan dominio.

`edani` queda como el realm de AgentGateway y de las identidades máquina (service
accounts, identity binding por `sub`); no aloja webs. `master` es solo administración.

## Cómo se declara una web

Una entrada en `platform/keycloak-sso/realms.yaml` (chart `platform/keycloak-sso`,
Application `keycloak-sso`). De ella salen:

- el realm, entero desde git con keycloak-config-cli (Job hook Sync, wave -1:
  concilia antes de que cambie ningún proxy). Realm cerrado: sin registro, y el
  primer login con Google enlaza por email con un usuario declarado o falla; nunca
  crea usuarios;
- el client `oauth2-proxy` del realm, con un callback exacto por host y sin
  comodines, y su mapper de grupos (`groups`, ruta completa);
- `oauth2-proxy-<realm>` con cookie `_<realm>_sso` pegada al host (sin
  `cookie_domains`) y `allowed_groups` propio;
- la cadena `sso-<realm>-chain` (errors solo 401 + forward-auth) en ns `keycloak`;
- los secretos del ítem 1Password `keycloak-sso-<realm>` (`client_secret`,
  `cookie_secret` de 32 bytes base64url).

Pasos para una web nueva:

1. Ítem `keycloak-sso-<realm>` en 1Password (lo crea security).
2. Si entra con Google: el callback
   `https://auth-next.e-dani.com/realms/<realm>/broker/google/endpoint` en el
   cliente OAuth de Google Cloud (Request a IT).
3. La entrada en `realms.yaml`.
4. En la IngressRoute de cada host (edge y lan): `sso-<realm>-chain` en la ruta del
   host y una regla `PathPrefix(/oauth2)` **sin middleware** hacia
   `oauth2-proxy-<realm>` (forward-auth sobre el callback es un bucle).

## Contrato con la app

- Los grupos llegan por `X-Auth-Request-Groups`; la app deriva sus roles de esa
  cabecera, no consulta Keycloak. Las rutas vacían las cabeceras `X-Auth-Request-*`
  que vengan de fuera antes de la cadena.
- Solo el 401 se reescribe al login. Un 403 (sin grupo, o la propia app) se queda
  403: reescribirlo produce `ERR_TOO_MANY_REDIRECTS`. Nunca un 500 en authz.

## Cómo se hace cumplir

`tests/test_keycloak_realm_per_web_contract.py` (job `keycloak-realm-per-web` del CI)
renderiza el chart y recorre todas las IngressRoute del repo: ningún host en dos
realms, cada proxy contra su realm, callbacks exactos, y las cadenas del realm
compartido (`sso-chain` y las dedicadas sobre `edani`) solo pueden encoger. Al
migrar una web, sus hosts salen de `LEGACY` en el mismo PR.

## Migración (SC-2822)

Hecho: `alphalink`. Pendiente, una fase por PR: chat, hindsight, messages,
openclaw; skirmbooks y skirmshop; uriel; los clients OIDC nativos (grafana,
langfuse, correo, whatsapp, plaud, claude-ai); dgx; y el resto de consolas de
`sso-chain`. Al final se retiran `sso-chain`, el oauth2-proxy compartido y el client
`oauth2-proxy` de `edani` con su callback comodín.
