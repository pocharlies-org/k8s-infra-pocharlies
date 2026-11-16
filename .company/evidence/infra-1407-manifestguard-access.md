# INFRA-1407 (P1 de INFRA-1405) · evidencia — RBAC de solo lectura y egress del pool del guard

Dónde: worktree de la rama `INFRA-1407-manifestguard-access` (desde origin/main `a1e0eed5b`), pod
`company-0`, 16-11-2026. Cero `kubectl apply` real: el RBAC y la NetworkPolicy se entregan por
ArgoCD (kustomization de la raíz); lo único ejecutado contra el clúster son consultas de lectura,
dos pods efímeros de diagnóstico y un `--dry-run=server`.

La otra mitad de la historia (el scale set `arc-manifestguard`) está en
`pocharlies-org/k8s-gitops-pocharlies` (rama homónima, PR aparte): ver su
`.company/evidence/infra-1407-manifestguard-access.md`.

## 1. Estado real de los CRDs del clúster destino · PASS

`kubectl get crds -o json` (kubeconfig de administración, 16-11-2026):

```
total CRDs: 193
externalsecrets.external-secrets.io
  v1        served=True   storage=True
  v1beta1   served=False  storage=False
```

Es la premisa de `7b0d803`: el clúster sirve SOLO `v1`, así que un manifiesto `v1beta1` no tiene
esquema que lo valide y `kubeconform --strict` debe rechazarlo. Coincide con lo medido por el
architect (193 CRDs).

## 2. Por qué hace falta una NetworkPolicy nueva (medido, no asumido) · PASS

Dos pods efímeros en `arc-runners` con la imagen pinada del runner, sin token de SA, variando solo
la etiqueta `actions.github.com/scale-set-name` (así se ve la baseline frente a la policy ya
existente de `arc-hermes`):

```
label=arc-manifestguard  (sin policy propia — el caso de esta PR)
  https://kubernetes.default.svc/version  -> 401 y 000   (dos intentos: INTERMITENTE)
  https://10.43.0.1:443/version           -> 401 y 000
  https://100.107.21.89:6443/version      -> 000 siempre
label=arc-hermes         (con arc-hermes-cluster-egress, la policy que se copia aquí)
  https://kubernetes.default.svc/version  -> 401
  https://10.43.0.1:443/version           -> 401
  https://100.107.21.89:6443/version      -> 401
```

401 = llega al API sin credenciales: la ruta abierta, el permiso lo decide el RBAC. Sin policy
propia el runner no falla ruidosamente: a veces lee los CRDs y a veces no (el DNAT del service
`kubernetes` cae a un endpoint de tailnet que la baseline `arc-runners-egress` bloquea). Por eso la
policy nueva, con la forma exacta de la de `arc-hermes`: `10.43.0.0/16:443` (pre-DNAT) y los tres
`/32:6443` (post-DNAT). Endpoints comprobados el mismo día:

```
kubectl get endpoints kubernetes -n default -> 100.107.21.89 100.71.117.127 100.75.189.75
```

Pods de diagnóstico borrados por el propio `kubectl run --rm` (no queda nada).

## 3. Render y validación contra el API real · PASS

```
kustomize build .                     -> OK (35740 líneas), sin errores; el fichero nuevo entra
                                         por la línea 86 del kustomization de la raíz
kubectl apply --dry-run=server -f platform/arc/rbac-manifestguard.yaml
  serviceaccount/arc-manifestguard-cr-reader created (server dry run)
  clusterrole.rbac.authorization.k8s.io/arc-manifestguard-cr-reader created (server dry run)
  clusterrolebinding.rbac.authorization.k8s.io/arc-manifestguard-cr-reader created (server dry run)
kubectl apply --dry-run=server -f networking/arc-runners/networkpolicy.yaml
  networkpolicy.networking.k8s.io/arc-manifestguard-cluster-egress created (server dry run)
```

Dry-run de servidor: valida el esquema contra el clúster sin crear nada.

## 4. Contrato de lectura (test nuevo) · PASS

```
python3 -m unittest tests/test_arc_manifestguard_rbac_contract.py -v
  ... 6 tests ... OK
```

Falla si alguien añade un verbo de escritura, un segundo recurso, cambia el sujeto del binding,
saca el fichero del kustomization o abre en la NetworkPolicy un destino que no sea la API
(incluidos `0.0.0.0/0`, la tailnet entera y el `100.83.56.98` del x86). Añadido a la lista de
`python3 -m unittest` de `.github/workflows/ci.yml`, que es como se corren estos contratos.

## 5. Criterios de 00-spec.md

- **ClusterRole de solo lectura + binding al SA, por GitOps**: entregado aquí
  (`platform/arc/rbac-manifestguard.yaml`, en el kustomization → app `k8s-infra`). Nota: es
  **ClusterRoleBinding**, no RoleBinding: `customresourcedefinitions` es cluster-scoped y un
  RoleBinding no puede otorgarlo.
- **Scale set propio, no se ensancha `arc-k8s`**: en la PR de k8s-gitops
  (`infra/arc.yaml`, Application `arc-manifestguard`, min 0 / max 2, `template.spec.serviceAccountName`
  = el SA de este fichero). `arc-k8s` no se toca.
- **El runner lee los CRDs del destino**: la ruta (NetworkPolicy) está medida arriba; la lectura
  desde la identidad del SA se comprueba tras el sync (sección 6). No se da por buena aquí.
- **Solo lectura**: el ClusterRole tiene exactamente `get,list,watch` sobre
  `apiextensions.k8s.io/customresourcedefinitions` y ninguna otra regla (lo fija el test). La
  comprobación `auth can-i` con la identidad real, tras el sync (sección 6).
- **Ninguna credencial de escritura ni kubeconfig**: no hay Secret ni ExternalSecret en este
  cambio; el runner usa el token proyectado del SA (rota solo). El pool no lleva DinD ni
  contenedor privilegiado (lo fija el render en la PR de k8s-gitops).
- **Frontera de privilegios**: esta PR y la de k8s-gitops piden dictamen de `security` antes del
  merge.

## 6. Cómo se verifica tras el sync (no reclamado como hecho)

Con el RBAC ya aplicado por ArgoCD (app `k8s-infra` Synced):

```
kubectl auth can-i get   customresourcedefinitions.apiextensions.k8s.io \
  --as=system:serviceaccount:arc-runners:arc-manifestguard-cr-reader            # yes
kubectl auth can-i list  customresourcedefinitions.apiextensions.k8s.io \
  --as=system:serviceaccount:arc-runners:arc-manifestguard-cr-reader            # yes
kubectl auth can-i create externalsecrets.external-secrets.io \
  --as=system:serviceaccount:arc-runners:arc-manifestguard-cr-reader            # no
kubectl create token arc-manifestguard-cr-reader -n arc-runners > /tmp/tok      # token del propio SA
kubectl --token="$(cat /tmp/tok)" --server=https://100.107.21.89:6443 \
  get crds -o json | jq '[.items[] | select(.metadata.name=="externalsecrets.external-secrets.io")
       | .spec.versions[] | {name, served}]'                                    # v1 served=true, v1beta1 served=false
```
