# INFRA-825 P1 · evidencia

Dónde: worktree de la rama `infra-825-paseo` (desde origin/main 2f88208), x86, 10-10-2026.

## 1. Rojo primero (antes de los manifiestos) · FAIL esperado
`python3 -m pytest tests/test_public_panels_lan_contract.py -q`
```
FAILED tests/test_public_panels_lan_contract.py::test_paseo_public_route_requires_sso_chain_outside_trusted_networks
FAILED tests/test_public_panels_lan_contract.py::test_paseo_lan_route_points_at_the_x86_externalname_on_6767
2 failed, 5 passed
```

## 2. Verde tras el cambio · PASS
`python3 -m pytest tests/test_public_panels_lan_contract.py -q` -> `7 passed`

Mutación: quitar `sso-chain` de la regla comodín de `paseo-public.yaml` -> `1 failed, 6 passed`; restaurada -> `7 passed`.

`kubectl kustomize .` -> limpio. Objetos, antes (origin/main) y después (rama):
```
added:   IngressRoute traefik-edge/edge-paseo-public, IngressRoute traefik-lan/lan-paseo,
         Service traefik-edge/paseo-edge-x86, Service traefik-lan/paseo-lan-x86
removed: (ninguno)
344 -> 348
```

## 3. Suite completa · PASS (salvo 2 fallos previos)
`python3 -m pytest tests -q` -> `2 failed, 486 passed` (en origin/main: `2 failed, 484 passed`).
Los dos fallos son previos y no tocan Paseo:
`test_canonical_host_routing_contract::test_all_new_lan_routes_use_canonical_names_and_public_wildcard` (sobra `vault.e-dani.com`)
y `test_traefik_lan_ks5_ha_contract::test_harbor_lan_resolves_to_the_cluster_service` (CoreDNS `192.168.50.240 dgx.e-dani.com`).

## 4. WebSocket (`/ws`)
No hace falta regla propia: la regla comodín del host lo cubre (con `sso-chain` desde fuera) y Traefik pasa el `Upgrade`
sin configuración. El edge tiene el `readTimeout` de 60 s por defecto, pero no corta el WebSocket: `net/http` de Go quita
los deadlines al secuestrar la conexión (`hijackLocked` -> `rwc.SetDeadline(time.Time{})`, leído en golang/go master).
El LAN ya tiene `readTimeout=0`. Prueba extremo a extremo: tras el despliegue, en `70-qa.md`.

## Criterios
- C1: `kustomize build` limpio y tests del repo verdes (secciones 2 y 3).
- C2: `edge-paseo-public` solo enruta sin `sso-chain` en la regla de las ClientIP de LAN/tailnet; la regla comodín lleva `sso-chain` (test `test_paseo_public_route_requires_sso_chain_outside_trusted_networks`).
- C3: `lan-paseo` apunta a `paseo-lan-x86`, ExternalName `x86.taile0ad27.ts.net`, puerto 6767 (test `test_paseo_lan_route_points_at_the_x86_externalname_on_6767`).
