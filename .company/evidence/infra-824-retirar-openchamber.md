# INFRA-824 P2 · evidencia

Donde: worktree `infra-824-retirar-openchamber`, x86, 10-10-2026.

## 1. Rojo primero (antes del cambio) · FAIL esperado
`python3 -m pytest tests/test_public_panels_lan_contract.py -q`
```
FAILED tests/test_public_panels_lan_contract.py::test_no_route_serves_or_points_at_openchamber
  AssertionError: assert 'openchamber' not in '... networking/traefik-lan/openchamber-lan.yaml ...'
1 failed, 4 passed
```

## 2. Verde tras el cambio · PASS
`python3 -m pytest tests/test_public_panels_lan_contract.py -q` -> `5 passed`
`kubectl kustomize .` -> limpio. Diferencia de objetos (antes = origin/main, despues = rama):
```
removed: IngressRoute traefik-edge/edge-openchamber-public, traefik-edge/edge-openchamber-beta-public,
         traefik-lan/lan-openchamber, traefik-lan/lan-openchamber-public-host;
         Middleware traefik-edge/redirect-openchamber; ServersTransport traefik-lan/openchamber-lan-transport;
         Service traefik-edge/openchamber-edge-x86, traefik-edge/openchamber-beta-edge-host, traefik-lan/openchamber-lan-x86
added:   (ninguno)
```

## 3. Rutas contiguas · PASS
Mismo comando sobre 11 ficheros de contrato de rutas (public_panels, canonical_host_routing, dgx_*, edge_wan_firewall,
opencode_auth_routing, traefik_lan_ks5_ha, private_service_exposure, external_dns, sauvage_bot): 62 passed, 2 failed.
Los 2 fallos son previos al cambio (se reproducen igual sobre origin/main 60b1394 en un worktree limpio):
`test_canonical_host_routing_contract::test_all_new_lan_routes_use_canonical_names_and_public_wildcard` y
`test_traefik_lan_ks5_ha_contract::test_harbor_lan_resolves_to_the_cluster_service` (CoreDNS `192.168.50.240 dgx.e-dani.com`).

## Criterios
- C4: ningun IngressRoute con host `chamber*` ni `/openchamber` ni Service/middleware/transport `openchamber*` (test nuevo, seccion 2).
- C5: las demas rutas al x86 (oficinas, opencode, blog-drafts, jira-epic-trigger) tienen su propio ExternalName y no cambian; `kustomize build` limpio, `test_public_panels_lan_contract.py` verde.
- C6: CI = ver la PR.
