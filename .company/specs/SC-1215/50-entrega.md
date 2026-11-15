Rol: devops · Fecha: 2026-09-24 · Sesión: 2b8a9cb8-6717-4be2-bc54-34bfa5c0dd1b · Estado: LISTO

# SC-1215 — 50-entrega: formato del POST de role-mappings y diagnóstico del fallo

Rematada del despacho anterior, caído a mitad por error de API. Su trabajo real estaba sin
commitear en el checkout principal de k8s-infra (rama ya fusionada `sc-1215-keycloak-image-no-awk`);
se trajo a la rama nueva `sc-1215-role-mapping-post-format` sobre `origin/main`. El worktree del
otro repo (k8s-agentgateway, agent-a358a74964f0b3067) no tiene restos: limpio.

## Qué se hizo

`platform/keycloak-next/scripts/admin-keycloack-impersonation-grant.sh` (causas medidas el 24-09
contra el IdP vivo y el kcadm de la imagen fijada):

- El POST/DELETE de grant apunta a la colección `users/<id>/role-mappings/clients/<uuid>` — sin
  el sufijo `/roles`: ese subrecurso no existe y respondía 404.
- El cuerpo pasa a ser la representación del rol `{id,name,clientRole,composite,containerId}`:
  con `[{"id":...}]` el servidor responde 404 "Role not found" porque resuelve cada entrada por
  su `name`. Todos los campos salen de los lookups de solo lectura que el propio hook ya hacía.
- El paso final corre con `kcadm -H` y vuelca la respuesta capturada en el mensaje de fallo: el
  log del job incluye STATUS y CUERPO del servidor, sin credenciales (solo cabeceras de
  respuesta, nunca el Authorization de la petición).

`tests/test_admin_keycloack_impersonation_grant_contract.py`:

- El stub kcadm en-imagen replaya el contrato real 204/4xx (fixtures `create_status`/`create_error`).
- 2 casos nuevos en-imagen: stub 204 → grant aplicado (`present:true,changed:true`, POST a la
  colección con la representación en el log); stub 400 con cuerpo → el fallo incluye status y
  cuerpo y no hay línea de éxito.
- Asserts estáticos: sin sufijo `/roles`, body con `name`/`containerId`, `-H`, `server replied [`.

## PR

https://github.com/pocharlies-org/k8s-infra-pocharlies/pull/165 contra `main`
(commit 94341f7). CI: 12 checks en verde, mergeable CLEAN. NO fusionada: el merge lo pulsa el CTO.

## Cómo verificar

- `sh -n platform/keycloak-next/scripts/admin-keycloack-impersonation-grant.sh` — PASS
- `REQUIRE_IMAGE_CONTRACT=1 python3 -m unittest tests/test_admin_keycloack_impersonation_grant_contract.py`
  — 12/12 OK con la imagen keycloak 26.6.2 fijada, nada saltado
- Los 7 suites del job `keycloak-agentgateway-role-contract` — 75/75 OK
- `kubectl kustomize platform/keycloak-next` y `kubectl kustomize .` — rc 0; el configmap del
  overlay renderiza el script nuevo
- Reproducción end-to-end con kcadm real medida en la sesión anterior: 6 pasos en verde,
  incluido el 400 con status+cuerpo en el log y `delete -H`

## Checklist del mandato

- [x] cuerpo del POST = array de representaciones de rol con id/name (medido: es lo que resuelve el servidor)
- [x] ruta = colección role-mappings del cliente, sin `/roles` (medido: 404 con sufijo)
- [x] uuid del cliente `edani-realm` correcto (resuelto por lookup exacto, asserts anti near-miss reforzados)
- [x] el error del paso final imprime STATUS y CUERPO, sin credenciales
- [x] 2 casos de test en-imagen del POST (stub 204 → presente; stub 400 con cuerpo → status y cuerpo en el log)
- [x] auditoría de binarios en-imagen intacta (dinámica; cubre el `tr` nuevo)
- [x] sh -n, suite del contrato completa, kustomize overlay + raíz
