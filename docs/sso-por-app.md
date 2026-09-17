# Patrón SSO por app (un oauth2-proxy y una pareja de grupos por software)

Patrón de acceso SSO para una app que necesita **su propia lista de permisos**,
independiente de la del dashboard de control. Se documenta tal como quedó
desplegado y medido en SKIRM-15 (caso skirmbooks), sin propuestas de mejora.
Las conductas marcadas "medido" vienen del `qa.md` adjunto a SKIRM-17 (pasada
final QA 17-09-2026 sobre producción).

## 1. Cuándo aplica

Cuando una app necesita SSO propio con permisos independientes del dashboard,
**sin tocar la `sso-chain` compartida ni los grupos del dashboard**. El caso que
originó el patrón: skirmbooks (software fiscal — AEAT / 369 / OSS / tenants /
facturas) entraba por la `sso-chain` compartida con el dashboard, es decir la
misma cookie `_edani_sso` (`Domain=.e-dani.com`) y los mismos
`allowed_groups = [/edani-admins, /edani-operators]`. Consecuencia: quien podía
entrar en `dgx.e-dani.com` podía entrar en el software fiscal, y no había lista
de permisos por software. El patrón corta ese acoplamiento por app.

## 2. Las piezas, con sus nombres reales (el caso skirmbooks como referencia)

- **oauth2-proxy dedicado**: Deployment / Service `oauth2-proxy-skirmbooks`
  (ns `keycloak`, imagen `oauth2-proxy:v7.15.2`, `replicas: 2`) con su ConfigMap
  propio `oauth2-proxy-skirmbooks-config`. El mismo patrón ya lo tienen
  `oauth2-proxy-chat`, `oauth2-proxy-skirmshop` y
  `oauth2-proxy-openclaw-readonly`.

- **Cookie host-only con nombre propio**: `cookie_name = "_skirmbooks_sso"`, y
  **sin `cookie_domains`** a propósito. La cookie nace y muere en
  `skirmbooks.e-dani.com`. Por qué host-only:
  - el logout de skirmbooks **no** mata la sesión de `dgx.e-dani.com` — medido en
    C5: tras el clic de logout, `_skirmbooks_sso` desaparece y `_edani_sso`
    (`.e-dani.com`) queda intacto, dgx sigue pidiendo nada;
  - la cookie no viaja a otro host, así no se mezclan sesiones entre softwares.
  Poner `.e-dani.com` (como hace el proxy del dashboard) volvería a mezclar
  sesiones, que es justo lo que se está arreglando.

- **Chain de Traefik propia**: `sso-skirmbooks-chain` (ns `keycloak`), cadena de
  dos middlewares: `sso-skirmbooks-errors` (errors → `/oauth2/sign_in?rd={url}`,
  **solo 401**, ver D3) y `sso-skirmbooks-forward-auth` (forwardAuth al proxy,
  `authResponseHeaders`: `Authorization`, `X-Auth-Request-User`,
  `X-Auth-Request-Email`, `X-Auth-Request-Groups`, `X-Forwarded-User`). La chain
  se aplica **tanto en `traefik-edge` como en `traefik-lan`**. En cada uno hay
  además una regla `PathPrefix(/oauth2)` **SIN middleware** que sirve el proxy
  directo: el callback OAuth con forward-auth entraría en bucle.

- **Client en el realm `edani` de `auth-next.e-dani.com`**: SKIRM-15 **no crea un
  client nuevo** — reutiliza el client `oauth2-proxy` del realm (así lo declaran
  el ConfigMap y el Job reconciler: "lo que cambia por software es la cookie y
  los grupos, no hace falta un client nuevo"). Lo que se le añade al client es el
  `redirect_url` **exacto** `https://skirmbooks.e-dani.com/oauth2/callback`, vía
  el Job `keycloak-skirmbooks-sso`, **sin pisar** los redirect_uri ya existentes
  (el Job deja un canario con el callback de la `sso-chain` para detectar un merge
  que los rompa). GOTCHA: el comodín `*` solo vale al final de la URI, nunca en el
  host.

- **Grupos propios**: `/skirmbooks-users` y `/skirmbooks-admins` en el realm
  `edani`, declarados en `allowed_groups` del proxy (los grupos del dashboard NO
  dan acceso aquí). El mapper `oidc-group-membership-mapper`
  (`full.path=true`, `id.token.claim=true`, `claim.name=groups`) se crea sobre el
  client para que los grupos viajen en el token y oauth2-proxy los reenvíe a la
  app por cabecera. Los grupos y las membresías nominales las reconcilia el Job
  PostSync `keycloak-skirmbooks-sso` (wave 21).

## 3. Decisiones D1–D4 (SKIRM-15), cada una con su razón

- **D1 — Un oauth2-proxy y una pareja de grupos por software, con cookie
  host-only.** La cookie compartida `_edani_sso` con `Domain=.e-dani.com` hacía
  del acceso al software fiscal un efecto colateral del acceso al panel, y era la
  causa del incidente del 15-09 (403 por grupo ajeno → 500 eco del callback). La
  cookie va sin `cookie_domains` para que el logout de una app no toque a las
  demás (criterios 3 y 5).

- **D2 — Se cierra el bypass LAN/tailnet.** La regla
  `traefik-lan/lan-skirmbooks-public-host` (priority 300, casa por ClientIP
  `192.168.50.0/24`, `100.64.0.0/10`, `10.42/16`, `10.43/16`) pasa a llevar
  `sso-skirmbooks-chain`. Un software fiscal con tenants y facturas no puede
  servirse sin identidad a quien esté en la LAN o el tailnet. El break-glass no
  desaparece: sigue en `kubectl port-forward` al Service, que no pasa por el
  ingress.

- **D3 — La cadena reescribe solo 401; el 403 se queda 403.** Skirmbooks emite su
  propio 403 desde `requirePlatformAdmin`; reescribirlo a `sign_in` produce
  `ERR_TOO_MANY_REDIRECTS` (documentado el 10-08-2026). El criterio 2 se cumple
  con un 403 legible; lo que estaba prohibido era el 500.

- **D4 — Orden: SKIRM-16 antes que SKIRM-17.** El `SSO_LOGOUT_URL` de la app tiene
  que apuntar al proxy que realmente sirve la ruta; cambiarlo antes del vuelco
  dejaría el logout apuntando a un proxy que no gatea.

## 4. Contrato con la app

- Los grupos llegan **por cabecera**: `X-Auth-Request-Groups` (reenviada por el
  forward-auth). La app **NO** consulta Keycloak: deriva sus roles internos de esa
  cabecera (`roleFromGroupsHeader`, el header manda sobre la BD).
- Medido en C6: mismo principal, mismo path, solo cambia el grupo del header →
  con `/skirmbooks-users` da 403 en `/admin/descargas-facturas`; añadiendo
  `/skirmbooks-admins` pasa a 200. Los roles se derivan del header, no del login.
- **Nunca un 500 en authz** (medido): un usuario autenticado pero fuera de los
  grupos del proxy obtiene un **403 legible** (C2, D3 — sin bucle); un usuario sin
  fila de principal en la app cae a su página legible `/login?sso=no_principal`,
  no a un 500 (C1/C6).

## 5. Cómo replicarlo para la siguiente app

Se **duplica y renombra** (tomando skirmbooks como plantilla):

1. Deployment + Service `oauth2-proxy-<app>` y ConfigMap
   `oauth2-proxy-<app>-config` (ns `keycloak`), con `redirect_url` exacto de la app.
2. Cookie propia **host-only** (`cookie_name = "_<app>_sso"`, sin `cookie_domains`).
3. `allowed_groups` propio con la pareja de grupos de la app.
4. Chain propia `sso-<app>-chain` (errors-solo-401 + forward-auth) aplicada en
   **`traefik-edge` y `traefik-lan`**, más la regla `PathPrefix(/oauth2)` sin
   middleware en cada uno.
5. Job reconciler tipo `keycloak-<app>-sso` que asegure grupos, el `redirect_uri`
   exacto (sin pisar los existentes) y el mapper de grupos sobre el client.
6. La app lee `X-Auth-Request-Groups` y deriva sus roles; nunca un 500 en authz.

**NO se toca**: la `sso-chain` del dashboard, sus grupos (`/edani-admins`,
`/edani-operators`), ni los proxies de otras apps.

## 6. Anti-patrón

No compartir cookie de dominio entre apps (nunca `cookie_domains` con el dominio
común: es lo que acoplaba el acceso fiscal al del panel). El client `oauth2-proxy`
del realm **sí** se comparte por diseño — lo que aísla por app son la cookie y los
grupos, no un client por software.

## Qué aísla este patrón, y qué no

Lo que aísla de verdad son **dos** cosas, y conviene no confundirse sobre cuál hace el trabajo:

- La **cookie host-only**: sin `cookie_domains`, la cookie nace y muere en `skirmbooks.e-dani.com`. Es lo que hace que cerrar sesión aquí no toque la de `dgx.e-dani.com`, y lo que impide que la sesión viaje a otro host del dominio.
- El **`allowed_groups` propio** del proxy: cada oauth2-proxy decide por su cuenta a quién deja pasar, y los grupos del dashboard no abren esta puerta.

Lo que **no** aísla, y hay que saberlo antes de copiar el patrón: el **client OIDC de Keycloak es compartido** (`oauth2-proxy` del realm `edani`). A ese client compartido se le añaden, por cada app, el `redirect_uri` exacto y el mapper de grupos. Consecuencias reales:

- La lista de `redirect_uri` del client compartido **crece con cada app**. Es la pieza que se degrada con el número de apps, y el `*` solo vale al final de la URI, nunca en el host.
- Un secreto de client comprometido lo está **para todas** las apps del patrón, no solo para una.

Se aceptó así en SKIRM-15 porque los criterios de la épica piden permisos independientes por software, y eso lo dan la cookie y los grupos; un client por app era trabajo extra sin efecto medible sobre esos criterios. **Cuándo deja de valer:** cuando una app necesite un secreto de client, un tiempo de sesión o un flujo de consentimiento distintos del resto, o cuando el número de `redirect_uri` del client compartido deje de ser legible de un vistazo. Ese día, client por app — y es un cambio de diseño con su propia decisión, no un detalle de despliegue.
