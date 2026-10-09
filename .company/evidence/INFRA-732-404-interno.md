# INFRA-732 · 404 para /api/interno en las dos IngressRoute del dashboard

Rama: `devops/INFRA-732-404-interno` · Repo: `pocharlies-org/k8s-infra-pocharlies` · Tronco: `main` (ArgoCD app `k8s-infra`, `targetRevision: main`, path `.`).

## Mecanismo elegido

Regla de prioridad **500** (mayor que 450) que coincide con `PathPrefix(/api/interno)` y
**no reenvía al backend** (`dgx-dashboard-ui`): sirve el 404 en el borde desde
`edge-static-server` (ns `traefik-edge`, puerto 8080), que devuelve 404 para cualquier
`Host` no incluido en su allowlist de ficheros — `dgx.e-dani.com` y `dgx.lan.e-dani.com`
no lo están, así que el 404 es determinista para esas rutas. Reutiliza un servicio ya
desplegado (no se construye backend ni servicio nuevo). Un solo prefijo cubre las rutas
internas futuras. La regla de `/api/app/alarma` (DGX-695, control set 400) no se toca.

## Render (kubectl kustomize, repo raíz)

`cd <worktree> && kubectl kustomize .` → IngressRoute filtradas:

```
### edge-dgx-dashboard-public ns traefik-edge
  prio 500 | match: Host(`dgx.e-dani.com`) && PathPrefix(`/api/interno`) | services: [('edge-static-server', None)]
  prio 400 | match: Host(`dgx.e-dani.com`) && (ClientIP(`192.168.50.0/24`) || ... | services: [('dgx-dashboard-ui', 'control-nexus')]
### lan-dgx-dashboard-public-host ns traefik-lan
  prio 500 | match: (Host(`dgx.e-dani.com`) || Host(`dgx.lan.e-dani.com`)) && PathPrefix(`... | services: [('edge-static-server', 'traefik-edge')]
  prio 400 | match: (Host(`dgx.e-dani.com`) || Host(`dgx.lan.e-dani.com`)) && (ClientIP(`1... | services: [('dgx-dashboard-ui', 'control-nexus')]
```

PASS — la regla 500 precede a la 400 (control set con `/api/app/alarma` intacto) en las dos rutas.

## pytest del repo

`python3 -m pytest tests/test_dgx_api_interno_404_contract.py tests/test_dgx_app_pagos_sso_contract.py tests/test_dgx_messages_sso_contract.py -q`

```
3 passed (nuevo)   # edge + lan 404 rule + alarma-regression guard
```

Sin el cambio (los dos ficheros revertidos a `origin/main`):

```
2 failed, 1 passed   # test_edge_404_rule y test_lan_404_rule fallan (0 reglas /api/interno);
                     # el guard de /api/app/alarma sigue pasando
```

PASS — C2: el test falla sin el cambio y pasa con él.

## Criterios

- **C1** (regla 404 en las DOS rutas, prioridad > 450, precede a 200/400, no reenvía al backend): PASS — ver render y `test_edge_404_rule`/`test_lan_404_rule`.
- **C2** (test en `tests/` que falla sin el cambio): PASS — ver pytest arriba.
- **C3** (en vivo tras el sync, `curl ... = 404`): NO MEDIDO aquí (no se toca el cluster ni se espera el sync). Queda como procedimiento post-sync en `50-entrega.md`.

## Preexistente, fuera de scope

`tests/test_canonical_host_routing_contract.py::test_all_new_lan_routes_use_canonical_names_and_public_wildcard` falla ya en `origin/main` por un drift de datos (`vault.e-dani.com` en `canonical-hosts-lan.yaml`), fichero que esta PR no toca.
