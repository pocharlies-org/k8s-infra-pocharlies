# DGX-880 · P10 · evidencia

Dónde: worktree de la rama `dgx-880-ruta-stores` (desde origin/main 27fb5b0), x86 `ubuntu`, 15-10-2026.

## 1. Rojo primero (commit 9304c4c, antes de los manifiestos) · FAIL esperado
`python3 -m unittest tests/test_correo_secret_stores_contract.py tests/test_correo_lan_route_contract.py`
```
Ran 24 tests in 0.470s
FAILED (errors=21)
```
Los 21 errores son `FileNotFoundError` de los tres manifiestos que aún no existían. Los otros 3 casos son barridos de
regresión que ya pasan: ninguna ruta de `networking/` nombra `correo-machine`, traefik-edge no sirve nada de correo y su
allowlist no incluye el ns `correo`.

## 2. Verde tras el cambio · PASS
El mismo comando -> `Ran 24 tests ... OK`.

Mutaciones de control (12), cada una rompe UNA condición de S20 y pone rojo el test; el fichero se restaura y vuelve a
verde: Role con `list`, con `watch`, con un Secret de Gmail, el de Synapse con el suscriptor de Hermes, sin
`resourceNames`, store sin `conditions`, store con otro `remoteNamespace`, RoleBinding a otra SA, ruta con `sso-chain`,
ruta al Service `correo-machine`, ruta sin `ClientIP`, ruta con la clase de ingreso del borde -> 12 de 12 en rojo.

## 3. Render de ArgoCD · PASS
`kubectl kustomize .` (kustomize embebido) en origin/main y en la rama: 358 -> 367 documentos, sin ninguno quitado ni
cambiado. Los 9 añadidos:
```
ClusterSecretStore kubernetes-correo-hermes, kubernetes-correo-synapse
IngressRoute traefik-lan/lan-correo
Role correo/eso-correo-hermes-reader, correo/eso-correo-synapse-reader
RoleBinding correo/eso-correo-hermes-reader, correo/eso-correo-synapse-reader
ServiceAccount hermes/eso-correo-hermes-reader, synapse/eso-correo-synapse-reader
```
Los tres ficheros entran en la Application `k8s-infra` (path `.`, tronco `main`, sync automático) por el
`kustomization.yaml` raíz; ninguna app propia de traefik-lan los lee (su `values.yaml` es solo el chart).

## 4. Esquema y lint · PASS
- yamllint con la configuración de `reusable-ci.yml` (`relaxed`, línea máx. 220) sobre los cuatro ficheros: sin avisos.
- Los dos stores y la ruta contra el `openAPIV3Schema` de los CRD vivos (`clustersecretstores.external-secrets.io` v1,
  `ingressroutes.traefik.io` v1alpha1): ningún campo desconocido ni error de esquema. Control negativo (`condtions`): lo
  marca. `conditions[].namespaces` existe en el CRD del clúster.

## 5. Suite completa · PASS (salvo 2 fallos previos)
`python3 -m unittest discover -s tests -p 'test_*.py'` -> en origin/main `Ran 480 tests`, 2 failures; en la rama
`Ran 504 tests`, los mismos 2 failures. Previos y ajenos a esta PR:
`test_onepassword_quota_floor_contract::test_no_onepassword_externalsecret_here_opts_out_of_onchange` ("the glob broke")
y `test_traefik_lan_ks5_ha_contract::test_harbor_lan_resolves_to_the_cluster_service` (CoreDNS de SC-2443/SC-2445 deja
`192.168.50.240` en el bloque de `e-dani.com`).

## 6. `company-duplicados` · PASS
`company-duplicados` -> «Sin duplicación nueva» (jscpd 5.4.0, umbral 12 líneas; los formatos del detector no incluyen YAML).

## Criterios (C1 de `00-spec.md`, parte P10)
- C1 · ruta: `lan-correo` publica solo `correo.lan.e-dani.com`, desde LAN/tailnet/clúster, al Service `correo:80`, sin
  middlewares, con el certificado de la casa; `correo-machine` no aparece en ninguna ruta y el borde no sirve correo
  (secciones 2 y 3).
- C1 · stores: dos ClusterSecretStore kubernetes con Role de `get` por `resourceNames` (Hermes: productor y suscriptor;
  Synapse: solo su productor), sin `list`, `watch` ni Gmail/APNs, cada uno usable solo desde el ns de su consumidor
  (secciones 2 y 4).

Fuera de esta PR, tras la fusión y el primer sync de P9 (`release`/`qa`): el `curl` en vivo a `correo.lan.e-dani.com`, que
los stores queden `Valid` y que los ExternalSecret de P12 y P13 sincronicen.
