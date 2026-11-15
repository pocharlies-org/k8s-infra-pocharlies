Rol: developer · Fecha: 2026-10-04 · Sesión: INFRA-533-dev · Estado: LISTO

# INFRA-533 — entrega
Hecho: `sync-wave: "30"` en `platform/external-secrets/cluster-secret-store-onepassword.yaml` (con el comentario del plan; nombre y spec intactos); test `tests/test_onepassword_store_wave_contract.py` (4 tests); línea en `ARCHITECTURE.md` §8.

## Verificación
- `python3 -m unittest tests.test_onepassword_store_wave_contract -v` → Ran 4 tests, OK. Suite completa `unittest discover -s tests -p 'test_*.py'` lanzada: sin fallos visibles; tras el merge la ejecuta el CI.
- `kubectl kustomize . | kubectl diff --server-side --force-conflicts -f -` (solo lectura). Sin `--force-conflicts` falla por conflicto de field manager `argocd-controller` en un Secret (`.stringData.root-password/root-user`), ajeno a este cambio. Diferencias: el store `onepassword` gana solo `argocd.argoproj.io/sync-wave: "30"`; además aparecen los Jobs-hook PostSync de keycloak (efímeros, no existen en vivo) y 2 EndpointSlice de traefik-edge (ya difieren en main; no los toca esta PR).
- `company-duplicados`: sin duplicación nueva.
- Documentación: ARCHITECTURE.md §8: «El store `onepassword` va en la última wave (30) a propósito: con el cupo agotado queda `InvalidProviderConfig` y bloquearía las waves siguientes; un recurso nuevo con wave > 30 lo rompe (`test_onepassword_store_wave_contract`).»

## Rework (nota-architect-pr243)
- `.github/workflows/ci.yml`, job onepassword-connect-contract, step INFRA-523: añadido `tests/test_onepassword_store_wave_contract.py` a la orden (antes no corría en CI). Revisada la clase: es mi único test nuevo; los demás de la lista manual no son míos.
- Local: los tres tests de esa orden pasan.

## Rework 2 (decisión del CTO)
- `test_los_otros_stores_no_van_en_la_ultima_wave` ya no descarta ficheros ausentes: recorre todos los ClusterSecretStore del build, FALLA si faltan `onepassword-connect` o `kubernetes-control-nexus-pagos` (el nombre anterior `control-nexus-pagos` tampoco existía) y exige wave < 30 en los demás.
- `kubernetes-cnpg` no se define en k8s-infra: test aparte con `skipTest` explícito y motivo; si entra en el build, se mide.
- Clase revisada: `_build` saltaba en silencio los resources remotos (`://`); ahora lanza AssertionError. No quedan más bucles que descarten ausentes.
- Local: 3 tests de la orden de CI, OK (17 tests, 1 skip explícito: cnpg).

## 00-spec.md
- [x] store onepassword en la última wave, sin renombrar ni borrar
- [x] test de contrato
- [x] línea en ARCHITECTURE.md
Residuo (del plan): con el store caído `k8s-infra` seguirá Degraded; wave 1 y policies sí se aplican.

## Reutilizado
- Mecanismo `sync-wave` (patrón `platform/kyverno/policies.yaml` to-connect, waves -5/-4 de `cluster-secret-store-control-nexus-pagos.yaml`); estructura de `tests/test_pagos_hermes_reader_contract.py`.
- Búsquedas: `rg -n sync-wave`, `ls tests | rg wave|store`. No existía test de waves.
- Nuevo: solo el test, porque nada cubría el orden de waves; recorre `kustomization.yaml` en Python (no hay `kustomize` en el host/CI de tests).
