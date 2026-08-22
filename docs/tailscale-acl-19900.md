# Cerrar el `:19900` del x86 con una ACL de Tailscale

## El problema

`opencode serve --hostname 0.0.0.0 --port 19900` corre en el x86 con
`UnsetEnvironment=OPENCODE_SERVER_PASSWORD`. Medido el 20-08-2026:

```
curl -s -o /dev/null -w '%{http_code}\n' http://100.83.56.98:19900/session
200        # sin credencial, desde cualquier dispositivo del tailnet
```

Las sesiones que crea esa API ejecutan comandos como `dibanez`: sudo, docker,
`KUBECONFIG` de cluster-admin y un PAT con `admin:org` en
`~/.config/gh/hosts.yml`. Son 10 dispositivos en el tailnet con RCE disponible.

Viene del commit `eaf6acf` *"delegate web auth to ingress"*: la autenticación se
movió a Keycloak y el puerto se quedó desnudo por debajo.

## Estado actual de la política (leído por API el 21-08-2026)

Es **la de por defecto**, y usa `grants` (sintaxis nueva), no `acls`:

```jsonc
{
  "tagOwners": {
    "tag:k8s":         ["autogroup:admin"],
    "tag:ks5-control": ["autogroup:admin"],
  },
  "grants": [
    {"src": ["*"], "dst": ["*"], "ip": ["*"]},     // <-- esto es lo que abre el 19900
  ],
  "ssh": [ /* … */ ],
  "nodeAttrs": [ /* … */ ],
}
```

**Un grant es una concesión, no un filtro.** En Tailscale no existe "deny": lo
que no se concede queda negado, pero una concesión más amplia gana. Así que
`{"src":["*"],"dst":["*"],"ip":["*"]}` no se puede "recortar" — hay que
sustituirlo por reglas explícitas.

## Lo que NO se rompe (comprobado antes, no después)

| quién | cómo llega al 19900 | ¿le afecta? |
|---|---|---|
| `code.e-dani.com`, `code.lan.e-dani.com` | Traefik (`ks5-cp-*`, `tag:k8s`) → `100.83.56.98:19900` por EndpointSlice | **sí** → la regla 3 se lo concede |
| `dgx-dashboard-backend` (`OPENCODE_RELOAD_TARGETS`, `OPENCODE_RCA_URL`) | corre en el nodo `ubuntu`, **que es el x86** | **no**: `ip route get 100.83.56.98` → `local … dev lo`. El paquete no sale de la máquina |
| `openchamber` y `openchamber-beta` | `OPENCODE_HOST=http://127.0.0.1:19900` | **no**: loopback |
| runners de `arc-k8s` | ya cerrados por NetworkPolicy (21-08) | ya resuelto por otra vía |

Tu MacBook y el móvil abren `code.e-dani.com`, que va **por Traefik**. No
pierden nada.

## La política a aplicar

Conservar `ssh` y `nodeAttrs` tal cual. Cambiar solo `tagOwners` y `grants`:

```jsonc
"tagOwners": {
  "tag:k8s":         ["autogroup:admin"],
  "tag:ks5-control": ["autogroup:admin"],
  "tag:x86":         ["autogroup:admin"],    // NUEVO
},

"grants": [
  // 1. El tailnet sigue hablando entre sí como hasta ahora, salvo que el x86
  //    deja de estar cubierto por el comodín de destino.
  {
    "src": ["*"],
    "dst": ["autogroup:member", "tag:k8s", "tag:ks5-control"],
    "ip":  ["*"],
  },

  // 2. El x86 sigue abierto en TODO lo demás: SSH, :3000, :3001, :8799,
  //    :18790… Solo se excluye el 19900 del rango.
  {
    "src": ["*"],
    "dst": ["tag:x86"],
    "ip":  ["tcp:1-19899", "tcp:19901-65535", "udp:*", "icmp:*"],
  },

  // 3. El 19900, solo desde los nodos de k8s: es Traefik quien sirve
  //    code.e-dani.com contra ese puerto.
  {
    "src": ["tag:k8s"],
    "dst": ["tag:x86"],
    "ip":  ["tcp:19900"],
  },
],
```

Y **etiquetar el x86 con `tag:x86`** — hoy no tiene ninguno.

## Orden de operaciones (importa)

1. Guardar la política con `tag:x86` ya declarado en `tagOwners` y los tres
   grants. Mientras el x86 no lleve el tag, la regla 2 y la 3 no le aplican y
   **todo sigue como está**: cambio inerte, sin riesgo.
2. Etiquetar el nodo: en la consola, ficha del dispositivo `x86` → Edit ACL
   tags → `tag:x86`. En ese momento entra en vigor.
3. Comprobar (abajo). Si algo falla, quitar el tag revierte al instante.

> **Cuidado con el SSH al etiquetar.** El bloque `ssh` actual concede
> `autogroup:member` y `tag:k8s` sobre `tag:k8s`, y `autogroup:member` sobre
> `autogroup:self`. Un nodo **tagueado deja de ser `autogroup:self`** (pasa a
> pertenecer al tag, no al usuario), así que `ssh x86` puede dejar de funcionar
> desde el MacBook. Si quieres conservarlo, añadir al bloque `ssh`:
> ```jsonc
> {"action": "check", "src": ["autogroup:member"], "dst": ["tag:x86"],
>  "users": ["autogroup:nonroot", "root"]},
> ```
> Esto es lo más probable que muerda, y es reversible quitando el tag.

## Comprobación

Desde un dispositivo del tailnet que **no** sea k8s (el MacBook):

```sh
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://100.83.56.98:19900/session
# esperado: 000 (timeout), ya no 200

curl -s -o /dev/null -w '%{http_code}\n' -m 8 https://code.e-dani.com/
# esperado: sigue funcionando (va por Traefik)

curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://100.83.56.98:3001/
# esperado: 200 — el canario NO se toca
```

Y desde el propio x86, que va por loopback y no cruza la ACL:

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:19900/session   # 200
```

La consola de Tailscale trae además un comprobador de ACL: se le puede añadir
un test que afirme que `b13959085` **no** alcanza `100.83.56.98:19900`, y así
la política no se puede volver a guardar abierta por descuido.

## Quién puede aplicarlo

**Yo no**: la credencial OAuth que hay en Vault (`secret/aurora-tailscale`)
tiene scopes `devices:core:read, dns:read, policy_file:read, routes:read` — de
solo lectura. Por eso pude leer la política pero no escribirla. Se aplica desde
la consola de Tailscale (Access Controls), o con una credencial que tenga
`policy_file:write`.

## Por qué esta vía y no otra

- **Bindear a `127.0.0.1`** mataría `code.e-dani.com`: Traefik llega por la IP
  de Tailscale (`EndpointSlice` de `opencode-public.yaml`), no por loopback.
- **Devolver `OPENCODE_SERVER_PASSWORD`** puede romper el flujo de Keycloak —
  el propio fichero de ingress dice *"OpenCode does not emit a second Basic
  challenge"*. Requiere ventana y pruebas.
- La ACL no toca el servicio ni el ingress, y se revierte quitando un tag.
