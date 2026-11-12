# Escribir la política ACL de Tailscale sin pasar por la consola

INFRA-1312 documentó seis cambios de ACL bloqueados en el passkey de Dani en la consola:
ninguna credencial de la compañía podía escribir la política (aurora-tailscale: solo read;
el OAuth de `.ts-oauth-id`: solo `auth_keys:write`; la API key del vault, muerta).
INFRA-1315 creó un OAuth client dedicado con `policy_file:write` + `devices:core:write`.

## Credenciales (x86, modo 0600)

| fichero | qué es | scopes |
|---|---|---|
| `/home/dibanez/k8s/.ts-oauth-id` / `.ts-oauth-secret` | client de auth keys (ts_mint_authkey.py) | `auth_keys:write` |
| `/home/dibanez/k8s/.ts-oauth-acl-id` / `.ts-oauth-acl-secret` | client de ACL (ts_acl_policy.py) | `policy_file:write`, `devices:core:write` |

Copia de la segunda en el vault `k8s-pocharlies` de 1Password, junto a `aurora-tailscale`
(escribir ahí es de `security`).

## Slug del tailnet

La API no resuelve `-`, ni el nombre MagicDNS (`taile0ad27`), ni el StableID. El slug es el
nombre del tailnet que devuelve `tailscale status --json` en `CurrentTailnet.Name`: **`e-dani.com`**.
Se puede sobreescribir con `TS_TAILNET_SLUG`.

## Uso

```bash
scripts/ts_acl_policy.py get > /tmp/acl.hujson   # leer la política actual
scripts/ts_acl_policy.py put /tmp/acl.hujson     # reemplazarla
scripts/ts_acl_policy.py check /tmp/acl.hujson   # probar que la API la acepta y restaurar la anterior
```

Nunca se rota ni se retira ninguna de estas credenciales en sesión: las rotaciones van al
lote semanal con Dani (SC-3618, SC-2681).
