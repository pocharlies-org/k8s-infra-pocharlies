Rol: devops · Fecha: 2026-10-04 · Sesión: devops-INFRA-512 · Estado: LISTO

# INFRA-512 — Entrega

## Hecho
- `platform/kyverno/policies.yaml`: borrada la regla `onchange-existing` (la de `mutateExistingOnPolicyUpdate: true`) del ClusterPolicy `externalsecret-onepassword-onchange` (editado ese objeto, no creado otro). `onchange-at-admission` queda intacto. Borrado el ClusterRole `kyverno:background-controller:externalsecrets` (grep: sin más referencias en git). Comentarios de la policy actualizados.
- Nuevo test de contrato `tests/test_onepassword_onchange_policy_contract.py` (patrón de `tests/test_onepassword_change_detector.py`): falla si reaparece `mutateExistingOnPolicyUpdate`, la regla `onchange-existing`, algún `targets` en una regla mutate de la policy, o el ClusterRole (definido o referenciado en cualquier .yaml del repo).

## PR
- Rama `INFRA-512-quitar-mutate-existing`, PR https://github.com/pocharlies-org/k8s-infra-pocharlies/pull/238 contra `main`. Commit d17872e.

## Verificación
- `grep -rn mutateExistingOnPolicyUpdate platform/kyverno` → sin resultados.
- `python3 -m unittest discover -s tests -p 'test_*.py'` → 351 tests, OK.
- `kubectl kustomize .` → OK; el render no contiene el ClusterRole (grep sobre el render → 0).
- `git diff origin/main --stat` → solo `platform/kyverno/policies.yaml` y el test.

## Criterios del spec
- [x] La policy en el tronco (tras merge) no contiene `mutateExistingOnPolicyUpdate` ni `onchange-existing`.
- [x] El ClusterRole ya no está en git y no queda ninguna referencia.
- [x] grep sin resultados; `kustomize build .` y unittest en verde.
- [x] Test de contrato que falla si reaparece.
- [x] Nota de aplicación con `prune: false` — abajo.

## Al aplicar (ATENCIÓN — lo hace release/devops tras el merge, NO lo he tocado yo)
- La regla `onchange-existing` desaparece del clúster sola: el objeto ClusterPolicy vive en git y ArgoCD actualiza el objeto (prune no afecta a objetos que siguen existiendo). Sin `mutateExistingOnPolicyUpdate` ni `targets`, la política ya no lanza mutaciones en segundo plano sobre los ES existentes; no hay resync de ES.
- El ClusterRole `kyverno:background-controller:externalsecrets` SÍ queda vivo (ArgoCD `prune: false` no borra objetos retirados de git). Pendiente tras el merge, a mano y sin resync masivo de ES: `kubectl delete clusterrole kyverno:background-controller:externalsecrets` (es un ClusterRole agregado por label al background-controller de Kyverno; borrarlo solo retira el permiso de patch que ya nadie usa). Verificar antes que ningún otro manifest lo referencia (en git: ninguno).

## Reutilizado
- Reutilizado: la propia policy `externalsecret-onepassword-onchange` (se edita, no se crea otra) y su ClusterRole de admisión `kyverno:admission-controller:externalsecrets` (intacto); patrón de test de `tests/test_onepassword_change_detector.py`; PyYAML ya usado en `tests/test_canonical_host_routing_contract.py` y otros.
- Buscado: `grep -rn "kyverno:background-controller:externalsecrets"` en todo el repo (solo policies.yaml), `grep -rn mutateExistingOnPolicyUpdate platform/ tests/` (nada más), `grep -l "policies.yaml" tests/` (ningún test la leía).
- Nuevo: solo el test de contrato, porque no había ningún test que parseara policies.yaml.

## Documentación
Ninguna necesaria (declarado en el spec). El comentario de la policy documenta el porqué.

## Aplicación manual en el clúster (plan B, 04-10 — BLOQUEADA en el paso 2)
- Paso 1 (antes): `kubectl get updaterequests -A --no-headers | wc -l` → `0` (No resources found).
- Paso 2: `kubectl apply --server-side --force-conflicts -f <ClusterPolicy externalsecret-onepassword-onchange extraída sin editar de origin/main e96b478, rules=[onchange-at-admission]>` → DENEGADO por el hook de permisos del rol devops (fuera del mapa). No se busca otra vía. El fichero extraído y validado está en el scratchpad de la sesión (`policy512.yaml`).
- Pasos 3-5: no ejecutados (dependen del 2). Orden pendiente: aplicar → comprobar `spec.rules[*].name` = solo `onchange-at-admission` → `kubectl delete clusterrole kyverno:background-controller:externalsecrets` → recuento de updaterequests y `status.refreshTime` de los ES.
